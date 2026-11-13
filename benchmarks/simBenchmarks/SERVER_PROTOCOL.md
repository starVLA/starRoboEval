# SIM server interface

The simulator is a separately launched service. Models do not import it or own
its lifecycle. This protocol standardizes communication, not robot capabilities:
each benchmark still declares its own sensors, physical actions, reset schedule
and native scorer in `EVALUATION_PROTOCOL.md`.

```text
AgentPolicies/<profile>/                              benchmarks/simBenchmarks/<name>/
model <- allowed observation <- trusted driver -- HTTP --> server.py -> native SIM
      -> action decision      -> SIM client   <- declared sensors + private outcome
                    |                                  |
                    +---- records / source / media ----+
                                benchkit tools
```

## Ownership and access

- `<benchmark>/server.py` selects the native factory and benchmark-specific
  runtime capture/exclusions. Its adapter bridges the public contract to native
  execution. All implemented benchmarks group service adapters in
  `bench_server/`, with task definitions and public receipt schemas in `bench_server/protocol/`.
  `environment/` contains native workers, assets and installation tools. The
  [RoboDojo directory guide](RoboDojo/README.md#directory-responsibilities) maps
  these packages without changing the common wire protocol.
  Benchmark-owned task selection lives in the adapter or its protocol data.
- `benchkit/sim_server/` supplies transport, strict serialization,
  session lifecycle and artifact transfer. An agent supplies its own decision
  loop or uses optional reference utilities. `benchkit` supplies record,
  service source-capture and reporting tools, not a separate required control service.
- `AgentPolicies/<profile>/` contains the model policy/configuration and its results.
  A profile can represent a complete multi-model agent method. The wire protocol
  is the integration boundary; Python `Policy` and the reference runner are
  optional conveniences. Internal planning/tool calls do not grant additional
  environment channels. Declare the method and report available inference usage
  separately from decision and native-control counts.
  Policy code receives `EpisodeContext`, allowed `Observation` and execution
  counters. It does **not** receive the server client, endpoint, credential,
  task reset state, reward, metrics or management interface.

An explicitly reviewed model-owned **trusted driver** may retain the
administrative client for episode claims and results, but it must not pass that
client to the model actor. This client is not an episode-scoped, actor-safe
capability. Benchmark entrypoints share the `benchkit.sim_server` implementation.

The service has no grasp, navigation, task-solving or hybrid-policy RPC. One
`step` applies one native action vector, including only protocol-fixed native
control/units/interpolation. No simulator tick or model request is generated
while idle. A native runtime may own background rendering/resources; this
service does not create an autonomous physics stepping loop.

Action chunk length, repeated controls within a decision and replan timing are
policy-method choices, implemented by the trusted agent driver. The wire `step`
accepts one action, not a chunk or a repeat count. A driver may issue multiple
successive `step` requests from one decision; the shared service neither tracks
that decision boundary nor rejects a sixth control because a method example
used a five-control prefix. Action validity, exact sequencing, native execution
and termination, and the declared total execution budget still apply. A repeated
target is a new control at the next sequence, not a retry after an uncertain ACK.
The number of native physics substeps, control timing and protocol-fixed
interpolation inside one action are not policy-owned repeat settings.

Existing tracks are not all decoupled: explicitly selected `budget_mode=decisions`
contracts still couple `max_policy_calls` and `replan_interval` to an execution
cap, with adapter/client agreement checks. SIMPLE now defaults to a task-horizon
protocol without these method caps. Current CALVIN/DOMINO protocols no longer
declare `required_replan_interval`. The shared field remains readable for older
services; it is not a requirement to impose on new integrations. Historical
records and explicitly selected older contracts are not reinterpreted.

Process separation makes deployment ownership explicit; it is not an OS security
sandbox. Run an untrusted policy separately without evaluator credentials or
filesystem/process access. Merely putting a policy in another Python directory
does not enforce that restriction.

Robot state is not automatically privileged: measured joints, end-effector
poses or other proprioception may be declared by the benchmark's public sensor
contract. Undeclared object truth, private scoring predicates and hypothetical
simulator rollouts remain outside the policy interface. The selected service
workflow enforces this division through an evaluator-held client; legacy
in-process adapter factories remain available for explicitly selected local
workflows and tests, not as a second capability granted to the remote policy.

## Launch and connect

Select an implemented service through the shared entrypoint:

```sh
rsi-bench list
rsi-bench serve --benchmark simpler_env --help
```

Source-checkout equivalent: `python -B -m benchkit.sim_server.cli`. The explicit
registry delegates to the selected benchmark's `server.main(argv)`; it does not
replace its factory, schedule constraints or source/asset capture. Generic help
and listing import no benchmark modules. Selecting a service for help loads its
import-safe wrapper, but does not create a service or reset an environment.
The list describes development entrypoints, not installation or validation status.

Install the selected native environment first. Use a launcher Python satisfying
the benchmark's adapter dependencies; benchmarks with a private native worker
select that worker's interpreter in their deployment configuration. Launching
fixes the adapter parameters and episode schedule, but does
not call `reset`. Source capture and native package/assets readiness are separate.
Generate a strong URL-safe bearer token outside the repository and provide the
same `RSI_SIM_SERVER_TOKEN` environment value only to server and evaluator.
Do not put it in JSON parameters, prompts, command-line token arguments or Git.

Example (replace paths with your configuration and a **new** result directory):

```sh
rsi-bench serve --benchmark simpler_env \
  --parameters /absolute/benchmark-parameters.json \
  --seed 20260907 --episodes 1 --port 8765 \
  --output-dir /absolute/AgentPolicies/my_profile/results/simpler_env/raw/my-run/server
```

The selector includes all 14 implemented service routes; `rsi-bench list` shows
canonical IDs and repository-relative setup guides. Per-benchmark module entrypoints, such as
`python -B -m benchmarks.simBenchmarks.SimplerEnv.server`, remain valid. Neither
route changes the existing benchmark contract or implies native parity.

Schedule selection is benchmark-owned. RoboDojo requires a complete named
`panel` from [its protocol catalog](RoboDojo/bench_server/protocol/task_catalog.json) and rejects
server-side `--episodes` truncation: `classify_objects` offers fixed selections
of 5 or 50 layouts, each attempted once. Through the gateway, its panels are the
whole named selection and `remote-run` refuses case-file or limit subsets. See its
[launch example](RoboDojo/README.md#start-the-benchmark-server).

The server binds **only `127.0.0.1`**. For another node use an authenticated SSH
local forward, for example `ssh -N -L 8765:127.0.0.1:8765 YOUR_EVAL_NODE`.
HTTP is not a public-network API; no unauthenticated LAN/WAN bind is supported.
The client uses a direct connection without environment proxies or redirects.

Connect a trusted agent driver separately. A driver may implement this wire
protocol directly or use the Python client (RGB decoding requires NumPy).
Before claiming a case it must check the returned benchmark/protocol identity,
observation/action specifications, selected schedule and budgets. Model settings,
credentials, prompts and action-grouping choices belong to that method, not the
server configuration. See [agent-method integration](../../docs/agent-methods.md)
and the selected profile under [AgentPolicies](../../AgentPolicies/README.md)
for client commands.

Server-interface versions and method versions are independent. For example,
RoboDojo's Direct v2 names a robot-interface contract, not a required model
implementation. Neither changes the shared `starvla-rsi.sim-server/v1` wire
protocol. Legacy decision-budget tracks still require matching adapter/client
budget settings. For the optional reference CLI, `--benchmark` must match the
server's `descriptor.name`, not a registry alias; remote runs reject
`--benchmark-args` because only the server controls native construction.

`python -B -m benchkit.sim_server` launches only the synthetic smoke world with
the same flags. It needs no simulator and is not capability evaluation.

## Evaluator RPC, version 1

All requests are bounded JSON `POST /rpc`, authenticated with `Bearer`. The
envelope contains `protocol="starvla-rsi.sim-server/v1"`, a random `request_id`,
`server_id`, `op` and `params`. The initial `describe` uses null `server_id`;
all later calls bind that returned service identity. Responses echo protocol and
request identity and contain either `result` or a closed error code.

| Operation | Meaning |
| --- | --- |
| `describe` | Read immutable descriptors, budgets, deployment-source identities and selected episodes; no native control. |
| `open` | Permanently claim one predeclared episode ID; no caller-supplied reset metadata or native configuration. |
| `reset` | The one permitted initialization, with sequence 0. |
| `step` | Execute one server-validated native action, with exact next sequence 1, 2, …; return one transition. |
| `metrics` | Read adapter-owned cached native outcome; evaluator-only. |
| `finish` | Finalize artifacts once, close once, then inventory the closed files. Repeated finish reads the cached result, never repeats native cleanup. |
| `read_artifact` | Read at most 1 MiB from an inventoried relative path after finish; no arbitrary file access. |

Only one native episode is active per server. Different concurrent episodes need
separate service instances/output directories and explicit resource assignment.
Successful `open` is not successful reset. Claims precede native session creation;
failed openings are retained and cannot be reclaimed. Existing service directories
cannot be restarted or overwritten. Reconciliation/resumption of interrupted
servers is not implemented; a new directory is not permission to repeat a task.

Reset/step consume sequence numbers before native execution. Duplicate/stale or
out-of-order commands never execute another control. Any native/transport error
poisons further client controls. **No automatic action/reset retry** occurs,
even when a timeout leaves execution uncertain. Returned valid controls and
unknown in-flight native execution must not be conflated. The client timeout
does not kill or roll back a running native operation; retain server evidence and
use the deployment supervisor for a stuck process. Cleanup is still attempted
once. A failed native close blocks further sessions on that service.

### Pre-execution action rejection extension

New descriptions advertise `action_rejection: starvla-rsi.action-rejection/v1`.
Generic action checks and an optional benchmark-owned pure `validate_action_input`
hook run before consuming a sequence. The hook can check submitted values and
public contract constants only, not native state or task feasibility.

A rejected input returns `error.code=invalid_action`, a closed `rejection` issue
(code, declared field, optional finite actual/limit/component index),
`executed=false` and unchanged `next_sequence`. No control, sensor or scoring
call occurs. The session stays running. Only a negotiated, correlated receipt
permits a corrected command at the same sequence; old code-only errors and lost
replies remain fail-closed. Older strict clients may reject the new description;
use a matching pinned client/service pair.

An agent driver can select `invalid_action_handling=feedback` and return the
issue at the next counted policy call with the last acknowledged observation.
The current reference loop requires a finite decision-call safety budget for
this mode; it grants no extra sensors or task reset. Internal inference/tool
loops belong to the declared method, not a universal one-request rule.
ACKed valid prefixes retain their real counts.
`benchkit/validation.py` holds the shared data format, not the control loop.

## Observations, records and limits

The JSON codec rejects duplicate keys, non-finite numbers and messages exceeding
16 MiB. RGB is copied as lossless inline base64 `uint8 H×W×3` bytes with explicit
shape. No pickle, filesystem image references, arbitrary RPC method lookup or
code execution is accepted. Camera/state channels must match `ObservationSpec`.
Adapters remain responsible for the content allowlist: a transport cannot prove
that arbitrary metadata was derived only from permitted sensors. Transition
reward/info belongs to the evaluator, never the policy observation.

An optional `ObservationSpec.control_feedback_schema` declares a separately
versioned public robot-control receipt. Its `Observation.control_feedback` is
null at reset and a bounded JSON object after each acknowledged control, with
`schema` matching that declaration and `control_target` matching the observation
step. Without the declaration both wire keys remain absent; unsolicited,
missing, stale or reset receipts are rejected. Older strict clients reject the
new spec rather than silently dropping this sensor channel. The benchmark must
project a closed allowlist from actual execution, not forward its private logs,
metrics or arbitrary diagnostics. Payload semantics remain benchmark-owned.

The agent-side runner groups every acknowledged control in the executed prefix
as `control_acks` in normal execution or rejection feedback. Each entry binds
`environment_step`, `observation_step` and the public `payload`; a zero-execution
rejection carries an empty list, not the preceding decision's receipts. No
extra observation, model call, simulation tick or action replay is generated.
Uncertain execution still terminates; no acknowledgement is invented. The run
manifest binds `control_acknowledgement_version` and `control_feedback_schema`.
RoboDojo's [robot feedback](RoboDojo/ROBOT_FEEDBACK.md)
is mandatory in its current fixed Direct v2 service; the shared transport supports
other benchmarks without that channel. Model notes, preview images and target selection
remain under `AgentPolicies/<profile>/`; native RGB and evaluator-private records are
not replaced by model-side previews.

Older services may declare a positive integer `required_replan_interval` in
their description's budget object. Matching clients continue to reject a
mismatched prefix before claiming an episode; do not silently override an old
declared contract. New integrations should leave decision cadence to the agent.
The wire always acknowledges one control at a time, so an agent can inspect
each returned public instruction while executing a multi-control chunk.

The reference agent driver records `instruction_change_handling=replan-after-ack/v1`
in its result manifest: after a changed public instruction it stops the
unexecuted suffix and requests another decision. Native end and exhausted
budgets still take precedence. This is agent-side behavior, not a new RPC,
sensor or server-side policy. Its record audit permits that partial prefix only
when the declared behavior and recorded public instruction change justify it.
The current auditor rejects a record without the declaration.

The client manifest records server deployment provenance separately from its
own git revision and dirty flag; the client captures no source files. New service
launches capture an explicit shared-service source scope (`harness_source/` in
the service root) plus only the selected benchmark's declared runtime
supplements; they do not require reference-model drivers or other benchmarks'
source files. Existing inventories are not rewritten or reinterpreted. Neither
record proves loaded-memory, asset/dependency parity or provider identity.
Use the standalone remote runner with a predeclared service schedule; there is
no central campaign workflow.

Run services from a stable, versioned source snapshot and do not edit it during
operation. V1 records launch-time source bytes but does not recheck later worker
file reads; operators must verify snapshot integrity before and after a run.

`finish` preserves close-time receipts before transfer. For new services, videos
are the default permanent visual record on the server. After successful native
finalization/close, eligible temporary frame images are removed unless the server
was launched with `--retain-frame-images`; missing videos or cleanup errors retain
the images as fallback evidence. `server_media_retention.json` records retained
policy, omissions and fallback reasons. The final inventory describes remaining
files, not paths already deleted. Historical inventories are never rewritten.

Remaining regular files beneath the episode directory are inventoried. New clients
retain media references by default; `--copy-server-media` explicitly downloads
selected media with SHA-256 verification into `sim_server_files/`. Symlinks,
unsafe paths and overwritten destinations are rejected. V1 bounds each episode
to 100,000 files / 16 GiB; exceeding a bound is an explicit infrastructure error,
not silent truncation. A benchmark launcher may declare runtime-only directories
to omit from transfer; this is benchmark-owned storage classification, not a
policy option or permission to omit outcome evidence. SIMPLE and RoboDojo exclude
only their episode-local `cache/` directories; RoboTwin uses the same rule for
native CUDA build outputs. The exclusion is recorded in the
session receipts and the captured benchmark launcher. Observations, actions, native logs, metrics, source
provenance and videos are not excluded. Canonical server videos remain retained;
artifact downloads never delete or relocate them. Changed export declarations
apply only to new launches, never to historical inventories or results.

New clients can select optional **client retention** through
`RecordingOptions` before an episode starts. They still call `finish` once and
retain the private close receipt and native result/provenance records. Standard
mode disables retained client frame images and duplicate server-media downloads;
video references remain available in the receipt. The full server inventory and
omitted download paths remain recorded. A reference is not proof of downloaded
bytes. Live RGB/state transport and runtime capture remain unchanged; there is
no client RPC to delete server evidence or change native capture. Unknown
non-media artifacts are retained conservatively rather than dropped with images.
Selective copies cannot satisfy an audit requiring every original
file, but missing optional history does not prevent basic result publication.
See [recording settings](../../docs/recording.md).

The local `sim_server_receipt.json` records server identity, source references and
the closed artifact inventory without credentials. Legacy benchmark artifact
auditors assume older directory layouts; they are not yet validators of this
new server layout. Transport regression, native execution and model capability
are separate evidence claims. Task/case selection and model persistence rules
are independent of this communication protocol.
