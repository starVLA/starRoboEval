# Independent harness review after a development run

Run execution and review are separate roles. The execution policy sees only its
declared observations. The reviewer works after a run is closed and can inspect
private evaluator artifacts to audit correctness. Reviewer findings never feed
back into a scored episode.

## Execution record

Before running, record repository revision and dirty patch digest, task matrix,
seeds, policy identity, model/provider accounting, native horizons, decision
limit, replan interval, and allowed observation channels. Preserve every trial,
including unsuccessful and interrupted trials, under a unique run directory.

## Reviewer instructions

An independent agent reads the released protocol and completed artifacts, then
reports evidence for these questions:

1. Do delivered observations contain only declared image/state channels? Check
   policy context, metadata, paths, prompts, and exported files for hidden reset
   seeds, object state, native info, or score feedback.
2. Does the same physical action mean the same thing for every model in a given
   embodiment? Verify units, frame, rotation, gripper, chunk prefix, and actual
   environment steps against the pinned upstream implementation.
3. Are native final success, transient success, budget exhaustion, and
   infrastructure errors distinguished correctly? Recompute summary counts from
   episode results; do not replace the native scorer with visual judgment.
4. Can another user reconstruct the environment and run from its manifest?
   Check source/submodule pins, dependencies, assets, renderer, prompts, and
   whether model usage is measured or only self-reported.
5. Do images/videos/actions support the reported failure explanation? Cite
   exact artifact filenames and decision/step numbers. State uncertainty when
   evidence cannot distinguish policy failure from harness failure.

Write findings by severity with evidence, likely cause, proposed shared fix,
and whether existing scores remain comparable. Include an explicit verdict:
development-ready / requires harness fixes / insufficient evidence. Do not call
a development run a public benchmark result, and do not modify its files.

## Changes following review

Fix only general implementation defects under the existing protocol. If the
observation/action/budget/scoring contract must change, version it and repeat
the same affected matrix for every compared policy. Keep the original run and
review as evidence. Difficult tasks may remain unsuccessful without a harness
change.
