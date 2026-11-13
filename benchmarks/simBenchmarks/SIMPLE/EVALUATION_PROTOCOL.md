# SIMPLE evaluation protocol

SIMPLE evaluates sensor-driven whole-body humanoid control through native task
environments and fixed AMO or SONIC low-level controllers. Source revision
`5e3d6f84e85343e34e9bca8d157f0d7813231185` defines the native tasks and controllers.

## Tasks and reset configurations

SIMPLE's [native benchmark](https://psi-lab.ai/SIMPLE/index.html) spans
60 whole-body tasks, 50 indoor scenes and more than 1,000 object assets. Native
task identity, scene configuration, domain-randomization level and released
episode index must be distinguished when defining an evaluation panel.

The [native comparison protocol](https://github.com/physical-superintelligence-lab/SIMPLE/blob/5e3d6f84e85343e34e9bca8d157f0d7813231185/README.md#-simulation-benchmarking-results)
reports ten trials per task at each of three progressively varied distributions:

| Distribution | Changed conditions |
| --- | --- |
| DR0 | Table materials and distractor types/initial positions |
| DR1 | DR0 plus lighting |
| DR2 | DR1 plus target-object initial positions |

For the 12 task packages referenced by this integration, the
[released metadata](https://huggingface.co/datasets/USC-PSI-Lab/psi-data/tree/e78fb93cc28912a3031a10b8656d32d7f0a2b867/simple-eval)
contains ten explicit episode indices 0–9 per level: **30 configurations per
task, 360 across those 12 tasks**.
Episode metadata fixes the reset configuration; a seed is not a replacement for
its task/level/index identity. Report each level separately before aggregating.

## Available service bindings

The [service task inventory](bench_server/protocol/simple_released_tasks.json)
binds 12 registrations, each with only one selectable reset: seed 20260907,
DR0, episode index 0. The [task table](bench_server/protocol/RELEASED_TASK_SCOPE.md)
lists each task, backend, scene and native reference horizon. These bindings
span seven scene entrypoints; other episode indices and DR levels are not exposed.

Select one task/backend per server using `task_names=[task_id]`.
`task_scope="released-12"` permits all 12 tasks; the default `task_scope="pilot"`
permits BendPickMP and OpenFaucetTeleop. The adapter default is BendPickMP.

## Native timing

One public action advances **20 ms at 50 Hz**:

| Backend | Physics per control |
| --- | --- |
| AMO native `g1_wholebody` | 10 × 2 ms |
| SONIC native decoupled WBC | 4 × 5 ms |

AMO initialization uses 60 standing controls. SONIC stabilizes for at most 300
controls while preserving its controller history. These initialization controls
are outside agent execution budgets. Unstable initialization is an environment
error, not a task failure after agent control.

## Observations

- Exact released task language, including its original whitespace.
- One uint8 RGB image, `head_stereo_left`, shape 360×640×3, without resizing,
  cropping or color changes.
- By default, 31 measured joint encoders in radians, ordered as action slots 0–30.

RGB-only input is selectable for the two default-scope tasks; the 12-task
selection requires RGB and joint state. Depth, additional stereo channels,
world/root/EEF pose, object truth, maps, goal poses, reset metadata, native
rewards/success and demonstration actions are excluded from actor inputs.

## Physical 36-dimensional action

Each action contains exactly 36 finite real numbers:

| Slice | Meaning and order | Units |
| --- | --- | --- |
| `0:7` | Left hand: thumb 0/1/2, middle 0/1, index 0/1 | Absolute joint radians |
| `7:14` | Right hand: thumb 0/1/2, index 0/1, middle 0/1 | Absolute joint radians |
| `14:21` | Left arm: shoulder pitch/roll/yaw, elbow, wrist roll/pitch/yaw | Absolute joint radians |
| `21:28` | Right arm in the same order | Absolute joint radians |
| `28:31` | Waist roll/pitch/yaw | Absolute joint radians |
| `31` | Base height | Meters |
| `32:34` | Native forward/lateral velocity commands | Meters per second |
| `34` | AMO turning flag or SONIC turning gate | Backend control flag, not yaw rate |
| `35` | Target heading | Radians |

Joint commands use native G1 joint coordinates. AMO heading is relative to the
controller's initial orientation; SONIC heading uses native world-frame base
yaw. Forward/lateral inputs pass unchanged to each native controller; their
world/body-frame mapping is not established by the current interface.
They are not normalized EEF deltas. Hands use individual joint targets rather
than a single open/close scalar. The exact turn semantics and physical mechanism
ranges are in [the action reference](bench_server/protocol/POLICY_GUIDE.md).

Invalid dimensions, booleans and non-finite values are rejected without
execution. Finite joint targets reach native control without an additional
service-side range gate or clipping. Native actuator limits, PD behavior and
controller conversions remain unchanged. Optional motion guards belong to the
agent; no task-solving controller is added.

AMO receives native navigation/height commands and stabilized torso orientation
separately from the commanded waist targets. SONIC receives upper-body targets,
navigation commands and height through native `ActionCmd("decoupled_wbc")`.
These fixed controller conversions do not plan the task.

## Budget and native scoring

For the 12 service-bound tasks, native reference horizons are **400, 800, 1,000
or 1,200 controls**. Native scoring consumes the step's reward/`_success` result without an
extra scorer query: some predicates, including faucet behavior, are stateful.

By default, `budget_mode="horizon"` uses the selected task's metadata horizon
for all 12 service bindings. A method chooses its decision frequency and action
groups in its own driver; this mode does not accept service-side
`max_policy_calls` or `replan_interval` values. Every public `step` still executes
one native control. Native success or termination can end before the horizon.

| Budget selection | Actual control cap | Configuration |
| --- | ---: | --- |
| `budget_mode="horizon"` (default) | Task's native reference horizon | No service-side call/prefix limits |
| `budget_mode="decisions"` | 1,000 | Fixed `max_policy_calls=200`, `replan_interval=5` |

The default contract uses `native-horizon-<N>/v3`. The explicit decisions
selection retains `decision-200-prefix-5/v2` and defaults its two fixed settings
when omitted. Its 1,000-control cap extends 400/800-control tasks and shortens the
1,200-control task; it is not the native-horizon protocol. These track-specific
settings are not native SIMPLE requirements on reasoning. Actual decisions
cannot be inferred from controls by dividing by a prefix length.

Here, native reference horizon means the task metadata value, not a universal
setting shared by every upstream evaluation script. External evaluators may
select a different execution cap; report that cap separately.

## Scoring and result statistics

Report the selected task/reset, backend, sensors, native horizon and actual cap;
native success; actual decisions and controls; and the stop reason.
Across tasks, give trial counts and success counts per task and DR level before
an aggregate.

Keep native failure, voluntary stop, external truncation and infrastructure
error distinct.
Optional interaction/video recording uses
[shared recording settings](../../../docs/recording.md).

## Environment requirements

Runtime, source patches, controller weights, robot assets, released reset
metadata and scene dependencies must match the selected installation.
See [preparation and launch](README.md#prepare-the-environment). Asset
portability is incomplete, and native controller contexts may span multiple
visible GPUs. An available task definition does not by itself install its scene.
