# Historical robocasa_tabletop result adoption — 2026-09-10

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
| gr1_unified/PnPCupToDrawerClose_GR1ArmsAndWaistFourierHands_Env | tabletop-pilot-20260907-001 / case-000 | completed | false | 61 | 300 | [ego_view_bg_crop_pad_res256_freq20](media/robocasa_tabletop/2026-09-06-gr1_unified_PnPCupToDrawerClose_GR1ArmsAndWaistFourierHands_Env-follow-the-native-tabletop-task-instruction-supplied-after-reset-run-09a4a01fd550-case-000-7bd8ce3a/ego_view_bg_crop_pad_res256_freq20-ego_view_bg_crop_pad_res256_freq20.mp4) |
| gr1_unified/PosttrainPnPNovelFromTrayToCardboardboxSplitA_GR1ArmsAndWaistFourierHands_Env | tabletop-pilot-20260907-001 / case-001 | completed | false | 54 | 265 | [ego_view_bg_crop_pad_res256_freq20](media/robocasa_tabletop/2026-09-06-gr1_unified_PosttrainPnPNovelFromTrayToCardboardboxSplitA_GR1ArmsAndWaistFourierHands_Env-follow-the-native-tabletop-task-instruction-supplied-after-reset-run-5a7c6bd67c77-case-001-2381f6ee/ego_view_bg_crop_pad_res256_freq20-ego_view_bg_crop_pad_res256_freq20.mp4) |
| gr1_unified/PnPPotatoToMicrowaveClose_GR1ArmsAndWaistFourierHands_Env | tabletop-next-pair-20260909-001 / case-000 | completed | false | 57 | 280 | [ego_view_bg_crop_pad_res256_freq20](media/robocasa_tabletop/2026-09-08-gr1_unified_PnPPotatoToMicrowaveClose_GR1ArmsAndWaistFourierHands_Env-follow-the-native-tabletop-task-instruction-supplied-after-reset-run-494a30ea4ed9-case-000-668d5f4c/ego_view_bg_crop_pad_res256_freq20-ego_view_bg_crop_pad_res256_freq20.mp4) |
| gr1_unified/PnPMilkToMicrowaveClose_GR1ArmsAndWaistFourierHands_Env | tabletop-next-pair-20260909-001 / case-001 | completed | false | 33 | 160 | [ego_view_bg_crop_pad_res256_freq20](media/robocasa_tabletop/2026-09-08-gr1_unified_PnPMilkToMicrowaveClose_GR1ArmsAndWaistFourierHands_Env-follow-the-native-tabletop-task-instruction-supplied-after-reset-run-f06d0c59661f-case-001-d1d6c8a8/ego_view_bg_crop_pad_res256_freq20-ego_view_bg_crop_pad_res256_freq20.mp4) |

The complete index retains each run's original protocol, status/summary, metrics,
errors, usage, source paths and selected-record hashes. Historical context and
protocol caveats remain in [the benchmark result reports](../../README.md).
Index SHA256: `dee17391e224d54661c542f7cec341c141e512bcafa12bd80ca639013c48422a`.

Media is Git-ignored. Index and this navigation document are tracked.
