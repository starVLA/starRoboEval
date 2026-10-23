# BEHAVIOR 2026 native preparation

Status: the fixed DefaultWrapper debugging service has passed one two-control
HTTP native smoke check; see [verified scope](../README.md#verified-scope).
This is not a model score or a guarantee for another deployment. See the [launch and file-only
deployment capture guide](../README.md). Do not launch the archived 2025 VLA
bridge or publish its task inventory as the 2026 matrix.

## Source identity and permissions

Use [BEHAVIOR-1K v3.9.2](https://github.com/StanfordVL/BEHAVIOR-1K/tree/b1979916ec1549b10a4e65e630bc6504a9af1b00),
commit `b1979916ec1549b10a4e65e630bc6504a9af1b00`, as required by the
[2026 evaluation rules](https://behavior.stanford.edu/challenge/evaluation.html).
Pin the complete source and installed runtime independently of that mutable web page.

The [pinned installer](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/setup.sh)
contains separate dataset terms. Code access or an earlier Isaac Sim license
acceptance does not establish acceptance of the BEHAVIOR Data Bundle agreement.
Obtain operator confirmation before its acceptance flags or restricted data
download. Do not redistribute dataset files or keys in the public repository.
Use a fresh environment; never run the installer against another benchmark's
environment. Native model checkpoints and training demonstrations are not
requirements for a fixed-action infrastructure diagnostic.

## Native interface to preserve

Read `OmniGibson/omnigibson/eval/{eval.py,evaluator.py,r1pro.yaml}` and
`eval/wrappers/` at the pinned commit, not an archived policy launcher.
The [source-level contract review](NATIVE_CONTRACT.md) records the 23-action /
61-state mapping, observation allowlist and remaining runtime checks.

- The official wrapper is `RGBDFullResWrapper`: head RGB/depth at 720×720,
  wrists at 480×480, with robot proprioception. `DefaultWrapper` is a distinct
  224×224 RGB plus proprioception debugging configuration without depth; never
  silently substitute it.
- The bundled robot config uses R1Pro, absolute arm/trunk joint-position
  controllers, a velocity-controlled mobile base and native gripper controllers.
  Its `assisted` grasping setting is an explicit native mechanism, not an
  invitation to add an RSI task planner. Record it rather than silently changing it.
  Validate action order, dimension, units and timing against the installed native
  robot/controller contract before declaring an action schema.
- Native preparation resets, loads the selected instance, settles it for 25
  physics ticks while keeping relevant entities still, and resets for rollout.
  Keep this setup server-private; one rollout does not imply one underlying
  reset call. No reset/instance search is exposed to the model.
- Native `Evaluator.step` obtains one supplied action, steps the environment,
  updates observation/video and native metrics. The service must replace only
  the policy-input boundary, preserving native termination and scoring.
  Object states, private task metadata and metric internals remain server-private.

## Runtime compatibility and deployment acceptance

### Node-local temporary files

Set `TMPDIR` **before starting the server**, to a fresh operator-owned directory
on a node-local filesystem; the isolated worker inherits it. Keep results,
deployment manifests and evidence on persistent storage. No additional server
parameter or change to the native controller is required.

The pinned native runtime creates its temporary USD directory during import and
removes it before closing the Kit application. On NFS, an open file can become a
temporary `.nfs*` entry during unlink; recursive directory removal can then fail
with `ENOTEMPTY`. This failure was reproduced independently with an open-file
fixture on the evaluation deployment. A subsequent native shutdown crash must
still be recorded as an infrastructure error, not suppressed or converted to a
successful evaluation.

Use a dedicated mode-0700 child directory, not `/tmp`, `/dev/shm`, or a workspace
root itself. A tmpfs such as `/dev/shm` is an option only when both filesystem
capacity and the process cgroup memory budget have adequate headroom: its free
space is not a memory reservation. Check actual mount type, ownership, capacity
and memory before launching; do not infer local storage from a directory name.
Keep workers sequential when resources are constrained. Never delete other
runs' temporary files or discard failed-run evidence to make a check pass.

After changing the launch setting, use a new run ID and verify native controls,
video decoding and graceful worker cleanup through the same service. Do not
patch `og.cleanup`, ignore its errors or change native scoring. This is a
deployment correction, not a new observation/action protocol or a score result.

### CPython crash-handler initialization

The private worker starts with `python -X faulthandler -B -m ...`, registering
the real CPython crash handler before native imports, then enlarges the main
thread's POSIX alternate signal stack to at least 64 KiB. Early enable alone is
not sufficient: actual AMX use can still prevent crash-traceback delivery on
the smaller stack. On an affected Linux x86
runtime, enabling AMX extended CPU state before late `faulthandler.enable()`
can make alternate signal-stack registration fail with `OSError: ENOMEM`, even
with free memory. This is a worker-runtime compatibility fix, not a change to
the benchmark. Do not swallow the exception, monkeypatch the
handler or disable crash diagnostics. Crash output remains in the private
`native_worker.log`; native source, controls and scoring are unchanged.
`native_crash_handler.json` records the stack sizes and main-thread scope. The
Linux x86-64 bootstrap retains its small libc allocation for the process lifetime
so a registered signal stack never points at freed Python memory. It does not
claim to configure native SDK threads or replace their own crash handlers.
See the [Linux XSTATE documentation](https://docs.kernel.org/arch/x86/xstate.html)
and [Python startup options](https://docs.python.org/3.11/using/cmdline.html#cmdoption-X).

### Validation sequence

1. Verify a dedicated runtime, licensed asset revision and a fixed public task
   instance. Record all missing inputs without claiming an attempted rollout.
2. Freeze robot config, native task/instance schedule, observation allowlist and
   action semantics. Keep the old 2025 inventory separate.
3. The implemented `benchkit/sim_server` service selects DefaultWrapper RGB plus
   proprioception, not the full RGBD track. Full RGBD needs a separately reviewed
   depth representation; never encode metric depth as RGB or silently drop it.
4. Independently review no-reset startup, private-data filtering, native metric
   bridge, counters, media, source capture and cleanup; run offline regressions.
5. Predeclare one task/instance and two fixed valid controls for a no-model
   service diagnostic. Preserve any failure, with no automatic retry. Only
   after this gate may a separate model trial be called executable.

Cold startup may spend many minutes importing the scene and generating collision,
shader and rendering caches, especially on shared storage. Monitor CPU, I/O and
native logs; do not confuse a live initialization with an acknowledged reset.
Choose the bounded `worker_timeout` before claiming a case. Never extend a frozen
run silently or replay a timed-out reset/control.

The recorded smoke check does not grant license acceptance or establish an
installation on another host, model capability, or full challenge parity.
