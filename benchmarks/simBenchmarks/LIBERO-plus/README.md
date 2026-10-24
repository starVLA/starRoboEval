# LIBERO-Plus

LIBERO-Plus evaluates the robustness of language-conditioned robot manipulation
under changes to visual appearance, camera views, language, object layouts,
robot initialization and sensor noise. This integration serves the pinned native
variants with a declared RGB/action interface and native success checks,
independent of the participating agent method.

- [Evaluation protocol and 10,030-variant inventory](EVALUATION_PROTOCOL.md)
- [Server parameters](server.example.json)
- [Shared server interface](../SERVER_PROTOCOL.md)

## Benchmark tasks and variations

The [official benchmark](https://github.com/sylvestf/LIBERO-plus) contains
10,030 perturbation variants across four suites:

| Suite | Variants | Retained reference horizon |
| --- | ---: | ---: |
| `libero_spatial` | 2,402 | 220 controls |
| `libero_object` | 2,518 | 280 controls |
| `libero_goal` | 2,591 | 300 controls |
| `libero_10` | 2,519 | 520 controls |

The seven categories are background textures, camera viewpoints, language
instructions, light conditions, object layouts, robot initial states and sensor
noise. The [protocol](EVALUATION_PROTOCOL.md#task-universe-and-selection) gives
per-category counts; [frozen catalogs](bench_server/protocol/catalogs/) define
the native zero-based indices. Standard LIBERO's 90-task suite is excluded.

## Select variants through this service

Select an explicit increasing `task_ids` list within one suite. Every selected
variant uses released state index 0 and a predeclared seed. A variant specifies
a native perturbation such as viewpoint, language or
object layout; a seed does not select that variant or guarantee a new layout.
Report category, variant and attempt counts separately. The service's current
configuration does not select additional released-state indices.

The table's horizons are retained evaluator reference conditions, not a
universal native engine limit. The separate `decisions` track declares
`max_policy_calls × replan_interval` as its control cap and changes protocol
identity. In horizon mode, grouping controls between decisions is agent-owned.

## Observations, actions and scoring

The public input is the BDDL language instruction and two 256 × 256 RGB images:
`agentview` and `robot0_eye_in_hand`, each with the retained 180° transform.
Native image perturbations are preserved. Joint/object poses, calibration,
variation parameters and native scores are not public observations. The
language comes from the BDDL rather than parameter-bearing variant filenames;
this is an explicit track distinction from the upstream filename-derived prompt.

One control is a seven-value `OSC_POSE` vector in `[-1,1]` at 20 Hz: world
translation deltas (±0.05 m per axis), world axis-angle deltas (±0.5 rad per
axis), and gripper `-1` open / `+1` close / `0` retain target. Ten fixed
settling controls are initialization, recorded separately from agent controls.

The native step's `done = _check_success()` is authoritative. First native
success terminates the episode; reaching the declared cap without success is a
completed failure. Rendering, asset-loading and runtime errors remain separate
from task failures. Report call, decision,
control and settling counts separately.

## Directory responsibilities

`server.py` is the public factory/launch entrypoint. `bench_server/adapter.py`
owns the public sensor/action interface and native score bridge;
`bench_server/protocol/catalog.py` and `catalogs/` define the immutable task matrix.
Native installation, source pins and catalog-generation tools belong in
`environment/`; in particular `native_source_manifest.json` is a runtime pin,
not a task catalog. Operator paths and selected cases stay in the server
configuration. Agent implementations and results belong under
`AgentPolicies/<agent>/`; shared communication and report tools belong in
`benchkit/`.

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
  --output-dir /absolute/path/to/results/libero_plus/your-run/server
```

The service binds only `127.0.0.1` and initializes no simulator until the trusted
evaluator resets the selected session. Connect a compatible driver through the
[wire protocol](../SERVER_PROTOCOL.md); see
[agent integration](../../../docs/agent-methods.md) for participant-side code.
Omit `--episodes` to select the complete configured task list, or use an explicit
prefix length. Cross-node use needs an SSH tunnel. Every selected session is
claimed once, including errors; uncertain control acknowledgments are not replayed.

## Check rendering and control

Before capability evaluation, explicitly select a separate fixed-action
infrastructure diagnostic through the same SIM service. Retain reset/frame/action
receipts and check independent camera views, orientation stability and native
control counts. This does not award a model score or authorize repeating a
previous capability attempt. Robosuite 1.4's native renderer lifecycle requires
particular care after hard resets; a working EGL import is not proof that all
post-reset images are valid. No image-repair or renderer monkeypatch is applied
silently by this adapter.

## Results

Keep method implementations under `AgentPolicies/<agent>/` and generated reports
and evidence under `AgentPolicies/<agent>/results/libero_plus/`. Report the selected suite/variant
denominator, reset convention, protocol, native outcomes, counters and typed
errors. Separate different perturbation categories, observation conditions and
runtime backends where they affect comparability. See
[recording](../../../docs/recording.md) for optional interactions and server-side
videos, and [evaluation](../../../docs/evaluation.md) for closed-result tools.
