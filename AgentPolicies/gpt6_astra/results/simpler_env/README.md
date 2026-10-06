# SimplerEnv: GPT6Astra agent-method samples

## 2026-10-04: one closed native-horizon sample

The preselected `google_robot_pick_horizontal_coke_can` sample completed with
native failure: **0 successes / 1 selected case**, 0 errors, 76 policy calls,
76 executed action decisions and 80 controls. It reached the 80-control task
horizon with `environment:truncated`; no action was rejected and there was no
automatic retry.

- Protocol: `simpler-prepackaged-development/rgb/action-feedback/agent-method/v1`;
  seed `20260907`, control budget 80.
- Method: `codex-native/v1`, requested `gpt-6-astra` with `xhigh` reasoning;
  method-owned policy-call cap 200 and chunk/replan setting 5. These are not
  universal server limits.
- [JSON result](reports/2026-10-04-google_robot_pick_horizontal_coke_can-can-picking-post-convergence-once-independent-audit/result.json)
  and [HTML result](reports/2026-10-04-google_robot_pick_horizontal_coke_can-can-picking-post-convergence-once-independent-audit/index.html).
- Optional [overhead-camera video](raw/2026-10-04-google_robot_pick_horizontal_coke_can-can-picking-post-convergence-once/client/episodes/google_robot_pick_horizontal_coke_can-000000/artifacts/sim_server_files/video.mp4)
  is retained in the Git-ignored raw export; it is not bundled in this source checkout.

The CLI model/provider identity is requested, not independently attested.
Provider-internal request/retry counts and cost are unknown; available token
counts are CLI-reported. This single sample is not a benchmark-wide score or
native-full evaluation. Earlier readiness diagnostics are infrastructure checks,
not scored model cases. [The index](index.json) preserves each run separately;
do not pool this horizon track with the different 2026-09-20 decision track.

## 2026-09-20: preserved historical development-track attempt

This fixed horizontal-can sample closed with an **infrastructure error on policy
call 101** (`stderr_rejected`), after **100 executed action decisions and 103
controls**. There were zero rejected actions. Its original result retains
`success: null`: this is not a completed model failure or a measured 0% success
rate. One attempt was made, with no automatic retry.

The requested CLI model was `gpt-6-astra`, using `codex-native/v1` and
`codex-exec/v1`. The request is not independent backend model/provider identity
attestation. Full-run token totals remain unknown because call 101 did not
return usage; the report separately preserves the partial CLI-reported sum for
the 100 returned decisions. Provider-internal calls, retries and cost are unknown.

### Conditions and outcome

| Field | Recorded value |
| --- | --- |
| Task | `google_robot_pick_horizontal_coke_can` |
| Reset | Prepackaged seeded reset, seed `20260907` |
| Protocol | `simpler-prepackaged-development/rgb/decision-200-prefix-5/action-feedback/v1` |
| Model observation | `overhead_camera` RGB, 640×512; no robot state |
| Model action | Seven physical measured-pose translation/axis-angle/gripper deltas |
| Budget | 200 calls; at most 5 controls per decision; 1000-control cap |
| Native reference horizon | 80 controls; the selected development track is different |
| End | `error:infrastructure`, call 101, after 103 controls |
| Wall time | 2733.871 seconds (45.6 minutes) |
| Native success at control 80 | False |
| Last acknowledged native success, control 103 | False |
| Any intermediate native success | None observed |

The native flags are diagnostics from already acknowledged step records, not a
replacement final score for an interrupted attempt. SimplerEnv's scored protocol
uses the last executed step on a protocol-completed episode, not best-of-trajectory
success. No extra scorer queries, resets or retries were performed.

The CLI receipt records 172 stderr bytes and exit code -15 after the wrapper
stopped the invocation. It does not retain the underlying stderr text. Therefore
this report does not claim the cause was networking, quota or model behavior.
Known wrapper cleanup succeeded; the error remains in the original result.

### Reports and video

- [Sample result, conditions and evidence hashes](reports/2026-09-20-google_robot_pick_horizontal_coke_can-horizontal-can-picking-bench-server-native-v1-sample/result.json)
- [Episode outcome](reports/2026-09-20-google_robot_pick_horizontal_coke_can-horizontal-can-picking-bench-server-native-v1-sample/episodes.json)
- [Sanitized record audit](reports/2026-09-20-google_robot_pick_horizontal_coke_can-horizontal-can-picking-bench-server-native-v1-sample/record-audit.json)
- [Video inventory](reports/2026-09-20-google_robot_pick_horizontal_coke_can-horizontal-can-picking-bench-server-native-v1-sample/media.json)
- [Overhead camera video](media/2026-09-20-google_robot_pick_horizontal_coke_can-horizontal-can-picking-bench-server-native-v1-sample/overhead_camera.mp4)

The video decodes to 104 frames at 640×512, 3 Hz, with increasing timestamps
(initial observation plus 103 controls). Server original, local client download,
exported client and presentation copy hashes match. This verifies video bytes
and decoding, not visual proof of task success or renderer/asset parity.

The closed-record audit passed: 131 runtime-source and 29 model-source files,
101 started calls, 100 returned action decisions and 103 controls. Record
consistency does not establish native replay, OS isolation, backend identity or
trusted provider accounting.

`reports/` and [index.json](index.json) are portable summaries. `media/` is
Git-ignored and can be released using its inventory. Raw evidence is unchanged;
evidence `paths` arrays name alternative local/exported-client locations relative
to this result directory. Deployment provenance remains in private raw records.

See [the benchmark protocol](../../../../examples/simBenchmarks/SimplerEnv/EVALUATION_PROTOCOL.md)
and [result layout](../README.md).
