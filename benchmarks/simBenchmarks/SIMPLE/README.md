# SIMPLE

[SIMPLE](https://github.com/physical-superintelligence-lab/SIMPLE) is a whole-body
humanoid benchmark from Physical Superintelligence Lab. Its G1 robot tasks
combine locomotion, reaching and dexterous manipulation. SIMPLE is distinct from
SimplerEnv; the service ID here is `simple_humanoid`.

The [benchmark project](https://psi-lab.ai/SIMPLE/index.html) describes
**60 whole-body tasks, 50 indoor scenes and more than 1,000 object assets**.
Its task space includes manipulation while standing, bending, walking and
carrying; task names, scene identities and randomized reset instances are
different axes of evaluation.

The agent supplies **36 joint/controller values, not end-effector targets**.
Fixed native AMO or SONIC controllers handle low-level whole-body execution.
Their weights are environment dependencies, not the participant method being scored.

## Native tasks and reset distributions

The [published evaluation protocol](https://github.com/physical-superintelligence-lab/SIMPLE/blob/5e3d6f84e85343e34e9bca8d157f0d7813231185/README.md#-simulation-benchmarking-results)
uses three domain-randomization levels, with **10 evaluation trials per task
per level** in its reference comparisons:

| Level | Variation |
| --- | --- |
| DR0 | Table appearance and distractor types/initial positions |
| DR1 | DR0 plus lighting changes |
| DR2 | DR1 plus initial target-object position changes |

Released evaluation packages store explicit episode configurations. A task,
DR level and episode index select a case; a new runtime seed alone is not
another released episode. The [official evaluation data](https://huggingface.co/datasets/USC-PSI-Lab/psi-data/tree/e78fb93cc28912a3031a10b8656d32d7f0a2b867/simple-eval)
contains indices 0–9 at each level for the 12 tasks in the service task table:
30 configurations per task.

## Available service bindings

The [service task table](bench_server/protocol/RELEASED_TASK_SCOPE.md) binds
**12 tasks**, each at **DR0, released episode 0, seed 20260907**. The selected
configurations span seven scene entrypoints.

| Selection | Available tasks |
| --- | --- |
| `task_scope="released-12"` | All 12 tasks in the task table; one task/backend per server |
| `task_scope="pilot"` (default) | `G1WholebodyBendPickMP-v0` or `G1WholebodyOpenFaucetTeleop-v0` |

The adapter default is BendPickMP; [server.example.json](server.example.json)
selects OpenFaucetTeleop. Set `task_names` to a one-element task list.
Other DR levels and episode indices are not selectable through this service.

## Observations and 36-dimensional actions

| Interface | Current contract |
| --- | --- |
| Language | Exact released task instruction |
| RGB | `head_stereo_left`, 640×360 native RGB |
| Robot state | Normally 31 measured joint positions in radians; RGB-only is selectable for the two default-scope tasks |
| Joint commands | 14 dexterous-hand joints + 14 arm joints + 3 waist joints, all absolute radians |
| Other commands | Base height in meters, forward/lateral velocities in m/s, turn flag/gate, target heading in radians |
| Coordinates | Native G1 joint coordinates and backend navigation frame; not Cartesian EEF deltas |
| Control timing | One action is one 50 Hz control: ten 2 ms physics ticks for AMO, four 5 ms ticks for SONIC |
| Success | Native step reward/`_success` path, without an extra scorer query |

There is no binary gripper command: the 14 hand joints specify the two dexterous
hands. The service checks dimension and finite values but adds no joint-target
range rejection or clipping. Native motor/controller behavior remains in force.
Exact ordering and backend navigation semantics are in
[the action reference](bench_server/protocol/POLICY_GUIDE.md).

## Execution budget and current limits

For the 12 service-bound tasks, native horizons range from 400 to 1,200 controls;
the task table lists each one. The current service configuration instead binds
`max_policy_calls=200`, `replan_interval=5` and a 1,000-control cap. This is an
integration constraint, **not a native requirement** on inference frequency or
action grouping.

For the two default-scope tasks, `budget_mode="horizon"` selects the native
control horizon, but the adapter still requires the same 200/5 settings.
Use [the evaluation protocol](EVALUATION_PROTOCOL.md) to distinguish the native
horizon and the actual selected cap when comparing results.

## Prepare the environment

Use native source revision `5e3d6f84e85343e34e9bca8d157f0d7813231185`,
Python 3.10, Isaac Sim 4.5 and MuJoCo 3.3.6. Provision the native source,
controller weights, robot assets, released evaluation metadata and HSSD scenes
under their licenses. Installing RSI does not supply those dependencies.

[environment/upstream.json](environment/upstream.json) records required runtime,
source-patch, controller and asset identities. Set explicit `simple_root` and
`eval_root` paths; the worker interpreter is `<simple_root>/.venv/bin/python`.
The current runtime checks expect a compatible asset/source installation;
a portable all-assets bootstrap is not available.

SIMPLE can create controller contexts on multiple visible GPUs. Check actual
GPU capacity and process visibility; renderer selection alone is not isolation.
The separate [diagnostic tool](environment/diagnose.py) checks reset,
stabilization and hold control. Its deployment defaults need explicit adjustment
when used on a different installation.

## Launch and connect

Copy [server.example.json](server.example.json) to an operator-owned path. Set
runtime/asset roots, GPU, `task_scope` and one `task_names` entry.
Set the evaluator-only `RSI_SIM_SERVER_TOKEN` following the
[shared service protocol](../SERVER_PROTOCOL.md), then start a new server:

```sh
python -B -m benchmarks.simBenchmarks.SIMPLE.server \
  --parameters /absolute/simple-server.json \
  --seed 20260907 --episodes 1 --port 8765 \
  --output-dir /absolute/new-run/server
```

Startup fixes the selection without resetting the simulator. Connect a trusted
driver through [the agent interface](../../../docs/agent-methods.md); the actor
receives only declared language, sensors and execution feedback. Object truth,
reset metadata and private scores remain on the evaluator side.

## Results

Report the task, backend, DR level and episode index, selected sensors, native
horizon, actual execution cap, native success and termination reason.
Initialization controls are separate from agent-issued controls.
Interaction histories and video retention use
[shared recording settings](../../../docs/recording.md).

## Directory responsibilities

- `server.py`: public factory/launch entrypoint.
- `bench_server/adapter.py`: sensor/action interface, reset selection and native scoring.
- `bench_server/protocol/`: task/reset inventory and interface descriptions.
- `environment/`: private native worker, runtime dependencies and setup diagnostics.
