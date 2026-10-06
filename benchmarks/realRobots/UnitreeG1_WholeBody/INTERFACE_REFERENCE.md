# G1 interface reference and safety gates

This page retains interface context from the retired collection/conversion
notes, not a training workflow or a new executable hardware contract. Dimensions
below describe a historical `test_sonic` recording and must be checked against
the selected controller, calibration and measured sensor channels before use.
They do not establish current hardware readiness or authorize motion.

## Historical sensor and command schema

| Recorded field | Size | Recorded interpretation |
| --- | ---: | --- |
| `observation.images.ego_view` | Image | Ego camera; the recording reports 50 fps, not a verified hardware control rate |
| `observation.state` | 43 | Left leg 6, right leg 6, waist 3, left arm 7, left hand 7, right arm 7, right hand 7 |
| `observation.eef_state` | 14 | Left wrist position 3/quaternion 4, then right wrist position 3/quaternion 4; frame and quaternion order require verification |
| `action.wbc` | 43 | Historical WBC command record; not interchangeable with a motion token |
| `action.motion_token` | 64 | SONIC controller latent command |
| `teleop.left_hand_joints` / `teleop.right_hand_joints` | 7 each | Historical left/right hand command groups |

The retained deployment bridge splits 78 values into 64 motion-token values
and two 7-value hand groups. That route is not a universal G1 action space or
an EEF interface. Do not silently swap six- and seven-value hand routes, joint
targets and latent commands, or checkpoint normalization conventions. Model
normalization and inference remain method-owned; controller capabilities must
be declared by any future hardware track.

## Hardware acceptance before evaluation

- Confirm operator authorization, an independent emergency stop and supervision.
- Validate controller modes, calibration and mode switching in mock/replay or
  simulation before considering physical motion.
- Define action units, frames, bounds, velocity/acceleration limits and dispatch
  timing; reject incompatible commands rather than inferring their meaning.
- Check camera/state freshness, command timeout, controller health and pause/stop
  handling. Hardware must not inherit a simulator's paused-time assumption.
- Record task/case identity, synchronized sensor/action timestamps, camera order,
  schema version, control counts and objective outcomes. No automatic real-scene
  reset or retry is implied.

See [deployment safety requirements](step3_deployment/README.md#safety-requirements)
and [SDK/controller notes](sdk_tools/README.md). Existing mocks and deployment
scripts are retained references, not proof of safety or a unified bench server.
