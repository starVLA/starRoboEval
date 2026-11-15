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
- Predeclared accepted entries of a trusted private, hash-bound fixed episode
  manifest, one policy attempt each (modes below).
- Missing entries or failed dynamic initialization are errors, never triggers
  for resampling or automatic retries.
- Expert screening is separately authorized **private environment preparation**,
  not policy assistance or a public RPC. The service never invokes `play_once`.

`init_dynamic_motion_for_eval` requires the saved native motion payload.
All manifest data stays private; the service does not generate replacement
motion or turn dynamics off.

The manifest lists native accepted entries in candidate-seed order (from
100000, expert-screened during preparation). `evaluation_mode` selects entries
by one-based ordinal; omitted means `fast`:

| Mode | Manifest entries | Episodes | Cap per episode |
| --- | --- | ---: | ---: |
| `fast` (default) | 1, 2, 3, 4, 5 | 5 | 400 |
| `max` | 1–100, the complete native accepted set for `click_bell` / `demo_clean_dynamic` | 100 | 400 |
| `example` | 1 | 1 | 400 |

`max` reproduces the native per-(task, config) count: `eval_policy.py` sets
`test_num = 100` at eval seed 0. At startup the service refuses a `max` launch
unless the hash-bound manifest is the complete native screening record:

- metadata `format_version` 1, `git_commit` equal to the pinned revision,
  `task_name` `click_bell`, `task_config` `demo_clean_dynamic`, embodiment
  `aloha-agilex`, `cli_seed` 0, `st_seed` 100000, `test_num` 100, dynamic level
  1 and coefficient 0.1;
- exactly 100 accepted entries with unique ascending integer seeds, each with
  its `dynamic_motion_info` payload;
- every rejected seed logged with a native reason (`unstable`, `exception`,
  `expert_check_fail`, `dynamic_validation_fail`), and accepted plus rejected
  seeds forming one contiguous walk from 100000 to the 100th acceptance.

Upstream itself only warns about a short manifest and then evaluates fewer
episodes; the service refuses it instead. Rejections are preparation
provenance, recorded with the reset, never policy results. The service never
prepares, searches or edits the manifest. The preparation procedure is in
[environment setup](environment/README.md#private-fixed-episode-preparation-gate);
it has not yet been performed for this deployment. `fast` and `example` read
entries from the same kind of manifest and only need their entries present.

The benchmark-scope `max` set is the union of such deployments over the 35
tasks × {`demo_clean_dynamic`, `demo_random_dynamic`}, 100 accepted episodes
each (7,000 episodes). Only `click_bell` / `demo_clean_dynamic` is deployable
now. Whether published DOMINO results also count dynamic levels 2–3 is
UNVERIFIED; both pinned dynamic configs use level 1.

Episode IDs are `click_bell-manifest-entry{ordinal:03d}-episode000`. The reset
reads the entry's native seed and motion payload; the launch seed is a separate
recorded field. No dynamic-level, layout or variant overrides are exposed. One
process claims one episode, so launch each with `--episode-id`. The protocol
identity names the mode before its version, e.g.
`domino-9c94f2d/click-bell-fixed-manifest/qpos14-rgb-commanded-state/fast/v1`.

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
| Control | One target per public step; native TOPP expands targets into variable physics ticks at 250Hz |
| Horizon | 400 native target calls, from pinned `click_bell` entry in `_eval_step_limit.yml` |

State channel names use `commanded_target_` and explicitly declare commanded
provenance. No service motion/joint-range guard is added: dimension/type/finiteness
checks are mandatory, while native controller constraints stay native. Optional
movement guards belong to agents. The action spec therefore declares no
`low`/`high`: the native qpos path publishes no action bounds, and any service
range would be a non-native guard. NaN or infinite values are rejected as
`non_finite` before execution; finite out-of-range targets reach native
`take_action` unchanged. Physics ticks, started native targets, ACKs
and model decisions are recorded separately. Initialization/settling ticks are
not currently instrumented; do not report them as zero or model controls.

The current interface declares no mandatory action
prefix and does not require a model call after each target. The agent chooses
grouping; the service acknowledges each target separately and applies native
termination and the 400-target limit before accepting another. Native TOPP,
physics frequency, dynamics and scoring are unchanged. Report the returned
protocol identity.

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
