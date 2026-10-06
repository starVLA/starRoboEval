# RoboCasa365: one Codex-controlled SIM-server case

## Outcome and qualification

One explicitly selected `NavigateKitchen` attempt was completed through the
independently hosted SIM server. The original native result is **false**, with
`policy:safety_stop`: 10 policy calls, 9 executed action decisions and 41 controls.
There were no recorded execution/cleanup errors, and both processes exited 0.
No first native success was observed. No task was retried.

**This is an observation-anomaly-qualified attempt, not a clean model capability
failure or a complete native-validation pass.** Late native images from different
cameras collapse to essentially the same scene, alternating vertical orientation.
The policy reported unreliable views and stopped. Preserve the original result;
do not remove the attempt from the selected denominator or silently replace it.

## Conditions

- Execution source: local commit `c2a54f323ebb2b7bafacd6dab8ca27dc7208a52d`.
- Service transport: `starvla-rsi.sim-server/v1`; separate server and evaluator
  processes, with the policy restricted to its declared observation mailbox.
- Selection: default `pilot` scope, task ID 1, seed 20260907, one episode.
  This historically scoring task was selected for integration validation, not
  as a representative benchmark sample.
- Budget: decision track, at most 200 calls, up to 5 controls per response,
  1000-control cap; native task reference horizon remains 450.
- Policy: fresh Codex code-agent context, no configured model API, no fallback
  task solver. Provider/model snapshot and token/cost accounting are unknown;
  this is not a verified GPT6Astra score. Minimum ordinary-give-up decisions: 0.
- Three declared RGB views; no robot/world poses, scorer state or reset metadata
  were supplied to the policy. Native success remained evaluator-private.

## Closed evidence

Independent inspection found agreement between 41 native action starts/ends,
41 evaluator control events and the server's 41 returned transitions. All 137
exported artifacts match server originals and the transfer receipt. All 30
policy camera frames from the 10 observations match the corresponding server
PNGs pixel-for-pixel. Each of the three videos has 42 decoded frames.
The server and evaluator's 72-file harness snapshots match the unchanged
execution source. These are record/file checks, not native replay or provider
attestation.

The visual anomaly begins around controls 34–36. At control 41 the left/wrist
mean absolute pixel difference is approximately 0.012 on the 0–255 scale; the
vertically flipped left/right difference is approximately 0.014. Their reset
views differed by approximately 53. The anomaly therefore precedes HTTP and
mailbox transport; it is not evidence that those transports changed pixels.

Static inspection does not establish a definitive native root cause. Cached
observation reuse and stale renderer readback are hypotheses, not confirmed
diagnoses. Do not automatically flip images back, request an extra render or
change control semantics to repair a scored attempt. Further native investigation
requires a separately authorized diagnostic; this attempt remains closed.

The subsequent [offline RGB audit v2](../raw/2026-09-15-NavigateKitchen-navigate-to-kitchen-fixture-sim-server-v1/rgb-integrity-audit-v2.json)
checks all 126 PNGs at 42 steps against the clean 41-control receipt. It records
four heuristic warnings (one sustained camera-collapse run and three alternating
orientation runs), plus auditor/dependency identity and receipt/manifest hashes.
Its SHA256 is `42ece451dcf75965533b93bd3d7796ffdb69b5b6a9251bc21eade2d31f191634`.
The earlier v1 audit remains byte-identical; neither audit changes the result.

## Records and videos

[Hash-bound index](../indices/2026-09-15-NavigateKitchen-navigate-to-kitchen-fixture-sim-server-v1/index.json)
and [original run](../raw/2026-09-15-NavigateKitchen-navigate-to-kitchen-fixture-sim-server-v1/)
retain the selected denominator and failure. Raw records/media are Git-ignored;
the lightweight report/index are trackable. Exported videos preserve task
description and camera identity:

- [Left camera](../indices/2026-09-15-NavigateKitchen-navigate-to-kitchen-fixture-sim-server-v1/media/robocasa365/2026-09-15-NavigateKitchen-kitchen-navigation-NavigateKitchen-navigate-to-kitchen-fixture-direct-control-06051ad199cf-evaluator-13b982ee/robot0_agentview_left-robot0_agentview_left.mp4)
- [Right camera](../indices/2026-09-15-NavigateKitchen-navigate-to-kitchen-fixture-sim-server-v1/media/robocasa365/2026-09-15-NavigateKitchen-kitchen-navigation-NavigateKitchen-navigate-to-kitchen-fixture-direct-control-06051ad199cf-evaluator-13b982ee/robot0_agentview_right-robot0_agentview_right.mp4)
- [Wrist camera](../indices/2026-09-15-NavigateKitchen-navigate-to-kitchen-fixture-sim-server-v1/media/robocasa365/2026-09-15-NavigateKitchen-kitchen-navigation-NavigateKitchen-navigate-to-kitchen-fixture-direct-control-06051ad199cf-evaluator-13b982ee/robot0_eye_in_hand-robot0_eye_in_hand.mp4)

This one selected development case is neither native full evaluation nor a
statistically reliable model score.
