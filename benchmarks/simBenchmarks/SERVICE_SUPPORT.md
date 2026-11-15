# Service scope and deployment requirements

Use the [benchmark overview](README.md#choose-a-benchmark) to compare native
benchmark definitions. This page separately lists current interface coverage
and what is needed to deploy each service. Installing
this repository does not install the native simulators or grant asset licenses.

The implemented services below share the RoboDojo-derived directory
layout: `server.py`, `bench_server/adapter.py`, separate definitions under
`bench_server/protocol/` when needed, and native runtime under `environment/`.
Each service executes the declared robot actions and uses the native scorer;
it does not include a task-solving policy. This table describes the public
service, not a particular agent's results. A restricted adapter does not reduce
the task universe of its upstream benchmark.

Each service takes one `evaluation_mode`: `fast` (default) is the documented
evaluation subset, `max` the benchmark's official scope and `example` the first
`fast` episode. Step caps are native horizons.

| Benchmark | Implemented service scope | Deployment requirements / limitations |
| --- | --- | --- |
| [SimplerEnv](SimplerEnv/README.md) | One Google Robot / WidowX task per service; fast: 5 seeded resets; max: one pinned reference matrix per run, chosen with `reference_matrix` (visual matching, 960 episodes over 15 tasks; variant aggregation, Google tasks only, 1,992) | Matching SAPIEN assets and verified renderer device; hash-pinned real overlays; ray tracing for drawer/apple matrices; matrices are separate runs, never pooled |
| [SIMPLE](SIMPLE/README.md) | 12 released humanoid tasks, one per service; fast: DR0 episodes 0–4; max: DR0–DR2 × episodes 0–9 (30 per task, 360 total) at native success thresholds | Pinned WBC/assets; DR1/DR2 reset files are hash-recorded but not pinned |
| [LIBERO](LIBERO/README.md) | One suite per service; fast: all tasks × initial states 0–4; max: all 50 released states | Dedicated source/runtime pins and released BDDL/reset files |
| [RoboDojo](RoboDojo/README.md) | Category sorting; fast: layouts 0–4 (not stability-screened); max: the first 50 reset-stable layouts of 0–54 from a reset-stability manifest (preparation not yet performed) | Isaac license, native patches and matching asset manifest; complete schedule of the selected mode |
| [RoboCasa365](Robocasa_365/README.md) | 50 target tasks; fast: 5 attempts on one fixed scenario each; max: 50 seeded scenarios each (seeds 20260907+0..49, 2500 episodes) | Match EGL/material settings to the documented runtime; material clamping changes pixels |
| [RoboCasa Tabletop](Robocasa_tabletop/README.md) | 24 tasks; fast: 2 seeds each; max: 10 seeds each; 720-control cap | Pinned Python, controller, object inventory and renderer |
| [MetaWorld](MetaWorld/README.md) | 50 tasks; fast: 5 seeded trials each; max: 50 native MT50 goals each (goal-pool seed 4042, 2500 episodes) | Version-pinned native package; select and record image orientation |
| [LIBERO-Plus](LIBERO-plus/README.md) | One suite per service; fast: 5 ranked variants per base task and category (349 per suite); max: every variant; initial state 0 | Separate source/assets and variation-aware resets, not a standard LIBERO alias |
| [RoboTwin](Robotwin/README.md) | Two tasks with joint-target actions, one per service; fast: native seeds 100000–100004 (unscreened); max: the 100 accepted seeds and recorded native instructions of a hash-bound expert-screened seed manifest (preparation not yet performed) | Matching SAPIEN/OIDN runtime and GPU; fast seeds are not expert-screened; one case per process |
| [DOMINO](DOMINO/README.md) | One dynamic task with joint-target actions; fast: first 5 accepted manifest entries; max: all 100 entries of a complete, hash-bound native screening manifest (preparation not yet performed) | Matching dynamic manifest/runtime; no mandatory action prefix, each target acknowledged separately within the 400-target limit |
| [CALVIN](calvin/README.md) | 34 independent single-task cases × 4 pinned D validation resets (fast); max: native 1,000 five-subtask chains (calvin-chain0000–0999) | Pinned scene/reset data and hash-pinned chain list; no mandatory action prefix; 360 controls per case or per subtask (chain ≤1,800, no reset between subtasks); one case per process |
| [VLA-Arena](VLA-Arena/README.md) | 170 tasks, L0–L2; fast: 5 trials with initial states 0–4; max: 10 trials from the native default state | Pinned source/assets; perturbation flags off; long-horizon L1/L2 episodes carry a 600-control cap, others 300 |
| [BEHAVIOR](Behavior/README.md) | Seven tasks, one per service, RGB224 + robot state; fast: public instances 0–4; max: public instances 0–9 (10 per task) | v3.9.2 runtime, licensed assets and task-bound manifest; only instance 301 is hash-pinned; other instances record their observed state hash; observation differs from the challenge's RGB-D configuration |
| [VLN-CE](VLN-CE/README.md) | R2R val_seen/val_unseen, RGB512 and four native navigation actions; fast: up to 40 ranked routes per scene (373 on val_unseen); max: whole split | Habitat 0.3.3 worker and authorized MP3D assets; native success/SPL/distance, no nDTW or old-runtime parity claim |

Use each benchmark's protocol for its exact task/variation universe and supported
subset. A local installation in another user's workspace is only a readiness lead,
not a portable dependency specification or permission to alter that installation.
Reuse compatible verified assets read-only; install missing public dependencies
in a separate environment. Keep downloaded assets and environment-specific paths
out of Git. Do not bypass licence gates or replace missing selected scenes/tasks.

## Accepting another service

Apply the [shared service conventions](SERVICE_CONVENTIONS.md), derived from
RoboDojo. Directory cleanup alone is not service acceptance; the same review,
offline regression, native-readiness and separately authorized model-sample
gates apply to each added benchmark.

1. Pin native code/assets and inspect its evaluator, reset, physical actions,
   observation allowlist and scorer. Separate native setup from task-solving code.
2. Implement a lazy benchmark-owned adapter and server: construction/description
   must not reset a simulator. Predeclare tasks/seeds; retain one-attempt claims.
3. Check serialization, counters, invalid actions, scorer isolation, source capture,
   media and cleanup without a simulator. Keep these checks local and untracked.
   Review these boundaries independently.
4. In an isolated compatible runtime, run the shared no-model
   [readiness probe](SERVER_PROTOCOL.md#readiness-probe) through the same
   server/client path. A probe is not a task score and does not authorize a
   scored retry.
5. Only then schedule explicitly selected model attempts. Keep native sampling
   and capability results separate from service availability.

Setup may download public assets without evaluating a model. It does not bypass
gated asset agreements, silently change reset distributions or launch a model trial.
See the [service protocol](SERVER_PROTOCOL.md) for transport and lifecycle details.
