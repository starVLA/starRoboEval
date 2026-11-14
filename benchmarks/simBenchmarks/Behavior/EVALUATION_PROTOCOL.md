# BEHAVIOR 2026 evaluation protocol

## Native benchmark and challenge schedule

BEHAVIOR-1K defines **1,000 activities**. The 2026 challenge evaluates a
**100-task selection**, whose IDs, instructions and scenes are listed in the
[native task catalog](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/docs/challenge/task_data.json).
A task defines goals; a scene is the household environment; an instance fixes
initial object states and robot poses for that task. Sharing a scene does not
make two task instances the same evaluation case.

The [2026 rules](https://github.com/StanfordVL/BEHAVIOR-1K/blob/b1979916ec1549b10a4e65e630bc6504a9af1b00/docs/challenge/evaluation.md)
specify one rollout for each of the first ten public instances, indices 0–9,
per task: **1,000 task/instance trials** across the 100 tasks. Indices 10–19
are additional public development instances. Hidden instance indices are reserved
for organizers; their available index range does not determine the final panel.

The primary challenge ranking metric is final goal-predicate completion Q,
averaged across tasks; binary task success must be reported separately.
The native timeout is task-specific, based on 1.5 times mean human length.

## Available service bindings

The current integration uses BEHAVIOR-1K v3.9.2, source revision
`b1979916ec1549b10a4e65e630bc6504a9af1b00`. One deployment selects one of the
seven task bindings below and **one fixed instance**: public index 0 → native
instance 301, rollout 0. Native evaluation seed is 0; changing the run seed does
not select another layout. Other tasks and instance indices are not exposed.

| Task | Catalog name | Selected scene | Service control cap |
| --- | --- | --- | ---: |
| Task 0: Turning On Radio | `turning_on_radio` | `house_double_floor_lower` | 3224 |
| Task 1: Picking Up Trash | `picking_up_trash` | `house_double_floor_lower` | 7902 |
| Task 29: Clean Up Your Desk | `clean_up_your_desk` | `house_single_floor` | 32127 |
| Task 83: Store Honey | `store_honey` | `Rs_int` | 10151 |
| Task 51: Cook A Brisket | `cook_a_brisket` | `house_double_floor_lower` | 11003 |
| Task 22: Putting Shoes On Rack | `putting_shoes_on_rack` | `house_double_floor_lower` | 11590 |
| Task 34: Hanging Pictures | `hanging_pictures` | `house_double_floor_lower` | 3582 |

Task labels follow the [2026 task gallery](https://behavior.stanford.edu/challenge/tasks/index.html).
The [service task definitions](bench_server/protocol/__init__.py) bind each
selection's scene, instruction and instance.

## Observations

The service exposes language, three 224×224 RGB images (head, left wrist and
right wrist), and 61 measured robot-state values. Native camera alpha is removed;
images are not resized or annotated. Robot state includes body-frame base
velocity, joint/finger positions and velocities, and robot-relative end-effector
poses. See the exact order and units in [the native contract](environment/NATIVE_CONTRACT.md).

Language gives the selected goal, not current predicates or a solution.
Trash, desk, shoe-rack and hanging-pictures instructions come from native
`docs/challenge/task_data.json`; honey and brisket use goal-only text based on
their pinned BDDL definitions. The radio instruction is “Turn on the radio.”

This uses native `DefaultWrapper`, not the challenge's
`RGBDFullResWrapper` (head 720×720, wrists 480×480, plus metric depth).
Camera poses, global robot pose, object truth, numeric task IDs, reset metadata,
goal predicates and intermediate scores are excluded from actor observations.

## 23-dimensional action

Each request contains exactly 23 finite real values:

| Slice | Command | Units and semantics |
| --- | --- | --- |
| `0:3` | Base `vx, vy, wz` | Body-frame normalized velocity inputs; native scaling maps translation to ±0.75 m/s and yaw to ±1 rad/s |
| `3:7` | Four torso joints | Absolute joint positions in radians |
| `7:14` | Seven left-arm joints | Absolute joint positions in radians |
| `14` | Left gripper | Smooth normalized input: −1 close, +1 open |
| `15:22` | Seven right-arm joints | Absolute joint positions in radians |
| `22` | Right gripper | Smooth normalized input: −1 close, +1 open |

These are joint/base commands, not end-effector targets. Native input scaling,
motor constraints, smooth grippers and `assisted` grasping remain unchanged.
There are no additional service motion guards, clipping or task-solving actions.

One accepted action advances one **30 Hz control**, normally four **120 Hz
physics ticks**. Initialization is counted separately. The simulator does not
autonomously advance while the agent reasons.

## Decisions and control execution

An agent may choose several controls in one decision and submit them as
successive sequenced requests. Reasoning frequency and action grouping belong
to the method; native timing, termination and the total control budget do not.

**Current integration constraint:** radio requires a new observation/decision
after each control. The other six tasks do not impose that prefix-one setting.
It is a service constraint, not a native BEHAVIOR rule. Report model calls,
executed decisions and native controls separately; they need not be 1:1.

Invalid input does not execute a control. Native success or termination ends execution even when a submitted
action group has unused controls.

## Execution budgets

The native timeout parameter is
`H = int(mean_human_length × 1.5)`, based on native task metadata. The pinned
implementation checks its zero-based counter before incrementing it, so the
native timeout occurs on executed control **H + 1**, unless the task ends earlier.

| Task | Mean human length | Native timeout parameter H | Controls until native timeout |
| --- | ---: | ---: | ---: |
| Turning On Radio | 2149.64 | 3224 | 3225 |
| Picking Up Trash | 5267.75 | 7901 | 7902 |
| Clean Up Your Desk | 21417.875 | 32126 | 32127 |
| Store Honey | 6766.84 | 10150 | 10151 |
| Cook A Brisket | 7334.995 | 11002 | 11003 |
| Putting Shoes On Rack | 7726.145 | 11589 | 11590 |
| Hanging Pictures | 2387.415 | 3581 | 3582 |

The current radio service cap is 3224, one control before its native timeout;
that cap must be reported as an external truncation if native success has not
occurred. The other six service caps match the native timeout control count.
These are execution budgets, not limits on reasoning calls.

## Native scoring and result statistics

The worker preserves native evaluator reset, instance loading, control and
scoring. Binary success is native `env.task.success`; final `q_score` is partial
goal progress. Q is not success rate, and a model's own completion declaration
does not replace native success.

Report task/instance, binary success, final Q, actual controls and stop reason.
For several selected cases, report successes and the selected/attempted case
counts alongside Q statistics. Native failure, external truncation and
infrastructure error are separate result categories. The radio cap stop is
recorded as metric `external_cap_truncated: true` with native `truncated: false`.
`termination_reason` reads `environment:truncated` for both, so separate them
by `metrics.external_cap_truncated`.

Optional interactions and video recording use
[shared recording settings](../../../docs/recording.md). Environment/controller
details and source/asset requirements are in
[environment preparation](environment/README.md).
