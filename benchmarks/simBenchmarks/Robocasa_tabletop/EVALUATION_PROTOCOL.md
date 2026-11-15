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

The pinned upstream evaluation
([README.md:84-93](https://github.com/robocasa/robocasa-gr1-tabletop-tasks/blob/4840e671596f93ca03651524b9f72ffb1aadfeff/README.md?plain=1#L84-L93))
runs Isaac-GR00T `scripts/simulation_service.py --max_episode_steps 720
--n_envs 5 --n_episodes 10`: ten episodes per task, capped at 720 controls.
Parallel environment count is not a task or layout count. This is a reference
configuration, not an exhaustive enumeration of object/placement combinations.
Native task predicates determine binary success; scorer details appear below.

## Current Bench Server selection

The [adapter](bench_server/adapter.py) exposes the 24 official tasks; see
[service support](../SERVICE_SUPPORT.md) for the integration boundary.

| `evaluation_mode` | Selection | Episodes | Cap |
| --- | --- | ---: | --- |
| `fast` (default) | 24 tasks × seeds 20261020–20261021, one attempt each | 48 | 720 controls |
| `max` | 24 tasks × seeds 20261020–20261029, one attempt each | 240 | 720 controls |
| `example` | Task 0 at seed 20261020 | 1 | 720 controls |

The launch `--seed` must be 20261020; sample *k* resets with seed 20261020 + *k*.
Seeds are frozen before evaluation; there is no automatic or outcome-driven
selection. `max` mirrors the upstream example's ten episodes per task with
consecutive seeds, because that example does not pin its seeds.

The schedule is **sample-major, task-minor**: every task once with the first
seed, then every task with the second seed, and so on. Episode IDs are
`tabletop-task{TT}-seed{S}-attempt1`. `--episodes` selects a prefix and
`--episode-id` selects individual cases within the chosen mode; reports must
retain that selected denominator.

Ten seeds are **not ten distinct layouts**. Each task has the single candidate
layout listed above and all 12 style candidates. Native RNG selects styles,
objects and placements; repeated styles are permitted. The first and subsequent
samples all retain one fresh constructor followed by one explicit seeded reset,
without reset-search or success-screening. Actual selections are retained
privately, never projected to the policy.

The protocol identity
`robocasa-tabletop-4840e67/gr1-official24-seeded-control-720/rgb256-qpos29/{mode}/v1`
records the native pin, control cap and mode; the episode schedule records tasks and seeds.

The reported denominator is the mode's task × seed schedule, or its explicitly
selected subset. This sampler does not enumerate every native object placement
or reproduce the upstream ten-episode example's unpinned seeds.

## Environment and reset

Pin RoboCasa GR1 revision `4840e671596f93ca03651524b9f72ffb1aadfeff` and Robosuite revision `51cc01785bab80ffeed20da15e67d7dd4140e76a`. The runtime has been pinned with Python 3.10.21. Set `PYTHONHASHSEED=0` before Python starts; the adapter checks a hash sentinel.

Each episode passes its own seed to the
fresh native constructor and the one explicit seeded reset. Native constructor
initialization is retained. The pinned Gym reset seeds NumPy's global RNG;
it does not replace the constructor's environment RNG with a new generator.
The pinned Gym factory does not forward its layout/style arguments, so the
adapter does not claim to force actual style. Preserve the task
`VALID_LAYOUTS × 12 styles` candidate set and record actual native selection privately.

Do not reset-search, success-screen, substitute assets or shrink the object library. Reset-time native success is an error before policy control, not a reason to resample. Setup and the bounded asset-snapshot limitation are described in [environment/README.md](environment/README.md).

Deployment uses `render_gpu_device_id` as the recorded GPU index and
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

Every episode is capped at the upstream evaluator's 720 controls in every mode,
recorded in the protocol identity and in each episode's `environment_step_cap`.
The service publishes no policy-call limit: the policy/method chooses chunk
length and the trusted driver may declare its own call or replan limit. Each
service step still executes one native control; native success/termination and
the selected total cap stop execution even in the middle of a chunk.

The 720-control cap follows the upstream command above. Isaac-GR00T's
`MultiStepWrapper` (checked at tag `n1.5-release`,
[`4af2b62`](https://github.com/NVIDIA/Isaac-GR00T/blob/4af2b622892f7dcb5aae5a3fb70bcb02dc217b96/gr00t/eval/wrappers/multistep_wrapper.py#L200-L226))
truncates when its per-control reward list reaches `max_episode_steps`. It
therefore counts raw environment steps, not 16-control action chunks. The
upstream README does not pin an Isaac-GR00T revision. The native engine
horizon of 1000 with `ignore_done=True` is an engine setting, not the evaluated
cap; the adapter checks it unchanged and records it as `native_engine_horizon`.
Upstream seeds are unpinned, so the service's consecutive seed panel does not
reproduce the upstream episodes exactly. Reports must disclose the seed panel
and must not claim native-reference score parity. No scope adds service-side
limits on calls or controls per decision.

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

Report the evaluation mode, task IDs, seeds, selected subset if any, control budget, native
success, decisions, controls and termination/error reason. Report the number of selected task/seed
pairs rather than calling different seeds different layouts.

Every mode covers indices 0–23; the default fast mode uses seeds
20261020–20261021. Sampling may repeat native styles/placements.
The provisioned asset snapshot can produce native missing-category warnings;
keep those deployment qualifications visible rather than silently substituting
objects. See [environment setup](environment/README.md).

The server always writes native evaluator records into the bound episode
directory: provenance, controller contract, native episode metadata, initial
state and scene XML, used-asset manifest, per-step egoview PNGs with
`frames.jsonl`, native action events and the egoview MP4 with its decode check.
Reset refuses to start without that directory, and these records cannot be
switched off. Optional client-side interaction recording and media copying are
described in [recording](../../../docs/recording.md); they are separate from
native scoring and basic result publication.
