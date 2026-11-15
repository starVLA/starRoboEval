# VLN-CE

VLN-CE evaluates instruction-guided navigation in continuous Habitat scenes.
An agent follows a natural-language route instruction and must stop near the
goal. Episodes vary in building, start pose, route and instruction; unlike
manipulation benchmarks, there is no fixed list of named tabletop tasks.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): episode identity, permitted observations,
  native navigation actions and scoring.
- [Environment and asset prerequisites](environment/README.md): pinned source, runtime
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

## Bench Server

The service runs a complete R2R `val_seen` or `val_unseen` split, or a fixed
subset of it chosen by `evaluation_mode`:

| `evaluation_mode` | Episodes | Selection | Per-episode cap |
| --- | ---: | --- | ---: |
| `fast` (default) | 373 on `val_unseen` | One ranked instruction per route, ranked routes 1–40 of each scene | 500 actions |
| `max` | 1,839 / 778 | The complete declared split, in dataset order | 500 actions |
| `example` | 1 | The first `fast` episode | 500 actions |

`fast` ranks routes and instructions with a fixed sha256 key and takes ranks in
round-robin order over sorted scenes; on `val_seen` the same rule applies. It uses Habitat-Lab/Sim 0.3.3 in a separate native worker, with
RGB and instruction observations and four discrete navigation actions. The
server and client use the shared communication protocol. This runtime version
does not imply rendering or score parity with Habitat 0.1.7.

## Required data and access

A locally scored R2R validation configuration needs:

- Authorized Matterport3D scene assets in the format required by the pinned Habitat runtime.
- The complete selected `R2R_VLNCE_v1-3` episode split.
- Matching ground-truth paths/actions when using metrics that require them.
- Explicit paths, checksums, runtime versions and a frozen episode-selection rule.

MP3D assets require the dataset owner's authorization and applicable Terms of
Use. Obtain or reuse an authorized installation; code availability does not
grant scene-data rights. Do not bundle restricted assets, access credentials or
private dataset download links into the repository.

See [environment/README.md](environment/README.md#data-and-scenes) for the expected asset layout
and access requirements.

## Robot interface

The R2R RGB track provides a current image and instruction, with discrete
forward/left/right/STOP actions. The action is one integer ID: 0=STOP,
1=forward 0.25 m, 2=left 15°, 3=right 15°. It is not an arm-control vector.
The adapter owns the native runtime and
scorer; a policy cannot inspect simulator metadata, maps, goal coordinates,
oracle directions, distances or scoring data.

Native STOP must be executed as a Habitat action. A generic policy abort does
not send native STOP and cannot establish navigation success. The 500-action
budget includes STOP. Action grouping belongs to the agent.

## Start the service

Follow [environment preparation](environment/README.md), then copy
[server.example.json](server.example.json) to an operator-owned file and set
the dataset, scene root, native Python, split and `evaluation_mode`. The scene root
must contain the `mp3d/` directory referenced by the dataset. No personal path
is built into the adapter. Supplying `python_executable` keeps native Habitat
dependencies separate from the service's Python 3.10+ environment.

```sh
# Set RSI_SIM_SERVER_TOKEN privately for the trusted evaluator and server.
python -B -m benchkit serve --benchmark vln_ce \
  --parameters /absolute/vlnce-server.json --seed 0 \
  --port 8765 --output-dir /absolute/new-run/server
```

The service fixes the mode's episodes without starting Habitat. A client claim
initializes one episode and receives only RGB and language. Goal distances and
scores remain evaluator-private. Results include native success, SPL and final
distance to goal. This implementation does not compute nDTW or oracle metrics;
do not label these partial metrics as the complete original evaluation suite.
