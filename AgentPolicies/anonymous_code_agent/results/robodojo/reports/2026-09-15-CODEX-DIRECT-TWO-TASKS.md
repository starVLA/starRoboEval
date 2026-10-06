# Codex direct-control RoboDojo evaluation — 2026-09-15

Two selected tasks were each evaluated once using fresh-context interactive
Codex actors through the new framework's `anonymous_code_agent` mailbox profile.
No model API configuration, trained policy, fallback controller or task retry
was used. Provider/model snapshot and provider token/cost accounting remain
unverified; this is not an API-verified GPT6Astra score.

Evaluated framework revision: `44a539d772c6fa4489eefa6795c2c3bb9b92a4a0`.
Native RoboDojo revision: `36bfcb7c580b149c6e39ed2eb77d60689152e570`.
This is a qualified historical-asset, RGB-only joint14 **fast** development
evaluation, not the official full benchmark or complete renderer-parity proof.

## Results

| Task | Native outcome | Score | Policy calls | Executed action decisions | Controls | Termination |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `stack_bowls` | Failure | 0/100 | 51 | 50 | 246 | `policy:give_up` |
| `push_T` | Failure | 0/100 | 50 | 50 | 248 | `environment:terminated` |

The selected denominator is **2 attempted, 2 protocol-completed, 0 successful,
0 evaluation errors, 0 retries, 0 unattempted**. Completion means the evaluation
closed correctly, not that the robot succeeded. Both processes returned 0.

Stacking used 2,460 execution physics ticks; pushing used 2,480. Initialization
was separately 842 ticks per task. No native-success control/decision was
recorded. Native process score was 0 for stacking and unavailable (`null`) for
pushing; these are distinct from the reported benchmark scores.

Stacking's final call requested voluntary give-up and executed no action.
Native unsuccessful termination was recorded at pushing's final control, 248:
`end_flag=true`, `alive_flag=false`, `success=false`. The retained native logs
do not supply a more specific failure reason, so none is inferred from video.

The frozen limits were 200 policy calls, at most five controls per call, a
1,000-control runner cap, and unchanged native horizons of 800/600. The optional
minimum of 50 action decisions before give-up belongs to this policy, not the
benchmark; it did not cause pushing's native termination or force either
episode to consume the full call budget.

## Videos and records

All six videos fully decode at 640×480 and 25 Hz. Stacking has 247 frames per camera;
pushing has 249. Exports are exact-byte copies with task descriptions and camera
identity in their paths. Their date prefix uses the original UTC creation date
(September 14); the report date is September 15 in Asia/Shanghai.

| Task | Head camera | Left wrist | Right wrist |
| --- | --- | --- | --- |
| Bowl stacking | [Video](../indices/2026-09-15-codex-stack_bowls-and-push_T/media/robodojo/2026-09-14-stack_bowls-bowl-stacking-run-a187217294d6-case-000-c879d7dd/cam_head-cam_head.mp4) | [Video](../indices/2026-09-15-codex-stack_bowls-and-push_T/media/robodojo/2026-09-14-stack_bowls-bowl-stacking-run-a187217294d6-case-000-c879d7dd/cam_left_wrist-cam_left_wrist.mp4) | [Video](../indices/2026-09-15-codex-stack_bowls-and-push_T/media/robodojo/2026-09-14-stack_bowls-bowl-stacking-run-a187217294d6-case-000-c879d7dd/cam_right_wrist-cam_right_wrist.mp4) |
| T-block alignment | [Video](../indices/2026-09-15-codex-stack_bowls-and-push_T/media/robodojo/2026-09-14-push_T-t-block-alignment-run-c3b16f0872a7-case-001-2bfd66c0/cam_head-cam_head.mp4) | [Video](../indices/2026-09-15-codex-stack_bowls-and-push_T/media/robodojo/2026-09-14-push_T-t-block-alignment-run-c3b16f0872a7-case-001-2bfd66c0/cam_left_wrist-cam_left_wrist.mp4) | [Video](../indices/2026-09-15-codex-stack_bowls-and-push_T/media/robodojo/2026-09-14-push_T-t-block-alignment-run-c3b16f0872a7-case-001-2bfd66c0/cam_right_wrist-cam_right_wrist.mp4) |

[Exact-byte result/media index](../indices/2026-09-15-codex-stack_bowls-and-push_T/index.json).
Original results, events, images, source snapshots and errors remain under
[the frozen campaign](../raw/2026-09-15-stack_bowls-bowl-stacking-and-push_T-t-block-alignment-codex/campaign).

Independent closed-record/native-event/public-image/video checks passed:

- [Stacking audit](../raw/2026-09-15-stack_bowls-bowl-stacking-and-push_T-t-block-alignment-codex/stack_bowls-closed-audit.json), SHA256 `7234ce5439b55a7f50d3128d34a83d19b96407a9185758010a7040749064fe9e`.
- [Pushing audit](../raw/2026-09-15-stack_bowls-bowl-stacking-and-push_T-t-block-alignment-codex/push_T-closed-audit.json), SHA256 `d99abedcc8d1d203e9c7c8f709eef817ae6518fc45d1157c6c471409d07db5e9`.

Both cleanup acknowledgements, shutdown-start records and waited child exits
were verified. `app_shutdown_return_observed=false` remains recorded separately;
process exit is not substituted for a Python application-close return.
These audits establish retained artifact consistency, not native replay,
provider attestation or an enforced actor security sandbox.

## Environment evidence

[Deployment notes](../raw/2026-09-15-stack_bowls-bowl-stacking-and-push_T-t-block-alignment-codex/DEPLOYMENT.md)
record the read-only historical snapshot binding, existing SOCKS route for
original NVIDIA materials, and all retained non-capability readiness probes.
The successful probes each used zero policy calls and one diagnostic hold;
they are excluded from the model denominator. Earlier relative-path and
network-blocked probes remain explicitly failed/aborted, not hidden retries.

The host's 8,441 declared reference counterparts and 97 declared absent files
matched before and after execution (inventory SHA256
`cf15b95c0a4fa4e630df66058ede344f8f91594263b6d99d44af16ed15157f05`).
No shared reference asset or historical evaluation record was overwritten.
All native workers for this round have exited. No Git push was performed.
