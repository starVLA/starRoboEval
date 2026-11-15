# RoboDojo evaluation protocol

## Native benchmark and case selection

RoboDojo's core simulation benchmark contains **42 tasks**: 12 Generalization,
6 Memory, 8 Precision, 8 Long-Horizon and 8 Open tasks. The broader project also
defines 18 real-world tasks. The official simulation catalog's separate DLC
page is not part of the 42-task core evaluation. Task objectives and groupings
are defined by the [official task catalog](https://robodojo-benchmark.com/doc/sim-tasks/),
not by this repository's implemented task subset or any method's chosen tests.

### Tasks, variants, seeds and layouts

The native configuration at revision
`ee67a1468510da7624a089164402359f2afc72c8` specifies 50 episodes by default.
Each of the 12 Generalization tasks has a standard and a `_random` configuration,
with 25 episodes for each. They are two configurations of one task objective,
not two additional core task definitions. Task-specific robot, scene and timing
overrides also live in
[`task/RoboDojo/config/_task.yml`](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/ee67a1468510da7624a089164402359f2afc72c8/task/RoboDojo/config/_task.yml).

The native [SeedManager](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/ee67a1468510da7624a089164402359f2afc72c8/env/seed_manager/seed_manager.py)
loads stored reset files from
`Assets/Eval_Layout/<benchmark>/<robot-config>/<evaluation-seed>/<task>_<index>.json`.
The evaluation seed selects the directory; a layout ID indexes its ordered
task-specific files. Neither the number of files present nor an arbitrary new
seed establishes the intended evaluation sample count. Preserve the selected
task/configuration, embodiment, seed, layout identities and asset versions when
comparing methods.

Horizon and success conditions are task-specific. For example, the native
[`classify_objects` implementation](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/ee67a1468510da7624a089164402359f2afc72c8/task/RoboDojo/tasks/classify_objects.py)
sets 1100 controls and checks category placement, settling and arm return.
That horizon and those predicates are not rules for all RoboDojo tasks.

The pinned native [evaluation loop](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/ee67a1468510da7624a089164402359f2afc72c8/src/eval_client/main.py#L348-L436)
takes layouts in order and keeps going until success plus failure counts reach
the configured episode count. It skips a layout whose reset raises
`UnStableError` (lines 371–372), skips one after any other reset or episode
exception, and refills batches after a PhysX-broken report. Tasks that call
`mark_env_unstable` during an episode also drop that layout from the total
([`eval_env.py`](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/ee67a1468510da7624a089164402359f2afc72c8/src/eval_client/eval_env.py#L467-L473)). When layouts run
out, the loop stops short. The Bench Server instead fixes its complete case
list before execution and retains every later error without replacement; see
[`max`](#max-first-reset-stable-layouts). State the selected, attempted and
completed denominators; these different error-handling conditions must not be
hidden in an aggregate.

## Current service scope

The sections below specify the implemented Bench Server interface, not the
entire native task suite. Only `classify_objects` is currently exposed.

### Tasks and layouts

- Benchmark: `robodojo`
- Task: `classify_objects`
- Embodiment: two fixed-base ARX X5 arms
- Native task instruction: sort objects by category into three baskets
- Public instruction also requires both arms to return to their starting
  end-effector poses
- Launch seed: 20260907
- Native evaluation/simulator seed: 0
- `evaluation_mode`: `fast` (default) layouts 0–4 (5 cases), `max` the first
  50 reset-stable layouts of a reset-stability manifest (50 cases),
  `example` layout 0 (1 case), in order
- Attempts: exactly one per selected layout; no automatic retry or replacement
- Native horizon: 1100 acknowledged controls per layout

The service catalog enables one task and binds 55 stored layouts. The service selects
1, 5 or 50 of them; `max` matches the native configured episode count for
this task and can reach the spare layouts 50–54 only when earlier layouts were
reset-unstable. No mode includes other RoboDojo tasks. `fast` and `example`
layouts are not stability-screened, so an unstable reset stays in their
denominator as an infrastructure error.
Choose the mode before execution; this service does not accept
arbitrary layout subsets. The launcher rejects `--episodes` and the adapter
rejects any schedule limit, so a service schedule is always the complete mode
schedule. A gateway case service selects one case with `--episode-id` and
records the schedule size; the gateway refuses case files and limits, so an
evaluation still covers the whole schedule. The protocol identity is
`robodojo-ee67a14/classify-objects-fixed-layouts/rgb-proprio28-eef16/<mode>/v1`
for `fast` and `example`, and
`robodojo-ee67a14/classify-objects-reset-stable-layouts/rgb-proprio28-eef16/max/v1`
for `max`. The launch seed is fixed at 20260907; native startup
and evaluation use seed 0. Stored layout IDs, not changes to these fixed seeds,
select the reset data.

Case metadata describes the configured layout count, native reference episode
count, selection and retention of invalid cases without replacement, under
`starvla-rsi.robodojo.fixed-layout-selection/v1` for `fast`/`example` and
`starvla-rsi.robodojo.reset-stable-layout-selection/v1` for `max` (which also
records `stability_manifest` `{sha256, pinned}` and its screening counts). The selected
denominator is the complete mode schedule; report attempted and completed counts separately.
`official_full_protocol` is false for every mode: `max` reproduces the native
reset-stability skip but not the replacement after in-episode, PhysX-broken or
other errors, and its public instruction and EEF interface differ from native.
This metadata does not change the robot interface or native scoring.

### `max`: first reset-stable layouts

`max` needs the operator-supplied `stability_manifest` (absolute path without
`..` parts); `stability_manifest_sha256` is optional. At startup the service
computes the manifest's SHA-256. With a supplied hash it refuses a mismatch;
without one it records the observed digest with `"pinned": false` instead of
refusing. Either way it refuses a `max` launch unless the manifest is a
complete record:

| Field | Requirement |
| --- | --- |
| `schema` | `starvla-rsi.robodojo.reset-stability/v1`; no other top-level fields |
| `task` | `classify_objects` |
| `native_revision` | `ee67a1468510da7624a089164402359f2afc72c8` |
| `layout_inventory_sha256` | the pinned 55-layout inventory digest from `environment/reference_eef_snapshot.json` |
| `native_eval_seed`, `required_stable` | 0, 50 |
| `screened` | `{layout_id, result}` rows for layouts 0, 1, 2, … in order, at most 55; `result` is `stable`, `unstable` or `exception`; exactly 50 `stable`, the last row being the 50th |
| `preparation` | at least non-empty `runtime_manifest_sha256`, `created_at`, `procedure` strings (recorded, not compared) |

The schedule is the 50 `stable` layout IDs in order, with one attempt each.
If the 55 layouts hold fewer than 50 stable ones, no complete manifest exists
and `max` cannot run; upstream would stop short instead. Rejected layouts are
preparation provenance, never policy results. The service never screens,
searches or edits the manifest. Each native worker re-reads it at the digest
observed at startup and refuses a layout outside the schedule.

The screen resets each layout in order, with no policy and no action, in a
fresh native worker process per layout using the evaluated runtime. A layout
is `stable` when that reset completes the worker's post-reset check (native
`setup_scene` stability check passed, environment alive and not ended), and
`unstable` when the reset raises native `UnStableError` or fails that check.
The screen records any other reset error as `exception` (upstream also skips
it), stops at the 50th stable layout and is never rerun to improve a result.
**This preparation has not yet been performed**, and no preparation tool is
shipped; see [environment setup](environment/README.md#max-mode-reset-stability-preparation).

During a policy episode, a reset that is unstable although the manifest marked
it stable, or a native in-episode instability mark, is an infrastructure error
without a spare layout, never a policy failure. `classify_objects` never calls
`mark_env_unstable`, and the PhysX monitor stays disabled as upstream enables
it only for tasks with an `Articulation` section. Whether a reset-stability
result reproduces across processes, GPUs or runtimes is UNVERIFIED.

The benchmark-scope `max` set follows `_task.yml` `eval_nums`: 30 task
configurations × 50 plus the 12 Generalization tasks × (25 standard + 25
`_random`), 2,100 episodes over the 54 configuration files at the pinned
revision. Only `classify_objects` has a native Direct worker now. The other
tasks need their own workers; `imitate_sorting_sequence`, `make_kong` and
`play_tic_tac_toe` also use the `dual_x5_and_franka_competition` robot
configuration and mark in-episode instability. Whether the generalization
pairs share the screen procedure unchanged is UNVERIFIED.

The machine-readable definition is [bench_server/protocol/task_catalog.json](bench_server/protocol/task_catalog.json),
validated by [bench_server/protocol/task_catalog.py](bench_server/protocol/task_catalog.py). It is benchmark
protocol data, including the binding to the pinned layout inventory. It contains
no native assets or operator deployment paths. [server.py](server.py) loads the
[service adapter](bench_server/adapter.py), which applies this definition through
the private runtime under `environment/`.

### Public observation

At reset and after each acknowledged control the model receives:

- task language;
- original 640×480 `uint8` RGB for `cam_head`, `cam_left_wrist` and
  `cam_right_wrist`;
- 28 robot values: six measured joints and one last commanded gripper opening
  per arm, followed by each measured link6 world pose as `x,y,z,qw,qx,qy,qz`.

After a control, the observation additionally contains the closed
`starvla-rsi.robodojo.robot-control-feedback/v1` acknowledgement: executed joint command,
post-control public robot state, and robot-only DLS/FK diagnostics. Reset has no
acknowledgement.

The model never receives object poses/identities, layout or reset metadata,
camera calibration, contacts, depth, reward, native success, process score,
scorer state, simulator handles, worker logs or private errors.

### Public action

One action is 16 finite values:

```text
[left_x, left_y, left_z, left_qw, left_qx, left_qy, left_qz, left_opening,
 right_x, right_y, right_z, right_qw, right_qx, right_qy, right_qz, right_opening]
```

Positions are in metres. Poses are absolute link6 targets in the declared world frame.
Quaternions are absolute unit `wxyz` values with tolerance `1e-4`; openings are
continuous `[0,1]`, with 0 closed and 1 open. The benchmark performs a fixed robot-only numerical DLS
conversion, applies native soft-limit/measured-joint bounds and sends exactly
one native joint control. It does not plan around objects, choose targets, run a
support policy or roll out hypothetical actions.

Model-side step size, rotation size, chunk length and ordinary give-up rules are
policy configuration, not benchmark validity. Benchmark validity is limited to
the declared vector shape, finite values, quaternion norm and opening range.
Confirmed invalid actions execute zero controls and return structured feedback;
they remain recorded. The client may correct them on a later decision.

### Counting and termination

Count policy calls, action decisions, rejected actions, acknowledged controls
and physics ticks separately. One acknowledged control runs ten native physics
ticks at 0.004 seconds. A model may propose a bounded chunk, but the service
still executes and acknowledges controls one at a time.

Terminate on native success/end, native horizon, explicit model stop, or a
terminal infrastructure/policy error. The 1100-control horizon is this task's
native limit; model-call limits are model/evaluation configuration and must be reported
separately. Waiting for a model advances no physics. An uncertain native action
is never silently replayed.

### Scoring

Success is the pinned native result `end_flag[0] and success[0]`. Native reward
and cached process score are recorded without an extra stateful scorer call.
The result fields have different meanings:

| Field | Meaning |
| --- | --- |
| `success` | Boolean native task completion, including its end condition |
| `native_process_score` | Cached partial-progress score; may be unavailable |
| `native_benchmark_score` | Score on a 0–100 scale: 100 on native success, otherwise cached progress or 0 after a native reward check; `null` if no reward check occurred |

A score of 60 is not a 60% success rate. Report success count over the
selected layout denominator (1, 5 or 50), plus native
scores and all infrastructure or policy errors. Do not remove failures or
replace layouts; `max` excludes only the layouts its stability manifest
recorded before execution.

### Agent access

The trusted agent driver communicates through the authenticated loopback SIM
service. It gives the model only declared inputs and accepts its decisions;
administrative credentials and private results stay out of actor context.
The server owns the native environment, schedule and score; the agent owns its
decision loop. Shared `benchkit` tools may coordinate output and publish a closed
report, but it cannot expose server-private fields or generate actions.

Interaction history and media retention are optional and default enabled where
supported. See [recording settings](../../../docs/recording.md) for capture and
storage behavior; these settings do not change native controls or scoring.
