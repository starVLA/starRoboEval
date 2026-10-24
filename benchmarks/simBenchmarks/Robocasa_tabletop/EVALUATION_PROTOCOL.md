# RoboCasa GR1 Tabletop evaluation protocol

This protocol defines the official GR1 Tabletop task set and native variation,
then the sampling and robot interface of the `robocasa_tabletop` service. The
[robot contract](bench_server/protocol/robocasa_tabletop_contract.json) specifies
controller limits, encoder identities and source pins.

## Native task catalog

The official set has **24 tasks**: six container-closing tasks and eighteen
`PosttrainPnPNovel...SplitA` tasks. Other registered pretraining and
`Eval...SplitB` tasks are outside this set. Native environment IDs are
`gr1_unified/<task>_GR1ArmsAndWaistFourierHands_Env`.

The packaged [task catalog](bench_server/protocol/task_catalog.json) preserves the
exact order in the
[pinned official task list](https://github.com/robocasa/robocasa-gr1-tabletop-tasks/blob/4840e671596f93ca03651524b9f72ffb1aadfeff/README.md#simulation-based-evaluation-for-gr00t-n15-3b):

| Index | Native task class | Candidate layout |
| --- | --- | ---: |
| 0 | `PnPCupToDrawerClose` | 4 |
| 1 | `PnPPotatoToMicrowaveClose` | 2 |
| 2 | `PnPMilkToMicrowaveClose` | 2 |
| 3 | `PnPBottleToCabinetClose` | 5 |
| 4 | `PnPWineToCabinetClose` | 5 |
| 5 | `PnPCanToDrawerClose` | 4 |
| 6 | `PosttrainPnPNovelFromCuttingboardToBasketSplitA` | 0 |
| 7 | `PosttrainPnPNovelFromCuttingboardToCardboardboxSplitA` | 0 |
| 8 | `PosttrainPnPNovelFromCuttingboardToPanSplitA` | 0 |
| 9 | `PosttrainPnPNovelFromCuttingboardToPotSplitA` | 0 |
| 10 | `PosttrainPnPNovelFromCuttingboardToTieredbasketSplitA` | 0 |
| 11 | `PosttrainPnPNovelFromPlacematToBasketSplitA` | 0 |
| 12 | `PosttrainPnPNovelFromPlacematToBowlSplitA` | 0 |
| 13 | `PosttrainPnPNovelFromPlacematToPlateSplitA` | 0 |
| 14 | `PosttrainPnPNovelFromPlacematToTieredshelfSplitA` | 0 |
| 15 | `PosttrainPnPNovelFromPlateToBowlSplitA` | 0 |
| 16 | `PosttrainPnPNovelFromPlateToCardboardboxSplitA` | 0 |
| 17 | `PosttrainPnPNovelFromPlateToPanSplitA` | 0 |
| 18 | `PosttrainPnPNovelFromPlateToPlateSplitA` | 0 |
| 19 | `PosttrainPnPNovelFromTrayToCardboardboxSplitA` | 0 |
| 20 | `PosttrainPnPNovelFromTrayToPlateSplitA` | 0 |
| 21 | `PosttrainPnPNovelFromTrayToPotSplitA` | 0 |
| 22 | `PosttrainPnPNovelFromTrayToTieredbasketSplitA` | 0 |
| 23 | `PosttrainPnPNovelFromTrayToTieredshelfSplitA` | 0 |

## Native initialization and reference evaluation

Each task retains the single layout above and all **12 style candidates
(0–11)**. Native RNG selects the style, objects and placements; style repetition
is allowed. Task identity, layout, style and sampled placement are separate
dimensions. Changing a seed does not create a new task or guarantee a new layout.

The pinned upstream evaluation example runs ten episodes per task with
`max_episode_steps=720` and five parallel environments. Parallel environment
count is not a task or layout count. This is an example configuration, not an
exhaustive enumeration of object/placement combinations. Native task predicates
determine binary success; scorer details appear below.

## Current Bench Server selection

The [adapter](bench_server/adapter.py) exposes these task lists; see
[service support](../SERVICE_SUPPORT.md) for the integration boundary.

| `task_scope` | Official task indices | Seed selection |
| --- | --- | --- |
| `pilot` (default) | 0, 19 | Fixed 20260907 |
| `tabletop-next-pair-v1` | 1, 2 | Fixed 20260907 |
| `tabletop24-seeded-v1` | Increasing unique subset of 0–23, default all | One to five explicit distinct uint32 seeds |

Select `task_scope="tabletop24-seeded-v1"`, `budget_mode="horizon"`, and
`episode_seeds` containing **one to five distinct uint32 integers** (0 through
4294967295). Seeds are mandatory and frozen before evaluation; there is no
automatic or outcome-driven selection. `task_ids` is an increasing, unique
subset of indices 0–23, defaulting to all 24. The launch `--seed` must equal
the first entry of `episode_seeds`.

The schedule is **sample-major, task-minor**: every selected task once with the
first seed, then every task with the second seed, and so on. An explicit episode limit selects only a
prefix; reports must retain that selected denominator. A one-task, one-seed
service is also permitted for externally predeclared schedules, using the same
native constructor and reset logic.

Five seeds are **not five distinct layouts**. Each task has the single candidate
layout listed above and all 12 style candidates. Native RNG selects styles,
objects and placements; repeated styles are permitted. The first and subsequent
samples all retain one fresh constructor followed by one explicit seeded reset,
without reset-search or success-screening. Actual selections are retained
privately, never projected to the policy.

The service records the selected task/seed schedule and control cap in its
protocol identity. The two pair selectors reject `episode_seeds` and use seed
20260907.

The reported denominator is the selected task IDs × declared seeds, or its
explicitly selected prefix. This sampler does not enumerate every native
object placement or reproduce the upstream ten-episode example.

## Environment and reset

Pin RoboCasa GR1 revision `4840e671596f93ca03651524b9f72ffb1aadfeff` and Robosuite revision `51cc01785bab80ffeed20da15e67d7dd4140e76a`. The runtime has been pinned with Python 3.10.21. Set `PYTHONHASHSEED=0` before Python starts; the adapter checks a hash sentinel.

The two pair selections use seed 20260907; the 24-task selection
uses each predeclared `episode_seeds` value. Both pass that episode seed to the
fresh native constructor and the one explicit seeded reset. Native constructor
initialization is retained. The pinned Gym reset seeds NumPy's global RNG;
it does not replace the constructor's environment RNG with a new generator.
The pinned Gym factory does not forward its layout/style arguments, so the
adapter does not claim to force actual style. Preserve the task
`VALID_LAYOUTS × 12 styles` candidate set and record actual native selection privately.

Do not reset-search, success-screen, substitute assets or shrink the object library. Reset-time native success is an error before policy control, not a reason to resample. Setup and the bounded asset-snapshot limitation are described in [environment/README.md](environment/README.md).

Deployment uses `render_gpu_device_id` for the NVML resource-occupancy check and
optional `egl_device_id` for EGL renderer selection. Omitted EGL selection
defaults to the NVML index. Operators must verify
their physical-device mapping with a renderer-only UUID / PCI preflight before
claiming a task; the two enumeration orders are not assumed equivalent.
Both indices are recorded privately. This deployment setting changes no task
selection, sensor/action semantics, budget or scoring. See the
[renderer configuration guide](README.md#nvml-resource-index-and-egl-renderer-index).

## Observation allowlist

- One uint8 256 × 256 RGB image, `ego_view_bg_crop_pad_res256_freq20`.
- Native `annotation.human.coarse_action` language, including `unlocked_waist:`.
- Exactly 29 measured joint encoders in radians: left arm 7, right arm 7, left hand 6, right hand 6, waist 3.

The native image pipeline vertically flips a 1280 × 800 egoview, crops rows 310:770 and columns 110:1130, resizes to 720 × 480, pads to square, then resizes to 256 × 256. Copy that output without additional model-specific image or state transforms.

Hand encoder order is pinky, ring, middle, index intermediate joints, thumb proximal pitch and thumb yaw. Exact identities are in the contract's `state.parts`. Observation metadata is empty. No extra cameras, depth, object or end-effector ground truth, world root pose, calibration, reward/success, reset metadata or simulator handles cross the policy boundary.

## Absolute 29-dimensional joint action

One action contains absolute joint-position targets in radians at 20 Hz, using the native BASIC composite controller. It is not Cartesian motion, normalized [-1,1] output or joint velocity.

| Slice | Order | Bounds in radians |
| --- | --- | --- |
| Left arm [0:7] | Shoulder pitch/roll/yaw, elbow pitch, wrist yaw/roll/pitch | Low [-3,0,-3,-3,-3,-1.5,-1.5]; high [3,3,3,0,3,1.5,1.5] |
| Right arm [7:14] | Same joint order | Low [-3,-3,-3,-3,-3,-1.5,-1.5]; high [3,0,3,0,3,1.5,1.5] |
| Hands [14:20], [20:26] | Pinky, ring, middle, index, thumb pitch/yaw | Low all 0; high [1.57,1.57,1.57,1.57,1.22,1.74] |
| Waist [26:29] | Yaw/pitch/roll | Low [-1.05,-0.52,-0.7]; high [1.05,1.22,0.7] |

Each hand expands six commands to eleven actuators using [0,0,1,1,2,2,3,3,4,4,5]; bounds intersect coupled joint and actuator ranges. The adapter rechecks compiled mappings, limits and ordinary encoder identities after reset. Invalid commands are rejected, not clipped, rescaled, passed through IK or replaced by heuristics. Evaluator-only measured hold generation is not a policy action service.

## Budgets and scoring

For new service deployments, explicitly select `budget_mode="horizon"` and
`control_step_cap=1000`. A positive integer cap at most 1000 is allowed;
the selected cap is recorded in the protocol identity. The
service publishes `max_policy_calls=null` and `replan_interval=null`: the
policy/method chooses chunk length and the trusted driver may declare its own
call or replan limit. Each service step still executes one native control;
native success/termination and the selected total cap stop execution even in
the middle of a chunk. Service decision-limit parameters cannot be combined
with this track.

The omitted/default `budget_mode="decisions"` uses the
200-call, prefix-5, D × K control budget. It accepts D=1..200 and K=1..5.
`control_step_cap` is not accepted in that track.
These two budget identities must not be pooled as one protocol.

The native engine stays at horizon 1000 with `ignore_done=True`. This engine
setting is distinct from an evaluator's chosen execution budget and repetitions.
The pinned upstream README's external Isaac-GR00T example specifies
`--max_episode_steps 720 --n_envs 5 --n_episodes 10`. Its 720-step example is
not the retained 1000-control development cap. Reports using 1000 controls and
five seeds must disclose both differences and must not claim native-reference
score parity. The new seeded scope accepts only the independent horizon track;
it does not add service-side limits on calls or controls per decision.

Each adapter step executes one native control. Native reward uses `_check_success()`, and Gym returns `info.success = reward > 0`. Consume the flag without a second oracle query and stop at first native success. Preserve native termination and truncation separately.

The native scorer is delegated unchanged for every selected task. CupToDrawer
checks containment and drawer closure. Novel placement checks gripper separation,
receptacle placement, counter contact and uprightness. The microwave tasks require
the object's center inside the microwave (`partial_check=True`) and normalized
door fraction at most 0.005. Cabinet and other tasks use their own pinned native
predicates, not an adapter-side approximation. These are evaluator-private scoring
definitions, not policy feedback or alternate visual judges.

Record actual controls, policy calls, action decisions and first-success control/call index. A stop-only response has no action decision; shorter/truncated chunks invalidate division-by-five estimates. A minimum-actions-before-voluntary-stop preference belongs to the model profile and cannot delay native success, evaluator caps or errors.

## Results and sample coverage

Report task IDs, declared seeds, selected prefix if any, control budget, native
success, decisions, controls and termination/error reason. Report the number of selected task/seed
pairs rather than calling different seeds different layouts.

The service supports the two task pairs at fixed seed 20260907 or indices 0–23
with one to five distinct seeds. Sampling may repeat native styles/placements.
The provisioned asset snapshot can produce native missing-category warnings;
keep those deployment qualifications visible rather than silently substituting
objects. See [environment setup](environment/README.md).

Optional interaction/media retention is described in
[recording](../../../docs/recording.md); it is separate from native scoring and
basic result publication.
