# RoboTwin

This benchmark-owned server exposes native Aloha joint-target control, three
RGB cameras, language, 12 measured arm joint angles and two explicitly labeled
gripper command values. The model generates all task actions. The server
does not expose expert rollouts, object poses, IK or task-planning methods.

The adapter is a development fast track, not the native full score: choose
`lift_pot` or `click_bell`, one predeclared unscreened seed, one attempt.
Native imports, reset, image correctness and compiled controller validation are
runtime acceptance gates; a listening server or CPU test is not a native pass.
See [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) for exact differences.

The current `state14/fast-v3` and OIDN-compatible `state14-oidn233/fast-v4`
protocols add this robot-state reference for absolute joint control. The former
RGB-only v1/v2 results keep their frozen contracts; they do not gain retrospective
state. Arm positions come from native measured-joint getters, not the
misleadingly named `joint_action` drive targets. Gripper values remain commands,
not measured opening or grasp evidence. The new observation track needs its own
native acceptance; an old reset-only or zero-action model run is not that proof.

## Directory responsibilities

`server.py` is the public factory/launch entrypoint; `bench_server/adapter.py`
owns the supported two-task interface and native scoring. `environment/` owns
deployment, native/runtime pins and renderer readiness. The small task definition
remains in the adapter: no empty catalog or protocol package is required. Operator paths and track selection belong in
`server.example.json` or an operator-owned copy. No root adapter shim remains;
this relocation does not change native actions, budgets or scoring.

## Native environment and assets

The inspected local RoboTwin archive has no own Git revision. Its selected
runtime closure is pinned in [environment/native_snapshot.json](environment/native_snapshot.json):
2,088 files / 1,011,813,984 bytes, including Aloha, both object variants for the
two tasks, native task/config code and its CuRobo package. `native_source_revision`
is `null`; the descriptor uses a content-inventory SHA-256, not an invented
upstream or parent-repository commit.

This initial archive-specific adapter is not yet a one-command clean upstream
installation. An arbitrary current RoboTwin clone or the public asset release
alone will not satisfy the source pin. Supply the exact matching archive, or
review and version a new source inventory/protocol explicitly. Do not regenerate
the accepted inventory merely to bypass a mismatch.

The intended native environment is Linux/Python 3.11.15, SAPIEN 3.0.0b1,
MPLib 0.2.1 and TOPPRA 0.6.3, with the exact versions and SAPIEN/MPLib/TOPPRA
package bytes in [environment/runtime_snapshot.json](environment/runtime_snapshot.json).
The adapter checks them without importing the simulator. This is not a full
transitive environment, GPU driver or CUDA JIT attestation. Dependencies,
renderer/GPU availability and matching asset bytes are separate requirements.
In particular, bundled OIDN 2.0.1 has a limited CUDA architecture range. Run the
[renderer readiness check](environment/RENDERING.md) on the allocated device:
valid files and nonempty RGB frames do not establish a working denoiser.
For CUDA devices outside that version's architecture range, an explicit
`oidn_2_3_3_cuda_v1` renderer track is available. Follow the
[owned overlay instructions](environment/RENDERING.md#opt-in-oidn-233-cuda-compatibility-track)
and use [server-oidn233.example.json](server-oidn233.example.json). It keeps the
original environment and native task bytes untouched. The new renderer track
has a different protocol identity and does not claim image parity with 2.0.1;
the default example still selects the original track.

To materialize a new deployment from a matching reference archive:

```sh
python -B -m benchmarks.simBenchmarks.Robotwin.environment.deployment prepare \
  --reference-root /absolute/path/to/matching-reference-archive \
  --output-dir /absolute/path/to/new-owned-robotwin-deployment
```

This copies the selected closure without changing the reference. Only the two
Aloha `curobo_left.yml` / `curobo_right.yml` files are derived from their pinned
native `_tmp.yml` templates by native `ASSETS_PATH` expansion. The receipt records
original/template/deployed hashes and the `deployment_manifest_sha256`. Every
other byte and the exact file set must match. Extra source overrides, symlinks
and bytecode caches are rejected. Do not run a native wholesale installer
against an existing environment: its package patches, path rewrites and
unpinned downloads are not this deployment.

The closure includes `assets/objects/objaverse/list.json` and
`assets/objects/same.json`: native utility imports read both even when clutter
is disabled. They are unchanged native metadata, not generated substitutes.
These two clean tasks do not use randomized background/clutter geometry. That
does not establish release completeness or enable the randomized/full track.
Leave at least the selected closure's size plus headroom for a new copy, native
JIT caches and model-owned media. Full RoboTwin assets are substantially larger.

## Start one SIM service

From the RSI repository root, copy [server.example.json](server.example.json)
to an evaluator-private configuration. Replace both placeholder deployment
fields; the all-zero digest is intentionally not runnable. Select the task and
native seed before the attempt. The shared harness seed is recorded separately
and does not search for a native seed.

First verify files/runtime only:

```sh
python -B -m benchmarks.simBenchmarks.Robotwin.environment.runtime \
  --root /absolute/path/to/new-owned-robotwin-deployment \
  --manifest-sha256 YOUR_DEPLOYMENT_MANIFEST_SHA256
```

Set the same evaluator-only `RSI_SIM_SERVER_TOKEN` (32–256 URL-safe characters)
in the server and evaluator environments. The adapter creates a fresh per-episode
`cache/curobo-jit` and scopes `TORCH_EXTENSIONS_DIR` there during native calls;
it stays outside the pinned deployment and is excluded from artifact transfer.
Using the native environment, start:

```sh
python -B -m benchmarks.simBenchmarks.Robotwin.server \
  --parameters /absolute/private/robotwin-server.json \
  --seed 20260907 --episodes 1 --port 8771 \
  --output-dir AgentPolicies/anonymous_code_agent/results/robotwin/raw/lift_pot-pot-lifting-service
```

`-B` is required. The server binds loopback and starts with zero native resets.
Calls are serialized; waiting for a model does not advance physics. Follow the
[shared service setup](../SERVER_PROTOCOL.md) for evaluator-only URL/token setup
and SSH forwarding when the evaluator is on another node. Never give service
credentials or evaluator-side native records to the actor.

## Run a participant through the evaluator

Use a fresh model-owned result directory and a previously prepared opaque policy
mailbox; model setup belongs under `AgentPolicies/<profile>/`, not here.
For the external code-agent mailbox, the evaluator command is:

```sh
python -B -m benchkit run \
  --benchmark robotwin \
  --sim-server http://127.0.0.1:8771 \
  --model-profile anonymous_code_agent \
  --policy-args '{"directory":"/absolute/opaque-mailbox"}' \
  --seed 20260907 --episodes 1 \
  --budget-mode horizon --max-policy-calls 200 --replan-interval 5 --max-steps 1000 \
  --output-dir AgentPolicies/anonymous_code_agent/results/robotwin/raw/lift_pot-pot-lifting-evaluation
```

The native task still stops at 400 absolute joint-target controls, or native
success earlier. The runner's separate 200 calls / prefix 5 / 1,000-control
ceiling does not extend that horizon. Native controls, action decisions and
variable 250-Hz physics ticks are different counters. Policy persistence rules
are not benchmark requirements. No automatic reset, step replay or retry occurs.

Videos are named `head_camera.mp4`, `left_camera.mp4`, `right_camera.mp4` under
the model's result namespace, never here. PNG/hash records preserve delivered
RGB bytes; 10-fps MP4s present control-boundary samples, not real-time physics
or a 10-Hz controller. `frames.jsonl` records physical tick counts. After result
transfer, stop this one-episode server process: native `close_env` alone does
not attest GPU-memory reclamation. An errored attempt remains an attempt.

## Validation and remaining scope

Native reset plus fixed infrastructure controls must be separately
reviewed and recorded as non-capability diagnostics before participant use.
Randomized settings, the native 50-task/accepted-seed schedule, serial/sharded
native parity and clean upstream bootstrapping remain unimplemented.

Retired StarVLA model integration code remains in Git history, not as a server
dependency or supported evaluation entrypoint.
