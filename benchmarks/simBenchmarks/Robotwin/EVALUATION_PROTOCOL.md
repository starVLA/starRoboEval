# RoboTwin evaluation protocol

Service ID: `robotwin` (`rsi-bench serve --benchmark robotwin`).
The service description records the selected robot interface and renderer
identity; use those recorded values when comparing results.

## Native tasks, variation and evaluation

RoboTwin 2.0 has **50 bimanual manipulation tasks**. The official
[task catalog](https://robotwin-platform.github.io/doc/tasks/index.html) supplies
each task's description and scene examples, including coordinated lifting,
handover, sorting/stacking, placement, tool use and articulated-object tasks.

Task identity is independent of the native environment configuration. Clean
and randomized configurations control scene appearance and geometry; the
[configuration guide](https://robotwin-platform.github.io/doc/usage/configurations.html)
describes background, clutter, lighting, table-height and head-camera
randomization, as well as supported embodiments. Task code samples object
variants and initial placements. A seed drives this sampling; it is not a
universal layout index or a separate task.

The retained launcher lists 50 tasks and clean/randomized settings. The inspected
native `script/eval_policy.py` defaults to 100 accepted test episodes per task,
not the `episode_num: 50` collection field in demo_clean. It starts at
`100000 * (1 + seed)`, performs expert `play_once` feasibility screening, skips
unsuccessful seeds, then resets accepted seeds again for the participant.
Language templates may use expert-generated episode information.

Native success is the task's Boolean predicate. The native task limit controls
the number of target actions, not the number of physics ticks or agent
decisions; limits can differ across tasks. The 400-target limit below applies
to the two exposed tasks, not to the entire 50-task collection.

## Current Bench Server selection

The `robotwin` adapter exposes only `demo_clean` with native Aloha for
`lift_pot` and `click_bell`. See [service support](../SERVICE_SUPPORT.md).

This server never executes that expert/filtering loop. Each episode is one
task and one native seed declared in advance; the service calls `setup_demo`
once per episode. Native object-generation sampling within that seeded scene
setup is unchanged. `fast` and `example` use unscreened seeds and the task
JSON's fixed `full_description`. `max` replays seeds and instructions that an
offline native screen recorded (below).

| Implemented task | Native object variants retained | Native target-control horizon |
| --- | --- | --- |
| `lift_pot` | `060_kitchenpot`, IDs 0 and 1; native seeded sampling | 400 |
| `click_bell` | `050_bell`, IDs 0 and 1; native seeded sampling | 400 |

`evaluation_mode` fixes the native seeds; omitted means `fast`. The `task`
selector narrows within the mode to one task per service.

| Mode | Native seeds per task | Episodes | Cap per episode |
| --- | --- | ---: | ---: |
| `fast` (default) | 100000, 100001, 100002, 100003, 100004 | 5 | 400 |
| `max` | the 100 accepted seeds of a hash-bound accepted-seed manifest | 100 | 400 |
| `example` | 100000 | 1 | 400 |

Episode IDs are `{task}-native-seed{seed}-episode000`. Each episode has one
attempt; a second open/reset is rejected even after failure. One process claims
one episode, so launch each episode separately with `--episode-id`. A native
seed drives object variant and placement sampling; it is not a layout
identifier. Rejected resets are recorded as infrastructure errors, not replaced
by later seeds. EEF actions, the other 48 tasks and arbitrary native
configuration overrides are unsupported.

**`fast` and `example` seeds are unscreened.** Native sampling evaluates only
expert-accepted seeds, so seeds 100000–100004 are a different sampling
condition: an expert-infeasible scene stays in the denominator. Their language
is the fixed `full_description`, while native evaluation draws episode wording.

### `max`: accepted-seed manifest

`max` follows the inspected upstream evaluator
([`script/eval_policy.py` at `7a01414`](https://github.com/RoboTwin-Platform/RoboTwin/blob/7a01414/script/eval_policy.py)):

- eval seed 0 gives `st_seed = 100000`, and `test_num = 100` accepted episodes
  per task;
- each candidate seed runs `setup_demo` plus expert `play_once`. `UnStableError`,
  any other exception, or failing `plan_success and check_success()` skips it;
- each accepted seed is reset again for the participant. The instruction is
  `np.random.choice(generate_episode_descriptions(task, [episode_info["info"]], 100)[0][instruction_type])`,
  with `instruction_type: unseen` from the native policy `deploy_policy.yml`
  defaults.

That instruction draw uses expert `episode_info` and unseeded Python `random`
(`shuffle`/`choice` in `description/utils/generate_episode_instructions.py`),
so the service cannot reproduce it. The preparation therefore records the
drawn instruction for each accepted seed, and `max` presents that recorded
text. The service needs the operator-supplied `seed_manifest` path; at startup
it refuses a `max` launch unless the manifest is complete. An optional
`seed_manifest_sha256` pin is compared and a mismatch fails; without it the
observed SHA-256 is recorded as `{"sha256": …, "pinned": false}` in
`native_provenance.json` (`seed_manifest`).

| Field | Requirement |
| --- | --- |
| `schema` | `starvla-rsi.robotwin.accepted-seeds/v1`; no other top-level fields |
| `task`, `task_config`, `embodiment` | selected task, `demo_clean`, `["aloha-agilex"]` |
| `native_inventory_sha256` | the pinned content inventory below |
| `eval_seed`, `start_seed`, `accepted_count` | integers 0, 100000, 100 (type-strict: `false` or `100000.0` fail) |
| `instruction_type` | `unseen` |
| `accepted` | exactly 100 `{seed, instruction}` rows, unique ascending seeds, filled-in native text |
| `rejected` | every skipped `{seed, reason}`; reason `unstable`, `exception` or `expert_check_fail` |
| `preparation` | at least non-empty strings `deployment_manifest_sha256` (must equal the service's), `renderer_runtime`, `created_at`, `procedure` |

Accepted plus rejected seeds must form one contiguous walk from 100000 to the
100th acceptance. Rejections are preparation provenance, recorded with each
reset, never policy results. The service never prepares, searches or edits
the manifest. Expert `episode_info` is not stored or exposed to the model; only
the native instruction derived from it is.

**Max-mode instructions.** `max` presents the native `unseen`
instruction recorded during expert screening. For `click_bell`, the `{a}`
placeholder holds the arm the native expert chose from the bell's x position,
so a `max` instruction can name that arm. This is native upstream behaviour,
kept on purpose; `fast`/`example` keep the fixed `full_description`.

The preparation has not yet been performed, and no preparation tool is
shipped; see [environment setup](environment/README.md#max-mode-accepted-seed-preparation).
The archive's `script/eval_policy.py` (SHA-256 `abd498b3…`) matches no
inspected upstream commit, so whether its screening and instruction code equal
`7a01414` is UNVERIFIED. The archive's `click_bell.json` matches upstream
revisions from `8187d5b` up to, but excluding, `41995f7`; `lift_pot.json`
matches upstream.

The benchmark-scope `max` set is 50 tasks × 100 accepted episodes per native
configuration; only `lift_pot` and `click_bell` under `demo_clean` are
deployable now.

The protocol identity names the selection and the mode before its version:
`robotwin/clean-fixed-seed/qpos14-rgb320-state14/fast/v1` (and `/example/v1`),
`robotwin/clean-expert-accepted-seeds/qpos14-rgb320-state14/max/v1`
(`...-state14-oidn233/<mode>/v1` for the OIDN 2.3.3 renderer track).

## Service source and renderer requirements

The native local archive has no own Git metadata. Its selected files are pinned
in `environment/native_snapshot.json`, inventory SHA-256
`ab5a73b0482d50d9c83e8702b37e7e7eb10bf7033e03a8fec59b60b708bef08c`.
`native_source_revision` is `null`; the descriptor's required identity string is
`content-inventory-sha256:<digest>`. A parent repository's revision or current
upstream HEAD is not a substitute for this archive.

Prepare the content-matching deployment with its native Aloha CuRobo paths as
described in [environment setup](environment/README.md). The default
`renderer_runtime: bundled_oidn_2_0_1` uses the bundled denoiser;
`oidn_2_3_3_cuda_v1` selects an owned SAPIEN 3.0.0b1 overlay with OIDN 2.3.3
CUDA libraries. These rendering choices retain separate protocol identities
because their denoisers can produce different pixels. Neither changes the
native task, physics, camera definitions or success predicate. See
[renderer setup](environment/RENDERING.md) for preparation and device mapping.

## Observation boundary

The actor receives language plus `head_camera`, `left_camera`, `right_camera`
in that order, each native 320 × 240 RGB uint8. There is no flip, resize, crop,
overlay, image annotation or channel conversion. The native camera already
converts its Color buffer to uint8 RGB.

At reset and after every acknowledged control, `state` contains 14 robot values
in the following fixed order, declared individually in `state_names`:

| Indices | Fields | Source and units |
| --- | --- | --- |
| 0–5 | `measured_fl_joint1_rad` … `measured_fl_joint6_rad` | Actual left-arm articulation joint positions, radians |
| 6 | `commanded_left_gripper_01` | Last native normalized left-gripper command; 0 closed, 1 open |
| 7–12 | `measured_fr_joint1_rad` … `measured_fr_joint6_rad` | Actual right-arm articulation joint positions, radians |
| 13 | `commanded_right_gripper_01` | Last native normalized right-gripper command; 0 closed, 1 open |

The pinned native robot's `get_left_arm_real_jointState` and
`get_right_arm_real_jointState` read arm positions through articulation
`get_qpos` in the compiled arm-joint order. Each getter appends its native
gripper command cache. Thus there are **12 measured arm values and two commanded
gripper values**, not 14 measured encoders. Gripper commands do not establish
physical opening, contact or a successful grasp. These read-only getters do not
advance physics or invoke task logic; the state and cameras are sampled at the
same paused control boundary. Measured arm values are never clipped to action
bounds. Missing, non-finite or wrongly shaped state is an explicit error, not
a fabricated zero vector or a fallback to commanded joints.

The similarly named native `joint_action.vector` still contains drive targets;
it is not used as measured state. Only the declared camera arrays and robot
state are projected. Extra front camera, depth, point clouds, segmentation,
calibration, EEF/object poses, seeds, task metadata, native score and debug
channels remain excluded. No arbitrary native observation dictionary is forwarded.

## Direct action boundary

The actor selects this 14-D vector directly:

```text
[fl_joint1, fl_joint2, fl_joint3, fl_joint4, fl_joint5, fl_joint6, left_gripper,
 fr_joint1, fr_joint2, fr_joint3, fr_joint4, fr_joint5, fr_joint6, right_gripper]
```

Arm entries are absolute native joint radians with authored URDF bounds
`[-10, 10]`. Grippers are absolute normalized commands in `[0, 1]` (0 closed,
1 open), using the native `[-0.01, 0.045]` meter scale. At reset the adapter
checks actual compiled joint names/limits, gripper scale, horizon and physics
timestep. A mismatch is a contract/environment error before actor controls,
not permission to infer different bounds.

One `take_action(vector, action_type="qpos")` executes each control. Native
MPLib TOPP interpolates from previous drive targets to requested absolute joint
targets under fixed low-level velocity/acceleration constraints. It does not
select a grasp or plan around task objects. EEF/CuRobo planning, expert methods,
VLA proposals, fallback task policies and task-solving services are not exposed.

Native setup still constructs planners, moves to homestate, opens grippers and
performs object-stability settling. These are declared initialization, not model
decisions. No `play_once`, expert feasibility check, hidden-state action
generation or scored-seed search occurs.

Native qpos control catches TOPP exceptions/zero-sample paths and uses its fixed
50-tick gripper interpolation for the affected arm. This existing low-level
behavior is preserved and explicitly recorded by passive TOPP instrumentation;
the adapter never substitutes a task action or replays a failed control.
Exceptions outside that native controller retain errors.

## Timing, stopping and success

Physics uses native `1/250`-second ticks. A target consumes a variable number
according to TOPP; `control_hz` is unspecified, not inferred from video FPS.
Native `take_action_cnt` stops at 400 for both tasks, from the pinned
`_eval_step_limit.yml`. Runner decision limits do not extend that horizon.
The participant method chooses its own decision frequency, action grouping and
any additional call allowance. These choices do not change the native cap.

Native `take_action` checks `check_success` during each physics tick and caches
`eval_success`. The adapter consumes that result without adding a second
stateful scorer query after each target or inferring success from video.
Numeric transition reward only encodes this Boolean success; no shaped reward
is introduced. Success terminates immediately. Native horizon, runner limits,
errors and explicit policy stop can end unsuccessfully. Voluntary persistence
and minimum-decision rules remain policy-owned.

Record calls, executed action decisions, native started target controls,
acknowledged transitions and completed physics ticks separately. A passive
task-side scene view counts physics after reset. Initialization ticks are
unknown, not falsely zero; setup includes settling and fixed controls. On a
native exception, partially executed controls may have consumed physics without
an acknowledgment. Preserve that uncertainty and never replay the action.

## Results and supported samples

Report task, native seed, renderer/protocol identity, native success and exact
stop/error reason. Separate decisions, started target controls, acknowledged
transitions and completed physics ticks. A native error can leave partial motion
without an acknowledgement; do not count it as a proven zero-control failure or
replay it.

Use one episode per service process. Native `close_env` does not guarantee
GPU-memory reclamation; stop the process after collecting results. Setup and
renderer instructions are in [environment/README.md](environment/README.md).
Camera videos present control-boundary samples at 10 fps, not real-time physics.
See [recording](../../../docs/recording.md) for optional interaction/media
retention.
