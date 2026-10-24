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

| Benchmark | Implemented service scope | Deployment requirements / limitations |
| --- | --- | --- |
| [SimplerEnv](SimplerEnv/README.md) | Google Robot / WidowX service | Matching SAPIEN assets and verified renderer device; reference appearance/pose sweeps are not exposed by the task/seed selector |
| [SIMPLE](SIMPLE/README.md) | 12-task humanoid service | Pinned WBC/assets; current selection uses DR0 and released episode 0 |
| [LIBERO](LIBERO/README.md) | Suite/task/initial-state selection | Dedicated source/runtime pins and released BDDL/reset files |
| [RoboDojo](RoboDojo/README.md) | Category sorting with 5-layout or 50-layout selection | Isaac license, native patches and matching asset manifest |
| [RoboCasa365](Robocasa_365/README.md) | 50 target tasks, one scenario each | Match EGL/material settings to the documented runtime; material clamping changes pixels |
| [RoboCasa Tabletop](Robocasa_tabletop/README.md) | 24 tasks with explicit seed lists | Pinned Python, controller, object inventory and renderer |
| [MetaWorld](MetaWorld/README.md) | 50 tasks | Version-pinned native package; select and record image orientation |
| [LIBERO-Plus](LIBERO-plus/README.md) | 10,030 perturbation variants | Separate source/assets and variation-aware resets, not a standard LIBERO alias |
| [RoboTwin](Robotwin/README.md) | Two tasks with joint-target actions | Matching SAPIEN/OIDN runtime and GPU; native seeds are not expert-screened |
| [DOMINO](DOMINO/README.md) | One fixed dynamic scenario with joint-target actions | Matching dynamic manifest/runtime; current interface requires observation after each target |
| [CALVIN](calvin/README.md) | One fixed five-subtask sequence | Pinned scene/reset data; observation after each action; no per-subtask policy-reset hook |
| [VLA-Arena](VLA-Arena/README.md) | 60 L0 tasks | Pinned source/assets and initial-state index 0; L1/L2 selection is unavailable |
| [BEHAVIOR](Behavior/README.md) | Seven fixed-case tasks, RGB224 + robot state | v3.9.2 runtime, licensed assets and task-bound manifest; observation differs from the challenge's RGB-D configuration |
| [VLN-CE](VLN-CE/README.md) | Protocol draft; no runnable adapter/server | Authorized MP3D scenes, pinned runtime and an implemented/validated adapter are required; public code does not grant scene-data rights |

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
3. Test serialization, counters, invalid actions, scorer isolation, source capture,
   media and cleanup without a simulator. Review these boundaries independently.
4. In an isolated compatible runtime, use a separately labelled no-model native
   diagnostic through the same server/client path. A diagnostic is not a task
   score and does not authorize a scored retry.
5. Only then schedule explicitly selected model attempts. Keep native sampling,
   frozen-campaign support and capability results separate from service availability.

Setup may download public assets without evaluating a model. It does not bypass
gated asset agreements, silently change reset distributions or launch a model trial.
See the [service protocol](SERVER_PROTOCOL.md) for transport and lifecycle details.
