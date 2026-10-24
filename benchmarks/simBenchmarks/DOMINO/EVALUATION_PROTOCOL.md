# DOMINO evaluation protocol

Native source: [`9c94f2d3a700fff3b65f041df4038d497139ed1f`](https://github.com/H-EmbodVis/DOMINO/tree/9c94f2d3a700fff3b65f041df4038d497139ed1f).

## Native tasks and variation

DOMINO defines **35 dynamic manipulation tasks**. The complete executable
inventory is the task modules in
[`envs/`](https://github.com/H-EmbodVis/DOMINO/tree/9c94f2d3a700fff3b65f041df4038d497139ed1f/envs),
including pressing, tool use, handover, object placement and bottle manipulation.
The horizon YAML also contains names without matching task modules and must not
be used to enlarge this task count.

Task names, scene randomization and object-motion settings are independent.
Native `use_dynamic` enables motion; `dynamic_level` selects complexity 1, 2 or
3; `dynamic_coefficient` scales speed (default 0.1). Clean and randomized scene
configurations retain RoboTwin 2.0's background, clutter, lighting and geometry
options. See the pinned
[dynamic configuration definition](https://github.com/H-EmbodVis/DOMINO/blob/9c94f2d3a700fff3b65f041df4038d497139ed1f/README.md#12-data-collection).

## Native episode selection and scoring

The [native evaluator](https://github.com/H-EmbodVis/DOMINO/blob/9c94f2d3a700fff3b65f041df4038d497139ed1f/script/eval_policy.py)
starts candidate seeds at `100000 * (1 + seed)` and expert-screens candidates
until 100 solvable episodes are accepted per task. Its optional fixed-manifest
mode uses previously accepted episodes. The manifest stores the seed and saved
dynamic motion data, including start position, trajectory parameters and RNG
state; `init_dynamic_motion_for_eval` uses that payload to initialize motion.
Native episode descriptions can vary with the accepted scene.

Binary native success determines success rate. `EvalMetricsTracker` also
provides route completion (RC), penalties and manipulation score
`MS = RC × penalty factors`. MS is a quality metric, not success percentage.
Native evaluator checks include required lifting, success, contact-stop,
workspace boundaries, other failure and task horizon. Their applicability is
task-specific; for example, `click_bell` has `stop_on_contact=False`.

## Current Bench Server selection

The adapter exposes only `click_bell` with the following configuration; this
is an integration restriction, not DOMINO's task definition. See
[service support](../SERVICE_SUPPORT.md).

- `demo_clean_dynamic`, aloha-agilex, dynamic level 1, coefficient 0.1;
  background/clutter randomization disabled.
- One predeclared native seed from a trusted private, hash-bound fixed
  episode manifest, one policy attempt. Default selected seed: 100000.
- Missing entries or failed dynamic initialization are errors, never triggers
  for resampling or automatic retries.
- Expert screening is separately authorized **private environment preparation**,
  not policy assistance or a public RPC. The service never invokes `play_once`.

`init_dynamic_motion_for_eval` requires the saved native motion payload.
All manifest data stays private; the service does not generate replacement
motion or turn dynamics off.

The service's `native_seed` must identify an existing manifest entry. It is a
uint32 identifier used by native initialization, not a layout selector; the
launch seed is a separate recorded field. No dynamic-level, layout, variant or
multi-seed overrides are exposed. Each deployment selects one task/manifest
entry.

Language uses the native task's fixed `full_description`, not randomized
episode-specific seen/unseen wording. This language selection differs explicitly
from the upstream model launcher's episode-specific instruction sampling.

## Public robot interface

| Channel | Contract |
| --- | --- |
| RGB | `head_camera`, `left_camera`, `right_camera`; native uint8 240×320 RGB; no rotation/crop/resize |
| State | 14 **commanded targets**, not measured encoders: left six arm targets, left normalized gripper, right six arm targets, right gripper |
| Action | 14 absolute native qpos targets, same order; arm values in radians |
| Gripper | Nominal 0 closed/1 open; native clipping, interpolation and mapping to `[-0.01,0.045]` metres unchanged |
| Control | One target per public step; prefix 1; native TOPP expands targets into variable physics ticks at 250Hz |
| Horizon | 400 native target calls, from pinned `click_bell` entry in `_eval_step_limit.yml` |

State channel names use `commanded_target_` and explicitly declare commanded
provenance. No service motion/joint-range guard is added: dimension/type/finiteness
checks are mandatory, while native controller constraints stay native. Optional
movement guards belong to agents. Physics ticks, started native targets, ACKs
and model decisions are recorded separately. Initialization/settling ticks are
not currently instrumented; do not report them as zero or model controls.

No object truth, depth, camera-calibration mapping, expert plan, dynamic
motion parameters, hidden score, branch rollout or task-planning RPC is exposed.
The EEF path is not selected: this track only uses qpos with native TOPP.

## Native scoring and termination

Native `take_action` owns physics and per-tick success checks and records one
metrics step per target, including early success. The wrapper retains evaluator
order: lifting requirement, success, dynamic contact-stop, boundary failure,
other native failure, horizon. `click_bell` declares `stop_on_contact=False`;
its moving bell is not silently frozen when contacted.

Native `EvalMetricsTracker` supplies route completion (RC), manipulation score
(MS) and penalties. MS is RC times penalty factors; it is **not success rate**.
Native Boolean success is authoritative. All scores/penalty details/actors stay
server/admin-private and never enter policy observations.

Bounded diagnostics or early policy stops may retain partial scores marked
`native_score_complete=false`, not completed native task scores. Transport/native
errors retain uncertain started controls without replay. Only error-free native
terminal outcomes set that flag. Malformed actions are rejected before execution
through shared service validation.

## Runtime conditions and reporting

The SM120 runtime uses Torch2.7.1+CUDA12.8, SAPIEN3.0.0b1 and an owned
OIDN2.3.3 overlay. Upstream uses Torch2.4.1. CuRobo is pinned to v0.7.8 revision
`d64c4b005459db10c5dd867d8b30a87d5bda9bdb`. Keep these runtime conditions
explicit; [environment setup](environment/README.md) describes preparation.

Report task/manifest entry, native seed, native Boolean success, MS, RC,
score completeness, termination/error reason and separate decision/target/
physics counts. MS is a quality score, not a substitute for success rate.
Declare the selected native task and manifest entries independently of the
benchmark task count.

Videos present control-boundary samples at 10 fps, not real-time physics.
Optional interaction/media retention is described in
[recording](../../../docs/recording.md).
