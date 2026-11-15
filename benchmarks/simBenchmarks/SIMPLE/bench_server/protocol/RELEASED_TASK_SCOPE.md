# SIMPLE service task bindings

This table describes the service's selected task/reset bindings for SIMPLE
revision `5e3d6f84e85343e34e9bca8d157f0d7813231185`.
See [native scope and reset distributions](../../README.md#native-tasks-and-reset-distributions).
The service allows the following 12 tasks in native inventory order; select
exactly one per adapter with `task_names=[task_id]`.

Each task resets with seed 20260907 from a released row selected by
domain-randomization (DR) level and episode index. `evaluation_mode` selects DR0
episodes 0–4 (`fast`), DR0–DR2 × episodes 0–9 (`max`) or DR0 episode 0
(`example`). The service uses RGB and 31 measured joint encoders. Native
controller, timing and scoring are described in the
[evaluation protocol](../../EVALUATION_PROTOCOL.md).

## Tasks and reset variants

| Native task suffix after `G1Wholebody` | Backend | Native reference horizon | Native success threshold | Scene |
| --- | --- | ---: | ---: | --- |
| BendPickMP-v0 | AMO | 400 | 0.9 | scene0 |
| CloseDoorTeleop-v0 | SONIC | 1000 | 0.5 | scene0 |
| HandoverTeleop-v0 | SONIC | 800 | 0.9 | scene0 |
| LocomotionPickBetweenTablesTeleop-v0 | SONIC | 1200 | 0.4 | scene6 |
| OpenFaucetTeleop-v0 | SONIC | 1000 | 0.2 | scene2 |
| OpenOvenTeleop-v0 | SONIC | 1000 | 0.5 | scene1 |
| OpenTrashCanTeleop-v0 | SONIC | 800 | 0.9 | scene4 |
| PickAndPlaceAndHugContainerTeleop-v0 | SONIC | 1000 | 0.9 | scene14 |
| PushOfficeChairTeleop-v0 | SONIC | 800 | 0.9 | scene3 |
| TabletopGraspMP-v0 | AMO | 800 | 0.9 | scene2 |
| XMoveBendPickTeleop-v0 | SONIC | 800 | 0.8 | scene0 |
| XMovePickTeleop-v0 | SONIC | 800 | 0.9 | scene0 |

The table contains 12 tasks across seven scene entrypoints; all three DR
levels keep each task's scene. The worker rejects a released episode whose scene
differs from it. The threshold is the native `check_success` rule
`reward >= threshold`, from the task's constructor default, class metadata or a
literal (TabletopGrasp, XMoveBendPick); the service passes no override.

An omitted `task_names` selects BendPickMP, the first row. RGB-only input is
permitted only for BendPickMP and OpenFaucetTeleop; each server still selects
exactly one task/backend.

## Reset definitions and timing

[simple_released_tasks.json](simple_released_tasks.json) pins registration entrypoints, task/robot UIDs, source hashes, backend, native horizon metadata, released instruction, DR0 metadata-file hash, which pins every released DR0 row, and exact serialized DR0 episode-0 environment-configuration hash. DR1/DR2 metadata files are pinned in [environment/upstream.json](../../environment/upstream.json). The worker verifies the selected runtime class, task/backend, horizon, reset and instruction against this inventory and [environment/upstream.json](../../environment/upstream.json).

Backend selection follows the native environment/robot pair, not task-name suffix inference. `LocoManipulationEnv` with `g1_wholebody` uses AMO; `SonicLocoManipEnv` with `g1_sonic` uses SONIC. AMO executes ten 2 ms physics steps and SONIC four 5 ms steps per public 50 Hz control.

The service uses each task's metadata horizon from this table, with no
benchmark-imposed decision frequency or action-prefix length. Report the selected
protocol and actual control cap.

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
