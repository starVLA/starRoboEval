# Native VLA-Arena server environment

Use a new dedicated **Linux x86_64, CPython 3.11** environment and clean native
checkout. Do not change a model environment or another user's installation.
This service needs no provider credentials, learned checkpoint, demonstrations,
TensorFlow or upstream model evaluator.

## Pinned public source and bundled assets

```sh
git clone https://github.com/PKU-Alignment/VLA-Arena.git /absolute/new-vla-arena
git -C /absolute/new-vla-arena checkout --detach babe582ebffc82b979b77964a7e56417d02f63a4
git -C /absolute/new-vla-arena rev-parse --show-toplevel
git -C /absolute/new-vla-arena rev-parse HEAD
git -C /absolute/new-vla-arena status --porcelain --untracked-files=all --ignored=matching
```

The last command must be empty. The pinned
[official release](https://github.com/PKU-Alignment/VLA-Arena/tree/babe582ebffc82b979b77964a7e56417d02f63a4)
already bundles task definitions, initialization files and assets. The entire
`vla_arena/` package plus `pyproject.toml` is pinned as **4,529 files /
909,169,622 bytes** in [native_source_pin.json](native_source_pin.json).
Resources include 2,928 asset files, 306 BDDL files and 421 init files; some
belong to bundled LIBERO tasks excluded from this adapter's 170-task catalog.
These are file counts, not completed episodes.

Do not silently update the Task Hub, substitute assets, create native macro
overrides or run an opaque upstream install script. Real bytes must match the
pin; LFS pointers are not assets. Third-party licences remain applicable and
are not granted by this repository.

## Isolated SIM dependencies

From the StarVLA-RSI source checkout:

```sh
python3.11 -m venv /absolute/new-vla-arena-env
/absolute/new-vla-arena-env/bin/python -m pip install setuptools==79.0.1 wheel==0.45.1
/absolute/new-vla-arena-env/bin/python -m pip install \
  --index-url https://download.pytorch.org/whl/cpu torch==2.5.1+cpu
/absolute/new-vla-arena-env/bin/python -m pip install \
  -r benchmarks/simBenchmarks/VLA-Arena/environment/requirements.txt
/absolute/new-vla-arena-env/bin/python -m pip check
```

[requirements.txt](requirements.txt) records the tested SIM runtime and resolved
transitive pins. It is an installation manifest, not a file dynamically read by
the server; `runtime.py` checks selected dependency versions and native content
pins. CPU PyTorch serves only the native init-file loader. Gym/BDDL
may build pure-Python wheels from public sdists. Linux `evdev`, a transitive
Robosuite/pynput dependency, can need a C compiler, Python 3.11 development
headers and Linux input headers (`linux/input.h`); build its reviewed public
sdist only in this new environment. No joystick backend is used by this service.

The explicit `future==1.0.0` pin is required by BDDL's import path, despite its
metadata allowing `pip check` to pass without it. Run the import checks below.
Robosuite's optional private-macro, extra-robot and GR1 whole-body-IK warnings
do not enable those features; this track checks the built-in Panda OSC config.

If a node cannot reach public indexes, transfer exact target-platform wheels
from an authorized connected machine, then install with `--no-index --find-links
/absolute/wheelhouse`. Preserve download/build hashes and rerun the verifier.
Do not change versions while retaining the old protocol ID.

## Isolated config and read-only preflight

The native utility package otherwise creates `~/.libero` on import. Create its
small private config outside the source tree in a new directory:

```sh
/absolute/new-vla-arena-env/bin/python -B \
  -m benchmarks.simBenchmarks.VLA-Arena.environment.configure \
  --native-root /absolute/new-vla-arena \
  --config-directory /absolute/new-vla-arena-config
export LIBERO_CONFIG_PATH=/absolute/new-vla-arena-config
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export MUJOCO_EGL_DEVICE_ID=0
mkdir /absolute/new-vla-arena-preflight-cache
export NUMBA_CACHE_DIR=/absolute/new-vla-arena-preflight-cache
/absolute/new-vla-arena-env/bin/python -B \
  -m benchmarks.simBenchmarks.VLA-Arena.environment.runtime \
  --native-root /absolute/new-vla-arena
```

Use an allocated GPU index. NVIDIA devices and matching EGL/OpenGL driver
libraries must be exposed to the process/container. Configure never overwrites
an existing directory. The verifier imports native task/environment/scoring
APIs but **does not construct, reset, step or render a SIM**. It also compares
all 1,113 Robosuite files with the public 1.5.1 wheel pin and checks the loaded
default Panda controller. `-B` is required: bytecode or untracked/ignored native
checkout files fail closed.

Pins cover native/Robosuite source and assets plus dependency versions, not
loaded-memory or driver identity. Ordinary Robosuite CPython install caches
with source counterparts are explicitly excluded. Keep resolved package lists,
driver identity and setup receipts in deployment evidence. Import success alone
does not prove offscreen rendering.

Robosuite enables Numba caching by default. `NUMBA_CACHE_DIR` must be a new,
empty, private directory for each fresh process, outside both pinned native
and Robosuite trees. Use a different directory for preflight and the actual
server; do not share it across servers. Generated compiled cache files remain
process-owned setup artifacts, not pinned source or model observations.

## Launch and native acceptance

The pinned integration has passed one bounded no-model native service/client
diagnostic for the declared L0 example. It confirmed one reset, ten setup
controls plus two fixed diagnostic controls (native timestep 12), pixel-exact
transport of both RGB streams, two finalized three-frame videos at 20 Hz, and
clean shutdown. This is infrastructure validation only: no model was called,
and the unfinished task/partial cost is neither a capability failure score nor
evidence of full-task coverage. A new deployment still needs its own checks.

Copy [server.example.json](../server.example.json) into an agent-owned config,
set the pinned native path and predeclare L0 task keys. Set a private
evaluator-only `RSI_SIM_SERVER_TOKEN`, then launch from the RSI checkout:

```sh
mkdir /absolute/agent-owned/new-numba-cache
export NUMBA_CACHE_DIR=/absolute/agent-owned/new-numba-cache
/absolute/new-vla-arena-env/bin/python -B \
  -m benchmarks.simBenchmarks.VLA-Arena.server \
  --parameters /absolute/agent-owned/vla-arena-server.json \
  --seed 7 --episodes 1 --port 8765 \
  --output-dir /absolute/agent-owned/new-run/sim-server
```

Use the trusted client in [SERVER_PROTOCOL.md](../../SERVER_PROTOCOL.md).
Listening/scheduling performs zero resets. After independent review, perform
one labelled bounded infrastructure diagnostic through server/client: one
reset, fixed action prefix, both original camera streams, native scorer and
counter inspection, then clean shutdown. Retain failures; do not auto-retry
or count fixed diagnostic controls as a model score. Model evaluation uses real
model decisions through the same public interface.

The [protocol](../EVALUATION_PROTOCOL.md) specifies one fail-fast reset, ten
setup controls, the 300 policy-control cap, image orientation and separate
success/cost/safe-success fields. Full schedules remain unsupported. Results,
credentials, host paths and case diaries do not belong in this directory.
