# LIBERO-Plus SIM server

Run a pinned LIBERO-Plus simulator independently of the model/evaluator Python
environment. This benchmark owns native tasks, perturbations, observations,
actions and success. Policies stay in `AgentPolicies/<profile>`; shared transport and
records stay in `harness`.

- [Evaluation protocol and 10,030-variant inventory](EVALUATION_PROTOCOL.md)
- [Server parameters](server.example.json)
- [Shared server interface and evaluator launch](../SERVER_PROTOCOL.md)
- Retired StarVLA model launchers remain in Git history, not the active interface

## Directory responsibilities

`server.py` is the public factory/launch entrypoint. `bench_server/adapter.py`
owns the public sensor/action interface and native score bridge;
`bench_server/protocol/catalog.py` and `catalogs/` define the immutable task matrix.
Native installation, source pins and catalog-generation tools belong in
`environment/`; in particular `native_source_manifest.json` is a runtime pin,
not a task catalog. `checks/` contains offline regressions. There is no old root
adapter/catalog shim. Relocation preserves catalog bytes and native behavior;
operator paths and selected cases stay in the server configuration.

## Configure a native environment

Use a **separate Python 3.10 environment**; Plus and standard LIBERO both export
the `libero` namespace and must not coexist in one running process. Do not change
someone else's native checkout, environment or `~/.libero/config.yaml`.

1. Clone [the official repository](https://github.com/sylvestf/LIBERO-plus) into
   your own new directory and check out commit
   `4976dc30028e805ff8094b55501d532c48fec182`.
2. Download `assets.zip` from the
   [pinned official public release](https://huggingface.co/datasets/Sylvest/LIBERO-plus/tree/dd2bd61b7d9a6fef1abc52d606e983b41886a149).
   The archive is 6,395,849,578 bytes with SHA-256
   `96764a4bfbdaea98d4411598caeab235458318fe0f549611b93d1a323027b3cf`.
   Use the checked extraction command below: this release retains a long
   upstream build-path prefix, so a plain unzip into the checkout creates the
   wrong directory layout. The tool strips only the exact reviewed prefix.
   It requires a new asset directory and never merges or removes prior data.
   BDDL and init files come from the pinned source checkout. The ZIP has 457,675
   entries and about 9 GB of uncompressed file contents; allow at least 20 GB
   plus filesystem inode headroom for archive and extracted storage. Training
   datasets and model weights are not needed.
3. Install native EGL/OpenGL and ImageMagick Wand support. On a compatible
   Ubuntu NVIDIA server this normally includes `libegl1`, `libgl1`,
   `libexpat1`, `libfontconfig1`, and `libmagickwand-dev`. Host NVIDIA drivers
   and a working EGL vendor library are still required; pip alone cannot
   install the host driver. Use an isolated container/environment when system
   package changes are inappropriate.
4. In the new Python environment, install Torch `2.5.1+cpu` from the official
   CPU wheel index, then [runtime-requirements.txt](environment/runtime-requirements.txt),
   then the pinned native checkout with `pip install --no-deps -e <checkout>`.
   The native loader relies on Torch's pre-2.6 `torch.load` behavior; silently
   substituting a newer Torch is not this track. Configure the RSI checkout on
   `PYTHONPATH` or install RSI editable without replacing native dependencies.

From the RSI source root, with placeholder paths replaced:

```sh
python -B -m benchmarks.simBenchmarks.LIBERO-plus.environment.extract_assets \
  --archive /absolute/path/to/downloaded/assets.zip \
  --destination /absolute/path/to/LIBERO-plus/libero/libero/assets \
  --receipt /absolute/path/to/private-install-records/assets.json
python -B -m benchmarks.simBenchmarks.LIBERO-plus.environment.configure \
  --upstream /absolute/path/to/LIBERO-plus \
  --config-dir /absolute/path/to/libero-plus-runtime-config
export LIBERO_CONFIG_PATH=/absolute/path/to/libero-plus-runtime-config
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
```

The extractor validates release identity, paths, entry types, duplicates and
expansion bounds before creating the target. Extraction failures preserve the
partial directory and do not silently restart. Hundreds of thousands of tiny
asset files can be very slow on shared storage; prefer an owned node-local
deployment when available. A tmpfs deployment is ephemeral: retain the verified
archive and source pin on persistent storage and rebuild after a node restart.

The configuration tool only creates an explicit external path config and refuses
to overwrite a different one. Catalog and source-pin verification require no
reset, rendering, model, training data or policy API key.

```sh
python -B -m benchmarks.simBenchmarks.LIBERO-plus.environment.verify_environment \
  --upstream /absolute/path/to/LIBERO-plus --check-imports
```

This checks the 60 declared source files, resolved BDDL/reset bytes for all
10,030 variants, required asset-folder presence and native imports. It does not
deserialize reset pickles, construct a simulator, validate all asset contents,
or prove that EGL renders valid images.
Unrecorded Python, compiled extensions and bytecode caches in the executed native
package are rejected, including an added outer namespace `__init__.py`. Start
with `-B` and a clean owned clone; do not remove caches from someone else's tree.

## Start a fixed SIM service

Copy `server.example.json` to a private configuration file, replace the native
path and preselect the task IDs, seed and budgets before running any model.
Set `RSI_SIM_SERVER_TOKEN` using your evaluator's private secret provisioning;
never put its value into a policy prompt, tracked JSON or shell argument.

```sh
python -B -m benchmarks.simBenchmarks.LIBERO-plus.server \
  --parameters /absolute/path/to/libero-plus-server.json \
  --seed 20260907 --episodes 1 --port 8765 \
  --output-dir AgentPolicies/<profile>/results/libero_plus/raw/<task-description>/server
```

The service binds only `127.0.0.1` and initializes no simulator until the trusted
evaluator opens/resets the selected session. Use the neutral runner's
`--benchmark libero_plus --sim-server http://127.0.0.1:8765` from a separate
evaluator environment, following the shared service guide. Cross-node use needs
an SSH tunnel, not a publicly exposed server. Every selected session is claimed
once, including errors; do not retry a failed control acknowledgment.

## Validate without interpreting it as a model score

CPU contract checks:

```sh
python -B -m unittest discover \
  -s benchmarks/simBenchmarks/LIBERO-plus/checks -p 'test_*.py'
```

Before capability evaluation, explicitly select a separate fixed-action
infrastructure diagnostic through the same SIM service. Retain reset/frame/action
receipts and check independent camera views, orientation stability and native
control counts. This does not award a model score or authorize repeating a
previous capability attempt. Robosuite 1.4's native renderer lifecycle requires
particular care after hard resets; a working EGL import is not proof that all
post-reset images are valid. No image-repair or renderer monkeypatch is applied
silently by this adapter.
