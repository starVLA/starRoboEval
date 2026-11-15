# BEHAVIOR native environment

This guide prepares the native runtime used by the
[selected-case service](../README.md). It covers installation inputs and
deployment checks; participant methods and their results are separate.

## Source, runtime and assets

Use [BEHAVIOR-1K v3.9.2](https://github.com/StanfordVL/BEHAVIOR-1K/tree/b1979916ec1549b10a4e65e630bc6504a9af1b00),
commit `b1979916ec1549b10a4e65e630bc6504a9af1b00`, in a dedicated persistent
Python 3.11 / Isaac Sim 5.1 environment. Follow the
[pinned installer](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/setup.sh)
and native evaluator dependency instructions for that release.

The BEHAVIOR Data Bundle has its own license, separate from Isaac Sim and source
code licensing. Obtain the required permissions before downloading restricted
assets or accepting installer terms. Do not redistribute assets or credentials
in this repository. The service requires robot assets and selected task
instances; it does not require an agent checkpoint or training demonstrations.

Required bundles are `behavior-1k-assets`, `omnigibson-robot-assets` and
`2026-challenge-task-instances`. Code and asset release numbers need not match.
The deployed robot/controller configuration must match
[NATIVE_CONTRACT.md](NATIVE_CONTRACT.md): R1Pro, absolute arm/torso joint
controllers, mobile-base velocity control, native grippers and native
`assisted` grasping.

This integration uses `DefaultWrapper`: three 224×224 RGB cameras and
proprioception. The official `RGBDFullResWrapper` additionally supplies metric
depth and higher-resolution RGB. Identify the sensors actually used when
comparing results; these two observation configurations are not equivalent.

## Capture the selected deployment

Use the native worker interpreter with the RSI repository and the pinned source's
`OmniGibson`, `bddl3` and `joylo` directories on `PYTHONPATH`:

```sh
python -B -m benchmarks.simBenchmarks.Behavior.environment.deployment \
  --source-root /absolute/behavior-v3.9.2 \
  --data-root /absolute/behavior-assets \
  --receipts /absolute/extraction-receipts.json \
  --task picking_up_trash \
  --output /absolute/new-behavior-deployment.json
```

The receipts JSON maps each of the three bundle names above to its extraction
receipt path. A receipt contains `archive_sha256`, `source_commit` and absolute
extraction `target`. Keep the source archives and receipts in operator storage.
The capture checks files without importing OmniGibson or constructing a scene.

Use a separate capture for each selected task. The manifest must match the task
selected in the server configuration and binds its pinned instance files. Omitting `--task` selects
radio; a manifest cannot be used for another task.

Before initialization, the worker rechecks selected robot/task files, tracked
native package sources, runtime versions, interpreter and module origins.
Stale or untracked source bytecode is rejected. The recorded extraction receipts
identify archive/extraction provenance; they do not certify every live asset
byte or all host dependencies.

## Runtime placement

Set `TMPDIR` before launching the server to a fresh, private directory on
node-local storage. Keep result records, manifests and retained videos on
persistent storage. Native USD temporary-file cleanup can fail on NFS when open
files become `.nfs*` entries. Check actual mount type, ownership and capacity;
a directory name alone does not establish local storage.

Use a dedicated mode-0700 child directory, not a filesystem root. If using
tmpfs, account for both free space and the process memory limit. Do not remove
other jobs' temporary files or suppress native cleanup errors. Failed cleanup
is an infrastructure error, even after valid controls have executed.

The private worker enables CPython crash diagnostics before native imports and
reserves an enlarged main-thread alternate signal stack on the supported Linux
x86-64 runtime. This supports diagnostics with AMX-enabled native libraries.
The service records its scope in `native_crash_handler.json`; it does not
configure every native SDK thread. See the
[Linux XSTATE documentation](https://docs.kernel.org/arch/x86/xstate.html) and
[Python startup options](https://docs.python.org/3.11/using/cmdline.html#cmdoption-X).

## Readiness and launch

1. Verify native source/runtime, licensed assets, the selected instance and GPU capacity.
2. Create the deployment capture and copy its path/digest into an operator-owned
   [server configuration](../server.example.json).
3. Set `worker_python`, `gpu_id`, `worker_timeout` and the selected `task`
   before launching the [public entrypoint](../README.md#prepare-and-launch).
4. Against a dedicated `example` launch, run the shared
   [readiness probe](../../SERVER_PROTOCOL.md#readiness-probe). It verifies
   reset, all three RGB views, measured state size, timing and cleanup through
   the service, with no model or action. One valid control is first checked in
   the closed records of a separately authorized sample.
5. Keep a probe's outcome separate from a scored task attempt.

Cold scene initialization may take minutes to build collision, shader and
rendering caches. Choose a bounded worker timeout in advance and inspect native
logs when necessary. A listening HTTP server is not a completed native reset.
Do not replay a timed-out reset or control, change the frozen timeout mid-run,
or reinterpret a short diagnostic as a completed evaluation.
