# BEHAVIOR 2026 observation and action contract

This document specifies native sensors, robot commands, timing and scoring for
the supported task instances.
Source pin:
`b1979916ec1549b10a4e65e630bc6504a9af1b00` (`v3.9.2`). Paths below refer to
`OmniGibson/omnigibson/` at that revision.

## Sensor configuration

Use native `DefaultWrapper`: three 224×224 RGB views plus robot proprioception.
The challenge uses `RGBDFullResWrapper` (RGB and metric depth; head 720×720,
wrists 480×480).
The shared RGB transport cannot currently represent metric depth. Do not
silently drop depth, encode it as RGB, or treat these sensor configurations as
equivalent.

## Actions and native execution

`eval/utils/eval_utils.py` and `eval/r1pro.yaml` declare 23 action values:

| Slice (Python indexing) | Command | Native semantics |
| --- | --- | --- |
| `0:3` | Mobile base | Normalized velocity inputs; body vx/vy map to ±0.75 m/s, yaw to ±1 rad/s |
| `3:7` | `torso_joint1..4` | Absolute joint positions, radians |
| `7:14` | `left_arm_joint1..7` | Absolute joint positions, radians |
| `14` | Left gripper | Smooth normalized scalar, −1 close / +1 open |
| `15:22` | `right_arm_joint1..7` | Absolute joint positions, radians |
| `22` | Right gripper | Smooth normalized scalar, −1 close / +1 open |

The robot asset's raw controller order agrees. Its default arm controller is
IK, but the **evaluation configuration overrides it with absolute
JointController**. Loading only the asset defaults would change the protocol.
Arms and torso are not normalized actions or deltas. Preserve native input
scaling, motor limits and gripper behavior; do not add server-side soft-limit
rejection or policy motion guards.

The evaluated robot uses native `grasping_mode: assisted`. Record this native
physics mechanism explicitly; do not add an RSI task planner or silently switch
to physical grasping. No object-target, grasp, expert or primitive RPC is proposed.
Preserve the native evaluator, not just `r1pro.yaml`: its robot adjustments,
rendering configuration and task-specific transition rules also affect execution.
Constructing a generic environment from the robot YAML alone is not parity.

Code declares action/rendering at 30 Hz and physics at 120 Hz. The
service accepts one action per control (normally four physics ticks),
with no autonomous stepping between requests. Validate actual clock deltas in
the native diagnostic, separately from model decisions and initialization.
An agent may issue multiple controls from one decision. Action grouping cannot
extend the native control budget or delay native termination.

## Public sensors, not arbitrary native observation dictionaries

Native camera keys are `robot_r1::robot_r1:<link>:Camera:0::rgb` with links
`zed_link`, `left_realsense_link`, `right_realsense_link`. Native VisionSensor
declares these as uint8 RGBA; require 224×224×4 and explicitly select the first
three channels for public RGB. No resizing or task annotation is implied.

`robot_r1::proprio` contains 61 values in this exact configured order:

| Slice | Measurement |
| --- | --- |
| `0:3` | Body-frame base velocity vx/vy/wz |
| `3:10`, `10:17` | Left arm joint positions / velocities |
| `17:20`, `20:24` | Left EEF base-relative position / xyzw quaternion |
| `24:26`, `26:28` | Left finger positions / velocities |
| `28:35`, `35:42` | Right arm joint positions / velocities |
| `42:45`, `45:49` | Right EEF base-relative position / xyzw quaternion |
| `49:51`, `51:53` | Right finger positions / velocities |
| `53:57`, `57:61` | Torso joint positions / velocities |

`robots/robot.py` produces these from robot joints and kinematics. Joint
positions/velocities are radians and radians/s for revolute joints; gripper
fingers are prismatic, in metres and metres/s. EEF positions are metres.
These have encoder/kinematic real-robot counterparts; they are not object truth.

The wrapper alone is **not** an information filter: native evaluator preprocessing
also appends camera poses and a numeric task ID. The service selects
only the declared cameras, proprioception and explicit task instruction. Do not
forward camera-pose extras, global robot pose, object poses, grasp predicates,
task internals or metrics into actor observations.

## Schedule, initialization and scoring

Native code exposes 20 public indices 0–19 mapping to instance IDs 301–320.
The service selects public indices 0–4 (fast), 0–9 (max) or index 0 (example)
for each supported task; the worker verifies the native index-to-instance mapping.

Preserve the evaluator's initialization order: construct lazily, reset, load
the selected instance, reset for rollout. Loading includes 25 explicit physics
settling ticks; reset/load also perform other simulation and rendering work.
Do not report 25 as the total initialization count without measuring it.
No actor-controlled reset, seed search or fallback to training instances.

Native timeout configuration is `H = int(mean_human_length * 1.5)` unless an
explicit native override is selected. This parameter is not the number of
controls at which the pinned implementation returns timeout:

1. `envs/env_base.py::_reset_variables` starts `_current_step` at zero.
2. `_post_step` calls `task.step`, whose `termination_conditions/timeout.py`
   condition checks `env.episode_steps >= H`.
3. `_post_step` then increments `_current_step` and returns terminal flags.
4. `eval/eval.py` runs until native flags terminate; it adds no independent H cap.

Consequently, absent earlier termination, native timeout occurs after **H + 1
executed controls**. Each task uses H + 1 as its service control cap while
leaving the native timeout parameter at H. A smaller external cap must be
reported separately.
The selected task names, language provenance, human lengths, horizons and the known
instance hashes are pinned in `bench_server/protocol/__init__.py`; see the
[task table](../EVALUATION_PROTOCOL.md). A deployment manifest must bind the
selected task and its instance.

Preserve native evaluator step and metric ordering. Binary success comes from
`env.task.success`; native final `q_score` is partial goal progress, not success
rate. Success forces Q to 1; otherwise native scoring takes the maximum over
alternative goal conjunctions of newly satisfied predicates (false initially,
true now), divided by all predicates in that conjunction. Initially satisfied
predicates are not newly earned credit. Movement/global-pose metrics remain evaluator-private. Native
metrics can contain non-finite ratios for zero motion/time; define an explicit
JSON representation without silently turning these into zero.

## Robot asset sources

Required robot asset identities: `omnigibson-robot-assets` 3.8.2,
`models/r1pro/r1pro.yaml` SHA-256
`63f841cffd5c499102416a797a22fa5b4cbaf146539df7dde8a4a1053e2326f1`,
`models/r1pro/urdf/r1pro.urdf` SHA-256
`b0d76760cbedfbcbe1ddc280380dd5f497bbca380313bc096d7239a2c50dae61`.
Code and asset version numbers need not be identical.
