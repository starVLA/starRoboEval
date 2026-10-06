# LIBERO evaluation protocol

[LiberoBenchmarkAdapter](bench_server/adapter.py), registered as `libero`, owns reset, native control and scoring. The stable service launcher is [server.py](server.py); models use the [service interface](../SERVER_PROTOCOL.md) and [shared policy contract](../POLICY_PROTOCOL.md), never a simulator handle or evaluator-private state. Moving the implementation under `bench_server/` preserves existing protocol identities and control semantics.

## Selection and fast/full modes

| Suite | Native task entries |
| --- | ---: |
| `libero_spatial` | 10 |
| `libero_object` | 10 |
| `libero_goal` | 10 |
| `libero_90` | 90 |
| `libero_10` | 10 |

These are 130 suite-task entries, not necessarily 130 disjoint task semantics. [libero_catalog.json](bench_server/protocol/libero_catalog.json) freezes native ordering and reference horizons. This is service-owned protocol data, not an asset path or model configuration; operator paths/GPU and predeclared task selection belong in the service launch configuration.

The independent [source inventory](bench_server/protocol/phase2_task_inventory.json)
retains pinned task hashes, reset counts and evaluator references. It is reference
evidence, not an execution manifest or a model result.

Fast mode evaluates each preselected task once. Direct adapter defaults select LIBERO-10 indices 0 and 1. The compatibility scope `development` permits indices 0–4 of that suite; `scope="task_coverage"` with explicit `suite` and `task_ids` supports complete suite ordering. The [selection plan](bench_server/protocol/plan.py) selects all 130 entries once. Keep every failure and environment error; do not automatically retry or search resets.

The fixed selection uses released initial-state index 0, task-order index 0 and seed 20260907. LIBERO-10 has 50 released `.pruned_init` states per task, or 500 task-state cells. This does not certify a 130 × 50 full schedule.

**Native-aligned full mode is not implemented.** It requires an explicitly validated per-suite task/reset/episode schedule and baseline-equivalent budgets. All tasks sampled once, or repeated attempts at failed tasks, are not native full evaluation.

## Environment and initialization

The source pin is [LIBERO](https://github.com/Lifelong-Robot-Learning/LIBERO) revision `8f1084e3132a39270c3a13ebe37270a43ece2a01`, with Robosuite 1.4.0 and MuJoCo 3.2.3. See [installation](README.md).

A fresh native environment is reset, the selected released initial state is installed, and ten fixed settling controls `[0,0,0,0,0,0,-1]` run before the first policy observation. Settling is recorded separately from policy controls. Hash the BDDL, reset-state file and selected state; keep these identities private from the policy.

## Observation and action

The default observation is native task language and two contiguous uint8 RGB images, `agentview` and `robot0_eye_in_hand`, each 256 × 256. Apply the retained camera transform `image[::-1, ::-1]`, with no additional crop/resize. An explicitly selected proprioception track adds seven arm and two gripper encoders and must be reported separately from RGB-only.

Do not expose object/world or end-effector ground truth, calibration, simulator handles, reset identity/seed, reward, success or BDDL predicates. Execution counters are accounting feedback only.

One action is a seven-dimensional command to Panda's 20 Hz `OSC_POSE` controller:

| Slice | Contract |
| --- | --- |
| `[0:3]` | World-frame translation delta; normalized [-1, 1] maps to ±0.05 m per axis |
| `[3:6]` | Axis-angle rotation delta; normalized [-1, 1] maps to ±0.5 rad per axis |
| `[6]` | Gripper: -1 open, +1 close, 0 retain target |

Validate shape, finiteness and bounds. Apply only the declared prefix of a returned action chunk, then deliver a fresh observation. The policy cannot reset/step the simulator, query the scorer or read private artifacts.

## Budgets and scoring

`budget_mode="horizon"` uses the catalog's per-suite reference horizon. `budget_mode="decisions"` requires matching adapter/runner `max_policy_calls=D` and `replan_interval=K`, with adapter control cap D × K. A common explicit track is D=200, K=5, runner cap 1000.

LIBERO-10's reference horizon 520 is from the retained StarVLA evaluator, not a universal official LIBERO limit. The native lifelong-evaluation configuration uses 600; a generic simulator horizon can be 1000. Record the reference source and actual cap rather than claiming equivalent evaluation conditions.

Native `BDDLBaseDomain.step` returns `done` from `_check_success()`. Stop at first native success and preserve termination/truncation separately. A visual impression or model self-report does not override the native scorer.

Record policy calls, action decisions, executed controls and initialization controls separately. Stop-only responses consume a policy call but no action decision; chunks may execute fewer than K controls. Record first-success control and its actual policy-call index, never inferred by division. A model's voluntary-stop persistence rule belongs to its profile and cannot postpone native termination, evaluator caps or errors.

## Evidence and reporting

Retain frozen source/model/protocol identities, BDDL/reset hashes, delivered observations, action chunks and executed prefixes, native outcomes, counters, errors and decodable videos. Results belong under the selected [model profile](../../../AgentPolicies/README.md).

Distinguish selected, completed, failed, errored and unattempted cases. CPU checks and zero-policy environment diagnostics are infrastructure evidence, not capability attempts or native-full parity.
