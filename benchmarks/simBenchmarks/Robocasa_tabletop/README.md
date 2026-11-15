# RoboCasa GR1 Tabletop

[RoboCasa GR1 Tabletop](https://github.com/robocasa/robocasa-gr1-tabletop-tasks)
evaluates humanoid upper-body manipulation: placing objects in containers,
closing drawers and doors, and transferring novel objects between receptacles.
The robot is GR1 with arms, dexterous hands and waist control. This integration
is separate from the PandaOmron [RoboCasa365](../Robocasa_365/README.md) service.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): complete task catalog, sampling,
  native scoring, control bounds and differences from the native evaluator.
- [Environment setup](environment/README.md): pinned native sources, object
  inventory and readiness diagnostics.
- [Robot interface reference](bench_server/protocol/POLICY_GUIDE.md): measured
  encoders, joint target order and units.
- [Shared service protocol](../SERVER_PROTOCOL.md): connection and lifecycle.

## Native tasks, layouts and variation

The [official task list](https://github.com/robocasa/robocasa-gr1-tabletop-tasks/blob/4840e671596f93ca03651524b9f72ffb1aadfeff/README.md#simulation-based-evaluation-for-gr00t-n15-3b)
contains **24 tasks**: six container-closing tasks and eighteen novel-object
placement tasks. The [complete task table](EVALUATION_PROTOCOL.md#native-task-catalog)
and [catalog](bench_server/protocol/task_catalog.json) preserve its ordering.

| Native task family | Tasks | Layout candidates |
| --- | ---: | --- |
| Put a cup/can in a drawer and close it | 2 | Layout 4 |
| Put a potato/milk in a microwave and close it | 2 | Layout 2 |
| Put a bottle/wine in a cabinet and close it | 2 | Layout 5 |
| Transfer a novel object from a cutting board, placemat, plate or tray | 18 | Layout 0 |

Each task has one eligible layout and **12 style candidates (0–11)**. Native
sampling selects the style, object and placement; repeated samples can reuse
the same style. The eighteen placement tasks are the named `SplitA` tasks in
the official list; other registered pretraining or `SplitB` environments do not
enlarge this 24-task benchmark set.

Native success is task-specific: containment and closure for container tasks,
and the required placement/release conditions for novel-object tasks. The pinned
upstream evaluation uses **720 controls per episode and 10 episodes per
task**; it does not enumerate all initializations.

## Current Bench Server integration

The service runs all 24 task identities. `evaluation_mode` selects the seeded
samples; see [service support](../SERVICE_SUPPORT.md).

| `evaluation_mode` | Selection | Episodes | Cap |
| --- | --- | ---: | --- |
| `fast` (default) | 24 tasks × seeds 20261020–20261021, one attempt each | 48 | 720 controls |
| `max` | 24 tasks × seeds 20261020–20261029, one attempt each | 240 | 720 controls |
| `example` | Task 0 at seed 20261020 | 1 | 720 controls |

Launch with `--seed 20261020`; sample *k* resets with seed 20261020 + *k*. The
schedule is sample-major: all 24 tasks with the first seed, then all 24 with
the next. `max` follows the upstream example's ten episodes per task with
consecutive seeds, because that example does not pin its seeds. Seeds are not
layout IDs. The service exposes no independent layout/style selector and does
not enumerate all native initializations. `--episodes` and `--episode-id`
narrow the schedule within the chosen mode.

## Service robot interface and scoring

| Property | Published contract |
| --- | --- |
| Observation | Native task language, one 256 × 256 egocentric RGB image and 29 measured joint encoders in radians |
| Action | 29 absolute joint targets: left arm 7, right arm 7, left hand 6, right hand 6, waist 3 |
| Control | Native BASIC composite joint controller at 20 Hz; one action per service step |
| Success | Native task predicate via `info.success`; stop at first native success |
| Execution budget | Upstream evaluator's 720 controls per episode (`--max_episode_steps 720`) |

The **29-dimensional action** specifies absolute positions in each native joint's
coordinate system, in radians:

| Slots | Joint order |
| --- | --- |
| 0–6 | Left shoulder pitch/roll/yaw, elbow pitch, wrist yaw/roll/pitch |
| 7–13 | Right arm in the same order |
| 14–19 | Left pinky, ring, middle, index, thumb pitch/yaw |
| 20–25 | Right hand in the same order |
| 26–28 | Waist yaw/pitch/roll |

There is no binary open/close gripper field; each hand uses six joint targets
expanded to eleven native actuators. One vector advances 50 ms. Actions are
not EEF poses, normalized outputs or velocities. The
[protocol](EVALUATION_PROTOCOL.md#absolute-29-dimensional-joint-action)
defines command bounds and finger coupling. Native success
conditions differ by task; a visual impression of placement or agent-declared
completion does not replace the scorer.

The service leaves decision frequency and action grouping to the agent's
trusted driver. Every mode uses the pinned upstream cap of 720 controls; the
native engine horizon of 1000 is an engine setting, not the evaluated cap.
Upstream seeds are unpinned, so the service cannot reproduce those episodes
exactly; report the consecutive seed panel as a different condition.

## Start the benchmark service

Follow [environment setup](environment/README.md), then copy
[server.example.json](server.example.json) into an operator-owned file. Replace
`casa_source`, `suite_source`, `object_inventory` and the GPU with verified
deployment values. The example selects the fast mode: 48 episodes.

Supply the private `RSI_SIM_SERVER_TOKEN` only to the server and trusted
evaluator; see [connection setup](../SERVER_PROTOCOL.md#launch-and-connect).
From the repository root, using the pinned **Python 3.10.21** native environment:

```sh
PYTHONHASHSEED=0 python -B -m benchmarks.simBenchmarks.Robocasa_tabletop.server \
  --parameters /absolute/tabletop-server.json \
  --seed 20261020 --episodes 1 --port 8768 \
  --output-dir /absolute/new-tabletop-run/server
```

`PYTHONHASHSEED=0` must be set before Python starts. The service binds loopback
and freezes its schedule without resetting the simulator. A trusted driver
connects through the shared interface; it projects only declared language,
camera and encoder channels to its agent. It keeps credentials, simulator
handles, task reset data and scoring private. See the general
[agent integration guide](../../../docs/agent-methods.md).

### NVML resource index and EGL renderer index

`render_gpu_device_id` selects the NVML index recorded with the episode.
Optional `egl_device_id` independently selects the EGL renderer; when omitted,
it defaults to the same integer. Both must be nonnegative integers. NVIDIA and
EGL enumeration can differ.

Before claiming a case on a new deployment, use a renderer-only preflight to
match the actual graphics process by UUID / PCI address to the intended GPU.
Set an explicit EGL index if needed; the service does not guess mappings or
fall back to another device. Keep the verified mapping fixed during the run.

## Reporting and deployment

Record the evaluation mode, task indices, seeds, native outcome, protocol and budget, decisions,
controls and errors.

The server always writes native evaluator records into the bound episode
directory: provenance, controller contract, native episode metadata, initial
state and scene XML, used-asset manifest, per-step egoview PNGs with
`frames.jsonl`, native action events and the egoview MP4 with its decode check.
Reset refuses to start without that directory, and these records cannot be
switched off. Client-side interaction recording and copying media into results
are [optional](../../../docs/recording.md); essential outcomes and counters are
always retained.

The asset contract certifies a provisioned snapshot, not the entire official
release. Preserve native missing-category warnings and the reported used-scene
asset coverage. Portable all-assets provisioning remains incomplete.

`server.py` launches the service; `bench_server/adapter.py` owns sensor/action
mapping and native scoring; `bench_server/protocol/` holds task and robot
contracts; `environment/` contains native setup and diagnostics. Participant
methods, configurations and results remain outside this benchmark package.
