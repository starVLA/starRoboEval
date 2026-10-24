# MetaWorld MT50

MetaWorld MT50 is a collection of 50 robot-manipulation task families, including
reaching, grasping, placing and interacting with articulated objects. This
integration exposes the pinned native tasks through a benchmark service, with
a public RGB/action contract and native success checks independent of any agent.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): selection, native controls, horizons and scoring.
- [Task catalog](bench_server/protocol/task_catalog.json): all 50 canonical names and instructions.
- [Environment setup](environment/README.md): native package pins and graphics requirements.
- [Service configuration](server.example.json) and [shared wire protocol](../SERVER_PROTOCOL.md).

## Benchmark tasks and evaluation conditions

MetaWorld provides [multi-task and meta-learning suites](https://metaworld.farama.org/introduction/basic_usage/).
MT1, MT10 and MT50 cover 1, 10 and 50 task families; ML1, ML10 and ML45 evaluate
adaptation to held-out goals or tasks. This directory integrates MT50, not the
meta-learning adaptation procedure.

The [native MT50 evaluation](https://metaworld.farama.org/evaluation/evaluation/)
uses 50 goal/reset configurations per task and one episode per configuration.
It reports success if the native success flag becomes true during an episode,
then averages over tasks and goals. Thus the reference matrix is 50 task
families × 50 configurations, with a 500-control episode horizon. A goal/reset
configuration is not an additional task family.

## Select tasks through this service

Select a fixed list of `task_names`. Each task receives one seeded episode,
in declared order. The example selects `reach-v3`;
the same service accepts other catalog tasks or all 50.

The adapter constructs a fresh seeded MT50 for each selected task and evaluates
its first native reset. It does not iterate the native 50-configuration schedule.
There is no exposed layout/reset index
selector: the seed initializes native randomization, and distinct seeds do not
guarantee distinct visible layouts. Report task IDs, seeds and attempt counts.

The catalog's easy/medium/hard/very_hard labels come from a retained evaluator;
they are not an official MetaWorld difficulty taxonomy. Use canonical task
names and an explicit aggregation rule when reporting a selected subset.

## Observations, actions and scoring

| Item | Current contract |
| --- | --- |
| Native runtime | `metaworld==3.1.1`, MuJoCo 3.3.0 |
| Public observation | Language instruction and 480 × 480 `corner2` RGB |
| Default image orientation | Full-frame 180° rotation, without crop or resize |
| Action | Four values `[delta_x, delta_y, delta_z, gripper_effort]` in `[-1,1]` |
| Position control | World XYZ target delta, 0.01 m per unit |
| Gripper | Positive closes; negative opens |
| Native control frequency | 80 Hz, five physics ticks per control |
| Native total horizon | 500 controls, including one setup no-op |
| Agent-selected control cap | 499 controls |

No object/goal state, native 39-D state, private score or camera calibration is
provided to the agent. The action has no rotation component; native low-level
control fixes the end-effector orientation.

An explicitly selected `image_orientation: "native"` uses the unrotated image
and a different protocol identity from the default rotated view. Record the
identity returned by `describe`; compare only matching observation conditions.

Success comes from `info["success"] == 1` returned by the native step. The
service stops at first success or another native end; exhausting the horizon
without success is a completed failure. A visual impression or an agent's
completion claim cannot award native success.

One initialization no-op consumes the first of the native 500 controls, leaving
499 for the agent. Record setup controls, agent controls, action decisions and
inference calls separately. Action grouping and inference frequency belong to
the agent method and cannot enlarge that cap. Compare results only when their
execution budgets and observation conditions match.

## Install and start the service

Follow [environment setup](environment/README.md) in a dedicated native Python
environment, including package-content verification and EGL configuration.
Installation/import checks alone do not prove rendering. Before capability
evaluation, use a separately labelled infrastructure diagnostic through the
service to check reset, valid RGB, control and cleanup.

Copy [server.example.json](server.example.json) to an operator-owned file and
select task names and image orientation. Set a strong `RSI_SIM_SERVER_TOKEN`
privately for the server and trusted driver. From the prepared environment and
repository root, choose a new output directory:

```sh
python -B -m benchmarks.simBenchmarks.MetaWorld.server \
  --parameters /absolute/path/to/metaworld-server.json \
  --seed 4042 --episodes 1 --port 8765 \
  --output-dir /absolute/path/to/results/metaworld/your-run/server
```

Omit `--episodes` to select the complete configured task list. A smaller value
selects a prefix; it never repeats tasks. Startup and `describe` do not
construct native environments. The first reset initializes MT50, including
native task-pool generation, so startup can be slower than a single task reset.

The service binds loopback; use SSH forwarding for a driver on another node.
Connect through the [wire protocol](../SERVER_PROTOCOL.md) and
[agent integration contract](../../../docs/agent-methods.md). A driver that
counts model-selected controls uses the advertised cap **499**, not 500.
There is no required provider, prompt, inference allowance or fixed controls-per-decision
setting in this launch path.

## Directory responsibilities and results

`server.py` launches the service. `bench_server/adapter.py` owns observations,
actions and the native score bridge; `bench_server/protocol/task_catalog.json`
holds task definitions. `environment/` holds installation and package pins.
Operator configuration supplies deployment paths and selected cases.

Keep method implementations under `AgentPolicies/<agent>/` and generated reports
and evidence under `AgentPolicies/<agent>/results/metaworld/`. Report task/reset coverage, the
protocol, native outcomes, typed errors and separate counters. Native video
uses 80 fps: it represents control timing, not inference wall time.
See [recording](../../../docs/recording.md) for optional histories and server-side
media retention, and [evaluation](../../../docs/evaluation.md) for reporting.
