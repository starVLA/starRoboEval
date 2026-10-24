# Simulator integration interface

Each benchmark owns its simulator-facing protocol and adapter here. Each model
implements a policy under `AgentPolicies/<profile>/`. The shared Python types live in
[`benchkit/interfaces.py`](../../benchkit/interfaces.py) and
[`benchkit/contracts.py`](../../benchkit/contracts.py); do not create a different
copy of the policy API for each benchmark or provider.

For independent processes/nodes, use the [SIM server protocol](SERVER_PROTOCOL.md).
The native adapter is instantiated **inside** the benchmark server; the runner
holds `benchkit.sim_server.client.SimServerBenchmarkAdapter`. This retains the
typed interface below without sharing a simulator handle with policy code.

The supported product direction is **direct model control**, not hybrid control.
Do not add a VLA action proposer, learned fallback controller, autonomous task
skill service or hidden human correction between the model and simulator.

The interface standardizes the lifecycle, not robot capabilities. Camera sets,
state channels, action dimensions, coordinate frames, controllers and native
success conditions remain benchmark-specific. A model must declare compatibility
with those conditions instead of receiving an invisible task-solving wrapper.

## Who implements what

| Owner | Interface or artifact | Responsibility |
| --- | --- | --- |
| Benchmark adapter (`bench_server/adapter.py` in RoboDojo) | `BenchmarkAdapter` | Expose the pinned descriptor, observation/action specifications, selected episodes and an episode-session factory. |
| `<benchmark>/server.py` | Independently launched SIM server | Host the native factory, declare runtime supplements and keep native control/scoring private. Shared transport mechanics live in `benchkit/sim_server/`. |
| Benchmark adapter or native worker | `EpisodeSession` | Reset, execute one native control target, return the transition, collect native metrics/artifacts and close resources. |
| Benchmark selection definition (`bench_server/protocol/task_catalog.json` in RoboDojo; `bench_server/protocol/plan.py` where implemented) | Selection plan | Declare the task/variant/state schedule and required runtime resources. Selection is independent of model identity and observed success. |
| `<benchmark>/EVALUATION_PROTOCOL.md` | Native track specification | Explain sensors, actions, horizons, task variants, native scoring, sampling and verified limitations. |
| `AgentPolicies/<profile>/` | Agent method; optional Python `Policy` | Check compatibility, initialize episode memory, produce actions or a permitted stop from declared observations, and clear episode state. |
| Agent-owned trusted driver | Decision loop | Connect to the service, execute the method's chosen action grouping and count calls/controls; Python reference utilities are optional. |
| `benchkit/` | Communication, scheduling and result tools | Supply shared transport, fixed-case scheduling, records, source capture, audits and reports without selecting robot actions. |

RoboDojo's `bench_server/` groups its service adaptation, private worker client
and `protocol/` definitions. `environment/` contains the native runtime. See its
[directory guide](RoboDojo/README.md#directory-responsibilities).

Only the evaluator constructs an adapter or holds its session. The policy is not
given `reset`, `step`, `metrics`, simulator handles, task-state files or a scorer.
An in-process Python interface is an ownership boundary, not an OS sandbox.

## Episode lifecycle

```text
Frozen plan -> adapter.open_episode(EpisodeSpec) -> session.reset()
                                                       |
                                                       v
                   policy.act(permitted Observation) -> PolicyDecision
                                                       |
                                  agent driver executes a bounded prefix
                                                       |
                                  session.step(one native action) -> Transition
                                                       |
                                  next scheduled observation, or native/budget end
                                                       |
                                  native metrics + records + artifacts + cleanup
```

`EpisodeSpec` is evaluator-private. The runner builds the public
`EpisodeContext` for `Policy.start_episode`; never forward reset seeds or layout
metadata wholesale. `Policy.end_episode` clears method state. Optional
`ExecutionAwarePolicy.observe_execution` receives execution counters and any
protocol-declared robot-control receipts, not rewards or private simulator
state. Optional
`ArtifactBoundEpisodeSession.bind_artifact_dir` gives the session a runner-owned
artifact directory before reset.

## Observation and action rules

The adapter must explicitly construct an `Observation` from allowed fields.
Do not pass an upstream observation/info dictionary through unchanged: it may
contain object poses, segmentation, reward, success or reset information.
Document camera resolution/encoding and permitted state channels in the native
protocol; `ObservationSpec` is a compact declaration, not a complete data-leak
checker. The scoring side may retain richer evidence without exposing it to the
policy.

`ActionSpec` declares action dimension/order, bounds, frequency, frame, rotation
and gripper convention. An `ActionChunk` contains those native-contract vectors;
the agent-side driver chooses how many controls to execute before another
decision, subject to the selected track's constraints. Invalid vectors never
execute or undergo silent repair. A declared rejection-feedback track can return
a bounded public issue for a later, counted agent decision; a fail-fast track
ends instead. Neither path replays a control after uncertain execution.

Protocol-fixed units, joint ordering, interpolation and the native low-level
controller belong to the adapter. Visual localization, grasp selection, motion
planning, model-specific IK and voluntary
give-up preferences belong to the model implementation and must respect the
declared interaction budget. Learned auxiliary policies and autonomous task
skill services are outside this repository's direct-control scope.
See [POLICY_PROTOCOL.md](POLICY_PROTOCOL.md).

## Sampling, scoring and reports

Predeclare tasks, variants, layouts or initial states, seeds and attempts per
case. These are separate quantities, not evaluation-mode labels. RoboDojo offers
5-layout and 50-layout selections for `classify_objects`; both cover one task.
Document which selectors the service supports and what randomization they
control. Planned repetitions are not retries selected after a failure.
See [task and case selection](TASK_COVERAGE.md).

The native evaluator decides success. Keep native partial score distinct from
boolean success, and keep unavailable scores null. Record the selected sample
denominator, completed/failed/error/unattempted cases, policy calls, executed
action decisions, native controls and physics ticks where available. A stop
response counts as a policy call but executes no action. Infrastructure checks
remain diagnostics even if their controls happen to trigger native success.

Reports must distinguish direct-control model implementations, observation/action
tracks, native versions and budgets. Hybrid results from external reports are
not direct-control baselines for this repository.
Do not pool different benchmarks' raw scores or treat an external leaderboard
snapshot as a paired rerun. Store report outputs and generated media under
`AgentPolicies/<profile>/results/<benchmark>/`; the reporting implementation belongs to
`benchkit/`. Benchmark documentation must not accumulate model-run diaries.

## Integration acceptance

An adapter contribution needs a pinned upstream evaluator, reproducible
environment/asset instructions, the native protocol, a selected episode plan,
and dependency-light checks for filtering, action semantics, counters, scoring
delegation and cleanup. Registration and runtime source/package allowlists must
include the new extension without recursively capturing assets or results.

Validate from a separate, stable source snapshot. CPU fixtures and a successful
package import do not prove native parity. Any authorized native validation is
a separately recorded run through the same interface, with failures retained.
See the repository [workflow](../../docs/evaluation.md) for current entrypoints
and the individual benchmark's protocol for native readiness.
See [agent-method integration](../../docs/agent-methods.md) for client-side
implementation; this benchmark interface does not require a particular profile.
