# CALVIN native environment

The public service uses a dedicated Python 3.10 RGB runtime and the official
`calvin_debug_dataset` configuration. Equivalence with D-validation setup has
not been established. See the
[evaluation protocol](../EVALUATION_PROTOCOL.md).

## Native source and licenses

Provision separate native source/data directories outside the RSI repository.
Third-party source and asset licenses apply. An agent checkpoint, model API
credentials and the native training pipeline are not installation requirements
for this service.

| Native tree | Required Git revision |
| --- | --- |
| [mees/calvin](https://github.com/mees/calvin) | `fa03f01f19c65920e18cf37398a9ce859274af76` |
| [mees/calvin_env](https://github.com/mees/calvin_env) | `1431a46bd36bde5903fb6345e68b5ccc30def666` |
| [lukashermann/tacto](https://github.com/lukashermann/tacto) | `dd53360d9a8c186f0d6439372ec0be0fa5e21731` |

The latter two revisions are the native nested gitlinks:

```sh
git clone --no-checkout https://github.com/mees/calvin.git /absolute/new-calvin-native
git -C /absolute/new-calvin-native checkout --detach fa03f01f19c65920e18cf37398a9ce859274af76
git -C /absolute/new-calvin-native submodule update --init --recursive
git -C /absolute/new-calvin-native submodule status --recursive
```

Verify each tree's revision and actual tracked bytes, including submodules.
A matching parent revision does not certify a modified child tree. Keep native
source/configuration unchanged so the runtime can validate the declared inputs.

## Configuration asset

The [official dataset guide](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/dataset/README.md)
links the public debug archive:

```sh
curl --fail --location --max-time 1200 \
  --output /absolute/new-cache/calvin_debug_dataset.zip \
  http://calvin.cs.uni-freiburg.de/dataset/calvin_debug_dataset.zip
sha256sum /absolute/new-cache/calvin_debug_dataset.zip
```

Create the private destination directory first and use an unused output path.
The required archive is 1,299,150,917 bytes, SHA-256
`c66d09147e2c806b244f18ea7d61e388d4dac11f828929779437f728d03e1204`.
The publisher provides a [checksum list](http://calvin.cs.uni-freiburg.de/dataset/sha256sum.txt);
the download itself uses HTTP. Verify the pinned archive before safe extraction
into a new directory, retaining its checksum receipt.

Set `dataset_root` to the extracted `calvin_debug_dataset` directory.
The required `validation/.hydra/merged_config.yaml` is 7,287 bytes, SHA-256
`75c1c15067e4bd543d1b69a654769836f6cbbf55c4e44ae30da255c45609523f`.
Do not modify this file. The runtime reads its setup configuration, not
demonstrations or sampled dataset states. Dataset files and reset vectors are
not actor inputs.

## RGB runtime

From the RSI repository:

```sh
python3.10 -m venv /absolute/new-calvin-rgb-env
/absolute/new-calvin-rgb-env/bin/python -m pip install \
  -r benchmarks/simBenchmarks/calvin/environment/requirements-rgb-setup.txt
/absolute/new-calvin-rgb-env/bin/python -m pip check
PYTHONPATH=/absolute/new-calvin-native/calvin_env \
  /absolute/new-calvin-rgb-env/bin/python -B -c \
  "import calvin_env.envs.play_table_env; import calvin_env.envs.tasks; print('Native imports OK; no SIM constructed')"
```

The requirements pin the Linux Python 3.10 setup, including NumPy 1.26.4,
Gym 0.26.2 and PyBullet 3.2.7. Do not substitute Gymnasium or change native
controller dependencies without validating the interface. The import command does not
construct, reset or step the simulator. Package installation may need a compatible
wheelhouse on a disconnected node; preserve the exact dependency versions.

[runtime_snapshot.json](runtime_snapshot.json) defines the checked package
versions, selected binary hashes and source/configuration inputs. A generic
version-compatible installation is not necessarily byte-compatible with those
checks. The current loader has no operator-generated portable runtime manifest.

## Native configuration and rendering

| Setting | Declared value |
| --- | --- |
| Scene | Native table D, `calvin_scene_D` |
| Static camera | 200×200 RGB |
| Gripper camera | 84×84 RGB |
| Tactile camera | Not exposed by this RGB interface |
| Robot | `franka_panda/panda_longer_finger.urdf` |
| Low-level control | Native numerical IK, `use_ik_fast=False` |
| Timing | 240 Hz physics; eight ticks per 30 Hz control |

The adapter removes the tactile camera in memory and sets `show_gui=False`,
`use_vr=False` and `use_scene_info=True`. Scene info serves private native
scoring only. Original RGB images reach the actor without flipping, resizing
or cropping.

Allocate a headless EGL-capable GPU and a dedicated native process. Plugin
presence alone does not establish working rendering. The native EGL path assumes
PyBullet client 0; another simulator/client in the same process is unsupported.
Do not silently fall back to another renderer or alter camera settings.

## Preflight and validation

Run the file/import preflight from the RSI checkout with the prepared native
interpreter:

```sh
python -B -c 'from pathlib import Path; from benchmarks.simBenchmarks.calvin.environment.runtime import import_preflight; r=import_preflight(Path("/absolute/new-calvin-native"), Path("/absolute/new-assets/calvin_debug_dataset")); print({k:r[k] for k in ("native_constructions","native_resets","native_controls")})'
```

It checks source/runtime/configuration and imports native classes without
constructing a simulator. It rejects stale bytecode and executable overrides;
use `-B` with the clean native source.

Then follow the [server launch guide](../README.md#prepare-and-launch).
Check the fixed reset, both RGB views, control timing and clean disconnect on
the selected installation before collecting task scores. Reset derivation and
its dependency assumptions are stored in the evaluator-private
[sequence definition](../bench_server/protocol/frozen_sequence.json).
