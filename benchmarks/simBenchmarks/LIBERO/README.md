# LIBERO

This integration follows the [RoboDojo-derived service conventions](../SERVICE_CONVENTIONS.md).
LIBERO's task/init-state selection, native OSC actions and success rule remain distinct.

The `libero` adapter evaluates sensor-driven robot policies across five LIBERO suites (130 suite-task entries). This directory owns native environment integration, task selection and [the evaluation protocol](EVALUATION_PROTOCOL.md); model implementations and results belong under [AgentPolicies](../../../AgentPolicies/README.md).

## Directory responsibilities

```text
LIBERO/
├── server.py                      # stable public service launcher
├── server.example.json            # operator configuration template
├── bench_server/
│   ├── adapter.py                 # public contract, private native session/scoring
│   └── protocol/                  # task catalog, selection plan and source inventory
└── environment/                   # installation pins and readiness tools
```

The catalog is benchmark protocol data, not an environment deployment file or
model configuration. Copy the server configuration outside the source tree to
select a fixed suite/task subset, observation track, budget and GPU; configure
source and asset locations through `LIBERO_SOURCE` and `LIBERO_CONFIG_PATH`.
The canonical adapter lives in `bench_server/adapter.py`.
The active service reads `bench_server/protocol/libero_catalog.json` and fixes
its schedule at launch. The independent pinned native source inventory lives
beside it in [phase2_task_inventory.json](bench_server/protocol/phase2_task_inventory.json).
It records task identities and evaluator references, not an execution schedule
or capability results. Historical first-two and first-five selection manifests
remain recoverable from Git history.
Historical anonymous attempt evidence lives in its existing
[model result record](../../../AgentPolicies/anonymous_code_agent/results/libero/TASK_CHECKLIST.md);
its model/provider identity remains unverified.

This structure does not convert LIBERO into RoboDojo's EEF16 protocol. LIBERO
still accepts normalized seven-dimensional OSC delta actions, with its own RGB
or explicit RGB+joint-position track. A model must declare compatibility with
that contract; renaming a directory cannot make a Dojo-only policy compatible.

## Install the environment

Use a dedicated Python 3.10 environment. The pinned source includes BDDL tasks, meshes and released initial states; no VLA checkpoint or demonstration-action dataset is needed. Run from the RSI repository root, replacing the source path:

```sh
conda create -n starvla-rsi-libero python=3.10 pip
conda activate starvla-rsi-libero
export LIBERO_SOURCE=/path/to/LIBERO
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

The explicit upstream `PYTHONPATH` accommodates LIBERO's namespace-package metadata. CPU Torch deserializes released initial states; it does not run a robot policy. Runtime pins include Robosuite 1.4.0, MuJoCo 3.2.3 and NumPy 1.24.4. Select an available EGL GPU and use the same index in the adapter.

## Verify and evaluate

This diagnostic performs reset, ten settling controls, rendering and one neutral control, with zero policy calls. Use a new output directory and verify source/controller metadata and complete image/video decoding.

```sh
python benchmarks/simBenchmarks/LIBERO/environment/verify_environment.py \
  --render-gpu-device-id 0 --output-dir /path/to/new-libero-diagnostic
```

## Run as an independent SIM server

The server owns native reset, controls and scoring. The evaluator owns the SIM
client; the policy receives only allowed observations and never its endpoint,
token or private artifacts. Follow the [shared service protocol](../SERVER_PROTOCOL.md)
for evaluator-only token setup and SSH forwarding between nodes. The service
listens only on loopback. Native-free launcher checks do not certify a working
renderer or a native service-mode evaluation.

Copy [server.example.json](server.example.json) to an operator-owned configuration
and select the tasks, observation track and GPU before launch. The example fixes
LIBERO-10 task 0, released reset state 0 and a decision track of 200 calls,
prefix 5, control cap 1000. It does not use the retained 520-control reference
budget and is not a full native evaluation. Use the dedicated native Python and
the `LIBERO_CONFIG_PATH`, `PYTHONPATH` and EGL settings from installation:

```sh
python -B -m benchmarks.simBenchmarks.LIBERO.server \
  --parameters /absolute/path/to/libero-server.json \
  --seed 20260907 --episodes 1 --port 8766 \
  --output-dir AgentPolicies/anonymous_code_agent/results/libero/raw/libero_10-task-0-basket-groceries/server
```

In a separate evaluator process/environment with NumPy installed and the same
evaluator-only `RSI_SIM_SERVER_TOKEN`, connect an unused opaque
[mailbox actor endpoint](../../../AgentPolicies/anonymous_code_agent/README.md):

```sh
python -B -m benchkit run \
  --benchmark libero --sim-server http://127.0.0.1:8766 \
  --model-profile anonymous_code_agent \
  --policy-args '{"directory":"/absolute/opaque-mailbox","timeout_s":900,"max_chunk_length":5}' \
  --seed 20260907 --episodes 1 --budget-mode decisions \
  --max-policy-calls 200 --replan-interval 5 --max-steps 1000 \
  --output-dir AgentPolicies/anonymous_code_agent/results/libero/raw/libero_10-task-0-basket-groceries/evaluator
```

Use new result directories and a stable source snapshot, verified before and
after execution. Do not pass `--benchmark-args` to the remote runner. The server
freezes the schedule at launch but does not check native packages/assets until
the one permitted reset; startup and `describe` are not readiness results.
Native source, controller and reset-file checks remain in the adapter, and a
failed reset retains its attempt. No automatic reset/action retry is enabled.
`campaign prepare/run-case` still uses its existing execution path, not this
remote service workflow. Keep server/client evidence and media under the model
result namespace; legacy artifact auditors do not yet validate this layout.

Fast mode means one attempt per preselected task, preserving failures and errors without automatic retry. The direct adapter defaults to LIBERO-10 tasks 0 and 1; the [selection plan](bench_server/protocol/plan.py) selects all 130 suite-task entries once. Neither is full native reset-state coverage. See [the evaluation workflow](../../../docs/evaluation.md), [the catalog](bench_server/protocol/libero_catalog.json) and [protocol limitations](EVALUATION_PROTOCOL.md).
