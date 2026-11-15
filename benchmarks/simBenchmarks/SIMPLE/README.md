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
**12 tasks** with **seed 20260907**; `evaluation_mode` selects their DR levels
and released episode indices.

### Evaluation modes

| Mode | Selection | Episodes per task | Cap |
| --- | --- | ---: | --- |
| `fast` (default) | DR0 released episodes 0–4 | 5 | Native task horizon, 400–1,200 |
| `max` | DR0, DR1 and DR2 × released episodes 0–9 | 30 | Native task horizon, 400–1,200 |
| `example` | First `fast` episode, DR0 episode 0 | 1 | Native task horizon, 400–1,200 |

`max` is the native evaluation: every released episode at all three levels,
360 episodes across the 12 tasks. Episodes run by level, then index, with IDs
such as `G1WholebodyBendPickMP-v0/dr1/ep3`. Every mode scores with each task's
native success threshold (0.2–0.9), as the upstream evaluators do; see
[the evaluation protocol](EVALUATION_PROTOCOL.md#success-threshold).

Each server runs exactly one task, so all 12 tasks need 12 servers, one per
`task_names` entry; `task_names` narrows within the chosen mode. An omitted
`task_names` selects BendPickMP, the first task in the table. The DR0 reset
files are hash-pinned; DR1 and DR2 files are recorded as unpinned.

## Observations and 36-dimensional actions

| Interface | Current contract |
| --- | --- |
| Language | Exact released task instruction |
| RGB | `head_stereo_left`, 640×360 native RGB |
| Robot state | Normally 31 measured joint positions in radians; RGB-only is selectable only for BendPickMP and OpenFaucetTeleop |
| Joint commands | 14 dexterous-hand joints + 14 arm joints + 3 waist joints, all absolute radians |
| Other commands | Base height in meters, forward/lateral velocities in m/s, turn flag/gate, target heading in radians |
| Coordinates | Native G1 joint coordinates and backend navigation frame; not Cartesian EEF deltas |
| Control timing | One action is one 50 Hz control: ten 2 ms physics ticks for AMO, four 5 ms ticks for SONIC |
| Success | Native step reward/`_success` path at the task's native threshold, without an extra scorer query |

There is no binary gripper command: the 14 hand joints specify the two dexterous
hands. The service checks dimension and finite values but adds no joint-target
range rejection or clipping. Native motor/controller behavior remains in force.
Exact ordering and backend navigation semantics are in
[the action reference](bench_server/protocol/POLICY_GUIDE.md).

## Execution budget

For the 12 service-bound tasks, native horizons range from 400 to 1,200 controls;
the task table lists each task's metadata value. The service uses that
reference budget for every supported task. Decision-call limits and action
grouping are configured by the agent, not this server. One public step executes
one control, and native terminal conditions can end the episode earlier. See
[the evaluation protocol](EVALUATION_PROTOCOL.md#budget-and-native-scoring)
for the exact contract identity.

## Prepare the environment

Use native source revision `5e3d6f84e85343e34e9bca8d157f0d7813231185`,
Python 3.10, Isaac Sim 4.5 and MuJoCo 3.3.6. Provision the native source,
controller weights, robot assets, released evaluation metadata and HSSD scenes
under their licenses. Installing RSI does not supply those dependencies.

[environment/upstream.json](environment/upstream.json) records required runtime,
source-patch, controller and asset identities. Set explicit absolute
`simple_root` and `eval_root` paths. Optional `python_executable` selects the
native interpreter; its default is `<simple_root>/.venv/bin/python`.
Optional `cuda_root` selects a CUDA toolkit with `targets/x86_64-linux/include`
and `lib`; without it, existing `CUDA_HOME`, `CPATH` and `LD_LIBRARY_PATH`
environment settings are preserved. No particular Conda prefix is required.

Native source verification binds 596 Python files by repository-relative path,
size and SHA-256, plus the pinned Git revision and Python patch bytes. Moving an
identical installation does not change that source identity. Repaired HSSD
layers retain their byte hashes; the repair manifest's recorded host path does
not dictate the new installation root. This does not make the runtime and all
assets relocatable automatically: interpreter links, external libraries and
asset references still need valid deployment paths. A complete asset bootstrap
is not provided.

SIMPLE can create controller contexts on multiple visible GPUs. Check actual
GPU capacity and process visibility; renderer selection alone is not isolation.
Check reset and observation readiness with the shared
[readiness probe](../SERVER_PROTOCOL.md#readiness-probe) against a dedicated
`example` launch.

## Launch and connect

Copy [server.example.json](server.example.json) to an operator-owned path. Set
runtime/asset roots, GPU, `evaluation_mode` and one `task_names` entry.
Set the evaluator-only `RSI_SIM_SERVER_TOKEN` following the
[shared service protocol](../SERVER_PROTOCOL.md), then start a new server:

```sh
python -B -m benchmarks.simBenchmarks.SIMPLE.server \
  --parameters /absolute/simple-server.json \
  --seed 20260907 --port 8765 \
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
- `environment/`: private native worker and upstream runtime/source pins.
