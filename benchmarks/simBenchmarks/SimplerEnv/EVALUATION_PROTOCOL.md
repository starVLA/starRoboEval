# SimplerEnv evaluation protocol

Protocol: `simpler-prepackaged-development/rgb/v1`.

`interaction_mode="single_response"` is the default and preserves historical
protocol identities and interaction restrictions. Explicitly selecting
`interaction_mode="agent_method"` adds `/agent-method` immediately before
the final `/v1`, after any budget or action-feedback suffix. For example,
`simpler-prepackaged-development/rgb/action-feedback/agent-method/v1` retains
the native horizon and enables the separately declared agent-method interaction.
This selection changes only the interaction declaration; observations, actions,
reset selection, native control, scoring and execution budgets stay unchanged.
See [interaction modes](#interaction-modes).

An explicitly selected `action_rejection_feedback=true` adds
`/action-feedback` before the optional `/agent-method` and final `/v1` suffixes.
The default is `false`: historical fail-fast tracks and closed results are
unchanged. This flag is a benchmark service parameter, captured with the launch
configuration; it does not change native actions, sensors, horizons or scoring.
See [rejected-action feedback](#optional-rejected-action-feedback).

The native-horizon track has `horizon_multiplier=1`. An explicitly selected
`horizon_multiplier=2` is an extended-horizon track with a separate protocol
identity and score; it does not redefine the upstream task's native horizon.

For new decision-primary runs, explicitly select `budget_mode="decisions"`,
`max_policy_calls=D` and `replan_interval=K` in both adapter and runner. The
protocol adds `/decision-D-prefix-K/v1`, and the predeclared environment safety
cap is `D × K` (`evaluation_horizon` retains this resolved value). Upstream
`native_horizon` stays unchanged as a reference; its TimeLimit does not end this
track early. Horizon multipliers cannot be combined with decision-primary mode.
Stop, failed calls and short chunks each consume a decision. Native task
termination, policy stop and errors may still end an attempt earlier. Changes
apply only to a newly declared configuration; existing results remain unchanged.
The current fast campaign defaults to **200 decisions × at most 5 actions**
(1000-step safety cap). This is a development configuration, not a uniform native
reference budget. Always retain
actual decisions, controlled steps, first-native-success step and decision, and
termination reason so subsequent protocol design can use the evidence.

This document defines the executable prepackaged track and distinguishes it from
the native full reference. Report the selected tasks, reset conditions, controller,
observation channels and interaction budget with every score. An executable
adapter and native scoring do not by themselves establish upstream score parity.

Build the environment using [README.md](README.md). The complete alias inventory,
variation counts, and pinned primary sources are in [TASKS.md](bench_server/protocol/TASKS.md).

## Fast and full evaluation

| Mode | Schedule | Current implementation |
| --- | --- | --- |
| `fast` | One preselected reset and one attempt for each selected canonical task; retain failures and errors | Runnable prepackaged adapter; the campaign plan enumerates 15 task cells, each started explicitly |
| `full` | The chosen native protocol's complete task/variant/seed/episode matrix, with native evaluation settings | Reference matrices documented; unified full VM/VA scheduling is not implemented yet |

The pinned Visual Matching (VM) reference expands to 960 episodes per policy
checkpoint: 864 Google Robot and 96 WidowX. Google Variant Aggregation (VA)
expands to 1,992 episodes. These are separate protocols, not counts to combine.
The [task matrix](bench_server/protocol/TASKS.md) lists each family's variants and source scripts.
Running all 15 fast tasks, increasing a horizon, or repeating a failed attempt
does not make a run `full`. Native full repetitions are predeclared evaluation
cells, not success-seeking retries. Neither mode automatically retries failures.

Policy-specific persistence settings, including a minimum number of action
decisions before give-up, belong to the selected policy's configuration and
source bundle. They must not become a benchmark condition or redefine fast/full.

## Tasks and scope

The pinned upstream exposes **25 prepackaged aliases**, representing **10 broad
README task categories**. Its paper reproduction scripts cover **9 task families**.
Expanding can orientations and drawer levels gives **15 canonical subtasks** in
[bench_server/protocol/task_catalog.json](bench_server/protocol/task_catalog.json).

| Development task group | Subtasks | Native horizon per episode |
| --- | ---: | ---: |
| Pick horizontal, vertical, or standing coke can | 3 | 80 |
| Move near, baked-texture `v0` | 1 | 80 |
| Open top, middle, or bottom drawer | 3 | 113 |
| Close top, middle, or bottom drawer | 3 | 113 |
| Put apple into initially closed top drawer | 1 | 200 |
| Put spoon on towel | 1 | 60 |
| Put carrot on plate | 1 | 60 |
| Stack green cube on yellow cube | 1 | 60 |
| Put eggplant in basket | 1 | 120 |

Preselect the task list and reset seed before execution, and report both selected
and attempted denominators. The campaign freezes a fixed seed with its task
schedule; the standalone interface accepts an explicit seed. Failure is a valid
outcome. Do not search for easier reset positions, replace errors, or add
task-specific assistance until a success appears.

Construction uses the pinned alias mapping with independently copied kwargs,
`obs_mode="rgbd"`, and `prepackaged_config=True`. Native prepackaged reset samples
visual-matching conditions from its seed. This does not enumerate the full VM
or VA matrices in TASKS.md. Do not mutate the global upstream alias dictionary
or registered task definitions. Preserve each upstream `native_horizon` in the
catalog even when an explicit extended track configures a longer evaluation
time limit. Aliases, reset seeds, native environment IDs, source revisions,
and resolved run settings belong in evaluator provenance.

## Policy input and isolation

The default input is one current RGB frame, the current language instruction,
the public action contract, and non-privileged interaction counters and budgets.

| Robot | Policy camera | Native RGB shape | Control / simulation frequency |
| --- | --- | --- | --- |
| Google Robot | `overhead_camera` | 512 × 640 × 3 | 3 / 513 Hz |
| WidowX, including sink setup | `3rd_view_camera` | 480 × 640 × 3 | 5 / 500 Hz |

Frames are RGB `uint8`, without cropping or resizing. Transport may losslessly
encode the same pixels as PNG. Each call receives one current frame, with no
additional frame history supplied by the benchkit. Policy memory may retain
previously permitted inputs and its own actions within that episode and must
reset between episodes. Declare provider-side image processing with model settings.

The default is **RGB-only**: no qpos, qvel, TCP pose, depth, segmentation, camera
matrices, object poses, source/target IDs, contacts, reward, success flags,
subtask IDs, reset info, or other simulator metadata. Optional joint-position
input has the separate identity `simpler-prepackaged-development/rgb-qpos/v1`;
its ordered robot sensor fields must be declared and its results kept separate.

The policy receives only sanitized messages. Episode tokens must be opaque:
no seed, native episode index, reset coordinates, layout, asset path, or filename
encoding those values may reach `start_episode`, observations, or prompts.
Evaluator artifacts may contain provenance but are not policy inputs. During a
rollout the evaluated agent may read only its declared observation mailbox and
its own permitted history/artifacts; it cannot read simulator source, task
catalogs, reset manifests, scorer logs, or other processes' state. Source access
used to build the adapter does not grant the evaluated policy those capabilities.

## Interaction modes

```text
current RGB + instruction -> one Policy.act -> action chunk or stop
                                             |
                                  execute permitted prefix
                                             |
                                   next scheduled RGB
```

### Historical single-response mode

With the default `interaction_mode="single_response"`, one provider-backed
`Policy.act` may issue at most one inference request. No follow-up questions,
extra image requests, conversational tool loop, simulator
inspection, or second model message to repair an invalid response is allowed.
A service can enforce scheduled observation/action exchange, but cannot meter
hidden provider requests. Declare the method's enforcement and available
accounting evidence; one CLI invocation alone does not verify one provider request.

### Explicit agent-method mode

With `interaction_mode="agent_method"`, a declared method may compose multiple
general-purpose model calls, reasoning, memory and local tools over the already
permitted public observations and its own artifacts before submitting one action
chunk or stop. Declare model components, roles, tool availability and internal
decision behavior under the shared [method contract](../POLICY_PROTOCOL.md).
The mode adds no per-decision provider-request limit. Existing selected decision
caps, action prefixes, timeouts and native execution budgets still apply; internal
inference does not advance simulation or obtain a new observation.

Local tools receive no SIM client, credentials, simulator source, hidden state,
private score, hypothetical rollout or extra reset capability. The model selects
the actions through the same public contract. VLA proposals, fallback task
policies and automatic task-solving services remain out of scope.

Record decision calls, executed decisions and controls separately from measured
provider calls, tokens, latency and cost. Preserve unknown provider counts and
internal retries as unknown; neither mode turns service or CLI receipts into
provider metering or identity attestation. Explicit launch parameters appear in
the service description; resolved `interaction_mode` is also retained in episode
budget metadata, native provenance and metrics. Keep results from the two
interaction modes distinct; this selection does not rewrite frozen old runs.

### Conditions shared by both modes

A human correction during an episode changes the policy under evaluation and
must not be presented as an autonomous model result.

The shared [policy protocol](../POLICY_PROTOCOL.md) also applies. Declare whether
the policy is a fixed program, scripted harness check, or general-purpose model
method. The historical mode treats program generation or adaptation during
evaluation as a separate track; the explicit agent-method mode permits declared
local analysis/code tools within the unchanged observation and control boundary.

## Actions and deterministic control

### Optional rejected-action feedback

Only an explicitly selected `action_rejection_feedback=true` track permits a
rejected action to return a bounded public validation issue to the next normal counted
policy call. The invalid action is not executed; the same last acknowledged
observation is reused. There is no reset, new image request, simulator inspection
or additional within-call service repair exchange. Earlier acknowledged controls
remain counted if a later control of a chunk is rejected. Stop and successful native
execution retain their ordinary semantics.

Every rejected response consumes a policy call from the predeclared finite call
budget. Record rejected calls separately from accepted action decisions and
executed controls. Infrastructure failures, uncertain execution and lost action
acknowledgments remain errors, never permission to replay an action. Models and
trusted drivers must declare support for this track before claiming an episode;
`false` keeps the original terminate-on-invalid-response interaction. The
selected `interaction_mode` still applies: feedback does not itself enable
additional inference or local tools in the historical single-response mode.

### Native action contract

Each action is seven finite numbers:

```text
[dx, dy, dz, rotation_vector_x, rotation_vector_y, rotation_vector_z, gripper]
```

Translation uses metres; rotation is axis-angle in radians, not Euler angles.
RSI validates the native advertised Box: each translation component in `[-1, 1]`,
each rotation-vector component in `[-pi/2, pi/2]`, and gripper in `[-1, 1]`.
Invalid actions are errors and are not silently clipped. Upstream arm controllers
use `normalize_action=False`; their advertised arm limits are dummy limits in
native configuration. RSI's strict bounds are an explicit track constraint.

| Robot | Native arm behavior | Native gripper behavior |
| --- | --- | --- |
| Google Robot | `ee_align`: delta from measured EE pose, with base-aligned axes and native planner interpolation | Target joint-position delta: positive closes, negative opens, zero holds target |
| WidowX | `ee_align2`, `use_target=True`: accumulated target delta; rotation pivots around current measured EE position | Absolute joint position: `+1` open, `-1` closed, zero intermediate |

The exact controller names are:

```text
Google: arm_pd_ee_delta_pose_align_interpolate_by_planner_gripper_pd_joint_target_delta_pos_interpolate_by_planner
WidowX: arm_pd_ee_target_delta_pose_align2_gripper_pd_joint_pos
```

Native robot-only IK and interpolation stay inside the simulator adapter; they
are not model-call tools. The common track adds no model-specific scaling,
sticky-gripper conversion, oracle grasp planner, or task-dependent action repair.
A wrapper requiring such processing must declare it as part of its policy identity.

Sources: pinned [control selection](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/simpler_env/utils/env/env_builder.py),
[Google configuration](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/agents/configs/google_robot/defaults.py),
[WidowX configuration](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/agents/configs/widowx/defaults.py),
and [pose controller](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/agents/controllers/pd_ee_pose.py).

## Budgets and instruction transitions

The following quantities must be recorded separately:

| Quantity | Meaning |
| --- | --- |
| `native_horizon`, H | Upstream registered task horizon; fixed in the task catalog |
| `evaluation_horizon` | Selected native-step time limit: `H * horizon_multiplier` in horizon mode or `D * K` in decision mode |
| `max_policy_calls`, C | Maximum number of model decisions in this episode |
| `replan_interval`, K | Maximum action prefix executed from each decision |
| `action_decisions` | Non-stop decisions for which at least one control actually executed |
| `environment_steps` | Executed native control actions, not physics ticks |

An action vector advances one native control step; a model decision can contain
several such vectors. Therefore an episode cannot exceed
`min(evaluation_horizon, runner_step_cap, C * K)` executed steps. Actual coverage
can be shorter when a policy returns shorter chunks, stops, or encounters an
error. A larger simulator horizon does not automatically provide more model
decisions.

For example, 40 calls with five actions each permit at most **200 native actions**, enough
to reach every listed native horizon. Full five-action chunks require 12 calls
for a 60-step task, 16 for 80, 23 for 113, 24 for 120, and 40 for 200. Shorter
chunks spend the same call budget on fewer actions; this observation/action
tradeoff is part of the protocol. Record token limits, reasoning settings, and
timeouts for each model-backed run. Native construction may itself invoke reset
internally; this does not authorize a new evaluated attempt or seed selection.

### Native and overridden time limits

Spoon, carrot, and cube have upstream registered horizons of **60**, and the
pinned official Bridge script also evaluates them for **60** steps. The
explicitly selected 120-step setting is an override, not a correction to the
native task definition. Keep the registered horizon and resolved evaluation
time limit separate. See [TASKS.md](bench_server/protocol/TASKS.md#horizons-and-overrides) for native
sources and the full horizon table. Matching one numerical limit alone does
not establish parity with another evaluator's settings.

### Explicit extended-horizon evaluation

Select `horizon_multiplier=2` **before reset**, record a distinct extended-track
identity, and set `evaluation_horizon=2H`. Keep the native task logic, scorer,
control frequency, and instruction-transition schedule unchanged. Preserve H
as `native_horizon`; configure the episode time-limit wrapper for 2H rather
than editing the registered task definition.

Model-call and runner-step caps are still independent. With 40
calls and prefix five, a 60-step task can reach its extended 120-step horizon;
an apple task with H=200 cannot reach 2H=400. Reaching all doubled horizons
requires a predeclared budget of at least 80 full-five-action decisions and a
runner-step cap of at least 400. Such a budget is an explicit experimental
setting, never extra compute silently granted after failure.

A predeclared extended run may record native success at H and 2H **along one
uninterrupted trajectory**, using the already-returned step `info` at those
indices. It continues according to its original budget regardless of whether
success at H is true or false. It does not reset, retry, branch from a saved
state, or select the better checkpoint. If a stop, cap, or error prevents a
checkpoint from being reached, record it as unobserved (`null`) with the
termination reason; do not substitute a nearby step's success.

Keep `success_at_H`, `success_at_2H`, and the final executed-step success
distinct. The H checkpoint of a 2H-planned policy is an extended-run diagnostic,
not a replacement for a separately configured default-H score. Report extended
results separately from the default development track and upstream reference
scores; never merge the two horizons or report best-of-H-and-2H success.

For apple-in-closed-drawer, native timed advancement changes instruction on
**action 101**, after the pre-step elapsed count reaches 100. The adapter does
not expose model-controlled `advance_to_next_subtask`. Return the native new
instruction in the next scheduled observation. A policy returning one-action
chunks with a 40-call budget will exhaust it before that transition; it must not receive
extra calls or an oracle phase change. Do not pre-open the drawer, reposition
objects, change transition timing, or consult success to advance a subtask.
See the pinned [compound-task implementation](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/envs/custom_scenes/place_in_closed_drawer_in_scene.py).

## Native scoring and error accounting

Read success from the **last executed native step's `info["success"]`**.
Intermediate native success does not end an episode. Preserve it in evaluator
logs and continue until a declared stop condition. If recorded, `success_ever`
is diagnostic, not the primary score. No-step policy stop is unsuccessful;
a policy saying `done` never awards success.

The upstream evaluator also ignores intermediate native `terminated` as a loop
exit. Do not call `evaluate()` or `get_info()` again for a fresh score: native
scorers can update counters when called. Preserve the original step result.
Sources: [evaluator](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/simpler_env/evaluation/maniskill2_evaluator.py)
and [native step implementation](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/envs/sapien_env.py).

A completed attempt with final success false is a task failure, including a
policy-budget stop. Malformed output and policy-response timeouts are policy
errors; contract violations retain their typed category. Installation, reset,
rendering and native-runtime failures are infrastructure errors and must not
be silently converted into model failures. No automatic
infrastructure or policy retries are permitted. Keep a failed attempt and any
subsequent separately authorized evaluation as distinct records; never report
only the best outcome or replace the original record.

Retain rendering defects discovered after closure with their interpretation
caveats. A verified environment repair can apply prospectively to unstarted
evaluation cells when its dependency identity and changed condition are recorded.
See [native rendering preflight](environment/RENDERING.md); switching
shaders or disabling native denoising is not an equivalent repair.

Report coverage, successes, completed failures, typed errors, `success_rate`
over protocol-completed episodes, and `attempt_success_rate` over all attempts.
One episode per task is a development sample, not a reliable full-suite estimate.
Retain per-task outcomes and display the denominator of every aggregate.

## Required artifacts

Keep evaluator artifacts separate from the policy mailbox:

- Immutable benchmark/model/protocol identity, both upstream revisions, assets,
  task matrix, evaluator revision, reset seed, native controllers, and separate
  `native_horizon`, `evaluation_horizon`, `horizon_multiplier`, policy-call,
  action-prefix, and runner-step budgets.
- Exact policy-visible RGB/instruction messages, public action contract, and
  opaque episode token.
- One structured response per call, accepted chunks and executed prefixes,
  policy/provider call counts, tokens, latency, cost when known, and typed errors.
- Native per-step success/termination/truncation and evaluator-only diagnostics,
  final result, optional reached/unreached H and 2H checkpoints for the extended
  track, video or frame references, and summary.

Exclude credentials and hidden chain-of-thought. Persist failure evidence as
well as success evidence. The policy cannot read scorer artifacts while acting.

## Validation and comparability

Adapter validation checks install/import/reset/render, the 15-task catalog,
deterministic enumeration, action compatibility, sanitization, call limits,
final-step scoring, and artifact decoding. Successful task completion is not a
prerequisite for validating those paths; label a no-op policy as a harness check.

A formal released score additionally requires a frozen representative matrix,
provider/token/time settings, measured reset reproducibility, and appropriate
released-policy baseline comparison. This track changes upstream sampling,
interaction budgets, and subtask advancement. Native scoring alone does not
establish upstream score parity. Record evidence and explain the differences
before any formal release.
