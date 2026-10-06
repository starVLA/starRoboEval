# SIMPLE released task scope

This is the benchmark-owned task/reset inventory for SIMPLE revision `5e3d6f84e85343e34e9bca8d157f0d7813231185`. Explicit `task_scope="released-12"` allows the following 12 tasks in native inventory order; select exactly one per adapter with `task_names=[task_id]`.

The current protocol identity is `simple/released-12/{amo|sonic}/rgb-qpos31/decision-200-prefix-5/v2`. It fixes RGB+31 ordinary encoders, 200 maximum policy calls, execution prefix cap 5 and a separate 1000-control cap. Native controller, stabilization and scorer invocation follow [EVALUATION_PROTOCOL.md](../../EVALUATION_PROTOCOL.md). Version 2 removes the RSI-added joint-target range gate; valid finite targets reach the unchanged native controller without clipping. Frozen v1 results retain their original identity and behavior.

## Tasks and reset variants

| Native task suffix after `G1Wholebody` | Backend | Native reference horizon | DR0 episode-0 scene |
| --- | --- | ---: | --- |
| BendPickMP-v0 | AMO | 400 | scene0 |
| CloseDoorTeleop-v0 | SONIC | 1000 | scene0 |
| HandoverTeleop-v0 | SONIC | 800 | scene0 |
| LocomotionPickBetweenTablesTeleop-v0 | SONIC | 1200 | scene6 |
| OpenFaucetTeleop-v0 | SONIC | 1000 | scene2 |
| OpenOvenTeleop-v0 | SONIC | 1000 | scene1 |
| OpenTrashCanTeleop-v0 | SONIC | 800 | scene4 |
| PickAndPlaceAndHugContainerTeleop-v0 | SONIC | 1000 | scene14 |
| PushOfficeChairTeleop-v0 | SONIC | 800 | scene3 |
| TabletopGraspMP-v0 | AMO | 800 | scene2 |
| XMoveBendPickTeleop-v0 | SONIC | 800 | scene0 |
| XMovePickTeleop-v0 | SONIC | 800 | scene0 |

The fast selection uses seed 20260907, DR0 and released episode index 0. It schedules one attempt per task and retains failures, errors and unattempted entries. Inventory preparation is not completed coverage. **Native-aligned full mode is not implemented**: a complete released episode/DR schedule must be declared and validated separately.

The default compatibility scope `pilot` retains BendPickMP and OpenFaucetTeleop as its allowed identities, with BendPickMP as the direct adapter default. The default campaign selects both. Explicit `released-12` does not reinterpret old identities or authorize duplicate attempts in an existing one-attempt campaign.

## Frozen metadata and timing

[simple_released_tasks.json](simple_released_tasks.json) pins registration entrypoints, task/robot UIDs, source hashes, backend, native horizon metadata, released instruction, DR0 metadata-file hash and exact serialized episode-0 environment-configuration hash. The worker verifies the selected runtime class, task/backend, horizon, reset and instruction against this inventory and [environment/upstream.json](../../environment/upstream.json).

Backend selection follows the native environment/robot pair, not task-name suffix inference. `LocoManipulationEnv` with `g1_wholebody` uses AMO; `SonicLocoManipEnv` with `g1_sonic` uses SONIC. AMO executes ten 2 ms physics steps and SONIC four 5 ms steps per public 50 Hz control.

The 1000-control cap extends the 400/800 reference horizons, equals 1000 and shortens LocomotionPickBetweenTables' 1200. Preserve both extension and reduction in provenance. TabletopGrasp's source default render frequency is 30 Hz but its released reset metadata is 50 Hz; this track explicitly constructs all environments at 50 Hz. PickAndPlaceAndHugContainer and XMoveBendPick metadata omit horizons; their native classes supply 1000 and 800.

Native reset formats released language with the target asset name. Public observations preserve that exact string, including whitespace; episode metadata alone strips outer whitespace. Do not normalize observations to hide transport differences.

Seven scene entrypoints correspond to six distinct asset layers: scene1 and scene3 share an asset layer but have different table configurations and are not interchangeable. Matching scene entrypoints and repair-manifest hashes does not certify every texture, articulated object, container, USD dependency or successful native reset.

## Validation

These checks do not launch the simulator:

```sh
PYTHONPATH=. python -B benchmarks/simBenchmarks/SIMPLE/checks/test_inventory.py -v
PYTHONPATH=. python -B benchmarks/simBenchmarks/SIMPLE/checks/test_instruction_contract.py -v
PYTHONPATH=. python -B benchmarks/simBenchmarks/SIMPLE/checks/verify_inventory.py \
  --inventory benchmarks/simBenchmarks/SIMPLE/bench_server/protocol/simple_released_tasks.json
```

Native execution additionally requires the pinned runtime, licensed assets, controller stabilization, task-specific scoring and GPU capacity. SIMPLE may create contexts across multiple visible GPUs; renderer selection alone does not establish isolation. Treat asset/reset/render/scorer failures as explicit outcomes, not reasons to replace task inputs or automatically retry.
