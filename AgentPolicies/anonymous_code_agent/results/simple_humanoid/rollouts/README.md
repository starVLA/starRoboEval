> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/SIMPLE/rollouts/README.md` at source revision `29cb55d`;
> original SHA256: `e2e6417a320c01d2dd8bc15580731fc88f8d3efd7e3a1d99e9d7d8be62a7cb97`. Only documentation links were rebased.
> Existing relative export names below refer to the original `examples/simBenchmarks/SIMPLE/rollouts/` directory until an explicit adoption index records a new copy.

# Local development rollout videos

Generated archives are ignored by Git. Keep the original runs and all failures;
do not add video, frames, raw policy responses or generated indexes to commits.

- `2026-09-07-pilot-case000/`: BendPickMP / AMO, native failure, 295 controls /
  60 decisions. Four original-camera videos, each 296 frames, were copied with
  SHA256 verification. See [closed evidence](../reports/2026-09-07-pilot-case000.md).
- `2026-09-07-pilot-case001/`: OpenFaucetTeleop / SONIC, native success first at
  control 104 / decision 21. Two native head-camera videos, 105 frames each.
  See [case 1](../reports/2026-09-07-pilot-case001.md) and the
  [independent paired review](../../../../../project_readmes/reviews/2026-09-07-simple-closed-pilot-review.md).

Use the [shared exporter](../../../../../examples/simBenchmarks/SimplerEnv/export_videos.py) and repository-root
workflow documented in [task coverage](../../../../../examples/simBenchmarks/TASK_COVERAGE.md).
Export closed runs only; never rerender a replacement, overwrite the result,
or substitute a visual judgment for native success.

- `2026-09-07-released12-case000/`: CloseDoorTeleop, native false at335 controls/
  68 decisions, first success null; both336-frame videos independently decoded
  and hash-verified (left PNG parity; right has no retained PNG sequence). See the
  [released12 coverage report](../reports/2026-09-07-task-coverage.md).
- `2026-09-07-released12-case001/`: HandoverTeleop, native false at140 controls/
  29 decisions, first success null; both141-frame50Hz videos decoded and hashes
  checked by root (left PNG comparison; right has no retained PNG sequence).
- `2026-09-07-released12-case002/`: LocomotionPickBetweenTablesTeleop, false
  at425 controls/86 decisions, first success null; both426-frame50Hz videos
  independently checked, with exact public/left PNG binding and right decode/
  hash/timestamp checks. Runtime caveats remain in the closed review.
- `2026-09-07-released12-case003/`: OpenOvenTeleop, native false at280 controls/
  57 decisions, first success null; two281-frame50Hz videos retained. Pinned
  generic checks pass, including left PNG/public binding and right decode/
  hash/timestamps; native startup errors remain in the versioned caveat overlay.
- `2026-09-07-released12-case004/`: OpenTrashCanTeleop, first/final native
  success at223 controls/45 decisions; two224-frame50Hz videos retained, with
  pinned generic artifact checks passed and native-log caveats preserved.
- `2026-09-07-released12-case005/`: PickAndPlaceAndHugContainerTeleop,
  infrastructure warmup error before any policy decision/control. Two original
  one-frame50Hz videos retained, not a warmup trajectory or completed rollout.
  Success is null; no retry, rescore or failed-task reclassification.
- `2026-09-07-released12-case006/`: PushOfficeChairTeleop, native false at
  265 controls/54 decisions, first success null; two266-frame50Hz videos
  retained. All four pinned postprocessors passed; native warnings remain
  annotated separately and right-camera PNG parity is unavailable.
- `2026-09-07-released12-case007/`: TabletopGraspMP, native true at
  control8/decision2 (also first success). Four9-frame50Hz videos retained;
  all four pinned postprocessors passed. Head-left PNG correspondence is
  checked; other cameras have decode/hash/PTS only. Independent review confirms
  height-only native success, not stable grasp; the baseline comes from warmup
  and initial score history is unavailable. Preserve the v8 evidence caveat.
- `2026-09-07-released12-case008/`: XMoveBendPickTeleop, false at195
  controls/40 decisions, first successnull; two196-frame50Hz videos retained
  and all four pinned postprocessors passed. Independent native/source/parser
  and media review is complete; preserve v9 caveats and the native failure.
  Right-camera PNG parity remains unavailable.
- `2026-09-07-released12-case009/`: XMovePickTeleop, false at315 controls/
  64 decisions, first successnull; two316-frame50Hz videos retained. All four
  pinned postprocessors passed, with left PNG/public binding and right-camera
  decode/hash/timestamps only. Independent native/source/parser review is
  complete; preserve the actual9cm predicate, saved-reset/train identity,
  warmup-baseline uncertainty and runtime warnings in the v10 caveats.
