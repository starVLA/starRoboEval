# CALVIN native environment preparation

Status: **source/assets, native imports and a bounded standalone reset/control/
media/cleanup diagnostic verified**. Full task-chain and D-validation parity
remain unverified. This directory describes
reproducible environment inputs, not model scores or a completed CALVIN full
evaluation. See the [evaluation protocol](../EVALUATION_PROTOCOL.md).

## Keep native dependencies separate

Use a new Python 3.10 environment and new native source/data directories outside
this repository. Do not modify an existing model environment, import archived
VLA launchers or run the native repository's general training installation
script. The RGB setup below needs neither a model checkpoint nor API credentials.
Third-party code and asset licenses still apply; no native data is vendored here.

The verified source combination is:

| Native tree | Exact Git revision |
| --- | --- |
| [mees/calvin](https://github.com/mees/calvin) | `fa03f01f19c65920e18cf37398a9ce859274af76` |
| [mees/calvin_env](https://github.com/mees/calvin_env) | `1431a46bd36bde5903fb6345e68b5ccc30def666` |
| [lukashermann/tacto](https://github.com/lukashermann/tacto) | `dd53360d9a8c186f0d6439372ec0be0fa5e21731` |

The latter two revisions are the native nested gitlinks, not revisions inferred
from a parent workspace. Acquire and verify clean checkouts:

```sh
git clone --no-checkout https://github.com/mees/calvin.git /absolute/new-calvin-native
git -C /absolute/new-calvin-native checkout --detach fa03f01f19c65920e18cf37398a9ce859274af76
git -C /absolute/new-calvin-native submodule update --init --recursive
git -C /absolute/new-calvin-native submodule status --recursive
```

Check each tree's own `rev-parse --show-toplevel`, `HEAD`, tracked working tree
and index. Preserve a content inventory; a matching parent commit does not make
a dirty submodule equivalent. The inspected clean combination contains 158
tracked regular files in CALVIN, 287 in calvin_env and 188 in tacto, excluding
gitlinks. Actual bytes matched the Git blob IDs, with no unresolved Git LFS
pointers. The calvin_env tree includes the robot and table meshes.

## Start with the official debug asset

The [official dataset documentation](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/dataset/README.md)
provides a small public debug ZIP and much larger training/validation split
archives. For environment preparation, use the debug asset explicitly:

```sh
curl --fail --location --max-time 1200 \
  --output /absolute/new-cache/calvin_debug_dataset.zip \
  http://calvin.cs.uni-freiburg.de/dataset/calvin_debug_dataset.zip
sha256sum /absolute/new-cache/calvin_debug_dataset.zip
```

The existing cache directory must be private and the output filename unused.
The pinned archive is **1,299,150,917 bytes**, SHA-256
`c66d09147e2c806b244f18ea7d61e388d4dac11f828929779437f728d03e1204`,
matching the [publisher's checksum list](http://calvin.cs.uni-freiburg.de/dataset/sha256sum.txt).
The published download is HTTP; the checksum verifies these pinned bytes, not
transport authentication. Preserve the original archive and checksum receipt.

Verify the whole archive before extracting into a new private directory. Reject
absolute paths, traversal, backslash paths, duplicate normalized paths, symlinks,
special files and encrypted entries. Check decompressed sizes and ZIP CRCs,
then record each extracted file's SHA-256. The verified archive contains 4,477
entries: 4,468 files and nine directories, totalling 1,305,893,952 uncompressed
bytes. Every member is below `calvin_debug_dataset/`.

Use `calvin_debug_dataset` as the dataset root; the required configuration is
`validation/.hydra/merged_config.yaml`, 7,287 bytes, SHA-256
`75c1c15067e4bd543d1b69a654769836f6cbbf55c4e44ae30da255c45609523f`.
Keep that original file unchanged. The debug archive also contains training
samples; their presence does not authorize policy access to demonstrations or
private native state.

This asset is a **debug setup input**, not an asserted replacement for the full
native D validation split. No validation-only archive equivalence has been
established. Do not download the roughly 177-billion-byte D→D archive merely to
perform this import/configuration check, or label debug outcomes as full scores.

## Minimal RGB runtime

From a stable StarVLA-RSI checkout:

```sh
python3.10 -m venv /absolute/new-calvin-rgb-env
/absolute/new-calvin-rgb-env/bin/python -m pip install \
  -r benchmarks/simBenchmarks/calvin/environment/requirements-rgb-setup.txt
/absolute/new-calvin-rgb-env/bin/python -m pip check
PYTHONPATH=/absolute/new-calvin-native/calvin_env \
  /absolute/new-calvin-rgb-env/bin/python -B -c \
  "import calvin_env.envs.play_table_env; import calvin_env.envs.tasks; import calvin_env.robot.robot; import calvin_env.scene.play_table_scene; import calvin_env.camera.static_camera; import calvin_env.camera.gripper_camera; print('Native imports OK; no SIM constructed')"
```

These commands check dependencies and imports only; they do not construct,
reset, render or step a simulator. The dependency list pins the tested Python
3.10 RGB setup, including NumPy 1.26.4, Gym 0.26.2 and PyBullet 3.2.7. It is not
a recovered historical training environment or a native parity claim. Gym emits
an upstream maintenance warning; do not silently replace it with Gymnasium.
Hydra 1.3.2 warns that the native CLI decorator assumes compatibility version
1.1; the imported classes and config resolution were checked without invoking
that CLI or suppressing the warning.

On a disconnected evaluation node, download the pinned Linux CPython 3.10
wheels on an authorized connected machine and transfer a hashed wheelhouse.
Gym 0.26.2 and antlr4-python3-runtime 4.9.3 may require building their pure-Python
wheels from public source distributions; inspect their build definitions and
retain both source and wheel hashes. Install with `--no-index --find-links` and
rerun the same checks. No existing colleague environment needs modification.

## Verified debug configuration and bounded runtime

| Field | Native debug value |
| --- | --- |
| Scene | `calvin_scene_D`, native table D |
| Static camera | RGB 200×200 |
| Gripper camera | RGB 84×84 |
| Original third camera | Tactile, 120×160; omitted by the retained RGB evaluator |
| Physics frequency | 240 Hz |
| Control frequency | 30 Hz, eight physics ticks per native control |
| Robot | `franka_panda/panda_longer_finger.urdf` |
| IKFast | `use_ik_fast: false` |
| Native task-oracle configuration | 34 named task predicates |

The retained RGB evaluator removes `cfg.env.cameras.tactile` in memory and
uses `show_gui=False`, `use_vr=False`, `use_scene_info=True`. The last option is
for private scoring, never agent observations. The adapter declares these
overrides, preserves the original config hash and exposes only its public
RGB/language allowlist. No tactile renderer or IKFast compilation is needed for this setup;
their omission must not be generalized to arbitrary CALVIN configurations.

All six selected scene/robot/block/plane URDFs and their 31 unique mesh references
were resolved read-only. The PyBullet wheel contains its `eglRenderer` plugin;
plugin presence does not prove GPU/EGL loading or rendering. Before launching
the SIM service, allocate an appropriate headless NVIDIA device and
record driver/EGL identity. Do not switch renderer, camera or control settings
to hide a native error under an unchanged protocol.

## Gates still outstanding

The preparation/import commands above perform zero native constructions, resets
or controls. A separate, independently reviewed server/client diagnostic has now
verified one frozen reset, two predeclared native controls and clean shutdown;
it did not execute a model or claim task success.
The bounded adapter freezes one five-subtask sequence, public RGB/relative-action
contract, private reset vectors and oracle, per-subtask limits, counters and
source/runtime capture. It does not implement full D-validation parity. The existing native
evaluation utility imports learned-model code, Torch and pyhash; do not import
it into an otherwise model-free server merely to access a reset helper. The
private frozen state is derived from only two source-hash-verified pure-math
functions under an explicit pyhash compatibility assumption; the protocol and
CPU parity test record the exact derivation.

For an import/configuration-only preflight, run from the RSI checkout:

```sh
python -B -c 'from pathlib import Path; from benchmarks.simBenchmarks.calvin.environment.runtime import import_preflight; r=import_preflight(Path("/absolute/new-calvin-native"), Path("/absolute/new-assets/calvin_debug_dataset")); print({k:r[k] for k in ("native_constructions","native_resets","native_controls")})'
```

The checker requires the pinned Linux x86_64 Python 3.10 dependencies, checks
all three native Git trees plus actual tracked bytes, the original debug config
and named binary hashes, then imports native classes/config only. It accepts
the native namespace-package directories by their exact path, but rejects stale
bytecode or executable overrides in the native package. Keep using `-B` and do
not run other tools that populate bytecode in this clean native deployment.

The full native-runtime scope is in [runtime_snapshot.json](runtime_snapshot.json):
the debug archive checksum is preparation provenance; the runtime reads and
verifies only its merged config, never every demonstration or archive member.
Dependency versions plus selected binary bytes do not attest all transitive
libraries, loaded process memory, GPU drivers or EGL device selection.

The bounded native diagnostic observed one reset tick and eight physics ticks
per fixed control. Both native camera views rendered; six delivered RGB frames
matched their stored PNG pixels, all transferred artifact bytes matched, and each
camera video decoded completely as three frames at 30 fps. Cleanup recorded the
owned client disconnected and an external incomplete stop. This verifies the
short integration path, not five-stage task success, long-run behavior or a model
capability score. A different deployment must repeat its own labelled readiness
and infrastructure checks; never silently change renderer or control settings.

No direct model access to the simulator, extra private observations or automatic
task retries are permitted. Only after native matrix and validation equivalence
checks can a future `full` track claim the original sequence aggregate.
