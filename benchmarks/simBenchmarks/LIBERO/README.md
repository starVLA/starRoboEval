# LIBERO

LIBERO is a language-conditioned robot-manipulation benchmark with task suites
covering spatial relationships, object identity, goals and task combinations.
This directory exposes its native tasks, released initial states, observations,
actions and success checks through an independent benchmark service.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): selection, initialization, budgets and scoring.
- [Task catalog](bench_server/protocol/libero_catalog.json): native ordering, instructions and reset counts.
- [Source inventory](bench_server/protocol/phase2_task_inventory.json): pinned task and evaluator references.
- [Service configuration](server.example.json) and [shared interface](../SERVER_PROTOCOL.md).

## Benchmark tasks and initial states

The [official benchmark](https://libero-project.github.io/datasets.html) defines
LIBERO-Spatial, LIBERO-Object and LIBERO-Goal with 10 tasks each, plus
LIBERO-100 with 100 tasks split into LIBERO-90 and LIBERO-10. These test spatial,
object and goal generalization and the transfer/composition of manipulation
skills. The split produces the five named inventories below; it is not five
unrelated benchmark definitions. Each task has 50 released initial states.

| Suite | Task entries | Released states per task | Retained reference horizon |
| --- | ---: | ---: | ---: |
| `libero_spatial` | 10 | 50 | 220 controls |
| `libero_object` | 10 | 50 | 280 controls |
| `libero_goal` | 10 | 50 | 300 controls |
| `libero_90` | 90 | 50 | 400 controls |
| `libero_10` (LIBERO-Long) | 10 | 50 | 520 controls |

The catalog contains 130 suite-task entries; these are not necessarily 130
disjoint task semantics. The horizons above are retained evaluator reference
conditions, **not universal official LIBERO limits**. For example, the native
lifelong-evaluation configuration uses 600 for LIBERO-10. Report the selected
budget and its source rather than assuming equivalent conditions.

## Select cases through this service

Select a suite and increasing `task_ids` with `scope: "task_coverage"`.
`initial_state_indices` selects released `.pruned_init` entries; it does not
select arbitrary random layouts. The adapter checks each index against every
selected task. Omitting this list selects state 0; an explicit list defines a
separately versioned panel in task-major, state-minor order. The service requires
seed `20260907` and task-order index 0.

For example, this operator configuration fixes 25 task/state cells:

```json
{
  "suite": "libero_spatial",
  "scope": "task_coverage",
  "task_ids": [0, 1, 2, 3, 4],
  "initial_state_indices": [0, 1, 2, 3, 4],
  "proprioception": false,
  "render_gpu_device_id": 0,
  "budget_mode": "horizon"
}
```

Distinct released state indices do not guarantee visibly different layouts.
The catalog contains 6,500 suite-task/state cells (130 × 50); report the selected
suite, tasks and states explicitly. The example is a selection example, not
the benchmark's prescribed number of tasks or trials.

## Observations, actions and scoring

The RGB track provides the native task instruction and two 256 × 256 images:
`agentview` and `robot0_eye_in_hand`. Both use the fixed 180° camera transform,
with no additional crop or resize. An explicitly selected RGB+qpos track adds
seven arm and two gripper encoders; [the protocol](EVALUATION_PROTOCOL.md#observation-and-action)
lists their order and radians/metres units. Object truth, reset identity, BDDL predicates,
reward and success remain private to the evaluator.

One control is a seven-value `OSC_POSE` command in `[-1, 1]` at 20 Hz:
world translation deltas (±0.05 m per axis), world axis-angle deltas
(±0.5 rad per axis), and gripper `-1` open / `+1` close / `0` retain target.
Ten fixed settling controls precede the first observation and are recorded
separately from agent-selected controls.

Native `BDDLBaseDomain.step` returns success from `_check_success()`. The service
stops at the first native success, or at the selected cap without success.
A model's completion claim or a video's appearance does not change that result.
Record inference calls, action decisions, controls and settling separately.

The `horizon` track uses the table above. The explicit `decisions` track uses
`max_policy_calls × replan_interval` as an alternative control cap and changes
protocol identity. In horizon mode, action grouping and inference frequency
belong to the agent; they do not extend the execution cap.

## Install and check the environment

Use a dedicated Python 3.10 environment. The pinned checkout contains BDDL tasks,
meshes and released initial states; model weights and demonstration-action
datasets are not needed. From the RSI repository root:

```sh
conda create -n starvla-rsi-libero python=3.10 pip
conda activate starvla-rsi-libero
export LIBERO_SOURCE=/absolute/path/to/native/LIBERO
git clone https://github.com/Lifelong-Robot-Learning/LIBERO "$LIBERO_SOURCE"
git -C "$LIBERO_SOURCE" checkout 8f1084e3132a39270c3a13ebe37270a43ece2a01
python -m pip install --no-compile -r benchmarks/simBenchmarks/LIBERO/environment/runtime-requirements.txt
python -m pip install --no-compile torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install --no-compile --no-deps -e "$LIBERO_SOURCE"
python -m pip install --no-compile --no-deps -e .
python benchmarks/simBenchmarks/LIBERO/environment/configure.py \
  --upstream "$LIBERO_SOURCE" --config-dir "$CONDA_PREFIX/libero-config"
export LIBERO_CONFIG_PATH="$CONDA_PREFIX/libero-config"
export PYTHONPATH="$LIBERO_SOURCE${PYTHONPATH:+:$PYTHONPATH}"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export MUJOCO_EGL_DEVICE_ID=0
```

The explicit upstream `PYTHONPATH` accommodates LIBERO's namespace-package
metadata. CPU Torch deserializes initial states. Runtime pins include Robosuite
1.4.0, MuJoCo 3.2.3 and NumPy 1.24.4. Select an allocated EGL GPU and use the same
index in the server configuration.

The separate readiness diagnostic performs reset, settling, rendering and one
neutral control, with no model calls:

```sh
python benchmarks/simBenchmarks/LIBERO/environment/verify_environment.py \
  --render-gpu-device-id 0 --output-dir /absolute/path/to/new-libero-diagnostic
```

Inspect images/video and source/controller metadata before capability evaluation.
Import success and a service description alone do not validate rendering.

## Start the benchmark service

Copy [server.example.json](server.example.json) to an operator-owned file, or use
the panel example above. The checked-in example selects LIBERO-10 task 0 at
state 0 with a **200 × 5 = 1000-control decision track**; it does not use the
520-control reference horizon. Set `budget_mode: "horizon"` and omit decision
parameters to use that reference track.

Set a strong `RSI_SIM_SERVER_TOKEN` privately for the server and trusted driver.
Launch with the native environment and installation variables above:

```sh
python -B -m benchmarks.simBenchmarks.LIBERO.server \
  --parameters /absolute/path/to/libero-server.json \
  --seed 20260907 --episodes 1 --port 8766 \
  --output-dir /absolute/path/to/results/libero/your-run/server
```

For the 25-cell panel, omit `--episodes` or set it to 25, and select all 25 cells
in the trusted driver. The flag limits a schedule prefix, not tasks per suite.
The loopback service fixes its schedule at launch and constructs the native
environment only on reset. Connect through the [wire protocol](../SERVER_PROTOCOL.md);
see [agent integration](../../../docs/agent-methods.md) for participant drivers.

## Directory responsibilities and results

`server.py` is the public launcher. `bench_server/adapter.py` implements the
contract and native score bridge; `bench_server/protocol/` holds the catalog and
selection plan. `environment/` holds installation and readiness tools. Deployment
paths, GPU selection and credentials belong to operator configuration.

Keep method implementations under `AgentPolicies/<agent>/` and generated reports
and evidence under `AgentPolicies/<agent>/results/libero/`. Report the selected suite/task/state
denominator, protocol, outcomes, counters and errors, retaining every attempt.
See [recording](../../../docs/recording.md) for optional histories and server-side
videos, and [evaluation](../../../docs/evaluation.md) for closed-result tools.
