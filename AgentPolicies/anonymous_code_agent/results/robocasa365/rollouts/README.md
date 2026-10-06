> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/Robocasa_365/rollouts/README.md` at source revision `29cb55d`;
> original SHA256: `36faf632ec1b85b1e90ca355fd56d04331b9296d563e60403ebcc4cf438aa11a`. Only documentation links were rebased.
> Existing relative export names below refer to the original `examples/simBenchmarks/Robocasa_365/rollouts/` directory until an explicit adoption index records a new copy.

# Local development rollout videos

Generated run subdirectories are ignored by Git. Keep this index as documentation;
do not add videos, image sequences, raw responses or archive JSON to the repo.

- `2026-09-08-GetToastedBread-retrieve-toasted-bread-target50-case017/`:
  GetToastedBread, native false480 controls/97 decisions, give-up, no error;
  three481-frame videos exported by the fixed helper. The
  [independent closed review](../../../../../project_readmes/reviews/2026-09-08-casa017-closed-review.md)
  passed full-media and original-response checks. This export follows the naming rule;
  older export paths below are retained historical identifiers.
- `2026-09-07-target50-case018/`: KettleBoiling, native false146 controls/
  32 decisions, give-up, no error; three147-frame videos. The
  [independent closed review](../../../../../project_readmes/reviews/2026-09-08-casa018-closed-review.md)
  verified all frames, response parsing and exact export bytes.

- `2026-09-07-pilot-case000/`: OpenDrawer, native failure, 328 controls / 67
  decisions, three original-camera videos copied with SHA256 verification.
  See [the closed case report](../reports/2026-09-07-pilot-case000.md).
- `2026-09-07-pilot-case001/`: NavigateKitchen, native success at control 125 /
  decision 25, three 126-frame videos copied with SHA256 verification.
  See [case 1](../reports/2026-09-07-pilot-case001.md) and the
  [independent paired review](../../../../../project_readmes/reviews/2026-09-07-robocasa365-closed-pilot-review.md).

Use the shared closed-run exporter; never export an active attempt, rerender a
replacement video, delete the original result, or treat video appearance as a
replacement for the native success flag.

- `2026-09-07-target50-case000/`: CloseBlenderLid, native false at180 controls/
  37 decisions, first success null; three181-frame videos retained. See the
  [target50 coverage report](../reports/2026-09-07-task-coverage.md).
- `2026-09-07-target50-case001/`: CloseFridge, native false at245 controls/
  50 decisions, first success null; three246-frame20Hz videos retained and
  checked by the reviewed artifact CLI, including all presentation timestamps.
- `2026-09-07-target50-case002/`: CloseToasterOvenDoor, false at198 controls/
  41 decisions, first success null; three199-frame20Hz videos retained and
  checked by the accepted artifact CLI, including all presentation timestamps.
- `2026-09-07-target50-case003/`: CoffeeSetupMug, false at176 controls/
  37 decisions, first success null; three177-frame20Hz videos retained. An
  offline tool-update collision was rejected; a fixed-version check verified
  the unchanged closed artifacts without rerunning the native task.
- `2026-09-07-target50-case004/`: OpenCabinet, false at90 controls/19 decisions,
  first success null; three91-frame20Hz videos retained. The fixed-tool record,
  progress, export and complete artifact checks all finished successfully.
- `2026-09-07-target50-case005/`: OpenStandMixerHead, false at149 controls/
  32 decisions, first success null; three150-frame20Hz videos retained. All
  four fixed-tool postprocessors passed, with no native retry or rescore.
- `2026-09-07-target50-case006/`: PickPlaceCounterToCabinet, false at210
  controls/43 decisions, first success null; three211-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without native retry or rescore.
- `2026-09-07-target50-case007/`: PickPlaceCounterToStove, first/final native
  success at398 controls/81 decisions; three399-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without native retry or rescore.
- `2026-09-07-target50-case008/`: PickPlaceDrawerToCounter, native false at
  171 controls/37 decisions, first successnull; three172-frame20Hz videos
  retained. All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case009/`: PickPlaceSinkToCounter, native false at
  266 controls/55 decisions, first successnull; three267-frame20Hz videos
  retained. All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case010/`: PickPlaceToasterToCounter, native false at
  189 controls/40 decisions, first successnull; three190-frame20Hz videos
  retained. All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case011/`: SlideDishwasherRack, native false at230
  controls/47 decisions, first successnull; three231-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case012/`: TurnOffStove, native false at318 controls/
  66 decisions, first successnull; three319-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case013/`: TurnOnElectricKettle, native false at33
  controls/8 decisions, first successnull; three34-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case014/`: TurnOnMicrowave, native false at267 controls/
  56 decisions, first successnull; three268-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case015/`: TurnOnSinkFaucet, native false at366 controls/
  75 decisions, first successnull; three367-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without retry or rescore.
- `2026-09-07-target50-case016/`: DeliverStraw, native false at205 controls/
  42 decisions, first successnull; three206-frame20Hz videos retained.
  All four fixed-tool postprocessors passed, without retry or rescore.
