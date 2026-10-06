# RoboTwin: GPT6Astra agent-method sample

## 2026-10-04: one closed pot-lifting sample

The preselected `lift_pot` sample completed with native failure:
**0 successes / 1 selected case**, 0 errors, **1 policy call, 0 executed action
decisions and 0 controls**. The first response requested `give_up` without an
action. This is a normal model stop, not an infrastructure error; it does not
demonstrate model-controlled robot motion. There was no automatic retry.

- Protocol: `robotwin-local-content/clean-fixed-seed/qpos14-rgb320-oidn233/fast-v2`;
  `demo_clean`, one preselected unscreened native seed `100000`, episode 0.
  The separate run/episode seed recorded by the client is `20261004`.
- Budgets: native target-control horizon 400, method-owned policy-call cap 400;
  method-owned chunk/replan setting 5. Unused budget is not executed control.
- Method: `codex-native/v1`, requested `gpt-6-astra` with `xhigh` reasoning.
- Native source identity: local content inventory, not an invented Git revision;
  the inventory identity is retained in the report.
- Observations: language plus three native 320×240 RGB cameras, no state vector;
  the public control contract is 14 absolute native joint/gripper targets.

This fixed-seed development track does not run expert feasibility screening,
search for a successful seed, or implement the native full evaluation schedule.
The explicit OIDN 2.3.3 renderer compatibility track is separate from the bundled
OIDN 2.0.1 track; pixel parity or interchangeable scores are not claimed.
Closed records do not prove complete final-scene asset coverage. Native setup
includes fixed homestate/gripper/settling behavior; zero model controls does not
mean zero initialization motion or physics.

The CLI model/provider identity is requested, not independently attested.
Provider-internal requests/retries and cost are unknown; available tokens are
CLI-reported. This is a single selected sample, not a benchmark-wide score or
native-full result. Earlier readiness diagnostics are infrastructure evidence,
not scored model cases.

## Reports and optional videos

- [JSON result](reports/2026-10-04-lift_pot-pot-lifting-post-convergence-once/result.json),
  [HTML result](reports/2026-10-04-lift_pot-pot-lifting-post-convergence-once/index.html),
  and [result index](index.json).
- Raw-export videos: [head camera](raw/2026-10-04-lift_pot-pot-lifting-post-convergence-once/client/episodes/lift_pot-native-seed100000-episode000/artifacts/sim_server_files/head_camera.mp4),
  [left camera](raw/2026-10-04-lift_pot-pot-lifting-post-convergence-once/client/episodes/lift_pot-native-seed100000-episode000/artifacts/sim_server_files/left_camera.mp4),
  and [right camera](raw/2026-10-04-lift_pot-pot-lifting-post-convergence-once/client/episodes/lift_pot-native-seed100000-episode000/artifacts/sim_server_files/right_camera.mp4).

Each video contains just the initial observation frame; it is not a motion demo.
These optional Git-ignored artifacts are not bundled in this source checkout.
Private audits and raw records are separate from public result requirements.

## Follow-up: immediate-stop diagnosis

The exact first model output explicitly requested `give_up`, with no actions,
and explained that measured joint state was absent and the arms were not
visible enough to choose reliable absolute targets. The delivered prompt,
three RGB attachments and output schema match the recorded request hashes;
the retained final text matches its response hash. The parser did not synthesize
the stop, and the driver exited before any robot control. This establishes the
stop path, not a counterfactual claim about what the model would have done with
different inputs.

Inspection found an observation-design gap in this old RGB-only track. The
native `joint_action.vector` is indeed commanded drive targets, not measured
encoders, but the pinned robot also provides `get_left_arm_real_jointState`
and `get_right_arm_real_jointState`. Their arm values come from articulation
`get_qpos`; each appended gripper value remains a command, not measured opening.
Those robot-owned channels were not exposed by this track. The image transfer
was intact; this is not evidence of a transport loss or an engine time limit.

A separately versioned server observation repair is being validated. It must
label measured arm joints and commanded grippers distinctly, keep object truth
private, and preserve native actions, cameras, scoring and budgets. This old
sample remains a one-call, zero-control failure under its original protocol;
it does not validate model actuation. No replacement outcome or automatic retry
is implied by the repair.

See the [benchmark protocol](../../../../examples/simBenchmarks/Robotwin/EVALUATION_PROTOCOL.md)
and [result organization](../README.md).
