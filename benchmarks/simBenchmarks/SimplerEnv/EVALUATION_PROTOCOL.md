# SimplerEnv evaluation protocol

SimplerEnv evaluates manipulation under real-to-sim visual conditions for
Google Robot and WidowX. Task families, reset conditions and visual variations
are separate benchmark dimensions. The server owns resets, robot controls and
native scoring; agent methods use the declared sensor/action interface.

See [installation](README.md) and [task/variation definitions](bench_server/protocol/TASKS.md).
Select tasks, seeds, sensor settings and execution budgets before running, and
record the protocol identity returned by the service with every result.

## Native reference matrices

The pinned Visual Matching (VM) reference expands to 960 episodes per policy
checkpoint: 864 Google Robot and 96 WidowX. Google Variant Aggregation (VA)
expands to 1,992 episodes. These are separate protocols, not counts to combine.
The [task matrix](bench_server/protocol/TASKS.md) lists each family's variants and source scripts.
These reference matrices specify object/layout, robot-pose and appearance
conditions explicitly. `max` mode enumerates one of them for the selected task;
the prepackaged seeded resets of `fast` and `example` do not. Report
selected tasks, seeds and attempts separately from coverage of reference visual
conditions.

Policy-specific persistence and give-up settings belong to the selected
policy's configuration. They must not become benchmark task or sampling requirements.

## Task families and service selection

The pinned upstream exposes **25 prepackaged aliases**, representing **10 broad
README task categories**. Its paper reproduction scripts cover **9 task families**.
Expanding can orientations and drawer levels gives **15 canonical subtasks** in
[bench_server/protocol/task_catalog.json](bench_server/protocol/task_catalog.json).

The current service exposes the following 15 canonical subtasks. This table
describes its selector, not a separate definition of the benchmark's task count.

| Service task group | Subtasks | Native horizon per episode |
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

The service selects one canonical task; `evaluation_mode` fixes its resets.

| `evaluation_mode` | Selection | Episodes | Step cap |
| --- | --- | ---: | --- |
| `fast` (default) | Selected task, prepackaged resets with seeds `seed + 0..4` | 5 | Native task horizon |
| `max` | Selected task's complete pinned-script matrix chosen by `reference_matrix` | see below | Native task horizon |
| `example` | First `fast` episode, reset seed `seed` | 1 | Native task horizon |

`max` runs one reference matrix per service run, as upstream runs one script.
The `reference_matrix` parameter selects `visual_matching` (default) or
`variant_aggregation`; the latter exists for Google Robot tasks only, and the
parameter is rejected in `fast` and `example`. Episodes per task and matrix,
from the pinned
[`scripts/`](https://github.com/allenai/SimplerEnv/tree/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts)
for one checkpoint:

| Task | `visual_matching` | `variant_aggregation` |
| --- | ---: | ---: |
| Each pick coke can orientation (3 tasks) | 100 | 275 |
| Move near `v0` | 240 | 600 |
| Each open/close drawer (6 tasks) | 36 | 63 |
| Put apple into closed top drawer | 108 | 189 |
| Each Bridge task (4 tasks) | 24 | — |
| **All 15 tasks, as separate runs** | **960** | **1,992** |

### Prepackaged seeded resets (`fast`, `example`)

Episode index `i` uses reset seed `seed + i`. Native reset samples
visual-matching conditions, including object episode IDs where applicable.
A seed is not a layout index and does not guarantee a unique scene.
The protocol identity names the mode before its version, e.g.
`simpler-env-c701ea2/prepackaged-seeded/rgb/fast/v1`.

Construction uses the pinned alias mapping with independently copied kwargs,
`obs_mode="rgbd"`, and `prepackaged_config=True`. Native prepackaged reset samples
visual-matching conditions from its seed. This does not enumerate the VM
or VA matrices in TASKS.md. Do not mutate the global upstream alias dictionary
or registered task definitions. Preserve each upstream `native_horizon` in the
catalog even when an explicit extended track configures a longer evaluation
time limit. Aliases, reset seeds, native environment IDs, source revisions,
and resolved run settings belong in evaluator provenance.

### Reference matrices (`max`)

Each `max` episode reproduces one `run_maniskill2_eval_single_episode` call of
the pinned scripts, transcribed in
[`max_matrix.py`](bench_server/protocol/max_matrix.py). The server builds a
fresh environment through upstream `build_maniskill2_env` with the script's
environment ID, scene, robot, control mode, frequencies, additional build kwargs,
`camera_cfgs={"add_segmentation": True}` and real overlay; it does not use
`prepackaged_config`. Reset passes the script's robot `init_xy`/`init_rot_quat`
and object `init_xy` or `episode_id` as options, with **no seed**, exactly as
upstream. The fresh environment's construction-time RNG then fixes residual
randomness, so the launch `--seed` does not change a `max` scene; the episode
seed `seed + i` is recorded only. Segmentation is computed natively but never
reaches the policy.

The schedule holds only the selected matrix, ordered by variant, then episode,
with stable IDs `<task>-<vm|va>-<variant index>_<variant name>-<episode index>`,
e.g. `google_robot_open_top_drawer-va-03_lighting_brighter-005`. Opening an ID
outside the selected matrix is a protocol error. Each episode's
driver-side metadata records its `matrix`, `variant` (index, name, axis and value),
source script and resolved native configuration. These IDs and metadata belong
to the trusted driver; the policy still receives only an opaque episode token.

Report VM and VA per matrix, with their own denominators; **never pool them**
into one score. Separate runs and protocol identities keep them apart. Upstream defines no Bridge VA, so WidowX tasks have VM only.
The pinned
[metrics tool](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/tools/calc_metrics_evaluation_videos.py)
averages per-variant success rates (pick: per variant group) rather than pooling
episodes, and its pick and move-near VA averages omit the two alternative-camera
variants that the scripts run. `max` schedules every scripted variant; retain
per-variant outcomes so that either aggregate can be reproduced and state which
one is reported. Success is the native final-step success over the native
horizon, as for `fast`.

The scripts use the native ray-tracing shader (`shader_dir=rt`) for all drawer
and apple episodes, including the VA background, lighting and cabinet variants.
The server builds them as upstream does, but RT rendering of these matrix
scenes is **UNVERIFIED** on the current runtime; validate it with the
[rendering preflight](environment/RENDERING.md) before relying on drawer or
apple `max` results. Move-near VA uses `MoveNearGoogleInScene-v0` while VM uses
the baked-texture `v0`; apple VA uses `model_ids=apple` while VM uses
`baked_apple_v2`. Both follow the pinned scripts. Overlay images are hashed and
compared with pinned SHA-256 values; an unpinned overlay is recorded as unpinned.
The protocol identity names the matrix, e.g.
`simpler-env-c701ea2/reference-visual-matching/rgb/max/v1` or
`simpler-env-c701ea2/reference-variant-aggregation/rgb/max/v1`.

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
input has the separate identity `simpler-env-c701ea2/<selection>/rgb-qpos/<mode>/v1`
(`prepackaged-seeded`, `reference-visual-matching` or `reference-variant-aggregation`);
its ordered robot sensor fields must be declared and its results kept separate.
The [interface's joint table](bench_server/protocol/INTERFACE.md#joint-position-order)
specifies the 11 Google Robot or 8 WidowX measured positions, their native order
and radians/metres units; these are not controller targets.

The policy receives only sanitized messages. Episode tokens must be opaque:
no seed, native episode index, reset coordinates, layout, asset path, or filename
encoding those values may reach `start_episode`, observations, or prompts.
Evaluator artifacts may contain provenance but are not policy inputs. Public
benchmark descriptions and interface definitions may be read; they do not grant
access to the evaluator's private reset manifests, scorer logs, native runtime
or other processes' state. During a rollout, live environment information must
come only from the declared observation channel and permitted interaction
history. Public documentation access is not permission to inspect a private
task/reset catalog or execute simulator source to obtain additional state.

## Interaction modes

```text
current RGB + instruction -> one Policy.act -> action chunk or stop
                                             |
                                  execute permitted prefix
                                             |
                                   next scheduled RGB
```

### Single-response setting

With `interaction_mode="single_response"` (the default), one provider-backed
`Policy.act` may issue at most one inference request. No follow-up questions,
extra image requests, conversational tool loop, simulator
inspection, or second model message to repair an invalid response is allowed.
A service can enforce scheduled observation/action exchange, but cannot meter
hidden provider requests. Declare the method's enforcement and available
accounting evidence; one CLI invocation alone does not verify one provider request.

### Agent-method setting

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
interaction modes distinct; this selection does not rewrite old runs.

### Conditions shared by both modes

A human correction during an episode changes the policy under evaluation and
must not be presented as an autonomous model result.

The shared [policy protocol](../POLICY_PROTOCOL.md) also applies. Declare whether
the policy is a fixed program, scripted infrastructure diagnostic, or general-purpose model
method. The single-response setting treats program generation or adaptation during
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
`false` (the default) ends the attempt on invalid input. The
selected `interaction_mode` still applies: feedback does not itself enable
additional inference or local tools in the single-response setting.

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
| WidowX | `ee_align2`, `use_target=True`: base-aligned accumulated target delta; rotation pivots around current measured EE position | Absolute joint position: `+1` open, `-1` closed, zero intermediate |

Both translation and rotation-vector components are expressed along the robot
articulation's base axes, not end-effector-local axes or necessarily world axes.
See [target transforms](bench_server/protocol/INTERFACE.md#actions) for the
measured-pose versus retained-target distinction.

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

The task catalog supplies the native horizon H. The default
`horizon_multiplier=1` preserves it; multiplier 2 declares a longer execution
condition. This is a configurable execution condition, not a benchmark-wide
inference or grouping requirement.

The following quantities must be recorded separately:

| Quantity | Meaning |
| --- | --- |
| `native_horizon`, H | Upstream registered task horizon; fixed in the task catalog |
| `evaluation_horizon` | Selected native-step time limit: `H * horizon_multiplier` |
| `max_policy_calls`, C | Driver-selected maximum number of model decisions in this episode |
| `replan_interval`, K | Driver-selected maximum action prefix executed from each decision |
| `action_decisions` | Non-stop decisions for which at least one control actually executed |
| `environment_steps` | Executed native control actions, not physics ticks |

An action vector advances one native control step; a model decision can contain
several such vectors. Therefore an episode cannot exceed
`min(evaluation_horizon, runner_step_cap, C * K)` executed steps. Actual coverage
can be shorter when a policy returns shorter chunks, stops, or encounters an
error. A larger simulator horizon does not automatically provide more model
decisions.

The method chooses its call allowance and action grouping; neither is a native
task definition. Record selected method limits separately, including any cap
that prevents reaching the declared control horizon. Native construction may
itself invoke reset internally; this does not authorize a new evaluated attempt
or seed selection.

### Native and overridden time limits

Spoon, carrot, and cube have upstream registered horizons of **60**, and the
pinned official Bridge script also evaluates them for **60** steps. The
explicitly selected 120-step setting is an override, not a correction to the
native task definition. Keep the registered horizon and resolved evaluation
time limit separate. See [TASKS.md](bench_server/protocol/TASKS.md#horizons-and-overrides) for native
sources and the task horizon table. Matching one numerical limit alone does
not establish parity with another evaluator's settings.

### Explicit extended-horizon evaluation

Select `horizon_multiplier=2` **before reset**, record a distinct extended-track
identity, and set `evaluation_horizon=2H`. Keep the native task logic, scorer,
control frequency, and instruction-transition schedule unchanged. Preserve H
as `native_horizon`; configure the episode time-limit wrapper for 2H rather
than editing the registered task definition.

Method call limits and runner-step caps are independent. If selected, they may
end an attempt before its declared control horizon; report that reason rather
than extending the attempt after a failure.

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
results separately from the default native-horizon track and upstream reference
scores; never merge the two horizons or report best-of-H-and-2H success.

For apple-in-closed-drawer, native timed advancement changes instruction on
**action 101**, after the pre-step elapsed count reaches 100. The adapter does
not expose model-controlled `advance_to_next_subtask`. Return the native new
instruction in the next scheduled observation. A method's own call limit may stop it before that transition; it must not
receive an unrequested phase change or an extension after exhausting its limit. Do not pre-open the drawer, reposition
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
One episode per task samples only that task's selected reset conditions.
Retain per-task outcomes and display the denominator of every aggregate.

## Reporting

Report selected tasks and reset seeds, attempted/completed/unattempted counts,
native successes, completed failures and typed errors. Give both completed-case
and all-attempt denominators; a rendering or runtime interruption is distinct
from an unsuccessful completed trajectory.

Identify the native source/controller, sensor settings, actual control horizon,
method configuration and separate call/decision/control counts. Keep final
success distinct from intermediate success and any H/2H diagnostics. Compare
results only when task sampling, native execution and observation conditions
are aligned. The prepackaged seeded-reset selection of `fast`/`example` is not
the explicit VM/VA condition matrix described in [TASKS.md](bench_server/protocol/TASKS.md);
only `max` enumerates it, one matrix per run. Report `max` per matrix and per variant.

Results belong under `AgentPolicies/<agent>/results/simpler_env/`. Optional
interactions and media follow [recording](../../../docs/recording.md).
