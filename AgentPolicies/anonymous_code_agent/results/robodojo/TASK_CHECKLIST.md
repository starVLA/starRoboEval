# RoboDojo task/round ledger

Different authorized rounds remain separate; this is not a pooled success rate.
Model/provider identity is unverified. Diagnostics never count as task attempts.

| Task | Round | State | Policy calls | Action decisions | Controls | Native success |
| --- | --- | --- | ---: | ---: | ---: | --- |
| stack_bowls | original pilot | prelaunch failure | — | — | — | unknown |
| push_T | original pilot | malformed-response error | 1 | — | 0 | unknown |
| stack_bowls | authorized round2 | completed, give-up | 70 | — | 345 | false |
| push_T | authorized round2 | completed, give-up | 41 | — | 200 | false |
| pack_objects_into_box | next-pair-v1 | completed, give-up | 15 | — | 70 | false |
| fold_clothes | next-pair-v1 | held, missing textures; unclaimed | — | — | — | — |
| hang_mugs | continuation-pair-v1/cache-checkpoint-v1 | completed once, give-up | 53 | 52 | 256 | false |
| sweep_blocks | continuation-pair-v1/cache-checkpoint-v1 | completed once, give-up | 51 | 50 | 246 | false |

Historical policy-call totals include the stop-only response. They are not the
same as controls or the new separately recorded executed-action-decision count.
Do not retroactively apply the new50-action-decision floor to earlier rounds.
The historical action-decision column is left unpopulated instead of silently
backfilling a separately introduced counter. Both new results have score0/100,
no episode error, no timeout and null first-native-success evidence.

See [round2](reports/2026-09-07-ROUND2.md),
[pack/fold](reports/2026-09-08-NEXT-PAIR.md), and
[the closed continuation pair](reports/2026-09-11-continuation-results.md).
