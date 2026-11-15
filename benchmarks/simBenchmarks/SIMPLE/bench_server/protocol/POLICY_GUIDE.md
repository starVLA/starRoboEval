# SIMPLE observation and action reference

This document contains general interface/robot mechanism information only. It
does not contain an episode seed, reset configuration, demonstrated action,
diagnostic hold vector, target/object coordinates, success feedback or a solution.

Your input is current native head-left RGB (640×360) and native language. The
declared RGB/joint-state interface also supplies 31 measured robot joint encoders in
radians; their order is exactly the first 31 `ActionSpec.names`. RGB-only input
supplies no joint state. Never infer that an undeclared state channel is
available. The fixed WBC controller privately handles balance using its own
robot sensors/history; you do not output leg torques or call that controller.

Each service action is a 36-number vector and advances one native 20 ms control
tick. The service adds no hidden repetition or task-specific macro. The
native-horizon contract leaves decision frequency and action grouping to the
agent's driver. See [budget and native scoring](../../EVALUATION_PROTOCOL.md#budget-and-native-scoring)
for the total control cap.
Method-specific prompting, planning and voluntary-stop behavior remain separate.

Joint values are absolute targets in physical units, not normalized numbers.
The remaining slots are native height/navigation commands:

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

The **heading reference differs by backend**:

| Backend | Slot 35 target heading |
| --- | --- |
| AMO | Yaw relative to the orientation captured when the AMO controller first initializes its evaluation observation; zero refers to that initial orientation |
| SONIC | Yaw in the native world frame, compared with Euler-xyz yaw from the floating-base quaternion |

The worker does not convert these two heading conventions into a common frame.
Slots 32–33 are forwarded unchanged to the native forward/lateral command
inputs. The current interface does not establish their learned controller's
world/body-frame mapping; do not treat them as verified world-axis velocities.
The SONIC keyboard interface uses positive forward and positive left inputs.

These mappings follow the installed sources under `simple_root`:
`src/simple/robots/policy/AMO_Policy.py:get_eval_observation`,
`third_party/decoupled_wbc/control/policy/g1_gear_wbc_policy.py` and
`src/simple/robots/g1_sonic.py:prepare_obs`. No global pose or heading sensor is
added to the public observation by documenting the command convention.

All 36 entries must be finite real numbers; booleans and strings are rejected.
The service forwards finite joint targets without additional range rejection
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

The runtime policy channel is observation → action. Public benchmark
documentation and interface definitions may be consulted. Private worker data,
live simulator/scorer state, reset metadata and evaluator-only diagnostic or
episode evidence must not become additional runtime inputs. Generic policy
stop ends the rollout; it does not create native success.
