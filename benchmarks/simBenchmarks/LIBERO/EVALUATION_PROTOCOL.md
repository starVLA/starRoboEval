# LIBERO evaluation protocol

LIBERO evaluates language-conditioned manipulation across spatial, object and
goal changes, with a separate 100-task collection for skill transfer and
composition. This protocol describes its task/reset organization and the
observation, action and scoring rules used by the benchmark service.

## Suites, tasks and initial states

The [official task collections](https://libero-project.github.io/datasets.html)
are Spatial, Object, Goal and LIBERO-100. LIBERO-100 is split into the
`libero_90` and `libero_10` inventories below. The 50 released states per task
specify resets, not 50 different task instructions.

| Suite | Native task entries | Released states per task | Task/state cells |
| --- | ---: | ---: | ---: |
| `libero_spatial` | 10 | 50 | 500 |
| `libero_object` | 10 | 50 | 500 |
| `libero_goal` | 10 | 50 | 500 |
| `libero_90` | 90 | 50 | 4,500 |
| `libero_10` | 10 | 50 | 500 |

These are 130 suite-task entries, not necessarily 130 disjoint task semantics. [libero_catalog.json](bench_server/protocol/libero_catalog.json) freezes native ordering and reference horizons. This is service-owned protocol data, not an asset path or model configuration; operator paths/GPU and predeclared task selection belong in the service launch configuration.

The independent [source inventory](bench_server/protocol/phase2_task_inventory.json)
retains pinned task hashes, reset counts and evaluator references. It is reference
evidence, not an execution manifest or a model result.

## Service selection and current constraints

[LiberoBenchmarkAdapter](bench_server/adapter.py), registered as `libero`, owns
reset, native control and scoring. Its public launcher is [server.py](server.py).
Use `scope="task_coverage"` with an explicit `suite` and increasing `task_ids`
to select tasks from that suite. Add `initial_state_indices` to select released
resets.

Without `initial_state_indices`, selection uses released initial-state index 0.
Task-order index 0 and seed 20260907 are fixed by this integration. The catalog
contains 6,500 suite-task/state cells (130 × 50); this inventory is not an
automatic execution schedule. The direct adapter's default `scope="development"`
selects LIBERO-10 task IDs 0 and 1, permits task IDs 0–4, and uses state 0 only.
Use `task_coverage` for the suite and explicit state selection described here.

### Explicit released-state panel

With `scope="task_coverage"`, the service additionally accepts
`initial_state_indices`, a nonempty, unique, increasing list of nonnegative
integers. Each selected index must exist in **every selected task's** catalog
entry. The service validates this before claims and rechecks the native state
count and selected index during reset. It installs that exact released tensor
and records the index and selected-state hash in evaluator-private provenance.
An initial-state index selects a released reset, not a new random seed or a
retry of the preceding episode. No guarantee of visually distinct layouts is
implied merely by selecting distinct indices.

An explicit state list is recorded in the service's protocol identity, including
when it contains only `[0]`. Record the returned identity and resolved schedule.
Observation/action semantics, controller, seed, settling and reference horizons
are unchanged by state selection. Cases are task-major, then state-minor, with
IDs such as `libero_spatial-task00-init04`. `--episodes` limits an episode prefix,
not the number of tasks; omit truncation to execute the complete selected panel.

For comparisons, specify suites, task IDs, state indices and budgets explicitly.
Evaluating more states changes reset coverage; adding a new seed is not a
substitute for selecting another released state.

## Environment and initialization

The source pin is [LIBERO](https://github.com/Lifelong-Robot-Learning/LIBERO) revision `8f1084e3132a39270c3a13ebe37270a43ece2a01`, with Robosuite 1.4.0 and MuJoCo 3.2.3. See [installation](README.md).

A fresh native environment is reset, the selected released initial state is installed, and ten fixed settling controls `[0,0,0,0,0,0,-1]` run before the first policy observation. Settling is recorded separately from policy controls. Hash the BDDL, reset-state file and selected state; keep these identities private from the policy.

## Observation and action

The default observation is native task language and two contiguous uint8 RGB images, `agentview` and `robot0_eye_in_hand`, each 256 × 256. Apply the retained camera transform `image[::-1, ::-1]`, with no additional crop/resize. An explicitly selected proprioception track adds seven arm and two gripper encoders and must be reported separately from RGB-only.

The nine-value state concatenates measured `robot0_joint_pos` and
`robot0_gripper_qpos`, not controller targets. Indices are zero-based; native
joint names below omit the robot/gripper instance prefixes:

| State indices | Native joint names in order | Unit |
| --- | --- | --- |
| 0–6 | `joint1`, `joint2`, `joint3`, `joint4`, `joint5`, `joint6`, `joint7` | radians |
| 7 | `finger_joint1` (left finger) | metres, signed sliding-joint position |
| 8 | `finger_joint2` (right finger) | metres, signed sliding-joint position |

The finger positions are separate coordinates, not a normalized open/close value
or a single aperture. Their native ranges are 0 to 0.04 m and −0.04 to 0 m,
respectively. Robosuite 1.4.0's
[Panda joint model](https://github.com/ARISE-Initiative/robosuite/blob/v1.4.0/robosuite/models/assets/robots/panda/robot.xml#L164)
and [Panda gripper model](https://github.com/ARISE-Initiative/robosuite/blob/v1.4.0/robosuite/models/assets/grippers/panda_gripper.xml#L28)
define the order/types; the
[arm sensor](https://github.com/ARISE-Initiative/robosuite/blob/v1.4.0/robosuite/robots/robot.py#L159)
and [gripper sensor](https://github.com/ARISE-Initiative/robosuite/blob/v1.4.0/robosuite/robots/single_arm.py#L203)
read the corresponding simulated joint positions.

Do not expose object/world or end-effector ground truth, calibration, simulator handles, reset identity/seed, reward, success or BDDL predicates. Execution counters are accounting feedback only.

One action is a seven-dimensional command to Panda's 20 Hz `OSC_POSE` controller:

| Slice | Contract |
| --- | --- |
| `[0:3]` | World-frame translation delta; normalized [-1, 1] maps to ±0.05 m per axis |
| `[3:6]` | Axis-angle rotation delta; normalized [-1, 1] maps to ±0.5 rad per axis |
| `[6]` | Gripper: -1 open, +1 close, 0 retain target |

Validate shape, finiteness and bounds. Apply only the declared prefix of a returned action chunk, then deliver a fresh observation. The policy cannot reset/step the simulator, query the scorer or read private artifacts.

## Budgets and scoring

`budget_mode="horizon"` uses the catalog's per-suite reference horizon: spatial
220, object 280, goal 300, LIBERO-90 400 and LIBERO-10 520 controls, excluding
settling. Method inference limits and action grouping do not alter these caps.
The alternative `budget_mode="decisions"` requires matching adapter/driver
`max_policy_calls=D` and `replan_interval=K`, with control cap D × K. Report
that changed execution condition separately; it is not the native task budget.

LIBERO-10's reference horizon 520 is from the retained StarVLA evaluator, not a universal official LIBERO limit. The native lifelong-evaluation configuration uses 600; a generic simulator horizon can be 1000. Record the reference source and actual cap rather than claiming equivalent evaluation conditions.

Native `BDDLBaseDomain.step` returns `done` from `_check_success()`. Stop at first native success and preserve termination/truncation separately. A visual impression or model self-report does not override the native scorer.

Record policy calls, action decisions, executed controls and initialization controls separately. Stop-only responses consume a policy call but no action decision; chunks may execute fewer than K controls. Record first-success control and its actual policy-call index, never inferred by division. A model's voluntary-stop persistence rule belongs to its profile and cannot postpone native termination, evaluator caps or errors.

## Reporting

Essential results retain benchmark/protocol and method/configuration identities,
selected suite/task/state cells, budget, native outcome, termination, counters,
typed errors and available inference usage. Include recorded source/environment
and BDDL/reset identities for reproducibility; unavailable accounting stays
unknown.

Optional interactions and media follow [recording](../../../docs/recording.md).
Results belong under the selected [agent profile](../../../AgentPolicies/README.md).

Distinguish selected, completed, failed, errored and unattempted cases, and give
the denominator for every success rate. Keep suite and reset coverage visible
rather than combining unlike selections into an unexplained average.
