# Public GR1 Tabletop robot interface

Use only the current declared RGB image, task language and 29 measured joint
encoders. The native language may begin with `unlocked_waist:`. The image is the
native 256x256 egocentric crop. No other view, object/EEF/world pose, reward,
success signal, reset metadata or simulator API is available to the policy.

Each action contains 29 physical absolute joint-position targets in radians,
not normalized values, velocities or Cartesian deltas. Each service step
executes one vector and advances 50 ms, with no hidden extra repeats. The
public action specification gives the ordered joint names and command bounds.

In `budget_mode="horizon"`, the selected `control_step_cap` is at most 1000;
decision frequency, action grouping and additional call limits belong to the
participant method. The separately retained `budget_mode="decisions"` track
couples D=1–200 calls and K=1–5 controls per response to a D × K control cap.
These are different protocol tracks, not a universal decision limit. The
24-task seeded scope supports only the horizon track. See the
[evaluation protocol](../../EVALUATION_PROTOCOL.md#budgets-and-scoring).

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
