# RoboTwin environment setup

This integration requires a matching native archive, an isolated Linux runtime
and verified graphics support. Follow the [evaluation protocol](../EVALUATION_PROTOCOL.md)
for the selected clean-task distribution and robot interface.

## Source and runtime requirements

The source archive has no own Git revision. Its selected closure is pinned in
[native_snapshot.json](native_snapshot.json): **2,088 files / 1,011,813,984
bytes**, including Aloha, both object variants for the two supported tasks,
native task/configuration code and CuRobo. Its source revision is explicitly
`null`; the content inventory supplies the deployment identity.

An arbitrary current RoboTwin clone or asset release does not satisfy this pin.
Supply a matching reference archive; changing the accepted source inventory
requires a separately reviewed protocol change. A clean upstream bootstrap is
not yet provided.

The native runtime is Linux/Python **3.11.15**, SAPIEN **3.0.0b1**, MPLib
**0.2.1** and TOPPRA **0.6.3**. [runtime_snapshot.json](runtime_snapshot.json)
records selected package versions and SAPIEN/MPLib/TOPPRA bytes. These checks
do not certify every transitive dependency, driver or compiled JIT output.

## Prepare an owned deployment

From the RSI checkout:

```sh
python -B -m benchmarks.simBenchmarks.Robotwin.environment.deployment prepare \
  --reference-root /absolute/matching-reference-archive \
  --output-dir /absolute/new-owned-robotwin-deployment
```

The helper copies the selected closure without changing the reference. Only
the two Aloha `curobo_left.yml` / `curobo_right.yml` files are derived from
pinned native `_tmp.yml` templates through native `ASSETS_PATH` expansion.
Retain the generated receipt and `deployment_manifest_sha256`; all other bytes
and the exact file set must match. Extra source overrides, symlinks and bytecode
caches are rejected.

Native utility imports need `assets/objects/objaverse/list.json` and
`assets/objects/same.json` even with clutter disabled; both are included.
These clean tasks do not cover randomized scenes or assets for other tasks. Allow space
for the selected closure, JIT caches and episode media. Do not run a wholesale
native installer over another environment: its package patches, path rewrites
and unpinned downloads are outside this deployment contract.

## Renderer selection and verification

Run the [renderer readiness checks](RENDERING.md) on the assigned device.
Bundled OIDN 2.0.1 supports a limited range of CUDA architectures. An explicit
`renderer_runtime="oidn_2_3_3_cuda_v1"` track uses an owned SAPIEN overlay;
follow the [overlay setup](RENDERING.md#opt-in-oidn-233-cuda-runtime)
and [OIDN 2.3.3 server example](../server-oidn233.example.json).

The default example keeps `bundled_oidn_2_0_1`. OIDN 2.3.3 changes denoising
implementation/default quality, so its protocol identity is different. Neither
nonempty RGB arrays nor a file inventory proves correct image rendering.

Using the prepared interpreter, verify the deployment without resetting or
controlling the simulator. Select the bundled track explicitly:

```sh
python -B -m benchmarks.simBenchmarks.Robotwin.environment.runtime \
  --root /absolute/new-owned-robotwin-deployment \
  --manifest-sha256 YOUR_DEPLOYMENT_MANIFEST_SHA256 \
  --renderer-runtime bundled_oidn_2_0_1
```

For the OIDN 2.3.3 deployment, prepend its verified overlay as described in
[renderer setup](RENDERING.md#opt-in-oidn-233-cuda-runtime) and replace
the last argument with `--renderer-runtime oidn_2_3_3_cuda_v1`. Interpreter or
`PYTHONPATH` selection alone does not select the readiness track: omitting this
argument defaults to the bundled OIDN 2.0.1 pin. Use the same renderer choice in
the service configuration.

## Max-mode accepted-seed preparation

`max` needs an accepted-seed manifest; this preparation has not yet been
performed and no tool for it is shipped. The owned deployment lacks the native
instruction generator (`description/utils/`), so run the screen from the
matching reference archive in its native runtime, offline and once per task:

1. Construct the task with the `demo_clean` configuration and walk candidate
   seeds from 100000. For each seed call `setup_demo(now_ep_num=…, seed=seed,
   is_test=True, **config)` and `play_once()`, then `close_env()`.
2. Reject `UnStableError` as `unstable`, any other exception as `exception`,
   and failing `plan_success and check_success()` as `expert_check_fail`.
3. For an accepted seed, `setup_demo` again, then record
   `np.random.choice(generate_episode_descriptions(task, [episode_info["info"]], 100)[0]["unseen"])`
   as its instruction, as the native evaluator does before the policy runs.
4. Stop at the 100th acceptance and write
   `starvla-rsi.robotwin.accepted-seeds/v1` JSON with every rejection and
   the preparation provenance listed in the
   [protocol](../EVALUATION_PROTOCOL.md#max-accepted-seed-manifest). Set
   `preparation.deployment_manifest_sha256` to the digest of the deployment
   the service will run; startup rejects any other value.

Record the manifest SHA256, the archive evaluator SHA256, the runtime and any
failure; never rerun to improve a result. Keep expert `episode_info` out of the
manifest. Whether the archive's own evaluator applies exactly these steps is
UNVERIFIED.

Then follow the [service launch guide](../README.md#start-the-benchmark-service).
Use a separate labelled native readiness check for reset, compiled controller
bounds, all three camera streams, fixed controls, video decoding and cleanup.
Such diagnostics validate deployment behavior, not participant capability.
Keep their records separate from scored task attempts.
