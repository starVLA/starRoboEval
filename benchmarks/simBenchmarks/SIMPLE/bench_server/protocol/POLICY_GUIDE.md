# SIMPLE public policy interface

This document contains general interface/robot mechanism information only. It
does not contain an episode seed, reset configuration, demonstrated action,
diagnostic hold vector, target/object coordinates, success feedback or a solution.

Your input is current native head-left RGB (640×360) and native language. The
declared `rgb-qpos31` track also supplies 31 measured robot joint encoders in
radians; their order is exactly the first 31 `ActionSpec.names`. The `rgb`
track supplies no joint state. Never infer that an undeclared state channel is
available. The fixed WBC controller privately handles balance using its own
robot sensors/history; you do not output leg torques or call that controller.

Return one to five 36-number vectors per decision in the shared policy
interface. Each vector advances one native 20 ms control tick. Five vectors
advance 100 ms; there is no hidden repetition or interpolation chunk supplied
by the evaluator. The episode has at most 200 policy calls. The selected track
sets its total native-step cap independently. No task-specific macro or native
planner is an allowed policy action.

Action values are physical absolute targets, not normalized numbers:

| Slots | Meaning/order |
| --- | --- |
| 0–6 | Left hand thumb0, thumb1, thumb2, middle0, middle1, index0, index1 |
| 7–13 | Right hand thumb0, thumb1, thumb2, index0, index1, middle0, middle1 |
| 14–20 | Left shoulder pitch, roll, yaw; elbow; wrist roll, pitch, yaw |
| 21–27 | Corresponding right arm joints |
| 28–30 | Waist roll, pitch, yaw |
| 31 | Native base-height command, meters |
| 32–33 | Native forward and lateral velocity commands, meters/second |
| 34 | See the backend-specific public action name below |
| 35 | Native target heading, radians |

For AMO, slot 34 is `turning_flag`, which the native controller branches on at
0.5. It is not a smooth yaw-rate command. Waist targets are consumed separately
from the AMO balance controller's retained native torso orientation.
For SONIC, slot 34 is `turning_gate`, not a direct yaw-rate command. If its
absolute value is below 0.1, or the wrapped target-heading error is below
0.01 radians, native heading correction is zero. Otherwise native correction
is heading error divided by 0.5 seconds, saturated at ±1 radian/second.
The selected native upper-body group
contains all 31 declared hand/arm/waist joints, including the waist targets.
Base height/navigation are native controller commands, not world-pose setters.

All 36 entries must be finite real numbers; booleans and strings are rejected.
The v2 service forwards finite joint targets without additional range rejection
or clipping. Optional model target guards belong to the agent implementation.
The G1 physical joint ranges verified from both native robot descriptions
(radians) are listed below as mechanism information, **not server input bounds**:

| Joint | Left | Right |
| --- | --- | --- |
| Hand thumb0 | [-1.0472, 1.0472] | [-1.0472, 1.0472] |
| Hand thumb1 | [-0.724312, 1.0472] | [-1.0472, 0.724312] |
| Hand thumb2 | [0, 1.74533] | [-1.74533, 0] |
| Hand index0 / middle0 | [-1.5708, 0] | [0, 1.5708] |
| Hand index1 / middle1 | [-1.74533, 0] | [0, 1.74533] |
| Shoulder pitch | [-3.0892, 2.6704] | [-3.0892, 2.6704] |
| Shoulder roll | [-1.5882, 2.2515] | [-2.2515, 1.5882] |
| Shoulder yaw | [-2.618, 2.618] | [-2.618, 2.618] |
| Elbow | [-1.0472, 2.0944] | [-1.0472, 2.0944] |
| Wrist roll | [-1.97222, 1.97222] | [-1.97222, 1.97222] |
| Wrist pitch / yaw | [-1.61443, 1.61443] | [-1.61443, 1.61443] |

Waist roll/pitch each have [-0.52, 0.52]; waist yaw [-2.618, 2.618]. These are
mechanism limits, not a claimed safe task-action envelope or extra command gate. They are not
dataset-statistics normalization ranges. The adapter adds no height, velocity
or turn-input clipping; finite values are required. Height/forward/lateral
command safety envelopes are not established here. Native SONIC heading-rate
saturation above, native interpolation, fixed controller output/PD saturation
and AMO's low-level network-output clipping remain unchanged. Do not confuse
absence of a schema bound with a guarantee of safe arbitrary commands.

The only policy channel is observation → action. Do not inspect private worker
files, simulator state, scoring code during an episode, reset metadata, previous
evaluation traces, demonstrations or developer diagnostic artifacts. Generic
policy stop ends the rollout; it does not create native success.
