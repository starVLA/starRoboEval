# RoboDojo

This directory defines one public RoboDojo benchmark service. It owns the
simulator schedule, public observations and actions, fixed robot-only execution,
native scoring and evidence. Models never import or drive the native simulator.

- [Evaluation protocol](EVALUATION_PROTOCOL.md)
- [Environment preparation](environment/README.md)
- [Action rejection](ACTION_VALIDATION.md)
- [Robot-control acknowledgements](ROBOT_FEEDBACK.md)
- [Shared SIM wire protocol](../SERVER_PROTOCOL.md)

## Directory responsibilities

```text
RoboDojo/
├── server.py                       # public launch entrypoint
├── server.example.json             # deployment configuration example
├── bench_server/                   # benchmark service package
│   ├── adapter.py                  # public contract to native environment bridge
│   ├── native_worker_client.py     # private worker communication
│   └── protocol/                  # service-owned evaluation definitions
│       ├── task_catalog.json       # task definitions and fixed panels
│       ├── task_catalog.py         # catalog loading and validation
│       └── robot_feedback.py       # public robot-control receipt schema
└── environment/                    # native worker, kinematics and runtime pins
```

`bench_server/` owns both the service implementation and its evaluation protocol.
Its `protocol/` subpackage remains dependency-light so catalog and reporting
tools can read definitions without starting the server or simulator.

This is an abbreviated responsibility view; protocol guides and package marker
files are omitted. [The task catalog](bench_server/protocol/task_catalog.json) is benchmark
protocol data: it defines instructions, seeds, horizons and fixed evaluation
panels. The server reads it to freeze the schedule. Native assets and runtime
bindings belong in `environment/`; operator paths, GPU selection and the chosen
named panel belong in `server.example.json` or an operator-owned copy.

`bench_server/native_worker_client.py` connects the adapter to the private
native worker. Model runners use the shared SIM service client instead. Moving
these modules into packages does not change the wire protocol, action semantics,
native scorer or historical result identities. The public launch command remains
`python -m benchmarks.simBenchmarks.RoboDojo.server`.

A private worker timeout or malformed acknowledgement faults that transport:
the service does not replay the operation or enqueue finalization behind an
unknown result. Cleanup uses bounded child termination and retains the error
and cleanup receipt. A complete, correlated native error can still permit
read-only finalization. Neither outcome authorizes an automatic case retry.

## Supported service

The only supported server interface is Direct v2:
`robodojo-direct-v2-rgb-proprio28-eef16-robot-feedback-v1`.
This identifies robot observations/actions and native execution, not the agent
method. The current GPT driver defaults to generic `codex-native/v2`; using it
does not change this server interface or reproduce the historical v2 method's scores.
The task catalog currently
enables `classify_objects` with two immutable schedules:

- `fast`: fixed standard layouts 0–4, each attempted once;
- `full`: layouts 0–49, matching the upstream configured 50 episodes, each
  attempted once;
- native horizon 1100 controls per layout;
- three RGB cameras plus measured robot joints/end-effector poses;
- absolute dual-arm end-effector targets;
- fixed numerical DLS conversion followed by one native control;
- one public robot-control acknowledgement after each executed control;
- native task success and score remain evaluator-private until reporting.

There is no runtime selector for earlier joint-control, v1, no-ACK, or
experimental arrange-number services. Their source remains recoverable from Git
history and local ignored `barks/`; it is not part of this public entrypoint.

## Ownership boundary

`benchmarks/simBenchmarks/RoboDojo` owns benchmark behavior. Model prompts,
conversation state, voluntary-stop rules and action-generation logic belong in
`AgentPolicies/<model-profile>/`. Public results belong in
`AgentPolicies/<model-profile>/results/robodojo/`. The shared `benchkit/` may validate
and publish closed evidence, but it does not choose robot actions.

The service may expose declared robot state. It never exposes object truth,
layout metadata, reward internals, success predicates, hidden scorer state or a
task-solving RPC. Invalid public actions are not executed; the service returns a
structured rejection so the client can make its next decision. An uncertain
native or transport failure remains terminal.

## Start the benchmark server

Copy [server.example.json](server.example.json) to an operator-owned path and
replace the runtime manifest path, digest and GPU. Protocol fields are not
configurable. Select only a named catalog `panel`; arbitrary layout lists are
rejected. Use a fresh server output directory and a strong evaluator-only token:

```sh
export RSI_SIM_SERVER_TOKEN='replace-with-a-url-safe-secret-of-at-least-32-characters'
python -B -m benchmarks.simBenchmarks.RoboDojo.server \
  --parameters /absolute/robodojo-direct-v2.json \
  --seed 20260907 --port 8765 \
  --output-dir /absolute/results-staging/robodojo/server
```

The service binds to loopback. Use authenticated SSH forwarding when the model
runner is on another node. Startup freezes the schedule but does not reset the
simulator. A case is claimed once; failed reset/action evidence is retained and
the case is not automatically retried.

Run the model-owned client separately, for example:

```sh
python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark robodojo \
  --control-method codex-native/v2 \
  --seed 20260907 --episodes 5 --max-steps 1100 \
  --max-policy-calls 240 --replan-interval 5 --budget-mode horizon \
  --output-dir /absolute/results-staging/robodojo/client \
  --run-id classify_objects-category-sorting-codex-native-v2-panel5
```

The client command and credentials are model-owned. The benchmark server does
not import `AgentPolicies/gpt6_astra`.
The five-control prefix is a method configuration, not a server-side repeat rule;
controls are submitted and acknowledged individually within the 1100-control horizon.
By default, native videos remain in the server output and the client retains
references. Use client `--copy-server-media` only when another local media copy
is wanted; see [recording options](../../../docs/recording.md).

## Evidence and status

Every case retains its outcome, counts, configuration and separate errors.
Detailed interactions and videos are optional, enabled by default where
supported; see [recording options](../../../docs/recording.md). The current
server still generates native evidence; client retention switches do not disable
that capture. New services keep the three server-side camera videos by default,
with client references instead of duplicate downloads. Temporary frame images are
not kept after successful close when video evidence is available; use server
`--retain-frame-images` to retain them explicitly. Paired receipts, native events and all three videos support the
existing full-evidence audit/publication path, not general participation or basic
result eligibility. `fast` is the five-layout reference comparison
panel; `full` is this task's 50-layout native evaluation schedule, not the whole
multi-task RoboDojo matrix. CPU tests and artifact audits
do not prove native rendering or task success. The latest recorded native panel
and public report live under the model result namespace; generated media and raw
evidence are intentionally outside Git and require durable artifact storage.
