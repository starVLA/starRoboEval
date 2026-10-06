# Generic persistent Direct control

`codex-direct/v3` is the active Direct method. It keeps a persistent Codex
conversation, image analysis and same-episode notes while choosing actions in
the **connected benchmark's declared numeric interface**. It is not an EEF
controller, a particular robot, or the historical RoboDojo reference method.

The file remains `methods/codex_direct.py`; the method version changes because
its inputs, action tool, feedback and prompt changed. Direct v2 source and results
remain in Git and frozen run packages. V3 does not inherit their success rates.

## Responsibilities

- The benchmark owns task language, robot sensors, action meanings, native
  control, budget and scoring. The trusted driver passes declared public fields.
- Direct owns reasoning, notes, image crops, action choice and chunk length.
  It contains no robot names, fixed cameras, layout rules, hardcoded home pose,
  automatic grasp/return trajectory or benchmark-specific solution hint.
- `tools/persistent_runtime.py` owns the shared model-side conversation lifecycle,
  permissions, accounting, rejection delivery and cleanup. Direct and Planned
  both use it; neither method inherits the other's policy.
- The model actor never receives the administrative SIM client, credentials,
  layout/seed metadata, hidden score, simulator handle or environment reset tool.

This continues the pinned CLI's existing dynamic-tool mechanism rather than
introducing a second robot connection. See the official
[Codex app-server documentation](https://learn.chatgpt.com/docs/app-server#dynamic-tool-calls-experimental).
These permissions are checked configuration, not independent kernel attestation.

## Public inputs and robot actions

The method consumes current task instruction, ordered public RGB, declared
state/state names, `action_spec`, remaining controls and acknowledged execution.
Action dimensions, bounds, units/frames, rotation and gripper conventions come
from the service. State is absent when the service declares no state. Camera
names are labels, not local paths. Original PNGs remain available; the default
attachment preview has a 480-pixel longest edge.

The `robot_act` tool accepts `request_id`, `actions`, `stop_reason` and a brief
observation-based `reason`. `actions` contains 1..`max_chunk_length` numeric
vectors in the declared order, including repeats only when the model chooses
them. Default chunk ceiling is 5, configurable from 1 to 32 in this method.
The server still executes individual native controls; this is not a universal
five-step server rule. No host-side clipping, action repair, IK proposal or
task-solving fallback is added.

Invalid input executes no rejected action and returns correction feedback at
the next counted call. A prefix already acknowledged remains real and counted.
The policy never replays an uncertain control or resets a case to recover.
Ordinary give-up and policy-requested `safety_stop` are disabled by default for
simulation evaluation. The driver accepts `--safety-stop` to explicitly opt in
or `--no-safety-stop` to explicitly keep it off; the factory accepts the Boolean
`safety_stop` parameter. This setting applies to Direct v3 and the current
Planned v1 preset, not Native, and is captured in the effective configuration and prompt. It is not a
benchmark safety detector or permission to disable hardware safeguards.
When disabled, an empty-action safety-stop submission is rejected without
execution and returns correction feedback at the next counted policy call;
it does not end the episode. When enabled, an explained stop ends the method's
attempt without awarding success. Native termination, budgets and genuine
errors remain authoritative in both modes. Historical frozen runs retain their
original enabled setting and results; the new default does not relabel them.

### Returning to the initial configuration

When the task explicitly requires return, the model should reserve control
budget and plan a return using the initial **public observation of this episode**.
The initial state is an observation, not a prerecorded home pose, an action
vector, proof of safety, or a reset command. Measured and commanded quantities
retain their declared meaning; no state-to-action mapping is guessed by code.
No two-arm, end-effector or particular embodiment assumption is made. If required
state/semantics are absent, they stay unknown rather than being manufactured.

### Documentation and feedback scope

Benchmark setup/evaluation documentation remains benchmark-owned. V3 consumes
the existing machine-readable public contract; it does **not** automatically
read `EVALUATION_PROTOCOL.md`, mount the benchmark tree or scrape native source.
The full evaluation document can include private schedule/scoring details.
This version has no general channel for additional actor-safe documentation or
per-state provenance beyond the currently declared fields; do not claim it does.

The model receives acknowledged action prefixes/counters and fresh public robot
state. It does not receive arbitrary `control_feedback` payloads: a schema name
alone does not validate their contents. In particular, the historical v2 Dojo
IK-detail projection is absent. The trusted run retains benchmark receipts
according to recording settings, but does not expose them wholesale to the actor.
This feedback change is part of the method, not a change to benchmark sensors
or native scoring; compare methods accordingly.

## Run a predeclared comparison

Start the selected benchmark server using its own README. Explicitly choose the
benchmark, case count and advertised native/development horizon, then run:

```sh
python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark BENCHMARK_ID \
  --control-method codex-direct/v3 \
  --seed SEED --episodes 1 --max-steps ADVERTISED_HORIZON \
  --max-policy-calls DECLARED_CALL_CAP --replan-interval 5 \
  --budget-mode horizon --invalid-action-handling feedback \
  --output-dir AgentPolicies/gpt6_astra/results/BENCHMARK_ID/raw \
  --run-id DATE-TASK-short-description-direct-v3-once
```

Replace uppercase placeholders; this is not an authorization to run a new case.
Use the existing Codex login and pinned CLI, without a separate API key. V3 has
no `--action-guard` or benchmark-specific protocol selector. Required replan
constraints of a selected service remain authoritative; unsupported contracts
must fail before a claim rather than be silently converted.

Counters distinguish policy calls, executed decisions and controls. Available
app-server token deltas are recorded; backend identity and internal provider
request counts are not independently attested. Same-thread network continuations
do not create a new task attempt. Uncertain action delivery remains terminal.
Recording is optional, default enabled, and never changes actor inputs.

Direct and Planned share explicit model-capacity recovery: the pinned app-server
must definitively complete the current turn as failed, with the structured code
`codexErrorInfo: "serverOverloaded"` in that completion or its latest matching
error notification. The runtime waits 30 seconds and starts
another turn in the same thread, using the last acknowledged observation, with
at most nine continuations (ten failed attempts total) between valid action
submissions. This does not restart a task, reset the simulator, change models or
replay an action. An error notification alone, missing closure, uncertain action
state, quota/authentication error or an unrecognized code does not authorize this
recovery. Existing network recovery remains separate. Receipts retain overload
counts and bounded error codes, not raw provider errors; backend-internal retries
and inference request counts remain unknown. Exhaustion is infrastructure failure,
not a native task failure.

## Validation and historical comparison

Offline regression covers heterogeneous numeric actions, arbitrary cameras,
state absence, initial-state isolation, rejected/partial action prefixes,
private-payload exclusion, shared runtime and frozen source auditing. It does
not establish native capability or success-rate parity. New captures use
`model-source/v6`; historical v1–v5 bundles retain their exact inventories.

See [reference comparison](REFERENCE_COMPARISON.md) for the separate historical
Direct v2 baseline and [results](../results/README.md) for actual native samples.
Do not relabel a v2 success, the Planned sample, or an offline check as a v3 result.
