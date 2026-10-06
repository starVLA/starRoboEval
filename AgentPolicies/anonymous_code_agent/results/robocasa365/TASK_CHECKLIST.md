> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/Robocasa_365/TASK_CHECKLIST.md` at source revision `29cb55d`;
> original SHA256: `59e9bf3f863ca0b41a88e6ec1cf220623708f12d10f577bde98a169ef0549a95`. Only documentation links were rebased.

# Robocasa_365 task checklist

Scope: target50:18 atomic_seen +16 composite_seen +16 composite_unseen. One selected attempt per task, including the two original
pilots. This is a **dated snapshot**, not live job status or a homogeneous score.
A closed failure/error is already attempted and must not be retried on resume.

Updated 2026-09-08: cases017/018 are closed and independently reviewed:
[GetToastedBread](../../../../project_readmes/reviews/2026-09-08-casa017-closed-review.md)
at480 controls/97 decisions and
[KettleBoiling](../../../../project_readmes/reviews/2026-09-08-casa018-closed-review.md)
at146 controls/32 decisions, both native false, give-up and no episode error.
**RoboCasa365 is user-paused; do not launch case019 or retry a closed task.**

Source: `runs/robocasa365-ledger-checkpoint-20260908-019/coverage.json`.
SHA256: `aa5df1102c253959525926f03c870951ca96d37e1077d3b4a3e0ad1c9ed84473`.
CSV SHA256: `e26496dbc553807a7a99a44c0d5d21a74512157abbcae971e5090fa4bc0d56bc`.
Collected at `2026-09-07T16:39:16.030272+00:00` (2026-09-08 Asia/Shanghai).
The full-ledger tool validated this snapshot with zero invalid rows.
All50 identities and both original carry-forward attempts were revalidated
with the accepted reporter and frozen campaign helpers. Checkpoint018 remains
unchanged; only selection indices19/20 advanced from claimed to completed.
The snapshot number019 is a reporting checkpoint, not a case019 launch.

At snapshot: 21/50 terminal, 2 native true,
19 native false, 0 infrastructure/policy errors,
0 active and 29 unattempted. The remaining29 tasks are paused, not cancelled.
Active/unattempted counters are not estimated; “—” means unavailable/null.
“active” means the snapshot's `claimed_without_terminal_outcome` status,
not independently observed process liveness. Check the actual handle on resume.
Controls exclude warmup; stop decisions can add a decision without a control.
First success is control / decision, not a replacement for final native scoring.

| Index | Task | Group | Source case | Protocol | Status | Controls / decisions | First success |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 0 | `CloseBlenderLid` | atomic_seen | new:000 | P1 | failure | 180 / 37 | — |
| 1 | `CloseFridge` | atomic_seen | new:001 | P1 | failure | 245 / 50 | — |
| 2 | `CloseToasterOvenDoor` | atomic_seen | new:002 | P1 | failure | 198 / 41 | — |
| 3 | `CoffeeSetupMug` | atomic_seen | new:003 | P1 | failure | 176 / 37 | — |
| 4 | `NavigateKitchen` | atomic_seen | pilot:001 | P2 | success | 125 / 25 | 125 / 25 |
| 5 | `OpenCabinet` | atomic_seen | new:004 | P1 | failure | 90 / 19 | — |
| 6 | `OpenDrawer` | atomic_seen | pilot:000 | P2 | failure | 328 / 67 | — |
| 7 | `OpenStandMixerHead` | atomic_seen | new:005 | P1 | failure | 149 / 32 | — |
| 8 | `PickPlaceCounterToCabinet` | atomic_seen | new:006 | P1 | failure | 210 / 43 | — |
| 9 | `PickPlaceCounterToStove` | atomic_seen | new:007 | P1 | success | 398 / 81 | 398 / 81 |
| 10 | `PickPlaceDrawerToCounter` | atomic_seen | new:008 | P1 | failure | 171 / 37 | — |
| 11 | `PickPlaceSinkToCounter` | atomic_seen | new:009 | P1 | failure | 266 / 55 | — |
| 12 | `PickPlaceToasterToCounter` | atomic_seen | new:010 | P1 | failure | 189 / 40 | — |
| 13 | `SlideDishwasherRack` | atomic_seen | new:011 | P1 | failure | 230 / 47 | — |
| 14 | `TurnOffStove` | atomic_seen | new:012 | P1 | failure | 318 / 66 | — |
| 15 | `TurnOnElectricKettle` | atomic_seen | new:013 | P1 | failure | 33 / 8 | — |
| 16 | `TurnOnMicrowave` | atomic_seen | new:014 | P1 | failure | 267 / 56 | — |
| 17 | `TurnOnSinkFaucet` | atomic_seen | new:015 | P1 | failure | 366 / 75 | — |
| 18 | `DeliverStraw` | composite_seen | new:016 | P1 | failure | 205 / 42 | — |
| 19 | `GetToastedBread` | composite_seen | new:017 | P1 | failure | 480 / 97 | — |
| 20 | `KettleBoiling` | composite_seen | new:018 | P1 | failure | 146 / 32 | — |
| 21 | `LoadDishwasher` | composite_seen | new:019 | P1 | unattempted | — | — |
| 22 | `PackIdenticalLunches` | composite_seen | new:020 | P1 | unattempted | — | — |
| 23 | `PreSoakPan` | composite_seen | new:021 | P1 | unattempted | — | — |
| 24 | `PrepareCoffee` | composite_seen | new:022 | P1 | unattempted | — | — |
| 25 | `RinseSinkBasin` | composite_seen | new:023 | P1 | unattempted | — | — |
| 26 | `ScrubCuttingBoard` | composite_seen | new:024 | P1 | unattempted | — | — |
| 27 | `SearingMeat` | composite_seen | new:025 | P1 | unattempted | — | — |
| 28 | `SetUpCuttingStation` | composite_seen | new:026 | P1 | unattempted | — | — |
| 29 | `StackBowlsCabinet` | composite_seen | new:027 | P1 | unattempted | — | — |
| 30 | `SteamInMicrowave` | composite_seen | new:028 | P1 | unattempted | — | — |
| 31 | `StirVegetables` | composite_seen | new:029 | P1 | unattempted | — | — |
| 32 | `StoreLeftoversInBowl` | composite_seen | new:030 | P1 | unattempted | — | — |
| 33 | `WashLettuce` | composite_seen | new:031 | P1 | unattempted | — | — |
| 34 | `ArrangeBreadBasket` | composite_unseen | new:032 | P1 | unattempted | — | — |
| 35 | `ArrangeTea` | composite_unseen | new:033 | P1 | unattempted | — | — |
| 36 | `BreadSelection` | composite_unseen | new:034 | P1 | unattempted | — | — |
| 37 | `CategorizeCondiments` | composite_unseen | new:035 | P1 | unattempted | — | — |
| 38 | `CuttingToolSelection` | composite_unseen | new:036 | P1 | unattempted | — | — |
| 39 | `GarnishPancake` | composite_unseen | new:037 | P1 | unattempted | — | — |
| 40 | `GatherTableware` | composite_unseen | new:038 | P1 | unattempted | — | — |
| 41 | `HeatKebabSandwich` | composite_unseen | new:039 | P1 | unattempted | — | — |
| 42 | `MakeIceLemonade` | composite_unseen | new:040 | P1 | unattempted | — | — |
| 43 | `PanTransfer` | composite_unseen | new:041 | P1 | unattempted | — | — |
| 44 | `PortionHotDogs` | composite_unseen | new:042 | P1 | unattempted | — | — |
| 45 | `RecycleBottlesByType` | composite_unseen | new:043 | P1 | unattempted | — | — |
| 46 | `SeparateFreezerRack` | composite_unseen | new:044 | P1 | unattempted | — | — |
| 47 | `WaffleReheat` | composite_unseen | new:045 | P1 | unattempted | — | — |
| 48 | `WashFruitColander` | composite_unseen | new:046 | P1 | unattempted | — | — |
| 49 | `WeighIngredients` | composite_unseen | new:047 | P1 | unattempted | — | — |

## Original protocol identities

- P1: `target50-development/rgb/decision-200-prefix-5/v1`.
- P2: `target-first2-development/rgb/decision-200-prefix-5/v1`.

“pilot” refers to the original carry-forward campaign; “new” refers to the
frozen continuation, not a retry. The detailed
[coverage report](reports/2026-09-07-task-coverage.md) links original campaigns,
protocol differences, native definitions, known errors and archived videos.
Keep those caveats alongside this table; native true does not certify runtime,
asset or model/provider provenance. This checklist is not policy input.

## Resume safely

Resume only after the user lifts the RoboCasa365 pause. Re-read the frozen
campaign and terminal outcomes before a new claim. Do not
restart a task because this static snapshot says active or because a monitor
timed out: verify the existing process/handle first. Continue only unclaimed
identities, with a fresh isolated actor ACK before native launch. Preserve the
original task order/reset, source guards and budgets. Do not resume LIBERO or
VLN-CE from this checklist; their user-requested pauses remain separate.
