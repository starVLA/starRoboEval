# RoboCasa GR1 Tabletop evaluation protocol

[TabletopBenchmarkAdapter](bench_server/adapter.py), registered as `robocasa_tabletop`, owns native reset, control and scoring. [robocasa_tabletop_contract.json](bench_server/protocol/robocasa_tabletop_contract.json) binds sources, controller limits, encoder identities and the provisioned object inventory. Policies use the [shared interface](../POLICY_PROTOCOL.md).

## Tasks, variants and fast/full scope

The official set has 24 tasks: six container-closing tasks and eighteen `PosttrainPnPNovel...SplitA` tasks. Other registered pretraining and `Eval...SplitB` tasks are outside that set. The service supports all 24 through the explicit `tabletop24-seeded-v1` development selection. The two historical fast presets remain unchanged:

| Scope | Native index | Task | Valid layouts | Styles |
| --- | ---: | --- | --- | --- |
| `pilot` (default compatibility name) | 0 | `PnPCupToDrawerClose` | [4] | 0–11 |
| `pilot` | 19 | `PosttrainPnPNovelFromTrayToCardboardboxSplitA` | [0] | 0–11 |
| `tabletop-next-pair-v1` | 1 | `PnPPotatoToMicrowaveClose` | [2] | 0–11 |
| `tabletop-next-pair-v1` | 2 | `PnPMilkToMicrowaveClose` | [2] | 0–11 |

Native environment IDs are `gr1_unified/<task>_GR1ArmsAndWaistFourierHands_Env`. The [campaign plan](bench_server/protocol/plan.py) selects one pair. Fast mode evaluates each preselected task once, retaining failures/errors without automatic retry. Existing protocol IDs retain `pilot-0-19` or `next-pair-1-2` for compatibility.

### Official task coverage with an explicit seed panel

The packaged [task catalog](bench_server/protocol/task_catalog.json) preserves the
exact order in the pinned upstream README:

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

Select `task_scope="tabletop24-seeded-v1"`, `budget_mode="horizon"`, and
`episode_seeds` containing **one to five distinct uint32 integers** (0 through
4294967295). Seeds are mandatory and frozen before evaluation; there is no
automatic or outcome-driven selection. `task_ids` is an increasing, unique
subset of indices 0–23, defaulting to all 24. The launch `--seed` must equal
the first entry of `episode_seeds`.

The schedule is **sample-major, task-minor**: every selected task once with the
first seed, then every task with the second seed, and so on. All 24 tasks with
five seeds gives 120 planned cases. An explicit episode limit selects only a
prefix; reports must retain that selected denominator. A one-task, one-seed
service is also permitted for externally predeclared schedules, using the same
native constructor and reset logic.

Five seeds are **not five distinct layouts**. Each task has the single candidate
layout listed above and all 12 style candidates. Native RNG selects styles,
objects and placements; repeated styles are permitted. The first and subsequent
samples all retain one fresh constructor followed by one explicit seeded reset,
without reset-search or success-screening. Actual selections are retained
privately, never projected to the policy.

This track has protocol
`gr1-tabletop-official24-seeded/rgb256-qpos29/control-N/v2` and adapter version
`0.4.0`, distinct from historical pilot/next-pair identities. The old tracks
reject `episode_seeds`; their fixed seed, budgets and schedules are unchanged.

**Native-aligned full evaluation is not implemented.** This is official-task
coverage with a declared development seed panel, not the native full reset /
variant / repetition protocol. Registering 24 task identities is not evidence
that all 24 have completed native evaluation. Layout/style variants do not
create additional task identities.

## Environment and reset

Pin RoboCasa GR1 revision `4840e671596f93ca03651524b9f72ffb1aadfeff` and Robosuite revision `51cc01785bab80ffeed20da15e67d7dd4140e76a`. The runtime has been pinned with Python 3.10.21. Set `PYTHONHASHSEED=0` before Python starts; the adapter checks a hash sentinel.

The historical pilot/next-pair tracks use seed 20260907; the new seeded track
uses each predeclared `episode_seeds` value. Both pass that episode seed to the
fresh native constructor and the one explicit seeded reset. Native constructor
initialization is retained. The pinned Gym reset seeds NumPy's global RNG;
it does not replace the constructor's environment RNG with a new generator.
The pinned Gym factory does not forward its layout/style arguments, so the
adapter does not claim to force actual style. Preserve the full task
`VALID_LAYOUTS × 12 styles` candidate set and record actual native selection privately.

Do not reset-search, success-screen, substitute assets or shrink the object library. Reset-time native success is an error before policy control, not a reason to resample. Setup and the bounded asset-snapshot limitation are described in [environment/README.md](environment/README.md).

Deployment uses `render_gpu_device_id` for the NVML resource-occupancy check and
optional `egl_device_id` for EGL renderer selection. Omitted EGL selection
defaults to the NVML index for historical compatibility. Operators must verify
their physical-device mapping with a renderer-only UUID / PCI preflight before
claiming a task; the two enumeration orders are not assumed equivalent.
Both indices are recorded privately. This deployment setting changes no task
selection, sensor/action semantics, budget or scoring. See the
[renderer configuration guide](README.md#nvml-resource-index-and-egl-renderer-index).

## Observation allowlist

- One uint8 256 × 256 RGB image, `ego_view_bg_crop_pad_res256_freq20`.
- Native `annotation.human.coarse_action` language, including `unlocked_waist:`.
- Exactly 29 measured joint encoders in radians: left arm 7, right arm 7, left hand 6, right hand 6, waist 3.

The native image pipeline vertically flips a 1280 × 800 egoview, crops rows 310:770 and columns 110:1130, resizes to 720 × 480, pads to square, then resizes to 256 × 256. Copy that output without additional preprocessing. Do not use the old model-specific 224-pixel resize or 58D sine/cosine state transform.

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
`control_step_cap=1000`. This independent-control development track has protocol
`gr1-tabletop-pilot-0-19/rgb256-qpos29/control-1000/v2` for the pilot selection
(or `gr1-tabletop-next-pair-1-2/...` for the next pair). A positive integer cap
at most 1000 is allowed; each cap has its own `control-N/v2` identity. The
service publishes `max_policy_calls=null` and `replan_interval=null`: the
policy/method chooses chunk length and the trusted driver may declare its own
call or replan limit. Each service step still executes one native control;
native success/termination and the selected total cap stop execution even in
the middle of a chunk. Service decision-limit parameters cannot be combined
with this track.

The omitted/default `budget_mode="decisions"` preserves the historical
200-call, prefix-5, D × K control budget and its existing `decision-D-prefix-K/v1`
identity. Its D=1..200 and K=1..5 limits, smaller budgets and frozen campaign
plans remain unchanged. `control_step_cap` is not accepted in that track.
These two budget identities must not be pooled as one protocol.

All these tracks remain provisional development tracks. The native engine stays at horizon
1000 with `ignore_done=True`; neither re-labels that engine setting as a verified
native-full evaluator budget or establishes full-native protocol parity.
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

## Evidence and acceptance limits

Retain source/model/protocol identities, actual task/layout/reset and native metadata, compiled scene XML, initial simulator state/hash, controller/encoder manifest, used-asset closure, delivered frames, action chunks/executed prefixes, per-control metrics, errors and decodable videos. Keep private native artifacts out of the policy mailbox. Store model outputs under `AgentPolicies/<profile>/results/robocasa_tabletop/`.

The object contract certifies a provisioned snapshot, not the complete official asset release. Preserve native missing-category warnings and catch-and-skip behavior, including possible `sketchfab/book` distractor warnings; validated used-scene assets do not erase that limitation. Do not silently modify the library to clear a warning.

Source checks, controller parity, sensor allowlisting, per-action scoring and video decoding are acceptance requirements. Zero-policy reset/hold diagnostics and CPU fixtures are infrastructure evidence, never capability attempts or complete 24-task coverage.
