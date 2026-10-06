# Historical simpler_env result adoption — 2026-09-10

This directory indexes 17 closed historical attempts and contains exact-byte
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
| google_robot_pick_horizontal_coke_can | simpler-codeagent-first-two-20260907 / case-000 | completed | true | 33 | 121 | [overhead_camera](media/simpler_env/2026-09-06-google_robot_pick_horizontal_coke_can-follow-the-current-instruction-in-the-camera-observation-run-3a90a7b22538-case-000-120cf31f/overhead_camera-video.mp4) |
| widowx_spoon_on_towel | simpler-codeagent-first-two-20260907 / case-001 | completed | false | 38 | 120 | [3rd_view_camera](media/simpler_env/2026-09-06-widowx_spoon_on_towel-follow-the-current-instruction-in-the-camera-observation-run-1214d86022d7-case-001-7da88c38/3rd_view_camera-video.mp4) |
| google_robot_pick_horizontal_coke_can | simpler-task-coverage-20260907-001 / case-000 | completed | true | 25 | 78 | [overhead_camera](media/simpler_env/2026-09-06-google_robot_pick_horizontal_coke_can-follow-the-current-instruction-in-the-camera-observation-run-4418bd8c8de4-case-000-120cf31f/overhead_camera-video.mp4) |
| google_robot_pick_vertical_coke_can | simpler-task-coverage-20260907-001 / case-001 | completed | true | 200 | 937 | [overhead_camera](media/simpler_env/2026-09-06-google_robot_pick_vertical_coke_can-follow-the-current-instruction-in-the-camera-observation-run-79c67731726d-case-001-c494314d/overhead_camera-video.mp4) |
| google_robot_pick_standing_coke_can | simpler-task-coverage-20260907-001 / case-002 | completed | true | 46 | 138 | [overhead_camera](media/simpler_env/2026-09-06-google_robot_pick_standing_coke_can-follow-the-current-instruction-in-the-camera-observation-run-50005d71f16d-case-002-0dae5b3d/overhead_camera-video.mp4) |
| google_robot_move_near_v0 | simpler-task-coverage-20260907-001 / case-003 | completed | true | 59 | 194 | [overhead_camera](media/simpler_env/2026-09-06-google_robot_move_near_v0-follow-the-current-instruction-in-the-camera-observation-run-c156499edc09-case-003-0243c76a/overhead_camera-video.mp4) |
| google_robot_open_top_drawer | simpler-task-coverage-20260907-001 / case-004 | completed | false | 2 | 1 | [overhead_camera](media/simpler_env/2026-09-06-google_robot_open_top_drawer-follow-the-current-instruction-in-the-camera-observation-run-fa1353c8516e-case-004-37f1e3e9/overhead_camera-video.mp4) |
| google_robot_open_middle_drawer | simpler-task-coverage-20260907-001 / case-005 | completed | false | 2 | 1 | [overhead_camera](media/simpler_env/2026-09-07-google_robot_open_middle_drawer-follow-the-current-instruction-in-the-camera-observation-run-b17dad38f403-case-005-c810627a/overhead_camera-video.mp4) |
| google_robot_open_bottom_drawer | simpler-task-coverage-20260907-001 / case-006 | completed | false | 35 | 130 | [overhead_camera](media/simpler_env/2026-09-07-google_robot_open_bottom_drawer-follow-the-current-instruction-in-the-camera-observation-run-53753b37b7ac-case-006-cf7f5a23/overhead_camera-video.mp4) |
| google_robot_close_top_drawer | simpler-task-coverage-20260907-001 / case-007 | completed | true | 53 | 195 | [overhead_camera](media/simpler_env/2026-09-07-google_robot_close_top_drawer-follow-the-current-instruction-in-the-camera-observation-run-dc97f41e68bd-case-007-4e692cd0/overhead_camera-video.mp4) |
| google_robot_close_middle_drawer | simpler-task-coverage-20260907-001 / case-008 | error | unknown | 12 | 23 | [overhead_camera](media/archive/simpler_env/2026-09-07-google_robot_close_middle_drawer-follow-the-current-instruction-in-the-camera-observation-run-721a3a471bbd-case-008-1e1aa5c1/overhead_camera-video.mp4) |
| google_robot_close_bottom_drawer | simpler-task-coverage-20260907-001 / case-009 | completed | true | 77 | 329 | [overhead_camera](media/simpler_env/2026-09-07-google_robot_close_bottom_drawer-follow-the-current-instruction-in-the-camera-observation-run-467a84fb60ce-case-009-95bb1660/overhead_camera-video.mp4) |
| google_robot_place_apple_in_closed_top_drawer | simpler-task-coverage-20260907-001 / case-010 | completed | false | 72 | 238 | [overhead_camera](media/simpler_env/2026-09-07-google_robot_place_apple_in_closed_top_drawer-follow-the-current-instruction-in-the-camera-observation-run-025bd8203a14-case-010-73a1c3b8/overhead_camera-video.mp4) |
| widowx_spoon_on_towel | simpler-task-coverage-20260907-001 / case-011 | completed | true | 52 | 206 | [3rd_view_camera](media/simpler_env/2026-09-07-widowx_spoon_on_towel-follow-the-current-instruction-in-the-camera-observation-run-55e6630615d5-case-011-7da88c38/3rd_view_camera-video.mp4) |
| widowx_carrot_on_plate | simpler-task-coverage-20260907-001 / case-012 | completed | true | 60 | 242 | [3rd_view_camera](media/simpler_env/2026-09-07-widowx_carrot_on_plate-follow-the-current-instruction-in-the-camera-observation-run-aefdf99e4605-case-012-93a13b83/3rd_view_camera-video.mp4) |
| widowx_stack_cube | simpler-task-coverage-20260907-001 / case-013 | error | unknown | 1 | 0 | [3rd_view_camera](media/archive/simpler_env/2026-09-07-widowx_stack_cube-follow-the-current-instruction-in-the-camera-observation-run-1f821215c4ae-case-013-dc65a1e5/3rd_view_camera-video.mp4) |
| widowx_put_eggplant_in_basket | simpler-task-coverage-20260907-001 / case-014 | completed | true | 22 | 49 | [3rd_view_camera](media/simpler_env/2026-09-07-widowx_put_eggplant_in_basket-follow-the-current-instruction-in-the-camera-observation-run-87ff0a901fca-case-014-fed3930a/3rd_view_camera-video.mp4) |

The complete index retains each run's original protocol, status/summary, metrics,
errors, usage, source paths and selected-record hashes. Historical context and
protocol caveats remain in [the benchmark result reports](../../README.md).
Index SHA256: `227f2c2489ccb733d46640d41e84bab7a366fd975244cff45e55ea4bf9d74369`.

Media is Git-ignored. Index and this navigation document are tracked.
