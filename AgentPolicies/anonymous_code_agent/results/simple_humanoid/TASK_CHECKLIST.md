> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/SIMPLE/TASK_CHECKLIST.md` at source revision `29cb55d`;
> original SHA256: `8796c84484da10269b025fbe4d8819e3ae1f729aea38440c1acb5b7d54d7de34`. Only documentation links were rebased.

# SIMPLE task checklist

Scope: released12 DR0/episode0. One selected attempt per task, including the two original
pilots. This is a **dated snapshot**, not live job status or a homogeneous score.
A closed failure/error is already attempted and must not be retried on resume.

Source: `runs/simple-ledger-checkpoint-20260907-011/coverage.json`.
SHA256: `f380a7e1f25867a18d6108a6687c9c074eb9eace0d42660bf3f339e2210fbd10`.
The full-ledger tool validated this snapshot with zero invalid rows.

At snapshot: 12/12 terminal, 3 native true,
8 native false, 1 infrastructure/policy errors,
0 active and 0 unattempted.
Active/unattempted counters are not estimated; “—” means unavailable/null.
“active” means the snapshot's `claimed_without_terminal_outcome` status,
not independently observed process liveness. Check the actual handle on resume.
Controls exclude warmup; stop decisions can add a decision without a control.
First success is control / decision, not a replacement for final native scoring.

| Index | Task | Group | Source case | Protocol | Status | Controls / decisions | First success |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 0 | `G1WholebodyBendPickMP-v0` | amo | pilot:000 | P1 | failure | 295 / 60 | — |
| 1 | `G1WholebodyCloseDoorTeleop-v0` | sonic | new:000 | P2 | failure | 335 / 68 | — |
| 2 | `G1WholebodyHandoverTeleop-v0` | sonic | new:001 | P2 | failure | 140 / 29 | — |
| 3 | `G1WholebodyLocomotionPickBetweenTablesTeleop-v0` | sonic | new:002 | P2 | failure | 425 / 86 | — |
| 4 | `G1WholebodyOpenFaucetTeleop-v0` | sonic | pilot:001 | P3 | success | 104 / 21 | 104 / 21 |
| 5 | `G1WholebodyOpenOvenTeleop-v0` | sonic | new:003 | P2 | failure | 280 / 57 | — |
| 6 | `G1WholebodyOpenTrashCanTeleop-v0` | sonic | new:004 | P2 | success | 223 / 45 | 223 / 45 |
| 7 | `G1WholebodyPickAndPlaceAndHugContainerTeleop-v0` | sonic | new:005 | P2 | error | 0 / 0 | — |
| 8 | `G1WholebodyPushOfficeChairTeleop-v0` | sonic | new:006 | P2 | failure | 265 / 54 | — |
| 9 | `G1WholebodyTabletopGraspMP-v0` | amo | new:007 | P4 | success | 8 / 2 | 8 / 2 |
| 10 | `G1WholebodyXMoveBendPickTeleop-v0` | sonic | new:008 | P2 | failure | 195 / 40 | — |
| 11 | `G1WholebodyXMovePickTeleop-v0` | sonic | new:009 | P2 | failure | 315 / 64 | — |

## Original protocol identities

- P1: `simple/amo/rgb-qpos31/decision-200-prefix-5/v1`.
- P2: `simple/released-12/sonic/rgb-qpos31/decision-200-prefix-5/v1`.
- P3: `simple/sonic/rgb-qpos31/decision-200-prefix-5/v1`.
- P4: `simple/released-12/amo/rgb-qpos31/decision-200-prefix-5/v1`.

“pilot” refers to the original carry-forward campaign; “new” refers to the
frozen continuation, not a retry. The detailed
[coverage report](reports/2026-09-07-task-coverage.md) links original campaigns,
protocol differences, native definitions, known errors and archived videos.
Keep those caveats alongside this table; native true does not certify runtime,
asset or model/provider provenance. This checklist is not policy input.

## Resume safely

Re-read the frozen campaign and terminal outcomes before a new claim. Do not
restart a task because this static snapshot says active or because a monitor
timed out: verify the existing process/handle first. Continue only unclaimed
identities, with a fresh isolated actor ACK before native launch. Preserve the
original task order/reset, source guards and budgets. Do not resume LIBERO or
VLN-CE from this checklist; their user-requested pauses remain separate.
