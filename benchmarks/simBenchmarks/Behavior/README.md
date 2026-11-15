# BEHAVIOR-1K and the 2026 challenge

[BEHAVIOR](https://behavior.stanford.edu/) evaluates household activities that
combine navigation, manipulation and changes to object state. Native task
definitions determine completion and partial goal progress. BEHAVIOR-1K contains
**1,000 household activities**; the **2026 challenge selects 100 tasks** from
that larger benchmark.
[Benchmark overview](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/README.md),
[2026 challenge](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/docs/challenge/index.md).

## Native tasks and evaluation instances

The [100-task catalog](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/docs/challenge/task_data.json)
covers activities such as cleaning, cooking, organizing and object-state changes.
A task specifies the household goal; an instance supplies initial object states
and robot poses in a scene. A scene name, instance index and random seed are not
interchangeable layout identifiers.

The 2026 reporting schedule uses **public instance indices 0–9 once per task**:
100 tasks × 10 instances = 1,000 trials. Public indices 10–19 are additional
development instances, not part of that reporting panel. The challenge ranks
mean final goal-predicate completion (Q); binary success is a separate outcome.
See the [native evaluation rules](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/docs/challenge/evaluation.md).

## Available service bindings

This integration uses BEHAVIOR-1K v3.9.2 and R1Pro. It binds the following
**seven tasks**, one task per deployment, rather than the entire challenge panel:

| Task | Service task ID | Selected scene |
| --- | --- | --- |
| Task 0: Turning On Radio | `turning_on_radio` | `house_double_floor_lower` |
| Task 1: Picking Up Trash | `picking_up_trash` | `house_double_floor_lower` |
| Task 29: Clean Up Your Desk | `clean_up_your_desk` | `house_single_floor` |
| Task 83: Store Honey | `store_honey` | `Rs_int` |
| Task 51: Cook A Brisket | `cook_a_brisket` | `house_double_floor_lower` |
| Task 22: Putting Shoes On Rack | `putting_shoes_on_rack` | `house_double_floor_lower` |
| Task 34: Hanging Pictures | `hanging_pictures` | `house_double_floor_lower` |

`evaluation_mode` selects instances within the deployed task; `task` narrows
the mode to one task:

| Mode | Selection | Episodes per task | Cap |
| --- | --- | ---: | --- |
| `fast` (default) | Public indices 0–4 → native instances 301–305, rollout 0, native seed 0 | 5 | Native H + 1 |
| `max` | Public indices 0–9 → native instances 301–310, rollout 0, native seed 0 | 10 | Native H + 1 |
| `example` | Public index 0 → native instance 301 | 1 | Native H + 1 |

`max` matches the native per-task reporting schedule for the deployed task.
The 1,000-trial challenge panel is the union over deployments of all 100 tasks;
only the seven tasks above are bound, so it is not yet available.

Episode IDs have the form `<task>-public<index>-instance<native>-rollout0`.
Only instance 301 has a pinned state hash. Instances 302–310 come from the
hash-pinned instance archive; reset records their state hash as unpinned in
`loaded_contract.json`. Changing the run seed does not change
the layout.

See the [evaluation protocol](EVALUATION_PROTOCOL.md) for task-specific execution
budgets, sample selection and native scoring.

## Observations and 23-dimensional actions

| Interface | Current contract |
| --- | --- |
| Language | Selected task instruction; no live goal predicates or solving plan |
| RGB | Head, left-wrist and right-wrist views, each 224×224; native alpha is removed |
| Robot state | 61 measured proprioceptive values: base velocity, joints, finger state and robot-relative end-effector poses |
| Action | 3 body-frame base velocity inputs + 4 absolute torso joints + 7 left-arm joints + left gripper + 7 right-arm joints + right gripper |
| Units | Base inputs use native normalized scaling; torso/arm targets are radians; grippers use −1 closed / +1 open |
| Control timing | One action is one 30 Hz control, normally four 120 Hz physics ticks |
| Success | Native `env.task.success` |
| Partial score | Native final `q_score`, separate from binary success |

The service uses native `DefaultWrapper` RGB/proprioception. The challenge
`RGBDFullResWrapper` instead exposes higher-resolution RGB and metric depth;
results using these sensor configurations should not be treated as identical.

Native controllers, `assisted` grasping, initialization and termination are
preserved. No object-target action or task planner is added. Object truth, reset
metadata and intermediate scores stay on the evaluator side. Exact action/state
ordering, units and scaling are in the [native contract](environment/NATIVE_CONTRACT.md).

Agents choose their action grouping and decision cadence. Inference calls,
controls and physics ticks remain separate counters. See
[decisions and control execution](EVALUATION_PROTOCOL.md#decisions-and-control-execution).

## Prepare and launch

Follow [environment preparation](environment/README.md) for the native source,
Python/Isaac Sim runtime, licensed assets and deployment manifest. Installing
this repository does not provide those dependencies or accept their licenses.

Copy [server.example.json](server.example.json) to an operator-owned location.
Set the native interpreter, task-bound deployment manifest and its digest, GPU
and worker timeout. Add `"task": "picking_up_trash"`, or another supported task
ID; omitting `task` selects radio. Set `evaluation_mode` as above. Set the evaluator-only
`RSI_SIM_SERVER_TOKEN` as described in the [shared service protocol](../SERVER_PROTOCOL.md):

```sh
python -B -m benchmarks.simBenchmarks.Behavior.server \
  --parameters /absolute/behavior-server.json \
  --seed 20260922 --episode-id turning_on_radio-public0-instance301-rollout0 --port 8765 \
  --output-dir /absolute/new-run/server
```

Each process claims one episode; `--list-episodes` prints the schedule.
Startup fixes the schedule without initializing the simulator. Reset starts the
private native worker. The service binds to loopback; use SSH forwarding for a
remote driver. Keep credentials and administrative operations out of actor inputs.
See [agent integration](../../../docs/agent-methods.md).

## Scoring and results

Report the selected task and instance, native success, final Q, actual controls
and termination reason. Q measures partial goal progress, not success rate.
Distinguish a native timeout from a smaller external limit or infrastructure
error, and report the selected number of task/instance pairs when aggregating.

Optional interactions and video retention use the
[shared recording settings](../../../docs/recording.md).

## Directory responsibilities

- `server.py`: public launch entrypoint and deployment settings.
- `bench_server/`: public interface, task definitions and private worker communication.
- `environment/`: native loading, source/runtime/asset configuration and setup.
- `EVALUATION_PROTOCOL.md`: selection, execution and scoring rules.
