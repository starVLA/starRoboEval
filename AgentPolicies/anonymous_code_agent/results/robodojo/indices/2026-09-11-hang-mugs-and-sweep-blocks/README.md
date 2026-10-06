# Hang mugs / sweep blocks: six original videos

Both once-only tasks ended native unsuccessful (0/100); these are moving policy
trajectories, not reset/hold probes. [Results and decision counts](../../reports/2026-09-11-continuation-results.md).

| Task | Frames per camera | Playback at25fps | Videos |
| --- | ---: | ---: | --- |
| hang_mugs — mug hanging | 257 | 10.28 s | [Head](media/robodojo/2026-09-10-hang_mugs-mug-hanging-run-21751fde5b3f-case-000-b7517fe5/cam_head-cam_head.mp4) · [Left wrist](media/robodojo/2026-09-10-hang_mugs-mug-hanging-run-21751fde5b3f-case-000-b7517fe5/cam_left_wrist-cam_left_wrist.mp4) · [Right wrist](media/robodojo/2026-09-10-hang_mugs-mug-hanging-run-21751fde5b3f-case-000-b7517fe5/cam_right_wrist-cam_right_wrist.mp4) |
| sweep_blocks — block sweeping | 247 | 9.88 s | [Head](media/robodojo/2026-09-10-sweep_blocks-block-sweeping-run-0fe2b2b75169-case-001-636de90f/cam_head-cam_head.mp4) · [Left wrist](media/robodojo/2026-09-10-sweep_blocks-block-sweeping-run-0fe2b2b75169-case-001-636de90f/cam_left_wrist-cam_left_wrist.mp4) · [Right wrist](media/robodojo/2026-09-10-sweep_blocks-block-sweeping-run-0fe2b2b75169-case-001-636de90f/cam_right_wrist-cam_right_wrist.mp4) |

All six640x480 videos fully decoded and were copied byte-for-byte from the
closed runs:4,482,515 bytes total. No rerender, concatenation or frame repair.
Each starts with one reset observation, followed by one frame per completed
control target. Playback excludes policy waiting and intermediate physics ticks.
Directory names retain the original manifest's UTC date (September10); the
campaign date in Asia/Shanghai is September11. Task IDs and short English
descriptions are included in every video directory name.

The [machine-readable index](index.json) retains original result/source/video
hashes, anonymous identity, protocols, errors and null first-success evidence.
Its SHA256 is
`907fffe57a20df46b99028c8bd3a06e0b9b63c14e4aa83aad2006b8b30292e45`.
The [preselected source list](../../reports/2026-09-11-continuation-video-sources.json)
contains exactly these two runs and three cameras each. Original records remain
under the model-owned raw campaign. This is not full benchmark coverage or a
verified named-model score. Track this README/index, not generated `media/`.
