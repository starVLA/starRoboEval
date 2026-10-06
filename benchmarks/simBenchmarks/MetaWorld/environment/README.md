# Native MetaWorld server environment

Use a dedicated Python 3.10 or 3.11 environment. Do not reuse or modify a model's
environment. The benchmark source and MuJoCo assets are included in the public
`metaworld==3.1.1` wheel; this integration needs no private task dataset, model
checkpoint or licensed scene download. Public code/asset licenses still apply;
this repository does not grant rights to redistribute third-party content.

From the StarVLA-RSI source checkout:

```sh
python3.10 -m venv /absolute/new-metaworld-env
/absolute/new-metaworld-env/bin/python -m pip install \
  -r benchmarks/simBenchmarks/MetaWorld/environment/requirements.txt
PYTHONPATH="$PWD" /absolute/new-metaworld-env/bin/python -B \
  -m benchmarks.simBenchmarks.MetaWorld.environment.runtime
```

The last command is read-only: it verifies native package/dependency versions,
the import origin and all 440 code/asset files against
[package_pin.json](package_pin.json). It does not instantiate, reset, step or
render a SIM. The manifest was derived from the installed public wheel's RECORD
and verified against actual bytes, not from an assumed Git revision. A modified
or different native package must fail, not silently acquire the same protocol ID.

NumPy 1.24.4 has no Python 3.12 wheel; use the stated interpreter versions. The
pin covers MetaWorld package code/assets plus selected dependency versions, not
every dependency, renderer binary or GPU driver. Preserve the resolved runtime
package list and GPU/renderer identity with deployment evidence.

For headless NVIDIA nodes, configure before starting the native process:

```sh
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export MUJOCO_EGL_DEVICE_ID=0
```

Check the optional native renderer imports in that same environment before
claiming an episode:

```sh
/absolute/new-metaworld-env/bin/python -B -c \
  "import metaworld; import gymnasium.envs.mujoco; print('Native imports OK; no environment constructed')"
```

This import-only check still performs no reset, step or rendering. The explicit
`packaging==26.2` dependency is required by Gymnasium's MuJoCo renderer even
though a minimal install can pass `pip check` without it. Package metadata
consistency is therefore not a substitute for checking the native import path.

Replace the GPU index with an allocated device. The host must expose NVIDIA
devices and EGL/OpenGL driver libraries (including `libEGL.so.1`) to the process.
Import success alone does not prove offscreen rendering works. Missing EGL,
unsupported GPU/device indices or scene/render errors are environment failures;
do not replace observations to hide them. The declared protocol's full-frame
orientation (`rot180` by default, or explicit `native`) is a fixed benchmark
interface convention, not an environment-error recovery mechanism.

If a node cannot reach a package index, download the exact public wheels on an
authorized connected machine for the target Python/platform, transfer the
wheelhouse, then install with `--no-index --find-links /absolute/wheelhouse`.
Keep download hashes and rerun the same native content verifier. Do not replace
missing distributions with a different version while keeping this protocol ID.

After read-only checks and source review, perform a separately labelled bounded
infrastructure diagnostic using the independent SIM server and trusted harness
client, not direct environment manipulation. Preserve the declared orientation,
original returned frames and protocol identity in that evidence. The native MT50 constructor internally
generates goal pools for all 50 classes; startup can take longer than a single
task reset. A diagnostic is not an authorized model retry or a capability score.

No model/provider credentials, policy prompts or result files belong in this
directory. Keep operational paths and private deployment logs outside public
benchmark documentation.
