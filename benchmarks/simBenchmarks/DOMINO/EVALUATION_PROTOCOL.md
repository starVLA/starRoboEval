# DOMINO direct-control protocol

Identity: `domino-9c94f2d/click-bell-fixed-manifest/qpos14-rgb-commanded-state/sm120-v1`.
This is an implemented **compatibility/debug track**, with native execution
acceptance pending. Offline tests do not establish a SIM score or full parity.

Upstream has 35 dynamic manipulation tasks. This service implements **only
`click_bell`**, pinned to
[`9c94f2d3a700fff3b65f041df4038d497139ed1f`](https://github.com/H-EmbodVis/DOMINO/tree/9c94f2d3a700fff3b65f041df4038d497139ed1f).
The horizon YAML contains historical names without matching task sources; it is
not an executable task catalog.

## Frozen scene selection

- `demo_clean_dynamic`, aloha-agilex, dynamic level 1, coefficient 0.1;
  background/clutter randomization disabled.
- `fast`: one predeclared native seed from a trusted private, hash-bound fixed
  episode manifest, one policy attempt. Default selected seed: 100000.
- Missing entries or failed dynamic initialization are errors, never triggers
  for resampling or automatic retries.
- `full` is not implemented. Upstream's default evaluator expert-screens
  candidates until 100 solvable episodes are found. Its optional fixed-manifest
  mode retains those accepted episodes and associated dynamic motion data.
- Expert screening is separately authorized **private environment preparation**,
  not policy assistance or a public RPC. Preparation attempts/resets have their
  own evidence and counters. The service never invokes `play_once`.

`init_dynamic_motion_for_eval` requires the saved native motion payload.
Copying a seed alone, inventing a trajectory or turning dynamics off is not the
reference evaluation. An exactly-one-candidate preparation diagnostic is not
the upstream 100-accepted-episode matrix. All manifest data stays private.

Language uses the native task's fixed `full_description`, not randomized
episode-specific seen/unseen wording. This language selection differs explicitly
from the upstream model launcher; no full-parity claim is made.

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

No object truth, depth, full camera-calibration mapping, expert plan, dynamic
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

## Runtime and evidence

The **SM120 compatibility track** records Torch2.7.1+CUDA12.8, SAPIEN3.0.0b1
and an owned OIDN2.3.3 overlay. It does not claim upstream Torch2.4.1 runtime
parity. CuRobo is pinned to v0.7.8 revision
`d64c4b005459db10c5dd867d8b30a87d5bda9bdb`.
Native source, assets, path-only derived configs and selected runtime files are
hash-bound; JIT output is isolated in an episode-owned cache.

Retain trusted manifest hash, configuration, all attempts/errors, control/ACK/
physics counts, closed native outcome, cleanup and three-camera video.
Video uses 10fps presentation, not physical control frequency. Model results
belong under `AgentPolicies/<agent>/results/domino/`; no-model diagnostics have
separate, explicit ignored diagnostic storage.
