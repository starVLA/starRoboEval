# SimplerEnv: one Codex-controlled SIM-server case

One selected `google_robot_pick_horizontal_coke_can` attempt finished with native
success **false**: 49 policy calls, 48 executed action decisions and 109 controls.
The final call voluntarily stopped without an action. The policy reported no
stable grasp after repeated approaches and withdrew as the can approached the
table edge. Native scoring, not that explanation, determines the result. No first
native success was recorded, and the attempt was not retried.

## Conditions and limits

- Source: `c2a54f323ebb2b7bafacd6dab8ca27dc7208a52d`.
- Independent SIM server and evaluator, `starvla-rsi.sim-server/v1`;
  the policy used only its declared observation mailbox.
- One prepackaged task/reset, seed 20260907. This historically scoring task
  was selected for integration validation, not representative sampling.
- Decision track: at most 200 calls, up to 5 controls per response, a
  1000-control cap. This task's pinned registration reference horizon is 80;
  success at that horizon was also false. This is not native full VM/VA scoring.
- Public RGB/language and direct 7-dimensional end-effector delta-pose/gripper
  actions at 3 Hz; no native poses, reward or scorer metadata given to the policy.
- Fresh Codex context, no configured model API and no task-solving fallback.
  Provider/model snapshot and token/cost accounting remain unknown; this is not
  a verified GPT6Astra score. Ordinary give-up minimum was 0, a model-owned setting.

The generic closed-record audit passed, with no recorded execution or cleanup
error. This single development attempt does not establish a benchmark-wide model
score or full native parity, and must not be merged into historical coverage.

Independent inspection matched all 115 exported artifacts against native files
and evaluator copies, and all 49 public RGB observations pixel-for-pixel against
native PNGs. All 110 PNGs validated; the video decoded 110 frames at 3 fps with
no identical adjacent frames. Visual checks at controls 0, 55 and 109 show robot
and can motion. Both processes exited 0. Counts agree across events, receipts and
retained native metrics, but no independent native action-start/end physics trace
exists; these checks must not be represented as such a trace.

## Records and video

The [hash-bound index](../indices/2026-09-15-google_robot_pick_horizontal_coke_can-horizontal-can-pickup-sim-server-v1/index.json)
contains the result, first-success fields and one exact-byte camera video copy.
The [original run](../raw/2026-09-15-google_robot_pick_horizontal_coke_can-horizontal-can-pickup-sim-server-v1/)
retains observations, controls, native receipts and source captures. Raw records
and media are Git-ignored; the report and lightweight index are trackable.
