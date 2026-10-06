# VLN-CE

VLN-CE evaluates instruction-guided navigation in continuous Habitat scenes.
This integration is **`protocol_draft`**: upstream requirements and a proposed
policy contract are documented, but there is no runnable unified
`VLNCEBenchmarkAdapter`. Fast and full evaluation are not implemented yet.

Deployment is deferred until an authorized MP3D installation is available.
Public code or episode-data downloads do not satisfy this scene-asset gate.
Other benchmarks can be configured independently; no substitute scene set or
unverified download source is used to bypass the requirement.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): episode identity, permitted observations,
  native navigation actions and scoring.
- [Environment and asset prerequisites](PREFLIGHT.md): pinned source, runtime
  requirements, licensed scene assets and validation checklist.

## Required data and access

A locally scored R2R validation configuration needs:

- Authorized Matterport3D scene assets in the format required by the pinned Habitat runtime.
- The complete selected `R2R_VLNCE_v1-3` episode split.
- Matching ground-truth paths/actions required by the selected native metrics.
- Explicit paths, checksums, runtime versions and a frozen episode-selection rule.

MP3D assets require the dataset owner's authorization and applicable Terms of
Use. Obtain or reuse an authorized installation; code availability does not
grant scene-data rights. Do not bundle restricted assets, access credentials or
private dataset download links into the repository.

R2R `val_unseen` contains 1,839 navigation episodes across 11 scenes. Episodes,
routes and scenes are different denominators: full coverage is not one episode
per scene. RxR, language/role settings and challenge configurations are separate
variants. See [PREFLIGHT.md](PREFLIGHT.md#data-variants-and-access) for sources.

## Intended interface

The draft R2R RGB track provides a current image and instruction, with discrete
forward/left/right/STOP actions. The adapter must own the native runtime and
scorer; a policy cannot inspect simulator metadata, maps, goal coordinates,
oracle directions, distances or scoring data.

Native STOP must be executed as a Habitat action. A generic policy abort does
not send native STOP and cannot establish navigation success. Any adapter must
validate this distinction, native step limits, observation isolation and
retained artifacts before being advertised as runnable.

Historical StarVLA integration files are available from Git history, not as
supported unified evaluation commands. A reachable model server does not
validate the Habitat environment, native metrics or an adapter.
