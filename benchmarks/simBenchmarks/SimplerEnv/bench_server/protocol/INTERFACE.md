# SimplerEnv public interface

This document describes the benchmark's public sensor and action contract.
[server.py](../../server.py) exposes it through the shared
[SIM wire protocol](../../../SERVER_PROTOCOL.md). The trusted driver handles
session selection, initialization and result collection; the evaluated actor
receives only the declared observations and submits robot actions.

The wire contract does not require a particular model, SDK, mailbox transport,
prompt or decision loop. See [agent integration](../../../../../docs/agent-methods.md)
for participant-side implementations, [installation](../../README.md) for the
service environment, and [the evaluation protocol](../../EVALUATION_PROTOCOL.md)
for exact scoring and track identities.

## Public observations

Each acknowledged native control returns one observation; reset supplies the
initial observation. A driver may group successive controls before requesting
another model decision. Idle service time performs no control.

| Field | Meaning |
| --- | --- |
| `step` | Number of executed native control steps |
| `instruction` | Current native language instruction |
| `images` | The declared camera's original RGB `uint8` pixels |
| `state` | Absent in RGB-only; ordered robot joint encoders in the RGB+qpos track |

The service description also declares the action/observation specification and
selected execution budget. A trusted driver may expose their public content and
acknowledged counters to the actor; service credentials, reset metadata and
scoring methods remain private.

| Embodiment | Camera and image shape (H × W × C) | Optional joint positions |
| --- | --- | ---: |
| Google Robot | `overhead_camera`, 512 × 640 × 3 | 11 encoders |
| WidowX | `3rd_view_camera`, 480 × 640 × 3 | 8 encoders |

The RGB+qpos setting has its own protocol identity. Native RGB receives no
additional crop or resize. The actor may retain previously delivered inputs and
its own actions within an episode; that memory belongs to the method.

### Joint-position order

`state` copies the native articulation's measured `qpos`, not controller drive
targets. For the pinned robot definitions, its zero-based order is:

| Robot | Indices | Joint names in order | Unit |
| --- | --- | --- | --- |
| Google Robot | 0–6 | `joint_torso`, `joint_shoulder`, `joint_bicep`, `joint_elbow`, `joint_forearm`, `joint_wrist`, `joint_gripper` | radians |
| Google Robot | 7–8 | `joint_finger_right`, `joint_finger_left` | radians |
| Google Robot | 9–10 | `joint_head_pan`, `joint_head_tilt` | radians |
| WidowX | 0–5 | `waist`, `shoulder`, `elbow`, `forearm_roll`, `wrist_angle`, `wrist_rotate` | radians |
| WidowX | 6–7 | `left_finger`, `right_finger` | metres |

Google Robot uses the fixed-wheel embodiment; its fingers are rotary joints.
WidowX finger values are individual prismatic-joint displacements, not a
normalized gripper command or a single aperture value. The source-defined orders
are in [Google Robot](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/agents/robots/googlerobot.py#L21)
and [WidowX](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/agents/robots/widowx.py#L24);
joint types are defined by their
[Google URDF](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/assets/descriptions/googlerobot_description/google_robot_meta_sim_fix_wheel_fix_fingertip.urdf#L519)
and [WidowX URDF](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/assets/descriptions/widowx_description/wx250s.urdf#L322).

### Unavailable observations

No additional camera query, depth, segmentation, object/target pose, camera
calibration, contacts, native `info`, reward, success or hypothetical rollout
is provided. Reset seeds, variant identifiers, scorer records and native
simulator handles are evaluator-private.

## Actions

Each `step` request supplies one seven-value vector:

```text
[dx_m, dy_m, dz_m, rx_rad, ry_rad, rz_rad, gripper]
```

Translation uses metres. Rotation is an axis-angle vector in radians, not Euler
angles. Accepted component bounds are `[-1,1]` for translation and gripper,
and `[-pi/2,pi/2]` for rotation. These are the service's declared validation
bounds; the native unnormalized arm controller's advertised limits are dummy
limits, as explained in [the action contract](../../EVALUATION_PROTOCOL.md#native-action-contract).

| Embodiment | Arm target convention | Gripper convention | Control frequency |
| --- | --- | --- | --- |
| Google Robot | `ee_align`: measured-pose delta, base-aligned axes | Positive closes, negative opens, zero holds target | 3 Hz |
| WidowX | `ee_align2`: accumulated target delta, base-aligned axes | +1 open, −1 closed, zero intermediate | 5 Hz |

For both robots, translation and rotation-vector components use the robot
articulation's base axes, not the rotating end-effector axes. These are not
necessarily world axes when the base is rotated. Google Robot adds translation
to the measured end-effector position and left-multiplies its orientation by
the delta rotation. WidowX retains the previous target and rotates it about the
**current measured** end-effector position before adding translation. Thus a
rotation can also change the retained target position when target and measured
positions differ. This follows the pinned
[pose-controller transforms](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/agents/controllers/pd_ee_pose.py#L192),
with [WidowX target accumulation](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/agents/configs/widowx/defaults.py#L131).

Native robot-only IK and controller interpolation execute the submitted target.
The service provides no object-localization, grasp, navigation or task-solving
operation. It neither chooses actions nor silently pads, clips or repairs them.

An action advances one native control, not one physics tick. A method can submit
several successive actions from one decision, subject to sequencing, validity,
native execution and the selected total cap. Repeated targets are new sequenced
controls, never replays of an uncertain acknowledgment.

## Track selection and validation

The service configuration explicitly selects compatible conditions before any
case is claimed:

| Parameter | Meaning |
| --- | --- |
| `proprioception` | RGB-only or separately identified RGB+qpos observation |
| `budget_mode: "horizon"` | Task horizon × predeclared multiplier (1 or 2) |
| `budget_mode: "decisions"` | Distinct development cap `max_policy_calls × replan_interval` |
| `interaction_mode: "single_response"` | Default: at most one provider request per decision call |
| `interaction_mode: "agent_method"` | Declared internal inference and tools over permitted inputs |
| `action_rejection_feedback` | Explicit rejected-action feedback track; false retains fail-fast behavior |

These selections affect protocol identity. The benchmark cannot verify hidden
provider activity; report available call/token usage and leave unavailable
accounting unknown. Agent-method mode adds no sensors, reset permission or
execution budget. Decision-budget tracks retain their configured coupling;
horizon-mode action grouping and inference allowance belong to the method.

With rejection feedback selected, an invalid action executes no control and
returns a bounded validation issue. A compatible driver can deliver it with the
last acknowledged observation at its next counted decision call. The rejection
does not acquire a fresh image. Uncertain transport/native execution is an
infrastructure error, not a recoverable invalid-input receipt and not permission
to replay an action. See [rejection semantics](../../EVALUATION_PROTOCOL.md#optional-rejected-action-feedback).

## Outcome and records

The primary score is success at the last executed native control. Intermediate
success is diagnostic and does not end this benchmark; native score remains
private while the actor is acting. Stop preferences and self-reported completion
belong to the agent method and do not award native success.

Record model calls, accepted action decisions, executed controls and any native
physics accounting separately. Optional
interaction/media recording follows the shared
[recording policy](../../../../../docs/recording.md); result records identify
the selected denominator and native outcome.

Service process separation defines responsibilities, not an OS sandbox.
Deployment must keep administrative credentials, native processes/files and
private result channels outside an untrusted actor's permissions.
