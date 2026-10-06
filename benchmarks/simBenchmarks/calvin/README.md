# CALVIN

The standalone SIM server exposes two native RGB views, the current language
instruction and seven-dimensional relative robot control. Models choose every
action; task-oracle state and future instructions remain evaluator-private.

The implemented track is **`debug-sequence0`, fast, one frozen five-subtask
sequence, one attempt**. It is not the original 1,000-sequence/full D validation
score. A reviewed standalone server/client infrastructure diagnostic has verified
one fixed reset, two predeclared direct controls, both RGB streams, video decoding
and cleanup. This is bounded integration evidence, not model task success or
five-subtask/native-full parity. See [the protocol](EVALUATION_PROTOCOL.md).

## Directory responsibilities

`server.py` is the public factory/launch entrypoint; `bench_server/adapter.py`
owns the current-language control interface and native score bridge.
`bench_server/protocol/` owns the immutable sequence inventory and selected
`frozen_sequence.json`. Those reset vectors and future tasks stay evaluator-private;
putting them in a protocol package does not expose them to the actor.
`environment/` owns native loading, source/runtime pins and setup; `checks/`
contains offline regressions. No old root adapter shim remains. The path changes
preserve source-data bytes, native scoring and the required prefix-one interface.

The frozen record retains its original `sequence_file: environment/eval_sequences.json`
as historical provenance. The same byte-identical file now lives at
`bench_server/protocol/eval_sequences.json`; do not edit the frozen record to
rewrite that historical path. No old-path alias is provided.

## Prepare the native environment

Follow [environment/README.md](environment/README.md) for exact source revisions,
public debug assets, checksums and the isolated Python 3.10 RGB environment.
Use the unchanged debug `validation/.hydra/merged_config.yaml`; do not point this
track at arbitrary validation data or import a model checkpoint/evaluator.
The loader verifies all three native Git trees and their actual tracked bytes,
pinned dependencies, selected binary bytes and the original debug config.
These are scoped disk-input checks, not complete driver/loaded-memory attestation.

Copy [server.example.json](server.example.json) to a private configuration and
replace its two absolute path placeholders. Do not edit native source/configs
to bypass readiness checks. Allocate a headless EGL-capable device explicitly;
there is no fallback to a different renderer under the same protocol.

Set the same evaluator-only `RSI_SIM_SERVER_TOKEN` (32–256 URL-safe characters)
in the server and evaluator environments, then run from the RSI checkout:

```sh
python -B -m benchmarks.simBenchmarks.calvin.server \
  --parameters /absolute/private/calvin-server.json \
  --seed 20260907 --episodes 1 --port 8772 \
  --output-dir AgentPolicies/anonymous_code_agent/results/calvin/raw/sequence0-five-subtask-manipulation-service
```

The native environment must use Python 3.10 with `-B`. A listening service has
performed zero native constructions/resets. The service serializes native calls;
waiting for a model does not advance physics. Use the
[shared server protocol](../SERVER_PROTOCOL.md) for loopback/SSH forwarding and
the private bearer token. Never give the actor native paths or service credentials.
Use a fresh, dedicated process: native EGL plugin calls assume Bullet client 0,
and passive connection/tick tracing is process-scoped. Existing client 0 is
rejected before construction; other SIM owners/threads in this process are not
supported. The service is not a multi-SIM hosting container.

## Connect a participant

Model configuration and the opaque mailbox belong under `AgentPolicies/<profile>/`.
After preparing that mailbox, the trusted evaluator can use:

```sh
python -B -m benchkit run \
  --benchmark calvin \
  --sim-server http://127.0.0.1:8772 \
  --model-profile anonymous_code_agent \
  --policy-args '{"directory":"/absolute/opaque-mailbox"}' \
  --seed 20260907 --episodes 1 \
  --budget-mode horizon --max-policy-calls 200 --replan-interval 1 --max-steps 1800 \
  --output-dir AgentPolicies/anonymous_code_agent/results/calvin/raw/sequence0-five-subtask-manipulation-evaluation
```

**Prefix 1 is required**: observe the current language after every control,
including native subtask transitions. This is an interface requirement, not a
model persistence rule. The example's 200 model calls are a separate, changeable
evaluator cap; smaller call/control caps are allowed and recorded as truncation.
To permit the full native control ceiling of this one debug sequence, choose a
call cap of at least 1,800 or omit it. Neither choice enables the `full` track.
Native failure after 360 controls in any one subtask ends the sequence; success
transitions to its next subtask without resetting the SIM or exposing future tasks.

The current generic policy interface keeps one policy session across the sequence;
it has no per-subtask `Policy.reset` hook. This is explicitly different from the
native model evaluator's memory reset. No hidden reset or claimed memory parity
is introduced. Policies may respond to the current public instruction changing.

Results include completion depth, success-at-depth 1–5, per-subtask completion
control, total controls, physics ticks, failure/error status and native provenance.
PNG records retain exact delivered RGB bytes and hashes. `rgb_static.mp4` and
`rgb_gripper.mp4` are 30-fps control-boundary videos under the model's results,
not this benchmark directory. OpenCV's RGB→BGR conversion is encoding-only;
native views are not flipped, resized or cropped. Stop the one-sequence service
after artifact transfer; restarting is not permission to retry a scored attempt.

## Contract regressions

```sh
python -B -m unittest discover \
  -s benchmarks/simBenchmarks/calvin/checks -p 'test_*.py' -v
```

These tests use fake native objects; optional array checks need NumPy. The native
helper parity check needs `CALVIN_NATIVE_SOURCE_ROOT` and pinned NumPy but only
executes two source-hash-verified pure-math functions. It does not import model
helpers, construct a simulator, reset or step. Full schedules, alternative
sequences, D-validation equivalence and native policy-memory-reset parity remain
unsupported and must be separately versioned and validated.

The separate bounded native check observed one reset physics tick and sixteen
control ticks for its two fixed actions. All six delivered RGB frames matched
the stored PNG pixels, and each camera video decoded as three frames at 30 fps.
Native close disconnected the owned client and the final metrics recorded an
external incomplete stop. These checks do not establish a task-completion score,
long-run stability or rendering compatibility on a different deployment.

Historical StarVLA integration code remains in Git history, never as the active
server entrypoint or model implementation.
