# MetaWorld MT50 SIM server

The benchmark owns the native simulator, RGB/action contract and success check.
Models own only their observation-to-action policy under `AgentPolicies/<profile>/`;
the neutral harness owns communication, counters and reports.

This is a **development server adapter**, not a completed native MT50 score.
The current protocol supports an explicit fast subset, one attempt per selected
task. Native full evaluation and retained-evaluator parity are not established.

- [Environment setup and package verification](environment/README.md)
- [Evaluation protocol](EVALUATION_PROTOCOL.md)
- [All 50 canonical task names, instructions and retained difficulty buckets](bench_server/protocol/task_catalog.json)
- [Shared SIM service interface](../SERVER_PROTOCOL.md)
- [Example fixed server configuration](server.example.json)

## Directory responsibilities

`server.py` is the public factory/launch entrypoint. `bench_server/adapter.py`
owns observation, action and native scoring; `bench_server/protocol/task_catalog.json`
owns the immutable task inventory. `environment/` owns native setup and package
pins; `checks/` contains offline contract regressions. Deployment paths and the
selected schedule belong in an operator copy of `server.example.json`.
There is no root adapter compatibility entrypoint. This layout changes neither
the public wire protocol nor native control/scoring semantics.

## Launch a fixed schedule

Use the prepared native Python, from a stable source checkout. Set a strong
`RSI_SIM_SERVER_TOKEN` outside Git in the **server and trusted evaluator only**.
Never give the token, service management interface or native filesystem to a
model actor. Choose a fresh result directory for each authorized schedule.

```sh
python -B -m benchmarks.simBenchmarks.MetaWorld.server \
  --parameters benchmarks/simBenchmarks/MetaWorld/server.example.json \
  --seed 4042 --episodes 1 --port 8765 \
  --output-dir /absolute/AgentPolicies/my_profile/results/metaworld/raw/reach-direct-control/server
```

Launch/list/describe do not construct the native simulator. The first claimed
episode's `reset` constructs MT50, selects the task and performs native setup.
The service binds loopback only; use SSH forwarding for a separate evaluator
node. There is no background control loop and no reset/action replay on errors.

From the evaluator environment, with the policy already configured:

```sh
python -B -m benchkit run --benchmark metaworld \
  --sim-server http://127.0.0.1:8765 \
  --model-profile anonymous_code_agent \
  --policy-args '{"directory":"/absolute/opaque-mailbox"}' \
  --seed 4042 --episodes 1 --budget-mode horizon \
  --max-steps 400 --max-policy-calls 200 --replan-interval 5 \
  --output-dir AgentPolicies/anonymous_code_agent/results/metaworld/raw/reach-direct-control/evaluator
```

Use `horizon` here: the cap is 400 executed model-selected controls, not a
200×5=1000-control extension. A 200-call cap or shorter policy chunks can end an
attempt earlier. Stop calls execute no control. The one native setup no-op is
recorded separately. Ordinary give-up preferences belong to the policy, not
this benchmark.

The actor receives full-frame 480×480 `corner2` RGB and the instruction, never
native object/goal state. The default `image_orientation="rot180"` rotates the
native upside-down view exactly 180 degrees; it performs no crop or resize.
The explicit `native` orientation preserves the earlier raw fast-v1 track under
its original protocol ID. These are distinct observation conditions, recorded
in provenance, not interchangeable scores. The actor selects a four-dimensional
bounded native action. No model server or VLA-specific preprocessing is used.
Old model scripts remain in Git history; the adapter never imports them.

All per-run results, evidence and videos belong to the selected profile's
`results/metaworld/`, not this benchmark directory. A failed fast task is retained;
changing directories or restarting a service does not authorize another attempt.
