# Native service support and remaining gates

An entrypoint, an installed environment, a successful reset/control diagnostic
and a model capability score are different evidence levels. Do not infer one
from another. Every active service exposes only the benchmark's declared physical
actions; no task-solving policy or expert action service is added.

The implemented services below share the RoboDojo-derived directory
layout: `server.py`, `bench_server/adapter.py`, separate definitions under
`bench_server/protocol/` when needed, and native runtime under `environment/`.
No root adapter/evaluation compatibility packages remain. This structural
conformance is separate from the native acceptance and full-schedule gates below.

| Benchmark | Native service integration | Remaining gate / next work |
| --- | --- | --- |
| [SimplerEnv](SimplerEnv/README.md) | Development adapter and SIM server | Fast cases only; native full VM/VA schedule pending |
| [SIMPLE](SIMPLE/README.md) | Development adapter and SIM server | Pinned WBC/assets required; full schedule pending |
| [LIBERO](LIBERO/README.md) | Development adapter and SIM server | Dedicated source/runtime pins; service entrypoint alone is not native parity |
| [RoboDojo](RoboDojo/README.md) | Development adapter and SIM server | Isaac licence, native patches and asset manifest must match the declared track |
| [RoboCasa365](Robocasa_365/README.md) | Development adapter and SIM server; explicit EGL lifecycle/material compatibility tracks | Historical native rendering has known defects; validate the selected track's native RGB on the deployment; material clamping is not native pixel parity |
| [RoboCasa Tabletop](Robocasa_tabletop/README.md) | Development adapter and SIM server | Exact Python/hash, controller, object inventory and renderer requirements |
| [MetaWorld](MetaWorld/README.md) | Development adapter and SIM server | Version-pinned native package; explicit camera-orientation tracks; no frozen full campaign |
| [LIBERO-Plus](LIBERO-plus/README.md) | Development adapter and SIM server | Separate source/assets and variation-aware reset mapping, not a standard LIBERO alias |
| [RoboTwin](Robotwin/README.md) | Two-task direct-qpos development SIM server with measured arm joints and labeled gripper commands; explicit OIDN 2.3.3 CUDA compatibility track | New state14 observation track requires native acceptance; previous RGB-only zero-action sample does not validate model actuation; matching source/runtime/GPU required; no expert-filtered full sampling |
| [DOMINO](DOMINO/README.md) | One-task fixed-manifest direct-qpos development service; explicit SM120 compatibility track | Native validation pending; requires a pinned private dynamic manifest and owned deployment. No online expert control, full-suite support or upstream-runtime parity claim |
| [CALVIN](calvin/README.md) | Debug-assets single-sequence development SIM server | Frozen five-subtask fast track; prefix 1 required; not native D validation/full sequence parity |
| [VLA-Arena](VLA-Arena/README.md) | Level-0 direct-control development SIM server | Public pinned source/assets, separate native success/cost/timeout; higher levels and full parity pending |
| [BEHAVIOR-1K](Behavior/README.md) | 2026 v3.9.2 one-task development server; explicit low-resolution RGB + proprioception debug track | One fixed-case HTTP native smoke passed: reset, two controls/eight physics ticks, three RGB views/videos, clean close; zero model calls. Dedicated runtime and licensed assets required. No full-resolution RGB-D or full challenge parity claim; 2025 inventory is historical |
| [VLN-CE](VLN-CE/README.md) | Deferred: licensed MP3D scenes | Authorized scenes must be supplied; public code does not grant scene-data rights |

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
5. Only then schedule explicitly selected model attempts. Keep native full sampling,
   frozen-campaign support and capability results separate from service availability.

Setup may download public assets without evaluating a model. It does not bypass
gated asset agreements, silently change reset distributions or launch a model trial.
See the [service protocol](SERVER_PROTOCOL.md) for transport and lifecycle details.
