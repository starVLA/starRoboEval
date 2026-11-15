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

[The adapter](bench_server/adapter.py) exposes the target scene split only,
with task IDs as target-set ordinals 0–49 (4=NavigateKitchen, 6=OpenDrawer).
The launch seed is always 20260907. In `fast`, every case uses that seed, so all
attempts on a task share one natively sampled scenario. In `max`, scenario `k`
of every task resets with seed 20260907 + `k`. See
[service support](../SERVICE_SUPPORT.md).

| `evaluation_mode` | Tasks | Scenario / attempts | Episodes |
| --- | --- | --- | ---: |
| `fast` (default) | All 50 | Seed 20260907, attempts 1–5 | 250 |
| `max` | All 50 | Scenarios 0–49, seed 20260907 + scenario, one attempt each | 2500 |
| `example` | Task 0 | Seed 20260907, attempt 1 | 1 |

`fast` is ordered by attempt and `max` by scenario. `fast` uses
`robocasa365-target50-task{TT}-attempt{AA}` for attempt 1 over tasks 0–49, then
attempt 2, and so on. `max` uses `robocasa365-target50-task{TT}-scenario{KK}`
for scenario 00 over tasks 0–49, then scenario 01, through scenario 49.
`--episodes` selects a prefix and `--episode-id` selects cases within the chosen
mode. There is no public layout/style override or seed selector. The native
sampler determines the actual kitchen/object placement, so seed and layout are
not interchangeable identifiers.

The descriptor protocol is
`robocasa365-b4684e6/target50-single-scenario-native-horizons/rgb/{mode}/v1`
for `fast` and `example`, and
`robocasa365-b4684e6/target50-seeded-scenarios-native-horizons/rgb/max/v1`
for `max`, both with `native-v1`; the other tracks extend the `rgb` segment as
listed below. Its step cap is the largest reference horizon in the schedule
(4350 for both fast and max);
each episode still stops at its own task's reference horizon. That per-task cap
is the episode metadata's `environment_step_cap`, and the runner uses it as the
episode's control budget, so the policy's remaining controls are per task.

The pinned dataset registry has horizon metadata for 317 task entries
(65 atomic, 252 composite); 48 implemented composite classes lack that metadata.
The service does not invent horizons for them or expose all 365 classes as an
executable evaluation schedule.

## Environment and reset

Pin RoboCasa 1.0.1 at `b4684e6ee37d377cc392e98302a6b916d588b415`, Robosuite 1.5.2 at `85abee228d1c43ab1939bce33028099945d453b4`, MuJoCo 3.3.1 and NumPy 2.2.5. Each imported native package must resolve to its own clean Git root. See [setup](README.md).

Rendering is an explicit protocol choice:

| `render_track` | Meaning and result identity |
| --- | --- |
| `native-v1` | Default native renderer, observation segment `rgb`; the pinned EGL lifecycle defect is present |
| `egl-owner-restore-v1` | Linux/EGL ownership and readback checks; observation segment `rgb-egl-owner-restore` |
| `egl-owner-material-clamp-v1` | Ownership repair plus temporary clamping of finite out-of-range scene shininess; observation segment `rgb-egl-owner-material-clamp` |

The first two tracks preserve the native scene/camera/pixel operations. The
third, selected by the service example, **can change pixels** and is not
native-pixel-equivalent. It restores materials after drawing and does not
change physics, task sampling, reset count, controls or scoring. Compare results
with matching rendering settings. Use a fresh single-thread process; tracks
cannot be mixed in one process. Setup and renderer details are in
[environment/RENDERING.md](environment/RENDERING.md).

Every selected reset uses the target split and the episode's seed: 20260907 in `fast`/`example`, 20260907 + scenario in `max`. Native construction may initialize a scene before the explicit seeded reset; retain this upstream behavior and record the actual reset. Do not search seeds, replace assets, resample initial success or force an easier kitchen.

### Max-mode scenarios

The upstream evaluation script that the RoboCasa benchmarking docs link to,
`scripts/run_eval.py` in the GR00T `robocasa-benchmark` fork (inspected at
`9d7d7a9eb7ad30bd8ce30448d9ab53a918b45b10`), runs `--n_episodes` 50 per task
with `max_episode_steps` from the task horizon. Its `gr00t/eval/simulation.py`
constructs the environment and resets it without a seed, so its 50 scenarios
are an unseeded random stream that cannot be replayed.

`max` replaces that stream with a deterministic stand-in. Each episode
constructs a fresh environment and passes seed 20260907 + `k` to native
construction and `reset(seed=...)`. In the pinned RoboCasa, `RoboCasaGymEnv.reset`
sets the kitchen's `rng` from that seed. The kitchen then draws (layout, style)
from the target pairs that remain after the task's `EXCLUDE_LAYOUTS` and
`EXCLUDE_STYLES`, and the native samplers place objects. The adapter never
forces a layout, style or object. The drawn layout and style are recorded in
evaluator-side native provenance only; the scenario index and launch seed are
also in the episode metadata.

Distinct seeds do not guarantee distinct kitchens. The target split has only
ten kitchens, and some tasks exclude several, so the 50 scenarios of one task
repeat kitchens and vary mainly in object selection and placement. That
seed-to-scene determinism is from source inspection, not a replay check.
`max` results are comparable with each other. They match the upstream
procedure in task set, scenario count, horizons and scoring, but not in the
exact scenarios drawn.

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

Base mode does not zero the other command dimensions. Preserve the native X-forward base transformation and native controller clipping behavior; do not insert a different frame conversion or high-level policy heuristic. Reject malformed, non-finite, out-of-bound or non-binary public commands instead of thresholding binary fields; a fractional `[6]` or `[11]` is an ordinary action rejection before execution, not a session fault.

## Budgets and native scoring

The native engine retains horizon 1000 with `ignore_done=True`. The adapter instead enforces the task reference horizon: OpenDrawer 750 and NavigateKitchen 450. Target-set reference horizons range from 450 to 4350; 33 exceed 1000. The service sets no policy-call or per-decision control limit; a trusted driver's own limits or step-cap override are recorded with the run, not reported as native leaderboard parity.

Native Gym returns `info.success` and sparse reward 1/0; require their agreement. Preserve native reward/scorer invocation multiplicity without an additional oracle query. Stop at first native success. Keep current native success, success-ever, termination and truncation distinct. Initial native success is an error before policy control, not a reset-search opportunity.

Count policy calls, action decisions and controls independently. A stop-only response has no action decision; a chunk can execute fewer controls than it proposes. Record first-success control and its policy-call index from events. Voluntary-stop persistence belongs to the model profile and cannot delay evaluator caps or native termination.

## Results and sample coverage

Report the evaluation mode, selected cases, seed, rendering and budget settings, native
success, decisions, controls and termination/error reason. Success rate uses the
declared selected cases; distinguish native failures from infrastructure errors
and unattempted cases. Per-task reference horizons can differ, so report the
actual cap as well as the reference.

The service supports target50 with one seeded scenario per task and repeated
attempts (`fast`), or 50 seeded scenarios per task (`max`). It does not replay
upstream's unseeded scenario stream or expose the other 315 implemented task
names. Exact source/asset and rendering
requirements are in [environment setup](environment/README.md).

Optional interaction/media retention is described in
[recording](../../../docs/recording.md); it does not change inputs, controls or
native scoring.
