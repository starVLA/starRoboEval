# RoboTwin

RoboTwin 2.0 evaluates bimanual robotic manipulation across household and
tabletop tasks. Its native task definitions cover coordinated lifting,
handover, object placement, tool use and articulated-object operation.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): task/reset selection, joint
  commands, timing, observations and native success.
- [Environment setup](environment/README.md): required archive, runtime,
  deployment preparation and renderer selection.
- [Shared service protocol](../SERVER_PROTOCOL.md): authenticated connection,
  lifecycle and result collection.

## Native tasks and scene variation

The official [50-task catalog](https://robotwin-platform.github.io/doc/tasks/index.html)
includes tasks such as `lift_pot`, `handover_block`, `open_microwave`,
`beat_block_hammer`, `stack_bowls_three` and `click_bell`. Each task defines its
objects, initialization and native success predicate; these examples are not
the entire benchmark task set.

Native scene configuration is separate from task identity. Clean and randomized
settings control backgrounds, clutter, lighting, table height and head-camera
perturbations. Task code also samples eligible object variants and placements.
The native framework supports multiple robot embodiments; specify the
embodiment and scene configuration along with the task. See the
[native configuration guide](https://robotwin-platform.github.io/doc/usage/configurations.html).

The reference evaluator screens candidate seeds with the expert planner until
100 solvable episodes are accepted per task, then evaluates the participant on
those scenes. This is initialization selection, not a task-count definition.
Success comes from the task's native predicate; target-control limits are
task-specific. The [protocol](EVALUATION_PROTOCOL.md) distinguishes this native
sampling procedure from the service sampler below.

## Current Bench Server integration

The current adapter exposes native Aloha joint control for the following two
tasks under `demo_clean`; it does not expose all 50 tasks or randomized settings.
See [service support](../SERVICE_SUPPORT.md).

| Task | Task description | Native control budget |
| --- | --- | ---: |
| `lift_pot` | Lift the pot | 400 target controls |
| `click_bell` | Press the bell | 400 target controls |

`evaluation_mode` selects the native seeds for the configured `task`; omit it
for `fast`. Each episode is one attempt at one native seed.

| Mode | Selection per task | Episodes | Cap |
| --- | --- | ---: | ---: |
| `fast` (default) | native seeds 100000–100004, `demo_clean` | 5 | 400 |
| `max` | 100 accepted seeds from a hash-bound accepted-seed manifest | 100 | 400 |
| `example` | native seed 100000 | 1 | 400 |

The `task` selector narrows within the chosen mode to one task per service.
One process claims one episode: launch each episode with `--episode-id`.

`fast` and `example` seeds are unscreened, unlike native sampling, and use the
native fixed `full_description`. `max` reads the native screening record
prepared offline: 100 accepted seeds, every rejection, and the native
instruction drawn for each accepted seed. Startup refuses an incomplete record
and names the preparation step; see the [protocol](EVALUATION_PROTOCOL.md#max-accepted-seed-manifest).
No expert runs and no seed is selected by outcome during a participant attempt.
Both native object variants for each supported task are retained.

The native seed controls native scene generation; it is not a layout or
object-variant ID. `lift_pot` keeps pot variants 0 and 1; `click_bell` keeps
bell variants 0 and 1. Native seeded sampling selects the variant/placement.

## Service robot interface

| Channel | Published contract |
| --- | --- |
| RGB | `head_camera`, `left_camera`, `right_camera`; native 320 × 240 RGB |
| State | 12 measured arm joint angles and two **commanded** gripper values |
| Action | 14 absolute targets: six left-arm joints, left gripper, six right-arm joints, right gripper |
| Units | Arm radians; normalized grippers, 0 closed / 1 open |
| Execution | Native qpos/TOPP interpolation; variable number of 250-Hz physics ticks per target |
| Success | Native cached `eval_success`; first success ends the episode |

The **14-dimensional action** is ordered as follows:

| Slots | Meaning and units |
| --- | --- |
| 0–5 | Left `fl_joint1` through `fl_joint6`, absolute native joint coordinates in radians |
| 6 | Absolute left gripper command in [0,1]: 0 closed, 1 open |
| 7–12 | Right `fr_joint1` through `fr_joint6`, absolute native joint coordinates in radians |
| 13 | Absolute right gripper command in [0,1]: 0 closed, 1 open |

Arm command bounds are [-10,10] rad. Grippers use the native [-0.01,0.045] m
scale. These are joint coordinates, not world/base-frame EEF deltas. Native
TOPP determines a variable target duration in 4 ms physics ticks; there is no
fixed wall-time duration per target or fixed control frequency.

The two gripper values are command history, not measured opening or grasp
evidence. The [protocol](EVALUATION_PROTOCOL.md#observation-boundary) specifies
all state names and sources. Object poses, depth, expert trajectories, task
metadata and private scoring are excluded from agent observations.

One service step executes one target. The agent chooses how many targets to
send between decisions; the native 400-control horizon remains authoritative.
Video FPS is not control frequency: target durations vary with interpolation.
Native setup/settling is distinct from participant actions.

## Start the benchmark service

Prepare the matching deployment and native environment using
[environment/README.md](environment/README.md). Copy
[server.example.json](server.example.json) to an operator-owned file and replace
`source_root` and `deployment_manifest_sha256` with its verified values. Select
`task`, `evaluation_mode` and renderer track before launching. For `max`, also
add `seed_manifest` (absolute path) and, to pin it, `seed_manifest_sha256`: a
given pin must match; without one the observed hash is recorded unpinned. The all-zero digest
is a placeholder, not a runnable deployment identity.

Set `RSI_SIM_SERVER_TOKEN` privately in the server and trusted evaluator
environments as described in the [connection guide](../SERVER_PROTOCOL.md#launch-and-connect).
From the repository root, using the prepared native interpreter:

```sh
python -B -m benchmarks.simBenchmarks.Robotwin.server \
  --parameters /absolute/robotwin-server.json \
  --seed 20260907 --episode-id lift_pot-native-seed100000-episode000 --port 8771 \
  --output-dir /absolute/new-robotwin-run/server
```

The launch `--seed` is recorded separately from each episode's native scene
seed. `--list-episodes` prints the episode IDs of the selected mode. The service binds loopback; use SSH forwarding for a remote evaluator.
Startup/description performs zero resets. A trusted participant driver connects
through the shared protocol and gives its agent only the declared observations.
Its model, prompts, tools and decision loop are independent of this package.

Use `-B` to keep bytecode out of pinned sources. Native JIT outputs are isolated
in episode-local `cache/curobo-jit`, excluded from artifact transfer. Close and
stop this one-episode service after results are collected; native `close_env`
alone does not demonstrate GPU-memory reclamation. Never replay a control after
an uncertain acknowledgement.

## Results

Report the task, native seed, renderer/protocol identity, native outcome and
separate counts for decisions, target controls and physics ticks. Errors can
leave an in-flight target partly executed; preserve that uncertainty separately
from acknowledged transitions.

Optional videos are `head_camera.mp4`, `left_camera.mp4` and
`right_camera.mp4`. Their 10-fps playback presents control-boundary samples,
not real-time physics. See [recording guidance](../../../docs/recording.md) for
default server media ownership and optional frame retention.

## Runtime requirements

The source pin is an archive content inventory, not a verified upstream Git
revision. Fresh upstream bootstrapping, accepted-seed preparation and the other
48 tasks remain unsupported. The bundled OIDN 2.0.1 and opt-in OIDN 2.3.3 renderer tracks have
different protocol identities and do not claim interchangeable pixels/scores.
Validate rendering and controls on the intended deployment before evaluation.

`server.py` is the launcher, `bench_server/adapter.py` owns the two-task
contract and native scoring, and `environment/` owns deployment and runtime
verification. Participant methods and their results live outside this package.
