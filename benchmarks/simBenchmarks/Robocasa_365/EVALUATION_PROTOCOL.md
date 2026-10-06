# RoboCasa365 evaluation protocol

[The adapter](bench_server/adapter.py), registered as `robocasa365`, owns native PandaOmron reset/control/scoring. Policies receive only the declared [shared-interface](../POLICY_PROTOCOL.md) observation. This is not the GR1 Tabletop benchmark.

## Task universe and fast/full selection

The pinned upstream implementation has 365 tasks: 65 atomic and 300 composite. Its dataset registry contains 317 entries: 65 atomic and 252 composite. The other 48 composites lack dataset/horizon metadata in that registry; do not invent it or confuse implementation count with the supported evaluation schedule.

| Target split | Tasks |
| --- | ---: |
| Atomic seen | 18 |
| Composite seen | 16 |
| Composite unseen | 16 |
| Total target set | 50 |

The 300-task pretraining set is separate. [robocasa365_target50.json](bench_server/protocol/robocasa365_target50.json) freezes the target task ordering, split membership, native horizons and module hashes.

Fast mode evaluates each preselected task once, retaining failure and infrastructure errors without automatic retries. The default `task_scope="pilot"` is a compatibility name for the two-task preset: local indices 0=OpenDrawer and 1=NavigateKitchen. Explicit `task_scope="target50"` uses target-set ordinals: 4=NavigateKitchen and 6=OpenDrawer. The [campaign plan](bench_server/protocol/plan.py) selects either the pair or all 50 once.

Target tasks use ten paired kitchens, layout/style pairs (1,1) through (10,10). The pretraining layout/style ranges 11–60 form a different candidate space. Individual task exclusions still apply; do not multiply all layout/style values indiscriminately. The native target reference uses 50 sampled scenarios per task, or 2500 target trials. **The native-aligned full sampler/schedule is not implemented here.** Fifty tasks sampled once is not full mode or complete 365-task evaluation.

## Environment and reset

Pin RoboCasa 1.0.1 at `b4684e6ee37d377cc392e98302a6b916d588b415`, Robosuite 1.5.2 at `85abee228d1c43ab1939bce33028099945d453b4`, MuJoCo 3.3.1 and NumPy 2.2.5. Each imported native package must resolve to its own clean Git root. See [setup](README.md).

Rendering is an explicit protocol choice. `render_track="native-v1"` preserves
the original descriptor ending in `/v1` and does not install a repair. It remains
the adapter default for historical compatibility, **not a reliability endorsement**:
this native EGL stack has a reproduced [lifecycle defect](environment/RENDERING.md).
`render_track="egl-owner-restore-v1"` has a descriptor ending in
`/egl-owner-restore-v1/v2`. That Linux/EGL-only track
installs the source-pinned, process-local ownership repair before any native
environment construction. It frees MuJoCo resources in their owning GL context,
restores another live previous EGL display/context/surfaces/API, and fails closed
on cleanup, GL readback or guard errors. No upstream file is modified. Use a new,
single-thread native process; tracks cannot be mixed in one process.

These two tracks keep the same scene sampler, constructor/reset behavior, cameras,
pixels and vertical flip, controls and scorer. There is no renderer replacement,
extra reset, pixel correction or success retry. Record the selected track and
private `render_lifecycle.json` receipt; do not merge repaired and historical RGB
results into one unqualified score. Geometry regression is not task acceptance:
native reset/control/media validation is also required for a deployment.

The service example explicitly selects a third, separate visual compatibility
track: `render_track="egl-owner-material-clamp-v1"`, descriptor suffix
`/egl-owner-material-clamp-v1/v3`. Native materials can contain shininess outside
`[0,1]`, which produces invalid OpenGL draw commands in this pinned runtime.
In addition to the lifecycle repair, v3 temporarily clamps only finite out-of-range
shininess on the current managed renderer's expanded scene, immediately around
the native draw, then restores every changed value in `finally`. Legal values are
not rewritten; non-finite values and restoration failures fail closed. It never
changes `mjModel`, XML, physics, task sampling, cameras, reset count or scoring.
**Pixels can change: this track is not native-pixel-equivalent.** No GL error is
ignored, and errors outside this narrowly declared conversion remain failures.
Compare only results with the same explicit rendering track. Native-v1 and v2
never enable this material conversion.

The selected fast reset uses seed 20260907 and the target split. Native construction may initialize a scene before the explicit seeded reset; retain this upstream behavior and record the actual reset. Do not search seeds, replace assets, resample initial success or force an easier kitchen.

## Observation contract

Expose native task language and three uint8 256 × 256 RGB cameras in order: left agent view, right agent view and eye-in-hand. Preserve the native Gym vertical flip; apply no extra crop, resize or policy-specific preprocessing. The exact camera keys are in the adapter observation specification.

This track has no proprioception. Do not expose object/world or end-effector ground truth, camera calibration, scene/reset metadata, reward/success or simulator handles. Only the evaluator can inspect native provenance and scorer state.

## Twelve-dimensional action

The native 20 Hz controller is `HYBRID_MOBILE_BASE`, with right-arm `OSC_POSE`, torso `JOINT_POSITION` and base `JOINT_VELOCITY_LEGACY`.

| Slice | Contract |
| --- | --- |
| `[0:3]` | Normalized current-base-frame end-effector translation, ±0.05 m |
| `[3:6]` | Normalized base-frame axis-angle delta, ±0.5 rad |
| `[6]` | Exact binary gripper: 0 open, 1 close; maps to native -1/+1 |
| `[7:10]` | Normalized native base forward/lateral/yaw velocity; scales ±1 m/s, ±1 m/s, ±1.5 rad/s |
| `[10]` | Normalized torso delta, ±0.05 m; native joint range 0–0.34 m |
| `[11]` | Exact binary base mode: 0 arm/achieved-goal update, 1 base/desired-goal update |

Base mode does not zero the other command dimensions. Preserve the native X-forward base transformation and native controller clipping behavior; do not insert a different frame conversion or high-level policy heuristic. Reject malformed, non-finite, out-of-bound or non-binary public commands instead of thresholding binary fields.

## Budgets and native scoring

The native engine retains horizon 1000 with `ignore_done=True`. The adapter's `budget_mode="horizon"` instead enforces the task reference: OpenDrawer 750 and NavigateKitchen 450. Target-set reference horizons range from 450 to 4350; 33 exceed 1000.

The explicit decision track permits D up to 200 maximum policy calls and K up to 5 controls per response, with cap D × K and matching runner settings. D=200/K=5 gives 1000 controls; it both extends and shortens different native task references. Record actual budgets and references separately, not as native leaderboard parity.

Native Gym returns `info.success` and sparse reward 1/0; require their agreement. Preserve native reward/scorer invocation multiplicity without an additional oracle query. Stop at first native success. Keep current native success, success-ever, termination and truncation distinct. Initial native success is an error before policy control, not a reset-search opportunity.

Count policy calls, action decisions and controls independently. A stop-only response has no action decision; a chunk can execute fewer than K controls. Record first-success control and its policy-call index from events. Voluntary-stop persistence belongs to the model profile and cannot delay evaluator caps or native termination.

## Evidence and limitations

Retain source/model/protocol identities, private compiled scene XML and initial state, actual reset metadata, controller specifications, per-action before/after records, delivered frames, counters, native outcomes, errors and decodable videos under the selected model's `results/robocasa365/` namespace.

Hash the **used scene asset closure** from compiled XML, includes and file dependencies. Missing/out-of-root references fail closed and must remain visible as incomplete provenance. This closure is not proof of the entire upstream asset universe.

Zero-policy reset/hold diagnostics and nonadaptive direction checks are infrastructure evidence only. Report selected, completed, failed, errored and unattempted tasks separately; never drop environment errors, substitute visual scoring or claim native-full parity from CPU/diagnostic checks.
