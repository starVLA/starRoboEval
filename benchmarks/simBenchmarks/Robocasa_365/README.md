# RoboCasa365

RoboCasa365 evaluates mobile manipulation in kitchen environments: reaching
fixtures, operating appliances and containers, and completing tasks with kitchen
objects. Its task collection combines atomic skills with multi-stage household
activities. It is separate from the GR1 [RoboCasa Tabletop](../Robocasa_tabletop/README.md)
benchmark.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): task selection, reset conditions,
  exact observation/action semantics, budgets and scoring.
- [Environment setup](environment/README.md): pinned sources, assets, rendering
  tracks and readiness tools.
- [Target task catalog](bench_server/protocol/robocasa365_target50.json): ordered
  task IDs, split membership and reference horizons.
- [Shared service protocol](../SERVER_PROTOCOL.md): connection and lifecycle.

## Native tasks, kitchens and evaluation

RoboCasa365 defines **365 tasks: 65 atomic and 300 composite**. Atomic tasks
cover skills such as opening a drawer, navigating a kitchen and operating an
appliance; composite tasks combine skills into longer activities. Browse the
official [atomic tasks](https://robocasa.ai/docs/build/html/tasks/atomic_tasks.html)
and [composite tasks](https://robocasa.ai/docs/build/html/tasks/composite_tasks.html).

Task identity and scene split are separate choices. The native `target50` task
set contains 18 atomic seen, 16 composite seen and 16 composite unseen tasks;
it is one benchmark task set, not the entire 365-task collection. The native
registry also defines pretraining and lifelong-learning task sets. The
[target catalog](bench_server/protocol/robocasa365_target50.json) lists all 50
target tasks and their reference horizons.

| Native scene split | Kitchen design | Other variation |
| --- | --- | --- |
| `pretrain` | 50 layouts × 50 styles = 2500 candidate kitchens | Pretraining objects and sampled placements |
| `target` | Ten fixed layout/style pairs, (1,1) through (10,10) | Disjoint target objects and sampled placements |

Layouts define fixture arrangement; styles define appearance and fixture
attributes. Task-specific exclusions can reduce the eligible kitchens. These
are scene candidates, not additional task names, and a seed is not a layout ID.
See the official [scene definitions](https://robocasa.ai/docs/build/html/assets/scenes.html).

Native evaluation randomly samples **50 scenarios per task**, uses that task's
reference horizon and reports mean binary task success. Evaluating all 50 target
tasks therefore calls for 2500 scenarios. See the
[native evaluation rules](https://robocasa.ai/docs/build/html/benchmarking/benchmarking_overview.html).

## Current Bench Server integration

The service uses native PandaOmron control and scoring, but currently samples
only one scenario per selected task at launch seed **20260907**. It does not
expose the native repeated-scenario sampler, pretraining split or arbitrary
layout/style selection. See [service support](../SERVICE_SUPPORT.md).

| `task_scope` | Selectable task indices |
| --- | --- |
| `pilot` | `0=OpenDrawer`, `1=NavigateKitchen` |
| `target50` | 0–49 in the target catalog |

`task_ids` is an increasing, unique subset of the chosen scope's indices. Indices
are scope-specific: NavigateKitchen is 1 in `pilot` and 4 in `target50`;
OpenDrawer is 0 and 6 respectively.

The service currently exposes neither a layout/style override nor a seed panel:
each selected task gets one sample at the fixed seed. A larger `--episodes`
value cannot create repetitions beyond the selected task list. Additional
scenarios require an explicit extension of the sampling interface.

Set `task_ids` explicitly when changing scope. Omitting it selects indices
`[0,1]` in either scope; setting `task_scope="target50"` alone does not select
all 50 tasks. For example, `task_scope="target50", task_ids=[4,6]` selects
NavigateKitchen and OpenDrawer. Launch with `--episodes 2` for those two cases;
the same two IDs under the default scope would be invalid.

## Service robot interface and scoring

| Property | Published contract |
| --- | --- |
| Observation | Native task language and three 256 × 256 RGB cameras: left/right agent view and wrist view; no proprioception |
| Action | 12 values: base-frame end-effector translation/rotation deltas, binary gripper, base velocity, torso delta and binary base mode |
| Control | Native hybrid mobile-base controller at 20 Hz; one action per service step |
| Success | Native `info.success`, checked against sparse native reward; stop at first native success |
| Native-reference budget | `budget_mode="horizon"`: task-specific reference horizons, 450–4350 controls across target50 |
| Separate development budget | `budget_mode="decisions"`: declared calls D ≤ 200 and prefix K ≤ 5, with cap D × K |

The **12-dimensional action** uses these zero-based slices:

| Slots | Meaning, frame and units |
| --- | --- |
| 0–2 | Relative EEF translation in the current robot-base frame; normalized [-1,1], scale 0.05 m |
| 3–5 | Relative EEF axis-angle rotation in the base frame; normalized [-1,1], scale 0.5 rad |
| 6 | Exact binary gripper: 0 open, 1 close |
| 7–9 | Base forward/lateral/yaw velocities in the current base frame; normalized [-1,1], scales 1 m/s, 1 m/s, 1.5 rad/s |
| 10 | Relative torso joint displacement; normalized [-1,1], scale 0.05 m |
| 11 | Exact binary base mode: 0 achieved-arm-goal update, 1 desired-arm-goal update |

One vector advances one native 50 ms control. Mode selection does not zero
the other command fields. The controller applies its native scaling and limits;
the protocol specifies the exact accepted command bounds.

The native engine has horizon 1000 with `ignore_done=True`; this is distinct from
the task reference horizon. OpenDrawer's reference is 750 and NavigateKitchen's
is 450. The decision-budget track can shorten or extend those references and
must be reported separately. It retains a coupled budget contract; it is not a
universal rule for how often an agent must reason.

Only the declared language and camera images reach the agent. Object state,
reset details and native scoring stay on the evaluator side. Native controller
conversion is fixed by the protocol; prompts, planning, memory and action
grouping belong to the participant method.

## Start the benchmark service

Complete [environment setup](environment/README.md), then copy
[server.example.json](server.example.json) to an operator-owned file. Select the
GPU, task scope/IDs, rendering track and budget before launch. The supplied
example selects NavigateKitchen under `pilot`, the explicit
`egl-owner-material-clamp-v1` visual track, and D=200/K=5 (1000 controls).
To use its **450-control native reference**, change `budget_mode` to `horizon`
and remove `max_policy_calls` and `replan_interval` from that copy.

Supply `RSI_SIM_SERVER_TOKEN` privately to the server and trusted evaluator as
described in the [connection guide](../SERVER_PROTOCOL.md#launch-and-connect).
From the repository root, using the prepared native environment:

```sh
MUJOCO_GL=egl PYOPENGL_PLATFORM=egl python -B \
  -m benchmarks.simBenchmarks.Robocasa_365.server \
  --parameters /absolute/robocasa365-server.json \
  --seed 20260907 --episodes 1 --port 8765 \
  --output-dir /absolute/new-robocasa365-run/server
```

The service fixes the selected schedule without resetting the simulator. It
binds to loopback; use SSH forwarding for a remote evaluator. Connect a trusted
driver implementing the shared service protocol; no particular model, prompt or
agent package is required. Each selected case has one attempt, with failure and
infrastructure errors retained separately. Unknown control acknowledgements
must not be replayed.

## Results

Report the selected task scope/IDs, seed, rendering and budget tracks, native
outcomes, actual decisions and controls, and errors. Keep agent configuration,
usage and optional interaction/media records with the participant's results;
see [result and recording guidance](../../../docs/evaluation.md#inspect-and-report).
State the selected tasks and sampling conditions; task-name coverage alone does
not reproduce the native scenario distribution.

## Runtime requirements

Rendering configurations are not interchangeable: `egl-owner-material-clamp-v1` can
change pixels, while `egl-owner-restore-v1` repairs EGL ownership without that
material conversion. Native packages/assets require exact pins, and no complete
portable asset installer is provided. Verify the selected deployment before
evaluation; a listening service alone does not establish rendering readiness.

## Directory responsibilities

`server.py` is the public launcher. `bench_server/adapter.py` implements the
sensor/action/scoring contract; `bench_server/protocol/` holds task catalogs and
selection plans. `environment/` contains native readiness and rendering tools.
Deployment settings are operator-owned; participant methods and their results
live outside this benchmark package.
