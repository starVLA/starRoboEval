# RoboCasa365 evaluation protocol

This document describes RoboCasa365's native task and scene definitions, then
the selection and robot interface implemented by the `robocasa365` service.
This is not the GR1 Tabletop benchmark.

## Tasks, kitchen candidates and sample selection

The native collection has **365 tasks: 65 atomic and 300 composite**. Atomic
tasks isolate skills; composite tasks combine them into household activities.
The official [atomic](https://robocasa.ai/docs/build/html/tasks/atomic_tasks.html)
and [composite](https://robocasa.ai/docs/build/html/tasks/composite_tasks.html)
indexes describe this collection. The task set and scene split are independent
evaluation choices; neither a dataset entry nor a sampled kitchen is a new task.

The native `target50` task set is:

| Target split | Tasks |
| --- | ---: |
| Atomic seen | 18 |
| Composite seen | 16 |
| Composite unseen | 16 |
| Total target set | 50 |

The native registry also defines `pretrain300` and lifelong-learning task sets;
these named sets are not a disjoint partition of the 365 task classes. The pinned
[registry](https://github.com/robocasa/robocasa/blob/b4684e6ee37d377cc392e98302a6b916d588b415/robocasa/utils/dataset_registry.py)
defines membership. [robocasa365_target50.json](bench_server/protocol/robocasa365_target50.json)
provides the target ordering and native horizons locally.

Native `split="target"` uses ten paired kitchens, (layout, style) pairs (1,1)
through (10,10), and target objects. `split="pretrain"` uses layout IDs 11–60
crossed with style IDs 11–60: 2500 candidate kitchens and a separate object
split. Layouts set fixture arrangement; styles set visual appearance and fixture
attributes. Individual task exclusions still apply. Object selection and
placement add variation within a kitchen. See the official
[scene definitions](https://robocasa.ai/docs/build/html/assets/scenes.html).

The [native evaluation rule](https://robocasa.ai/docs/build/html/benchmarking/benchmarking_overview.html)
is 50 randomly sampled scenarios per evaluated task and mean binary task
success. The complete `target50` schedule therefore contains 2500 scenarios.
Reference horizons come from each task's pinned registry entry, not a uniform
cap shared by every task.

## Current Bench Server selection

[The adapter](bench_server/adapter.py) exposes the target scene split only.
The default `task_scope="pilot"` uses local indices 0=OpenDrawer and
1=NavigateKitchen; `task_scope="target50"` uses target-set ordinals, including
4=NavigateKitchen and 6=OpenDrawer. See [service support](../SERVICE_SUPPORT.md).

The current service selects one scenario per chosen task at seed 20260907.
`task_ids` must be an increasing, unique subset of the chosen scope's indices;
an episode limit selects a prefix without repeating tasks. There is no public
layout/style override, arbitrary seed selector or multi-seed panel. The native
sampler determines the actual kitchen/object placement, so seed and layout are
not interchangeable identifiers. The 50-scenario-per-task reference schedule
needs additional sampling support; selecting all 50 task names gives 50 cases,
not 2500 cases or coverage of all 365 implemented tasks.

The `task_ids` default is `[0,1]` in either scope. Selecting `target50` changes
the index namespace, not the selected list length; supply all desired indices
explicitly before launching.

The pinned dataset registry has horizon metadata for 317 task entries
(65 atomic, 252 composite); 48 implemented composite classes lack that metadata.
The service does not invent horizons for them or expose all 365 classes as an
executable evaluation schedule.

## Environment and reset

Pin RoboCasa 1.0.1 at `b4684e6ee37d377cc392e98302a6b916d588b415`, Robosuite 1.5.2 at `85abee228d1c43ab1939bce33028099945d453b4`, MuJoCo 3.3.1 and NumPy 2.2.5. Each imported native package must resolve to its own clean Git root. See [setup](README.md).

Rendering is an explicit protocol choice:

| `render_track` | Meaning and result identity |
| --- | --- |
| `native-v1` | Default native renderer, descriptor suffix `/v1`; the pinned EGL lifecycle defect is present |
| `egl-owner-restore-v1` | Linux/EGL ownership and readback checks; suffix `/egl-owner-restore-v1/v2` |
| `egl-owner-material-clamp-v1` | Ownership repair plus temporary clamping of finite out-of-range scene shininess; suffix `/egl-owner-material-clamp-v1/v3` |

The first two tracks preserve the native scene/camera/pixel operations. The
third, selected by the service example, **can change pixels** and is not
native-pixel-equivalent. It restores materials after drawing and does not
change physics, task sampling, reset count, controls or scoring. Compare results
with matching rendering settings. Use a fresh single-thread process; tracks
cannot be mixed in one process. Setup and renderer details are in
[environment/RENDERING.md](environment/RENDERING.md).

The selected reset uses seed 20260907 and the target split. Native construction may initialize a scene before the explicit seeded reset; retain this upstream behavior and record the actual reset. Do not search seeds, replace assets, resample initial success or force an easier kitchen.

## Observation contract

Expose native task language and three uint8 256 × 256 RGB cameras in order: left agent view, right agent view and eye-in-hand. Preserve the native Gym vertical flip; apply no extra crop, resize or policy-specific preprocessing. The exact camera keys are in the adapter observation specification.

This track has no proprioception. Do not expose object/world or end-effector ground truth, camera calibration, scene/reset metadata, reward/success or simulator handles. Only the evaluator can inspect native provenance and scorer state.

## Twelve-dimensional action

The native 20 Hz controller is `HYBRID_MOBILE_BASE`, with right-arm `OSC_POSE`, torso `JOINT_POSITION` and base `JOINT_VELOCITY_LEGACY`.

| Slice | Contract |
| --- | --- |
| `[0:3]` | Normalized current-base-frame end-effector translation, ±0.05 m |
| `[3:6]` | Normalized base-frame axis-angle delta, ±0.5 rad |
| `[6]` | Exact binary gripper: 0 open, 1 close; maps to native -1/+1 |
| `[7:10]` | Normalized native base forward/lateral/yaw velocity; scales ±1 m/s, ±1 m/s, ±1.5 rad/s |
| `[10]` | Normalized torso delta, ±0.05 m; native joint range 0–0.34 m |
| `[11]` | Exact binary base mode: 0 arm/achieved-goal update, 1 base/desired-goal update |

Base mode does not zero the other command dimensions. Preserve the native X-forward base transformation and native controller clipping behavior; do not insert a different frame conversion or high-level policy heuristic. Reject malformed, non-finite, out-of-bound or non-binary public commands instead of thresholding binary fields.

## Budgets and native scoring

The native engine retains horizon 1000 with `ignore_done=True`. The adapter's `budget_mode="horizon"` instead enforces the task reference: OpenDrawer 750 and NavigateKitchen 450. Target-set reference horizons range from 450 to 4350; 33 exceed 1000.

The explicit decision track permits D up to 200 maximum policy calls and K up to 5 controls per response, with cap D × K and matching runner settings. D=200/K=5 gives 1000 controls; it both extends and shortens different native task references. Record actual budgets and references separately, not as native leaderboard parity.

Native Gym returns `info.success` and sparse reward 1/0; require their agreement. Preserve native reward/scorer invocation multiplicity without an additional oracle query. Stop at first native success. Keep current native success, success-ever, termination and truncation distinct. Initial native success is an error before policy control, not a reset-search opportunity.

Count policy calls, action decisions and controls independently. A stop-only response has no action decision; a chunk can execute fewer than K controls. Record first-success control and its policy-call index from events. Voluntary-stop persistence belongs to the model profile and cannot delay evaluator caps or native termination.

## Results and sample coverage

Report the selected scope/task IDs, seed, rendering and budget settings, native
success, decisions, controls and termination/error reason. Success rate uses the
declared selected cases; distinguish native failures from infrastructure errors
and unattempted cases. Per-task reference horizons can differ, so report the
actual cap as well as the reference.

The service supports the two-task list or target50, each with one sample at
seed 20260907. It does not implement the native 50-scenario-per-task sampler or
the other 315 implemented task names. Exact source/asset and rendering
requirements are in [environment setup](environment/README.md).

Optional interaction/media retention is described in
[recording](../../../docs/recording.md); it does not change inputs, controls or
native scoring.
