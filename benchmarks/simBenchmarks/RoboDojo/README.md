# RoboDojo

[RoboDojo](https://robodojo-benchmark.com/) evaluates generalist robot
manipulation in simulation and on real robots. Its core benchmark comprises
**42 simulation tasks and 18 real-world tasks**. Simulation uses Isaac Sim and
includes rigid, articulated and deformable objects; task-specific native rules
determine completion and partial progress. See the
[official repository](https://github.com/RoboDojo-Benchmark/RoboDojo).

This directory documents the simulation benchmark and its Bench Server
integration. The native benchmark's scope is larger than the tasks currently
exposed by this repository's service.

## Native tasks and evaluation cases

The [official simulation catalog](https://robodojo-benchmark.com/doc/sim-tasks/)
organizes the 42 core tasks into five capability groups:

| Capability | Tasks | Examples |
| --- | ---: | --- |
| Generalization | 12 | Stack Bowls, Fold Clothes, Hang Mugs |
| Memory | 6 | Cover Blocks, Imitate Sorting Sequence |
| Precision | 8 | Insert Key, Fasten Screws, Build Tower |
| Long-Horizon | 8 | Classify Objects, Organize Table, Make Kong |
| Open | 8 | Solve Equation, Classify Objects By Language |

The catalog also has a separate DLC page, making 43 pages; its
[DLC entry](https://robodojo-benchmark.com/doc/sim-tasks/dlc/) is labelled for
training, not an additional core evaluation task. Standard and random-layout
versions of a Generalization task share its task objective and catalog page.

A native evaluation case identifies a task/configuration, robot embodiment,
evaluation-seed directory and stored layout. A task name is not a layout, and a
seed does not mean “generate any new scene.” In the pinned native evaluator,
the seed selects an asset directory and layout IDs enumerate its stored JSON
reset descriptions. The configured sample counts are:

| Native task configuration | Configured episodes |
| --- | ---: |
| Each Generalization task's standard configuration | 25 |
| The corresponding `_random` configuration | 25 |
| Other core task configurations, including `classify_objects` | 50 |

These counts come from the native
[`_task.yml`](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/ee67a1468510da7624a089164402359f2afc72c8/task/RoboDojo/config/_task.yml),
not from a particular model's evaluation. Available asset files, requested
episodes and completed attempts are different counts. Control horizons and
scoring conditions are task-specific; do not apply one task's budget to all
42 tasks. See [evaluation rules](EVALUATION_PROTOCOL.md#native-benchmark-and-case-selection).

## Evaluation rules

Declare the tasks, variants, embodiment, asset/runtime versions and selected
cases before evaluation. Use native task scoring, keep partial score separate
from binary success, and report the selected and completed denominators plus
infrastructure errors. An agent's reasoning, memory and action grouping do not
change native robot timing or task budgets.

The Bench Server exposes declared sensors, robot state and action feedback.
Object truth, private layout/reset data, reward internals and simulator handles
are not agent inputs. The agent selects robot actions; the service does not
provide task-solving plans or grasp actions.

## Current Bench Server integration

The current service exposes **`classify_objects` with two fixed-base ARX X5
arms**. This is one implemented integration, not the size of RoboDojo. The task
requires category sorting into three baskets and both arms returning to their
starting end-effector poses. Other native tasks are not selectable yet.

Its asset binding contains 55 stored layouts. `evaluation_mode` selects a
fixed set, once per layout:

| `evaluation_mode` | Selected layouts | Cases | Step cap |
| --- | --- | ---: | --- |
| `fast` (default) | 0–4 | 5 | 1100 native controls |
| `max` | the first 50 reset-stable layouts of a stability manifest | 50 | 1100 native controls |
| `example` | 0 | 1 | 1100 native controls |

The 50-case selection matches this task's configured native episode count.
Like the native evaluator, `max` skips layouts whose reset is unstable, so it
can reach the spare layouts 50–54. It runs only with a complete reset-stability
manifest prepared offline, which has not yet been done; see the
[`max` protocol](EVALUATION_PROTOCOL.md#max-first-reset-stable-layouts).
`fast` and `example` layouts are not stability-screened. `task_id` names the deployed task and narrows within
the mode. Arbitrary subsets and `--episodes` truncation are not supported: the
launcher and service adapter refuse a schedule limit, and the gateway refuses
case files and limits. `--episode-id` is for gateway per-case services only.
The launch seed is fixed at 20260907 and native evaluation uses seed 0;
changing the launch seed is not a way to choose layouts. See the
[service task definition](bench_server/protocol/task_catalog.json) and
[integration limits](../SERVICE_SUPPORT.md).

### Robot interface

| Channel | Current service contract |
| --- | --- |
| Images | Head, left-wrist and right-wrist RGB, each 640 × 480 |
| Robot state | 28 values: measured arm joints and end-effector poses, plus last commanded gripper openings |
| Action | 16 values: a 3D position, quaternion and gripper opening for each arm |
| Position / rotation | Absolute link6 targets in the world frame, metres and unit `wxyz` quaternions |
| Gripper | Continuous opening in [0,1], 0 closed / 1 open |
| Control timing | 25 Hz; one action executes 10 physics ticks of 0.004 s |
| Task budget | 1100 native controls per case; action grouping is chosen by the agent |

This interface uses fixed robot-only numerical IK to convert end-effector
targets into native joint commands. It is not a universal action definition for
every RoboDojo embodiment. See the [action specification](EVALUATION_PROTOCOL.md#public-action),
[action rejection contract](ACTION_VALIDATION.md) and
[robot-control acknowledgements](ROBOT_FEEDBACK.md).

### Start the benchmark server

Follow [environment preparation](environment/README.md) for the pinned native
runtime, authorized assets and deployment manifest. Copy
[server.example.json](server.example.json) to an operator-owned path and set its
runtime manifest, digest, GPU and `evaluation_mode`; `max` also needs
`stability_manifest` and takes an optional `stability_manifest_sha256` pin (an
unpinned digest is recorded, a mismatched pin refuses). The sensor/action protocol is
fixed; it is not a runtime selector. `max` uses its own protocol ID,
`robodojo-ee67a14/classify-objects-reset-stable-layouts/rgb-proprio28-eef16/max/v1`.

Use a fresh output directory and an evaluator-only token:

```sh
export RSI_SIM_SERVER_TOKEN='replace-with-a-url-safe-secret-of-at-least-32-characters'
python -B -m benchmarks.simBenchmarks.RoboDojo.server \
  --parameters /absolute/robodojo-server.json \
  --seed 20260907 --port 8765 \
  --output-dir /absolute/new-run/server
```

Startup fixes the schedule without resetting the simulator. The service binds
to loopback; use SSH forwarding for a remote trusted driver. Connect through
the [agent integration contract](../../../docs/agent-methods.md) and
[shared wire protocol](../SERVER_PROTOCOL.md), using the same seed and complete
selected schedule. Invalid actions do not execute; uncertain controls are not
replayed. Failed cases and infrastructure errors remain in the result record.

Report [native score and success](EVALUATION_PROTOCOL.md#scoring) separately.
Interaction/media retention is optional; see
[recording settings](../../../docs/recording.md). Results and method-specific
configuration belong under `AgentPolicies/<profile>/`, not this directory.

## Directory responsibilities

- `server.py`: public service entrypoint.
- `bench_server/`: interface, native-worker communication and service task definitions.
- `bench_server/protocol/`: selected task/layout catalog and feedback schema; not simulator assets.
- `environment/`: native worker, robot-only conversion, runtime/asset pins and setup.
- `EVALUATION_PROTOCOL.md`: native evaluation concepts and the implemented service contract.
