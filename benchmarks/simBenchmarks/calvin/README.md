# CALVIN

[CALVIN](https://github.com/mees/calvin) evaluates language-conditioned,
long-horizon tabletop manipulation with **34 language-conditioned manipulation
tasks** in **four environments, A–D**. Tasks include block rotation, pushing,
lifting, placement and stacking, plus drawer, sliding-door and light control.
The standard long-horizon evaluation chains five tasks in one continuous scene.

## Native tasks, environments and sequences

The [reference evaluator](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/calvin_agent/evaluation/evaluate_policy.py)
uses **1,000 five-task sequences**, not five independent layouts for every task.
Each sequence pairs an initial condition with a feasible ordered task chain.
The [sequence generator](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/calvin_agent/evaluation/multistep_sequences.py)
varies light states, drawer/slider states and block locations. It resets the
scene at sequence start, then preserves state as instructions change.

The released [environment splits](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/dataset/README.md)
are D→D, ABC→D and ABCD→D: the left side identifies training environments and
the right side evaluation environment D. A split is not a task suite or a
sequence ID. Report the actual scene/configuration and pretraining exposure;
this repository does not train the evaluated agent.

## Available service binding

The current service exposes one fixed five-task sequence and one initial
scene/robot state:

| Order | Subtask |
| --- | --- |
| 1 | `rotate_blue_block_right` |
| 2 | `move_slider_right` |
| 3 | `lift_red_block_slider` |
| 4 | `place_in_slider` |
| 5 | `turn_off_lightbulb` |

These are five successive instructions, not five independent resets. Live actor
inputs contain only the current instruction. Additional sequences and initial
states are not selectable; changing the run seed does not choose another layout. See the
[evaluation protocol](EVALUATION_PROTOCOL.md) for selection and scoring.

## Observations and 7-dimensional actions

| Interface | Current contract |
| --- | --- |
| Observation | Current language, `rgb_static` at 200×200 and `rgb_gripper` at 84×84 |
| Robot state | Not exposed |
| Action | `[dx, dy, dz, droll, dpitch, dyaw, gripper]`, seven finite values in `[-1,1]` |
| Translation | World-frame increments to the previous commanded target, 0.02 m per input unit |
| Rotation | Additive Euler xyz increments to the previous commanded target, 0.05 rad per input unit |
| Gripper | Positive opens; zero or negative closes |
| Timing | One action is one 30 Hz control, containing eight 240 Hz physics ticks |
| Scoring | Native subtask predicates; completion depth 0–5 and success at each depth |

There is no scene reset between subtasks. Each subtask allows at most 360
controls; the sequence ceiling is 1,800 controls. Earlier success advances to
the next subtask without using the remaining controls for the completed one.
Action grouping and inference frequency belong to the agent. Each control
returns an observation with the current public instruction. Handling a changed
instruction is the driver's responsibility; the service does not prescribe a
replanning strategy or require one model call per control.

## Current integration limits

- The service applies `[-1,1]` input bounds; the native controller itself does
  not clip the first six inputs to that range.
- Setup uses the official `calvin_debug_dataset` configuration. Equivalence
  with the D-validation dataset configuration has not been established.
- The native model evaluator resets model state per subtask. This service
  has one sequence-level session and no per-subtask policy-reset callback.

Object state, future instructions, reset vectors and scorer data remain private.
The service supplies neither a task plan nor a task-solving controller.

## Prepare and launch

Follow [environment preparation](environment/README.md) for the pinned
CALVIN/calvin_env/tacto sources, configuration asset and Python 3.10 runtime.
Use a dedicated native process and an EGL-capable device.

Copy [server.example.json](server.example.json) to an operator-owned path and
set `source_root` and `dataset_root`. Set the evaluator-only
`RSI_SIM_SERVER_TOKEN` following the [shared service protocol](../SERVER_PROTOCOL.md).
Launch from the repository using the prepared native Python environment:

```sh
python -B -m benchmarks.simBenchmarks.calvin.server \
  --parameters /absolute/calvin-server.json \
  --seed 20260907 --episodes 1 --port 8772 \
  --output-dir /absolute/new-run/server
```

Startup does not construct or reset the simulator. The trusted driver connects
through [the agent interface](../../../docs/agent-methods.md). The service
binds to loopback; use SSH forwarding for another node. The native EGL/PyBullet
path requires a dedicated process with simulator client 0.

## Results

Report the selected sequence, completed depth, success at depths 1–5, per-subtask
and total controls, and termination reason. A smaller external budget is not
the native 360-control subtask limit. Infrastructure errors remain separate from
task failures. Interaction histories and video retention are described in
[recording options](../../../docs/recording.md).

## Directory responsibilities

- `server.py`: public launch entrypoint.
- `bench_server/adapter.py`: RGB/current-language interface and native score bridge.
- `bench_server/protocol/`: sequence definitions and evaluator-private reset data.
- `environment/`: native runtime, dependency pins and environment preparation.
