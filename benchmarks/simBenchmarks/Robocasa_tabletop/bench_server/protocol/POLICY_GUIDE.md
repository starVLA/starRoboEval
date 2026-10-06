# Public GR1 tabletop policy interface

Use only the current declared RGB image, task language and 29 measured joint
encoders. The native language may begin with `unlocked_waist:`. The image is the
native 256x256 egocentric crop. No other view, object/EEF/world pose, reward,
success signal, reset metadata or simulator API is available to the policy.

Each action contains 29 physical absolute joint-position targets in radians,
not normalized values, velocities or Cartesian deltas. Execute one to five
vectors per decision; each vector advances 50 ms, with no hidden extra repeats.
The provisional budget is at most 200 policy decisions. The public action
specification gives the exact ordered joint names and command bounds.

| Slots | Joint/command order |
| --- | --- |
| 0–6 | Left shoulder pitch, roll, yaw; elbow pitch; wrist yaw, roll, pitch |
| 7–13 | Corresponding right arm joints |
| 14–19 | Left pinky, ring, middle, index, thumb pitch, thumb yaw |
| 20–25 | Corresponding right hand commands |
| 26–28 | Waist yaw, pitch, roll |

Each hand's six commands drive eleven native position actuators with expansion
indices `[0,0,1,1,2,2,3,3,4,4,5]`. Command limits intersect the paired joints'
mechanical limits and actuator ranges. Hand observations instead select the
native measured intermediate finger joints, thumb proximal pitch and thumb yaw;
they are not already the eleven actuator commands. The named public encoder
order is authoritative. Values near a measured joint limit need not be valid
targets for both joints sharing one command; use the declared action bounds.

Arm and waist actions use native absolute joint-position control. There is no
adapter IK, model normalization, clipping, grasp planner or task-specific macro.
All entries must be finite numbers within the public action bounds; strings and
booleans are invalid. A deliberate generic stop ends the rollout and does not
assert task success. Do not inspect native state or private evaluator artifacts
to plan actions or decide whether success occurred.
