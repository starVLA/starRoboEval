> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/SimplerEnv/rollouts/README.md` at source revision `29cb55d`;
> original SHA256: `c77ff63dc9f793377e1fb9b8a5a89c3eee6cd7b51d54960fde042478cd6336a3`. Only documentation links were rebased.
> Existing relative export names below refer to the original `examples/simBenchmarks/SimplerEnv/rollouts/` directory until an explicit adoption index records a new copy.

# Local rollout videos

Closed practical attempts are copied here, including failures:

```text
2026-09-07-first-two/
  google_robot_pick_horizontal_coke_can/video.mp4
  google_robot_pick_horizontal_coke_can/index.json
  google_robot_pick_horizontal_coke_can/progress.json
  widowx_spoon_on_towel/video.mp4
  widowx_spoon_on_towel/index.json
  widowx_spoon_on_towel/progress.json
```

The files appear only after each episode is closed and exported. `index.json`
records the source run, native result, protocol, horizons, step/decision usage,
errors and a SHA-256 digest of each copied video. A video is not evidence of
success unless the original native result says so. Failed attempts are retained.

`progress.json` records the first native-success step and decision when available,
actual final steps and decisions, and complete-log coverage. No success is null.

Original evaluator artifacts remain in their run directories. Every generated
rollout file is ignored by Git, including videos, frames, indexes and progress
JSON; only this README is tracked. They are not bundled with a code commit.
Policy actors must not access this directory during evaluation.

New task-coverage archives use `2026-09-07-task-coverage-caseNNN/`, separate from
the historical first-two pass. Case000 contains the horizontal-can attempt:
native final success, 78 controls / 25 decisions; first success at control 64 /
decision 21.
Its 79-frame video and source-bearing index are copied with SHA256 verification.
Case001 contains the vertical-can attempt: native final success at the decision
limit, 937 controls / 200 decisions; first native success at control 91 /
decision 31, while the native H80 checkpoint is false. Its 938-frame video and
source-bearing index are also copied with SHA256 verification. The final count
must not be mistaken for the first-success count.
Case002 contains the standing-can attempt: native final success after
138 controls / 46 decisions, first success at control 130 / decision 44;
H80 false and deliberate policy stop. Its 139-frame video and source-bearing
index are copied with SHA256 verification.
Case003 contains the move-near attempt: native final success after 194 controls /
59 decisions; first success at control41 / decision17, with intervening false
flags before the final31 successful controls. H80 is true; the final stop is
deliberate. Its 195-frame video and source-bearing index are hash-checked copies.
Cases004/005 each contain a two-frame drawer video: native failure after one
control / two decisions, with explicit give-up. Their black rendered foreground
and OptiX denoising errors are explained by the closed driver-data investigation. Exact image
transport and nonflat video do not establish usable rendering; keep the failures
and this caveat, without retries or reclassification of original records.
Case006 contains the first post-restoration capability attempt: native failure
after130 controls /35 decisions, explicit give-up and no first native success.
Its131-frame video is retained with hash-checked copies. Closed reset/final PNGs
show colored foreground and the console has no OptiX/denoising errors; this is
a bounded rendering check, not a task-success or full-parity assertion.
Case007 contains the close-top-drawer attempt: native final success after
195 controls / 53 decisions, first at control 96 / decision 27; H113 is true
and H1000 null. Its 196-frame video and source-bearing index are retained.
The final 100 controls logged native success before the actor's explicit stop;
the actor did not receive that private flag or an evaluator stop instruction.
Case008 preserves a policy-format error: 23 executed controls, 12 started
decisions, 11 accepted chunks and one rejected six-value action where seven
were required. Its 24-frame video/index are retained. Native final success is
null, not false; the rejected response executed no control and is not retried.
Case009 contains the close-bottom-drawer attempt: native final success after
329 controls / 77 decisions, first at control 186 / decision 47; H113 false
and H1000 null. The 330-frame video/index are retained. Success was interrupted
at controls 276–280 before the final 49 true controls and explicit policy stop.
Case010 contains the apple-in-drawer attempt: native failure after 238 controls /
72 decisions, no first success and explicit policy stop. H200 is false and
H1000 null; its 239-frame video/index are retained with SHA256 checks.
Case011 contains the WidowX spoon-on-towel attempt: native final success after
206 controls / 52 decisions, first at control 134 / decision 37. H60 is false
and H1000 null; the final 73 controls logged true before an explicit policy
stop. Its 207-frame 640×480 video/index are retained. This development result
does not overwrite the historical first-pass failure or certify H60 success.
Case012 contains carrot-on-plate: native final success after 242 controls /
60 decisions, first at 170 / 44, with 13 successful controls at the end.
Its 243-frame video/index are retained; H60 is false and cap1000 unreached.
Case013 retains an operator-induced schema error, not a capability failure:
one started decision, zero controls, null success. Its one-frame initial video
and error-bearing index are preserved without response repair or task retry.
Case014 contains eggplant-in-basket: native final success after49 controls /
22 decisions, first45/21, five final true controls and explicit policy stop.
The50-frame video/index are retained. H120 and cap1000 were not reached.
All15 task archives now exist; errors/defects remain visible, not scored away.
See [the in-progress coverage report](../reports/2026-09-07-task-coverage.md),
including the explicit policy-stop and unreached horizon-checkpoint semantics.
