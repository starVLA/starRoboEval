# DOMINO

DOMINO evaluates manipulation of **moving objects**. Its native evaluation
reports task success and manipulation quality, including route completion and
penalties. Tasks require interaction with objects whose motion continues during
robot control, rather than only with static initial placements.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): scene selection, public robot
  interface, control timing and native SR/MS definitions.
- [Environment setup](environment/README.md): native sources, assets, runtime
  and private fixed-episode preparation.
- [Server configuration](server.example.json).
- [Shared service protocol](../SERVER_PROTOCOL.md).

## Native tasks, motion and evaluation

DOMINO contains **35 dynamic manipulation tasks** at the
[pinned release](https://github.com/H-EmbodVis/DOMINO/tree/9c94f2d3a700fff3b65f041df4038d497139ed1f/envs).
They include moving-object interaction (`click_bell`, `click_alarmclock`),
handover (`handover_block`, `handover_mic`), placement (`place_object_basket`,
`place_phone_stand`), tool use (`beat_block_hammer`, `stamp_seal`) and object
manipulation (`adjust_bottle`, `shake_bottle`). The linked native task directory
is the complete task inventory; a horizon table alone is not the inventory.

Native task configuration separates task identity from motion and scene
variation:

| Native setting | Meaning |
| --- | --- |
| `use_dynamic` | Enable object motion |
| `dynamic_level` | Motion-complexity level 1, 2 or 3 |
| `dynamic_coefficient` | Motion-speed scale; default 0.1 |
| Clean/randomized scene configuration | Appearance and scene variation inherited from RoboTwin 2.0 |

The native evaluator normally accepts **100 expert-screened solvable episodes
per task**. Its optional fixed-episode mode saves accepted seeds together with
motion start positions, trajectory parameters and RNG state for paired
comparisons. A seed alone does not reproduce that motion initialization.
See the pinned [configuration and evaluation guide](https://github.com/H-EmbodVis/DOMINO/blob/9c94f2d3a700fff3b65f041df4038d497139ed1f/README.md#13-policy-evaluation).

Native scoring reports binary task success and manipulation score (MS).
MS combines route completion with penalties such as collisions and leaving the
workspace; it is not a success percentage. Task-specific native limits and
failure conditions govern termination.

## Current Bench Server integration

The current service exposes `click_bell` through Aloha joint control under the
settings below; other tasks and motion levels are not selectable. See
[service support](../SERVICE_SUPPORT.md).

| Setting | Supported selection |
| --- | --- |
| Native revision | `9c94f2d3a700fff3b65f041df4038d497139ed1f` |
| Scene | `demo_clean_dynamic`, aloha-agilex, dynamic level 1, coefficient 0.1 |
| Case selection | One predeclared entry from a trusted private fixed-episode manifest |
| Default native seed | 100000, selected before evaluation |
| Samples | One selected manifest entry per deployment; the upstream 100-accepted-case schedule is not exposed |

A seed alone is insufficient: the native manifest also carries saved dynamic
motion data. Upstream preparation may expert-screen candidates; that is a
separate environment preparation procedure, not an agent capability or an
online service action. The service neither screens new seeds nor replaces a
failed case. See the protocol for the exact initialization and language mapping.

`native_seed` selects an existing entry in the trusted manifest; it is not a
layout ID or a request to generate a new motion. Missing entries are errors.
There is no independent layout, dynamic-level or multi-seed selector. The launch
`--seed` is a separate recorded run field and does not change the native case.

## Service robot interface, budget and scoring

| Property | Published contract |
| --- | --- |
| Observation | Native language and three 320 × 240 RGB cameras |
| State | 14 **commanded targets**, not measured encoders: six arm targets plus gripper for each side |
| Action | 14 absolute native joint/gripper targets, with arm values in radians |
| Execution | One native qpos/TOPP target per step; variable physics ticks at 250 Hz |
| Budget | 400 native target calls |
| Action grouping | Chosen by the agent; each target is a separately acknowledged control |

The **14-dimensional action** is ordered as six left-arm absolute joint angles,
left gripper, six right-arm absolute joint angles, right gripper: slots 0–5,
6, 7–12 and 13 respectively. Arm values are native joint coordinates in radians,
not EEF poses or relative deltas. Grippers are absolute normalized commands,
nominally 0 closed and 1 open, mapped natively to [-0.01,0.045] m. Native
interpolation/clipping is preserved. One target takes a variable number of
4 ms physics ticks, so there is no fixed target-control frequency.

An agent may send successive targets from one decision; every target still
performs the native termination checks before another can execute. There is no extra service motion or
joint-range guard; dimensions, type and finiteness are checked, while native
controller clipping and interpolation remain native behavior. Object truth,
dynamic trajectories, expert plans and private metrics are not agent inputs.

Native Boolean success determines SR. Native manipulation score (MS) combines
route completion and penalty factors; **MS is not success percentage**.
Native success, contact/boundary/failure conditions and the horizon determine
termination. An early stop can retain partial metrics with
`native_score_complete=false`; it must not be presented as a complete native
task score.

## Start the benchmark service

Follow [environment setup](environment/README.md) and prepare the trusted
manifest before evaluation. Copy [server.example.json](server.example.json)
to an operator-owned configuration and replace the source/manifest paths and
both all-zero hashes with verified deployment values. The manifest is private
trusted input; never accept an agent-supplied pickle file.

Select the declared SM120 interpreter and verified renderer overlay as described
in the environment guide. Supply `RSI_SIM_SERVER_TOKEN` privately to the server
and trusted evaluator. From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python -B -m benchmarks.simBenchmarks.DOMINO.server \
  --parameters /absolute/domino-server.json \
  --seed 20260921 --episodes 1 --port 8765 \
  --output-dir /absolute/new-domino-run/server
```

The launch seed and native scene seed are distinct recorded fields. Startup and
description do not reset or actuate the simulator. A trusted agent driver
connects through the shared protocol and chooses its own action grouping.
The service binds loopback; remote drivers use SSH forwarding. No particular
model implementation or prompt is required.

## Reporting and deployment

Report the selected manifest/case, runtime/protocol track, native success,
MS/route completion, metric completeness, decisions, targets, physics ticks and
errors. Keep participant configuration and optional interaction/media records
with its results. Three-camera video uses 10-fps presentation, not physical
control frequency; see [recording guidance](../../../docs/recording.md).

The selected runtime differs from the upstream runtime conditions. Installation
and renderer requirements are documented in [environment setup](environment/README.md).

`server.py` launches the service, `bench_server/adapter.py` owns the public
contract, and `environment/` owns native deployment and scoring-order helpers.
Agent implementations and results remain outside this benchmark package.
