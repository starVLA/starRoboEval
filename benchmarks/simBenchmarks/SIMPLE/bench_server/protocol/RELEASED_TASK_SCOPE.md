# SIMPLE service task bindings

This table describes the service's selected task/reset bindings for SIMPLE
revision `5e3d6f84e85343e34e9bca8d157f0d7813231185`.
See [native scope and reset distributions](../../README.md#native-tasks-and-reset-distributions).
Explicit `task_scope="released-12"` allows the following 12 tasks in native
inventory order; select exactly one per adapter with `task_names=[task_id]`.

Each task has one selectable reset: domain-randomization level 0 (DR0), released
episode index 0 and seed 20260907. The service uses RGB and 31 measured joint
encoders. Native controller, timing and scoring are described in the
[evaluation protocol](../../EVALUATION_PROTOCOL.md).

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

The table contains 12 task/reset pairs across seven scene entrypoints.
Other released episode indices and DR levels are not currently selectable.

The default `task_scope="pilot"` permits BendPickMP and OpenFaucetTeleop, with
BendPickMP as the adapter default. Set `task_scope="released-12"` to select any
task listed above; each server still selects exactly one task/backend.

## Reset definitions and timing

[simple_released_tasks.json](simple_released_tasks.json) pins registration entrypoints, task/robot UIDs, source hashes, backend, native horizon metadata, released instruction, DR0 metadata-file hash and exact serialized episode-0 environment-configuration hash. The worker verifies the selected runtime class, task/backend, horizon, reset and instruction against this inventory and [environment/upstream.json](../../environment/upstream.json).

Backend selection follows the native environment/robot pair, not task-name suffix inference. `LocoManipulationEnv` with `g1_wholebody` uses AMO; `SonicLocoManipEnv` with `g1_sonic` uses SONIC. AMO executes ten 2 ms physics steps and SONIC four 5 ms steps per public 50 Hz control.

The current 12-task service configuration requires 200 maximum policy calls,
an action-prefix setting of five and a 1,000-control cap. These are integration
restrictions, not native SIMPLE rules. The cap extends the 400/800-control
reference horizons and shortens LocomotionPickBetweenTables' 1,200-control
horizon. Report both the reference horizon and actual cap.

TabletopGrasp's source default render frequency is 30 Hz but its released reset
metadata is 50 Hz; this service constructs all environments at 50 Hz.
PickAndPlaceAndHugContainer and XMoveBendPick reset metadata omit horizons;
their native classes supply 1,000 and 800.

Native reset formats released language with the target asset name. Public observations preserve that exact string, including whitespace; episode metadata alone strips outer whitespace. Do not normalize observations to hide transport differences.

Seven scene entrypoints correspond to six distinct asset layers: scene1 and
scene3 share an asset layer but have different table configurations. They are
not interchangeable layouts. Each task additionally binds its own robot/object
reset configuration.

Native execution requires the runtime, licensed scene dependencies and controller
weights described in [setup](../../README.md#prepare-the-environment).
