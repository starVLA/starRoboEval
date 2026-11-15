# LIBERO

LIBERO is a language-conditioned robot-manipulation benchmark with task suites
covering spatial relationships, object identity, goals and task combinations.
This directory exposes its native tasks, released initial states, observations,
actions and success checks through an independent benchmark service.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): selection, initialization, budgets and scoring.
- [Task catalog](bench_server/protocol/libero_catalog.json): native ordering, instructions and reset counts.
- [Source inventory](bench_server/protocol/task_inventory.json): pinned task and evaluator references.
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

`evaluation_mode` selects the cases of one suite; one service runs one suite.
Cases run in task-major, state-minor order with seed `20260907` and task-order
index 0. An initial-state index selects a released `.pruned_init` entry, not a
random layout. Seeding and per-case environment construction differ from
OpenVLA's evaluator; see the
[differences](EVALUATION_PROTOCOL.md#differences-from-the-openvla-evaluation).

| Mode | Selection | Cases | Cap |
| --- | --- | --- | --- |
| `fast` (default) | every task × released states 0–4 | tasks × 5 (`libero_10`: 50) | suite horizon |
| `max` | every task × every released state | tasks × 50 (`libero_10`: 500) | suite horizon |
| `example` | task 0, state 0 | 1 | suite horizon |

```json
{
  "suite": "libero_spatial",
  "evaluation_mode": "fast",
  "proprioception": false,
  "render_gpu_device_id": 0
}
```

Distinct released state indices do not guarantee visibly different layouts.
The catalog contains 6,500 suite-task/state cells (130 × 50); report the suite
and mode explicitly.

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

The control cap is the reference horizon in the table above. Action grouping
and inference frequency belong to the agent; they do not extend the execution cap.

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

Check readiness through the service with the shared
[readiness probe](../SERVER_PROTOCOL.md#readiness-probe). Launch a dedicated
service (for example `evaluation_mode: example`) with its own output directory;
the probe claims and resets one episode, with no model calls or actions, and
reports the reset image shapes. Check source/controller metadata before capability
evaluation. Import success and a service description alone do not validate rendering.

## Start the benchmark service

Copy [server.example.json](server.example.json) to an operator-owned file, or use
the example above. The checked-in example omits `evaluation_mode`, so it runs the
`fast` cases of LIBERO-10 (10 tasks × states 0–4) with the **520-control reference
horizon**; `--episodes 1` below runs only the first case, task 0 at state 0. Action grouping and model-call
limits are agent settings, not part of this server configuration.

Set a strong `RSI_SIM_SERVER_TOKEN` privately for the server and trusted driver.
Launch with the native environment and installation variables above:

```sh
python -B -m benchmarks.simBenchmarks.LIBERO.server \
  --parameters /absolute/path/to/libero-server.json \
  --seed 20260907 --episodes 1 --port 8766 \
  --output-dir /absolute/path/to/results/libero/your-run/server
```

Omit `--episodes` to run every case of the selected mode. The flag limits a
schedule prefix, not tasks per suite.
The loopback service fixes its schedule at launch and constructs the native
environment only on reset. Connect through the [wire protocol](../SERVER_PROTOCOL.md);
see [agent integration](../../../docs/agent-methods.md) for participant drivers.

## Directory responsibilities and results

`server.py` is the public launcher. `bench_server/adapter.py` implements the
contract and native score bridge; `bench_server/protocol/` holds the catalog and
task inventory. `environment/` holds installation and configuration tools. Deployment
paths, GPU selection and credentials belong to operator configuration.

Keep method implementations under `AgentPolicies/<agent>/` and generated reports
and evidence under `AgentPolicies/<agent>/results/libero/`. Report the selected suite/task/state
denominator, protocol, outcomes, counters and errors, retaining every attempt.
See [recording](../../../docs/recording.md) for optional histories and server-side
videos, and [evaluation](../../../docs/evaluation.md) for closed-result tools.
