# BEHAVIOR 2026 benchmark server

A bounded debugging service for BEHAVIOR-1K v3.9.2. The catalog supports the
historical `turning_on_radio` case and six selected tasks: `picking_up_trash`,
`clean_up_your_desk`, `store_honey`, `cook_a_brisket`, `putting_shoes_on_rack`, and
`hanging_pictures`. Each task currently
selects public index 0 (native instance 301), not a full challenge panel.
**The historical radio smoke check does not validate the four-task extension;
native readiness and model results must be reported separately. The Task 22 and
Task 34 catalog entries likewise do not establish native or model validation.**

- [Evaluation protocol](EVALUATION_PROTOCOL.md): schedule, sensors, actions and scoring.
- [Native contract](environment/NATIVE_CONTRACT.md): source evidence and acceptance gates.
- [Preparation](environment/README.md): licensed assets and runtime prerequisites.

`server.py` is the only public entrypoint. `bench_server/` owns adapter, fixed
protocol and private worker communication; `environment/` owns native runtime
and readiness. Shared HTTP transport remains in `benchkit/sim_server`. Agent
policy and result reports belong in `AgentPolicies/<agent>/`. Historical
`tasks.jsonl` is a **2025-only** inventory, not this service's schedule.

## Prepare without starting a simulator

Use a dedicated persistent Python 3.11 / Isaac Sim 5.1 environment and exact source
`b1979916ec1549b10a4e65e630bc6504a9af1b00`. Obtain the separate dataset license
before downloading restricted assets. Install the native evaluator dependencies;
no model policy server or training weights are needed. Paths are operator inputs.

Run the file-only capture with the **native worker interpreter**, with this
repository and the source's `OmniGibson`, `bddl3`, `joylo` on PYTHONPATH:

```sh
python -B -m benchmarks.simBenchmarks.Behavior.environment.deployment \
  --source-root /absolute/behavior-v3.9.2 \
  --data-root /absolute/behavior-assets \
  --receipts /absolute/extraction-receipts.json \
  --task picking_up_trash \
  --output /absolute/new-behavior-deployment.json
```

The receipts JSON maps `behavior-1k-assets`, `omnigibson-robot-assets`, and
`2026-challenge-task-instances` to extraction receipt paths. Each receipt binds
`archive_sha256`, `source_commit`, and absolute extraction `target`. This establishes
recorded archive/extraction provenance, **not every live asset byte**. Selected
robot/task files, tracked native package sources, runtime versions, interpreter
and module origins are rechecked before initialization. Stale/untracked source
bytecode is rejected. Capture never imports OmniGibson or resets a scene.
Use a separate matching capture for each selected task: the six selected tasks use
deployment v2 with an explicit task binding and that task's instance hash.
This deployment schema identifies native source/runtime/assets, not the service
protocol version or control cap; it remains v2 for the corrected v3 service.
Omitting `--task` keeps the historical radio v1 capture; it cannot authorize
another task.

## Launch

Copy [server.example.json](server.example.json); replace all paths and the
all-zero manifest digest, and select a GPU. A lightweight environment runs the
service; `worker_python` chooses the separate native runtime.
For a new task, add `"task": "picking_up_trash"` (or another supported name) to
the parameters and reference its matching deployment manifest and digest.
Omitting `task` retains the radio default. The task is fixed before a case claim;
the model cannot select or reset instances.

```sh
python -B -m benchmarks.simBenchmarks.Behavior.server \
  --parameters /absolute/behavior-server.json --seed 20260922 --episodes 1 \
  --port 8765 --output-dir /absolute/new-run/server
```

Provide `RSI_SIM_SERVER_TOKEN` through the environment as described in the
[shared protocol](../SERVER_PROTOCOL.md). Startup/describe do not start SIM.
Resetting a claimed case starts one isolated native worker; native shutdown
cannot terminate the HTTP process. Use a matching trusted service client.

The actor supplies 23-value direct actions. The six selected tasks use protocol v3:
the policy chooses how many sequential controls to execute before reasoning
again; one HTTP action still means one native control. Historical radio v1
retains prefix 1. See the [cadence guidance](EVALUATION_PROTOCOL.md) for the
distinction between decisions, controls and physics steps. Optional motion guards
are policy-owned. There is no expert, planner, oracle or automatic retry. Preserve
initialization errors and uncertain execution. Cache is excluded from transfer;
logs, controls, private outcome, three videos and cleanup receipts are retained.
A two-control diagnostic is not a failed full episode or an SR measurement.
Use the service-declared effective control cap, not the native timeout parameter,
in the trusted driver's `--max-steps`: for example, trash uses 7902 controls with
the unchanged native timeout parameter 7901. See the
[timeout ordering explanation](EVALUATION_PROTOCOL.md#fixed-selected-schedule-and-budgets).
The correction is versioned separately from frozen v2 interrupted runs; offline
tests alone do not establish a completed v3 native evaluation.

## Verified scope

On 2026-09-23, the fixed public instance 0 (native 301) completed initialization,
two public-state-derived hold controls and clean shutdown through this HTTP
service. Each control advanced four physics ticks (eight total). Three 224×224
RGB cameras and the 61-value robot state were returned; three videos were
retained. There were zero model calls. The diagnostic stopped deliberately after
two controls, with `native_episode_complete: false`; its Q=0 is not a model
failure or an SR estimate. No other task, full horizon or official RGB-D track
was validated by this check.

Tested service revision: `bb3c7e99053e669f7ca83a07c94fa9ef337e12ef`.
Closed diagnostic report SHA-256:
`3aeb3ad472d8f3d124c600d295a2ebd2a43d934900eecf0393cece821c7ab36a`.
Raw no-model evidence remains in operator artifact storage, not participant
model results. Every deployment still needs its own readiness check; a passing
record is not proof that another host has the same assets, drivers or runtime.
