# Historical robodojo result adoption — 2026-09-10

This directory indexes 4 closed historical attempts and contains exact-byte
copies of their recorded MP4s. Original campaigns, manifests, source snapshots,
results and videos remain unchanged at the source paths in [index.json](index.json).
The model/provider identity remains unknown; this is not a named-model score.
Separate pilot/coverage/round protocols are preserved, not merged into a score.

Policy calls include stop-only responses; controls are executed environment
steps. Unknown success denotes a retained error, not a failed completed task.
Errored or zero-control/no-policy videos are visibly under `media/archive/`.
Playback excludes model waiting time. This adoption did not rerun a task,
re-encode a video or infer success from video appearance.

| Task | Original campaign / case | State | Native success | Policy calls | Controls | Original-byte videos |
| --- | --- | --- | --- | ---: | ---: | --- |
| push_T | robodojo-user-reference-pilot-20260907-002 / case-001 | error | unknown | 1 | 0 | [cam_head](media/archive/robodojo/2026-09-07-push_T-push-the-t-shaped-block-to-align-it-precisely-with-run-1fd792e4a358-case-001-2bfd66c0/cam_head-cam_head.mp4), [cam_left_wrist](media/archive/robodojo/2026-09-07-push_T-push-the-t-shaped-block-to-align-it-precisely-with-run-1fd792e4a358-case-001-2bfd66c0/cam_left_wrist-cam_left_wrist.mp4), [cam_right_wrist](media/archive/robodojo/2026-09-07-push_T-push-the-t-shaped-block-to-align-it-precisely-with-run-1fd792e4a358-case-001-2bfd66c0/cam_right_wrist-cam_right_wrist.mp4) |
| stack_bowls | robodojo-user-reference-round2-20260907-001 / case-000 | completed | false | 70 | 345 | [cam_head](media/robodojo/2026-09-07-stack_bowls-stack-the-three-bowls-together-run-3c38532fac83-case-000-c879d7dd/cam_head-cam_head.mp4), [cam_left_wrist](media/robodojo/2026-09-07-stack_bowls-stack-the-three-bowls-together-run-3c38532fac83-case-000-c879d7dd/cam_left_wrist-cam_left_wrist.mp4), [cam_right_wrist](media/robodojo/2026-09-07-stack_bowls-stack-the-three-bowls-together-run-3c38532fac83-case-000-c879d7dd/cam_right_wrist-cam_right_wrist.mp4) |
| push_T | robodojo-user-reference-round2-20260907-001 / case-001 | completed | false | 41 | 200 | [cam_head](media/robodojo/2026-09-07-push_T-push-the-t-shaped-block-to-align-it-precisely-with-run-98306465dce2-case-001-2bfd66c0/cam_head-cam_head.mp4), [cam_left_wrist](media/robodojo/2026-09-07-push_T-push-the-t-shaped-block-to-align-it-precisely-with-run-98306465dce2-case-001-2bfd66c0/cam_left_wrist-cam_left_wrist.mp4), [cam_right_wrist](media/robodojo/2026-09-07-push_T-push-the-t-shaped-block-to-align-it-precisely-with-run-98306465dce2-case-001-2bfd66c0/cam_right_wrist-cam_right_wrist.mp4) |
| pack_objects_into_box | robodojo-next-pair-20260908-001 / case-000 | completed | false | 15 | 70 | [cam_head](media/robodojo/2026-09-07-pack_objects_into_box-place-all-the-objects-into-the-box-with-their-front-run-fd736369e766-case-000-8b02c354/cam_head-cam_head.mp4), [cam_left_wrist](media/robodojo/2026-09-07-pack_objects_into_box-place-all-the-objects-into-the-box-with-their-front-run-fd736369e766-case-000-8b02c354/cam_left_wrist-cam_left_wrist.mp4), [cam_right_wrist](media/robodojo/2026-09-07-pack_objects_into_box-place-all-the-objects-into-the-box-with-their-front-run-fd736369e766-case-000-8b02c354/cam_right_wrist-cam_right_wrist.mp4) |

The complete index retains each run's original protocol, status/summary, metrics,
errors, usage, source paths and selected-record hashes. Historical context and
protocol caveats remain in [the benchmark result reports](../../README.md).
Index SHA256: `270d4281bc2f366e1e65bc54a0dc20e8ac932482b3f3a2f25124c68e499a16d2`.

Media is Git-ignored. Index and this navigation document are tracked.
