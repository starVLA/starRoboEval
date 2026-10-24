# VLN-CE

VLN-CE evaluates instruction-guided navigation in continuous Habitat scenes.
An agent follows a natural-language route instruction and must stop near the
goal. Episodes vary in building, start pose, route and instruction; unlike
manipulation benchmarks, there is no fixed list of named tabletop tasks.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): episode identity, permitted observations,
  native navigation actions and scoring.
- [Environment and asset prerequisites](PREFLIGHT.md): pinned source, runtime
  requirements, licensed scene assets and validation checklist.

## Benchmark episodes and splits

The [released R2R-VLNCE v1-3 data](https://jacobkrantz.github.io/vlnce/data)
contains the following splits:

| Split | Episodes | Scenes |
| --- | ---: | ---: |
| Training | 10,819 | 61 |
| Validation, seen scenes | 778 | 53 |
| Validation, unseen scenes | 1,839 | 11 |
| Test | 3,408 | 18 |

Scenes are buildings, not individual tasks or layouts. An episode pairs an
instruction with a route/start state; several instructions may describe the
same route. Scene counts are split-specific and should not be summed as unique
buildings. RxR and challenge configurations have separate data and settings.

## Integration status

This directory is a **protocol draft** for R2R `val_unseen`; it does not yet
provide an executable benchmark service. Implementation and validation of the
adapter, plus an authorized MP3D installation, are required before deployment.
These are service prerequisites, not restrictions on VLN-CE's native dataset.

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

See [PREFLIGHT.md](PREFLIGHT.md#data-variants-and-access) for dataset variants
and their access requirements.

## Intended interface

The draft R2R RGB track provides a current image and instruction, with discrete
forward/left/right/STOP actions. The action is one integer ID: 0=STOP,
1=forward 0.25 m, 2=left 15°, 3=right 15°. It is not an arm-control vector.
The adapter must own the native runtime and
scorer; a policy cannot inspect simulator metadata, maps, goal coordinates,
oracle directions, distances or scoring data.

Native STOP must be executed as a Habitat action. A generic policy abort does
not send native STOP and cannot establish navigation success. Any adapter must
validate this distinction, native step limits, observation isolation and
retained artifacts before being advertised as runnable.

There is no supported server launch command yet. Implementing the adapter,
validating the selected Habitat configuration and supplying authorized assets
are separate prerequisites; a reachable agent endpoint satisfies none of them.
