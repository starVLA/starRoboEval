# VLN-CE environment preparation

Prepare the service Python (3.10+) separately from a native interpreter with
Habitat-Lab and headless Habitat-Sim 0.3.3. The service imports Habitat only in
its configured native worker. A compatible existing environment can be reused
read-only; copy it to an operator-owned prefix before changing packages or
patching installed code. Do not assume another node's identical path has a
working interpreter or matching libraries.

## Runtime

The native interpreter needs Habitat's R2R configuration and VLN task, NumPy,
Pillow, ImageIO and its ffmpeg backend. Confirm imports without constructing an
environment. Record both module and distribution versions; a version string
alone does not establish an exact Git revision. Runtime provenance records the
loaded source files and effective configuration rather than inventing a commit.

Habitat 0.3.3 uses structured configuration. This service starts from
`benchmark/nav/vln_r2r.yaml` and explicitly sets the contract in
[EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md): 500 actions, 0.25-metre forward,
15° turns, sliding enabled, RGB 512×512 / 90° FOV, instruction-only task sensing
and native success distance 3 m. It exposes only current RGB and instruction.
Do not reuse a model evaluation script that adds GPS, oracle sensors, extra
actions or a larger step budget.

## Data and scenes

Use an authorized [Matterport3D](https://niessner.github.io/Matterport/)
installation compatible with Habitat. Scene meshes and navigation meshes are
separate from the [R2R episode data](https://jacobkrantz.github.io/vlnce/data).
Code availability does not grant asset rights; do not distribute licensed
scenes or private download credentials with the repository.

The complete selected split must be readable as gzip JSON. Example layout:

```text
episodes/R2R_VLNCE_v1-3_preprocessed/
  val_unseen/val_unseen.json.gz
  val_unseen/val_unseen_gt.json.gz
scene_data/
  mp3d/<scene>/<scene>.glb
  mp3d/<scene>/<scene>.navmesh
```

Set `dataset_path` to the split JSON and `scenes_dir` to `scene_data`, since
episode scene IDs already contain `mp3d/`. Select `episode_ids` from the whole
split before inspecting outcomes or filtering by available scenes. Missing
selected assets block initialization; they never select replacement episodes.
Use `val_seen` or `val_unseen` for local scoring; test goals are withheld.

The preprocessed package supplies validation GT paths/actions. Optional
`gt_path` validates matching entries and records their origin; this version
reports native success, SPL and distance and does not compute nDTW.

## Readiness sequence

1. Check interpreter resolution, package versions, complete split/GT coverage
   and required GLB/navmesh files before claiming a case.
2. Set explicit native interpreter, data paths, selected IDs and GPU in a copy
   of [server.example.json](server.example.json). Keep local paths out of Git.
3. Verify the configured GPU is available. Start the service from stable source
   and use a trusted client for a separate, labelled no-model diagnostic:
   describe, claim, reset, inspect RGB, execute a valid action, execute STOP,
   read metrics and finish. Invalid actions must not move the simulator.
4. Confirm finalization, video decoding and owned worker cleanup. Only then
   declare model evaluation cases. A diagnostic STOP failure is not a model
   capability result, and a successful reset alone is not control validation.

Keep diagnostic output separate from scored model runs. Use the shared
[server interface](../SERVER_PROTOCOL.md); do not give simulator handles,
scenes, private route/goal fields or evaluator credentials to the model.
