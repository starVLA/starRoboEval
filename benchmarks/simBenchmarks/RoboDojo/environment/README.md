# RoboDojo environment

This directory owns the native Direct v2 worker, robot-only kinematics and
hash-bound runtime preparation. It contains no model policy, prompt, provider
client, training recipe or model result.

Task definitions and fixed layout selections live in [../bench_server/protocol/task_catalog.json](../bench_server/protocol/task_catalog.json).
The [service adapter](../bench_server/adapter.py) uses
[native_worker_client.py](../bench_server/native_worker_client.py) to communicate
with this directory's worker. That private connection is separate from the public
SIM service used by model runners. Deployment paths and GPU selection are supplied
through [../server.example.json](../server.example.json).

## Required runtime

Use legally obtained RoboDojo source/assets and the exact revisions recorded in
[reference_eef_snapshot.json](reference_eef_snapshot.json). The accepted
deployment baseline uses Python 3.11, Isaac Sim 5.1, IsaacLab 0.54.3, Torch
2.7.0+cu128, NumPy 1.26.0, SciPy 1.15.3, Gymnasium 1.2.1 and PyAV 18.1.0.
These are validation pins, not an automatic installer.

The operator must provide a compatible NVIDIA driver/GPU and accept applicable
runtime and asset licences. The tools do not copy an EULA marker, credentials or
licensed assets. Do not fabricate a manifest, weaken source checks or silently
replace unresolved materials.

## Prepare an owned deployment

The create-only preparation tool copies verified source and assets into a new
runtime root and emits an immutable manifest/digest:

```sh
python -B -m benchmarks.simBenchmarks.RoboDojo.environment.reference_eef_runtime prepare \
  --native-repository /absolute/upstream/git/repository \
  --base-assets /absolute/qualified-parent/Assets \
  --additional-assets /absolute/authorized-reference/Assets \
  --reference-assets /absolute/authorized-reference/Assets \
  --asset-parent-manifest /absolute/qualified-parent-manifest.json \
  --runtime-root /absolute/new-owned-runtime \
  --python /absolute/native-environment/bin/python \
  --isaaclab-root /absolute/pinned/IsaacLab \
  --curobo-root /absolute/pinned/curobo \
  --recording-support /absolute/recording-support \
  --archive /absolute/new-owned-runtime.tar.gz
```

Asset locations are operator-supplied paths. `--base-assets` supplies the exact
parent `files` inventory; `--additional-assets` supplies the pinned additional
asset leaves. The optional `--reference-assets` independently rechecks the
parent manifest's `reference_files` at a current location, including its absent
counterparts and declared URDF line-ending equivalence. It may point to the same
tree as `--additional-assets`, but the two options verify different inventories.
When omitted, preparation still verifies every base and additional asset byte;
it does not access the historical counterpart directory. The preparation receipt
records whether the optional counterpart comparison ran and its resolved path.

The parent manifest's `reference_root` is historical provenance, not a hardcoded
deployment requirement. Keep the original parent manifest bytes and pinned
digest when relocating assets. The service reads the prepared runtime's `Assets`
tree via its configured runtime manifest; it does not need the original
reference directory. No asset-root field is passed to the model.

`KNOWN_UNRESOLVED` records exact inherited material/texture references inside
the pinned assets. Those URI strings identify accepted missing references;
they are not deployment paths or configurable asset roots.

Retain the returned manifest, digest, preparation receipt and archive hash.
External interpreter/dependency paths are part of the deployment binding. A
relocated installation needs a new verified manifest; never edit a manifest
already associated with an episode.

## Readiness gate

Before model evaluation verify:

1. source, asset, layout and dependency hashes;
2. Isaac licence acceptance and actual GPU availability;
3. native reset and all three RGB streams;
4. measured robot state, fixed DLS conversion and one acknowledged control;
5. native scorer accounting, video decode and acknowledged worker cleanup.

The shared [readiness probe](../../SERVER_PROTOCOL.md#readiness-probe) checks
item 3 and worker cleanup through the service, with no model or action. Run it
against a dedicated `example` launch; RoboDojo rejects `--episodes` truncation.
Controls are first checked in the closed records of a separately authorized
sample. A probe is infrastructure evidence, not task success or a model score. Store diagnostics outside public capability results. Never add
simulator ticks while waiting for a model: waiting must not change physics.

## Max-mode reset-stability preparation

`max` needs a reset-stability manifest; this preparation has not yet been
performed, and no preparation tool is shipped. A separately authorized,
reset-only screen on the evaluated runtime:

1. resets layouts 0, 1, 2, … of `classify_objects` in order, one fresh native
   worker process per layout, with no policy and no action;
2. records `stable` when the reset passes the worker's post-reset check,
   `unstable` on native `UnStableError` or a failed check, and `exception` on
   any other reset error;
3. stops at the 50th stable layout, or reports that the 55 layouts hold fewer;
4. writes the `starvla-rsi.robodojo.reset-stability/v1` JSON described in the
   [protocol](../EVALUATION_PROTOCOL.md#max-first-reset-stable-layouts), with
   the runtime manifest SHA-256, creation time and procedure under
   `preparation`, then records the file's SHA-256 to pin it as
   `stability_manifest_sha256` (optional; without it the service records the
   observed digest as unpinned).

Keep the worker logs and any failure. Never rerun the screen to improve a
result or edit a manifest already associated with an episode. Screening
results are preparation provenance, not task outcomes or model scores.

See [the full Direct v2 binding](REFERENCE_EEF.md) and the parent
[evaluation protocol](../EVALUATION_PROTOCOL.md).
