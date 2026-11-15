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

`evaluation_mode` selects the schedule. In `fast`, trial `k` of every task uses
seed launch seed + `k`; `max` requires launch seed 4042, its fixed goal-pool seed.

### Evaluation modes

| Mode | Selection | Episodes | Cap |
| --- | --- | ---: | --- |
| `fast` (default) | All 50 tasks × 5 trials, catalog order | 250 | 499 controls |
| `max` | All 50 tasks × 50 native MT50 goals from `metaworld.MT50(seed=4042)`, each once | 2500 | 499 controls |
| `example` | First `fast` episode: `assembly-v3`, trial 0 | 1 | 499 controls |

Each episode gets a freshly constructed native environment and is evaluated
from its first native reset. In `fast` the native wrapper picks that reset's
goal, so there is no goal index and distinct seeds do not guarantee distinct
visible layouts. `max` pins pool goal `GG` (00–49) with native `set_task`; its
episode IDs are `<task>-seed4042-goal<GG>` and metadata records the goal-pool
seed and goal index. Both schedules are task-major. Report task IDs, seeds,
goal indices where present and attempt counts.

The pinned package's own `metaworld.evaluation.evaluation` helper draws each
episode's goal with replacement from the same pool, so it may repeat some goals
and skip others. `max` follows the documented one-episode-per-goal procedure
instead; see the [protocol](EVALUATION_PROTOCOL.md#current-service-selection).

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
select the evaluation mode and image orientation. Set a strong `RSI_SIM_SERVER_TOKEN`
privately for the server and trusted driver. From the prepared environment and
repository root, choose a new output directory:

```sh
python -B -m benchmarks.simBenchmarks.MetaWorld.server \
  --parameters /absolute/path/to/metaworld-server.json \
  --seed 4042 --port 8765 \
  --output-dir /absolute/path/to/results/metaworld/your-run/server
```

Omit `--episodes` to run the complete mode schedule; `max` also needs
`--seed 4042`. A smaller `--episodes` value selects
a prefix in task-major order; it never repeats episodes. Startup and `describe` do not
construct native environments. The first reset verifies the native package and
generates the native MT50 task pool, so it is slower than later resets.

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
