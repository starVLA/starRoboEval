# Robot-control acknowledgement feedback

The public RoboDojo service always exposes the declared, robot-only
`robodojo.robot-control-feedback/v1` channel. It is part of the fixed protocol,
not a runtime option or a requirement to use a particular agent.

The benchmark descriptor gains `-robot-feedback-v1` before any
`-infrastructure-only` diagnostic suffix. `ObservationSpec.control_feedback_schema`
advertises the exact schema; the selected episode's evaluator-private metadata
also records `robot_feedback_schema`. The fixed service parameters, descriptor,
observation spec and source are frozen before any claim.

Start from [server.example.json](server.example.json), replace the deployment
path/digest and select a named panel from [the task catalog](bench_server/protocol/task_catalog.json).
The server injects the feedback
schema and rejects protocol/feedback selectors in operator configuration.

## One receipt per real control

Reset has no `control_feedback`: no control has executed. After each actual
native control has passed its existing command/physics/reward counter checks,
the worker projects this closed payload into `Observation.control_feedback`:

| Field | Meaning |
| --- | --- |
| `schema` | Exactly `robodojo.robot-control-feedback/v1` |
| `control_target` | Positive acknowledged native-control count, matching this observation's step |
| `diagnostic_phase` | Exactly `pre_control`; applies to the DLS/FK diagnostics below |
| `executed_joint_command` | 14 finite values: left joint1–6 radians/opening, then right joint1–6/opening; the command passed to native control, not a measured achieved pose |
| `post_robot_state` | The same 28 robot measurements/last opening commands already present in this ACK's public state, after execution |
| `ik_diagnostics.left`, `.right` | The strictly defined robot-only numerical fields below |

Each arm diagnostic contains only:

- `target_position_error_m`, `target_rotation_error_rad`: nonnegative finite
  target errors **before this control's DLS update and physical execution**.
- `proposed_joint_delta`: six finite commanded-minus-measured joint values.
- `bounded_task_delta`: six finite DLS task-space values, translation then
  rotation vector; these are the existing fixed controller's numerical inputs.
- `measured_fk_check`: finite nonnegative `position_error_m`,
  `rotation_error_rad`, and `passed: true`, satisfying the existing 2 mm/0.01 rad
  guard before the control. This compares robot FK with measured link6, not an
  object, collision prediction or task-success check.

The fixed method remains `robot_only_numerical_jacobian_dls`. Neither a valid
receipt nor a small FK error establishes physical target tracking, collision
avoidance, a grasp, or task success. The measured post-state may differ from the
command; the channel does not replace it with an IK prediction. No post-target
error is invented, and no extra environment observation or scorer query is made.

The [projector and validator](bench_server/protocol/robot_feedback.py) reject unknown public fields,
invalid types, boolean numeric aliases, nonfinite values, wrong vector sizes,
invalid openings and invalid measured quaternions. The adapter binds every
receipt to this exact acknowledged count and public robot state. Undeclared,
missing, stale or reset-time receipts are protocol errors, not recoverable
action rejections. Native failures and uncertain ACKs do not produce a receipt
or authorize replay.

## Delivery and boundaries

The shared service serializes the explicitly declared observation channel, not
`Transition.info`, metrics or arbitrary worker mappings. The agent-side loop
retains **every** acknowledged control in its ordered `control_acks` feedback,
including an acknowledged prefix before a later deterministic action rejection.
It must not collapse a five-control chunk to only its final receipt or duplicate
the final observation as a second control. Rejected zero-execution input creates
no ACK. The model consumes this history through its own versioned policy and
prompt; the benchmark does not tell it what target to choose next.

No object pose/identity, scene layout, contacts, camera calibration, reward,
score, success predicate, private filename or environment handle is exported.
Static robot calibration is not part of this extension. The server continues
to own native execution; model actors have no reset, metrics or administrative
client access. No IK math, native physics, asset, horizon or scoring rule changes.

CPU checks exercise projection, causal binding, schema compatibility and mocked
ACK accounting. They do not establish native trajectory/pixel parity, provider
identity, actual-model capability, or permission to repeat a selected case.
