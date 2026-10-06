> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/SimplerEnv/reports/2026-09-07-infrastructure-review.md` at source revision `29cb55d`;
> original SHA256: `200e33ee289a663d431cbb6ea19341086cac36e12a9198f5970c2ebf8707d958`. Only documentation links were rebased.

# Independent infrastructure review — 2026-09-07

Verdict: **development-ready for the checked rendering, stepping, artifact, and
extended-time-limit paths**. These records do not establish model capability,
task-solving success, or complete SimplerEnv evaluation parity.

Review scope was restricted to three completed runs on the eval node under
`/mnt/workspace/users/jinhuiye/Projects/starVLA-RSI/runs/simpler-infrastructure/`:
`render-step-001`, `extended-timelimit-001`, and `google-render-step-001`.
All checks were read-only. No active model-run artifacts were inspected, and no
historical result, scorer, or rollout setting was changed.

## Verified run evidence

Every manifest identifies `constant-action-diagnostic`, kind `scripted`,
`model: null`, `provider: null`, and purpose `infrastructure_validation_only`.
**Model not run: true for all three records.** Their reported zero provider
requests/tokens/cost is consistent with the constant policy, whose `act` returns
a fixed chunk without inference. This is different from unavailable accounting
for a model accessed through an external code-agent runtime.

| Run | Task | Executed steps | Policy calls | PNG / decoded video frames | Termination |
| --- | --- | ---: | ---: | ---: | --- |
| `render-step-001` | WidowX spoon on towel | 1 | 1 | 2 / 2 | Runner step limit |
| `extended-timelimit-001` | WidowX spoon on towel | 120 | 24 | 121 / 121 | Environment truncation |
| `google-render-step-001` | Google horizontal coke can | 1 | 1 | 2 / 2 | Runner step limit |

All three have one completed episode, no recorded errors, and native final
success `false`. The one-step records are intentionally short diagnostics;
their unsuccessful task outcomes are not useful estimates of robot-policy
performance. The 120-step constant trajectory also does not measure model skill.

The review independently verified:

- `status.json` is completed; `result.json` equals its `episodes.jsonl` record.
- All summary denominators, successes, failures, coverage, and rates recompute
  from episode records. Each summary is 1 attempted / 1 completed / 0 errors /
  0 successes.
- Environment-step indices are contiguous, and policy-call start events match
  decision events and episode counters. Declared runner and policy-call limits
  are respected.
- Each video has one reset frame plus one frame per executed step. All
  **125/125 PNG file SHA-256 values** match `frames.jsonl`; frame indices are
  contiguous and there are no extra or missing PNG files.
- All three H.264 videos decode completely using the eval environment's
  `imageio` reader. Decoded frame counts and dimensions match the PNG sequences.
  Videos are lossy encodings; PNG hashes, not decoded-video equality, identify
  the exact observations.
- WidowX images are 480 × 640 × 3 at 5 video frames/s, and Google images are
  512 × 640 × 3 at 3 frames/s. All decoded PNG arrays have nonzero spatial
  variation; this checks against empty/uniform renders, not task correctness.
- Logged policy observations have RGB-only declarations; proprioception is not
  enabled. No claim about a model client's behavior follows from a constant
  policy diagnostic.

Native provenance records clean SimplerEnv revision
`c701ea271b16b80616d6fed9713c4a50a0adea3b` and ManiSkill2 real2sim revision
`ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682`. It records NumPy 1.24.4,
SciPy 1.10.1, SAPIEN 2.2.2, and Gymnasium 0.29.1. WidowX runs use native control /
simulation rates of 5 / 500 Hz; Google uses 3 / 513 Hz. Controller identities
and robot/camera names are present in each `artifacts/native_provenance.json`.

## Native H and extended 2H

`extended-timelimit-001` has native H=60 and a predeclared evaluation horizon of
120, with protocol `simpler-prepackaged-development/rgb/extended-2x/v1`. Its
manifest permits 24 decisions with a five-action prefix and 120 runner steps.

The event at step 60 has `truncated: false`; step 120 is the **only** truncated
step. The final result has `native_steps: 120`,
`success_at_native_horizon: false`, and `success_at_evaluation_horizon: false`.
Both checkpoints agree with the already-logged native success at their exact
step. No checkpoint was replaced with `success_ever` or a better earlier result.
These artifacts demonstrate that the effective wrapper reached 120 rather than
ending at the registered 60-step boundary.

Read-only source review confirms that construction passes the effective horizon
to `gym.make(..., max_episode_steps=...)`, preserving the registered native H.
The adapter copies checkpoint success from the existing step `info`; `metrics()`
returns cached values. It does not call native `evaluate()` or `get_info()` for
H, 2H, or final score. The reviewer independently reran the eight adapter boundary
checks in the installed SimplerEnv environment; all passed, including the
fixture that forbids direct scorer calls and captures distinct checkpoints.

This combination verifies the implemented non-repeating checkpoint path and its
logged outputs. The historical runs did not instrument a native scorer-call
counter, so their exact internal invocation counts cannot independently be
recovered from artifacts alone.

The Google record declares H=80 / evaluation horizon 160 but executes only one
step. Its H and 2H fields are correctly `null`. It verifies Google reset/render/
step behavior, **not** that the Google wrapper actually runs to step 160.

## Findings and limits

**Medium — historical harness snapshot is not fully reconstructible.** All three
manifests record evaluator Git revision
`b14e700ec0dbee5f9242d0682eee9cbbbdbcd0c1` with `dirty: true`, but no dirty-patch
digest or source snapshot. The clean upstream pins are recorded; the exact
uncommitted harness used by each run is not independently pinned by its manifest.
The current source review cannot repair that historical provenance gap. Future
runs should record a committed harness revision or preserved patch plus digest
before reset. Existing diagnostics remain useful as installation evidence and
must not be promoted into reproducible public scores retroactively.

**Not yet verified:** successful task completion; a real model or provider call;
adversarial process/filesystem isolation; model-call enforcement by a trusted
provider adapter; native-policy parity; repeated-seed reset reproducibility;
all 15 canonical subtasks; full visual-matching/variant-aggregation matrices;
Google full-horizon truncation; independent asset-content hashes; or a complete
published-score acceptance gate. A decoded video does not substitute for a
native success predicate or a visual review of task completion.

## Review fingerprints

These SHA-256 values identify the immutable files read during this review.
Artifact paths above are relative to the eval repository; run binaries are not
part of the tracked documentation.

| Run | File | SHA-256 |
| --- | --- | --- |
| `render-step-001` | `manifest.json` | `6f03cee7c56e8474ffcf1e35e30ab47cdd95e1dce864f1a1322a54550cac9326` |
| `render-step-001` | Episode `events.jsonl` | `8674f6e921cf2a85915cd1c3b4243c446ee64c2325725dc1bfc0a795093f8821` |
| `render-step-001` | `artifacts/video.mp4` | `eb86ee62af18cc605fdcd9d3d3d8137ce7a670824be8ccda3db79b1f4c5f1833` |
| `extended-timelimit-001` | `manifest.json` | `1fd0fe00bf9f61fa8e0786ecb9f25d6b9c3d440acb02cc0d95b68797835a9b0d` |
| `extended-timelimit-001` | Episode `events.jsonl` | `016d75c4b09366086a04d52cbd2b9bb9ee05ca03010bf1a20f9dfadcd889478e` |
| `extended-timelimit-001` | `artifacts/video.mp4` | `6f7715650548b5f6f0acd7f9f69881de2e0f029d3856f9e686e88071962eb60e` |
| `google-render-step-001` | `manifest.json` | `862aba478e87f14fbc04757c1fae0b2a85c3f4e8bb4d9219c70649b9da103480` |
| `google-render-step-001` | Episode `events.jsonl` | `ae7c2e30663f8f7fcad42347537cf6be228ea247e9116c221678c700495fface` |
| `google-render-step-001` | `artifacts/video.mp4` | `e9ca8e7574e2f3524d8cdf838bf16ad38c08a7fc1fe2f4949525520d3eeeeb76` |
