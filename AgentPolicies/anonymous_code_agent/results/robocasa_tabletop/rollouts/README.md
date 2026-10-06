> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/Robocasa_tabletop/rollouts/README.md` at source revision `29cb55d`;
> original SHA256: `de1b535b60f201be7ef8d30a836986872ce4b7f057c4d2d07632995b5c0e2e5e`. Only documentation links were rebased.
> Existing relative export names below refer to the original `examples/simBenchmarks/Robocasa_tabletop/rollouts/` directory until an explicit adoption index records a new copy.

# Local Tabletop rollout videos

Generated archives are ignored by Git; only this documentation index is tracked.
Original result directories and failures must remain intact.

- `2026-09-09-PnPPotatoToMicrowaveClose-potato-into-microwave-and-close-next-pair-case000/`:
  native failure,280 controls/57 decisions;281-frame20Hz video,14.05s playback.
- `2026-09-09-PnPMilkToMicrowaveClose-milk-into-microwave-and-close-next-pair-case001/`:
  native failure,160 controls/33 decisions;161-frame20Hz video,8.05s playback.

The September9 [closed pair report](../reports/2026-09-09-next-pair.md) links both
videos. In each new directory, `ego_view_bg_crop_pad_res256_freq20.mp4` is an
exact hash-checked camera-labelled copy of the pinned exporter's `video.mp4`;
the original `index.json` and native artifacts remain untouched. These are
capability videos, not reset/hold diagnostics. Policy waiting is not video time.

Earlier retained exports:

- `2026-09-07-pilot-case000/`: CupToDrawer, native failure, 300 controls /
  61 decisions, one 301-frame native-camera video. See
  [closed evidence](../reports/2026-09-07-pilot-case000.md).
- `2026-09-07-pilot-case001/`: Novel tray-to-cardboard-box, native failure,
  265 controls / 54 decisions, one 266-frame native-camera video. See
  [closed evidence](../reports/2026-09-07-pilot-case001.md).

Both originals and copies passed full decode and SHA256 checks in the
[independent paired review](../../../../../project_readmes/reviews/2026-09-07-tabletop-closed-pilot-review.md).

Use the [shared closed-run exporter](../../../../../examples/simBenchmarks/SimplerEnv/export_videos.py). Copies
are SHA256-checked and retain the original outcome and paths. Do not export
active attempts, replace original videos or infer success from appearance.
