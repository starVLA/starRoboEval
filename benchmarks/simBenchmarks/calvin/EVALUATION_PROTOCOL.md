# CALVIN evaluation protocol

## Tasks, sequences and initial states

CALVIN provides 34 language-conditioned manipulation tasks and four environment
configurations A–D. Its [released splits](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/dataset/README.md)
are D→D, ABC→D and ABCD→D; these describe training/evaluation environment
exposure, not different task counts.

The [native evaluator](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/calvin_agent/evaluation/evaluate_policy.py)
evaluates 1,000 sequences of five ordered subtasks, using
[34 task definitions](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/conf/callbacks/rollout/tasks/new_playtable_tasks.yaml).
Task count, sequence count and number of initial states are different quantities:
a five-subtask sequence is one continuous episode, not five scene layouts.

The [native sequence generator](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/calvin_agent/evaluation/multistep_sequences.py)
pairs feasible task chains with initial conditions covering light, drawer,
slider and block states. Its deterministic selection pairs an initial condition
and ordered task chain as one evaluation case.

## Evaluation modes

`evaluation_mode` selects the schedule:

| Mode | Selection | Episodes | Cap per episode |
| --- | --- | --- | --- |
| `fast` (default) | All 34 tasks × trials 0–3, one instruction per reset | 136 | 360 controls |
| `max` | Native `get_sequences(1000)`: five-subtask chains, no reset between subtasks | 1,000 | 360 controls per subtask, at most 1,800 per chain |
| `example` | `close_drawer` trial 0 (first `fast` case) | 1 | 360 controls |

Protocol IDs:

- `fast`, `example`: `calvin-fa03f01/single-task-d-validation/rgb-relative7/<mode>/v1`
- `max`: `calvin-fa03f01/long-horizon-1000/rgb-relative7/max/v1`

### Single-task cases (`fast`, `example`)

Episode IDs are `<task>-trial<NN>`, in task-major order. The public, hash-pinned
[case panel](bench_server/protocol/single_task_panel.json) holds each case's
15-value robot and 24-value scene reset vectors from the D validation data, its
native instruction (`new_playtable_validation.yaml[task][0]`) and extraction
provenance. For each task, validation annotation segments are sorted by
(start, end, index); a segment is accepted when it starts after the previous
accepted segment ends, and trial *k* resets at the start frame of the *k*-th
accepted segment. There is no scoring, success screening or expert replay in this
selection. The run seed does not change the reset.

### Native five-subtask chains (`max`)

Episode IDs are `calvin-chain0000` to `calvin-chain0999`, in the native
`get_sequences(1000)` order. The tracked
[chain list](bench_server/protocol/long_horizon_sequences.json) holds each
chain's symbolic initial condition and five subtasks. Startup checks it against
a pinned SHA-256 and checks that every chain is feasible under the native
symbolic task table. `long_horizon.verify_regeneration()` reproduces the list
from the native algorithm (192 initial conditions, NumPy legacy MT19937 seeded
per condition, final shuffle under seed 0) in pure Python; it takes about a
minute, so startup does not run it.

Reset applies the native `get_env_state_for_initial_condition`: a fixed robot
pose, and slider, drawer, lights and block positions from the condition. Block
table placement and z rotations come from a NumPy legacy RNG seeded with
pyhash `fnv1_32` of `str(initial_condition.values())`; the service recomputes
both in pure Python and records the vectors and seed in provenance. The run
seed does not change the chain or its reset.

The service never sends the panel, the chain list or reset vectors to the
actor. Because they are public, this is an interface boundary, not secrecy;
disclose any method tuned with knowledge of them. Initialization physics is
separate from scored controls.

## Observations

The actor receives the current instruction and two native uint8 RGB views:
`rgb_static` at 200×200×3 and `rgb_gripper` at 84×84×3. Images are copied without
flipping, resizing, cropping or overlays. Robot/scene state, object/goal poses,
contacts, future instructions, reset data and scoring internals are not exposed.

In `max`, the public episode task is `long_horizon_chain` and the episode
instruction is the first subtask's annotation. When a subtask succeeds, the
acknowledged observation carries the next subtask's annotation
(`new_playtable_validation.yaml[task][0]`), as the native `rollout` does.

## 7-dimensional action

Each action contains exactly seven finite real values in `[-1,1]`:

| Slots | Values | Semantics |
| --- | --- | --- |
| `0:3` | `dx, dy, dz` | World-coordinate increments to the previous **commanded** target position; 0.02 m per input unit |
| `3:6` | `droll, dpitch, dyaw` | Additive Euler xyz increments to the previous commanded target orientation; 0.05 rad per input unit |
| `6` | `gripper` | Positive → `+1` open; zero/negative → `-1` closed |

The reference is the previous commanded target, not the measured end-effector
pose. Execution uses unchanged native PyBullet numerical IK and joint motors
with `use_ik_fast=False`. There is no object-aware planner or task-skill action.

One action executes one **30 Hz control**, containing eight **240 Hz physics
ticks**. No autonomous stepping occurs while the agent reasons. Model inference,
executed decisions, native controls and physics ticks are separate counts.

## Execution budget and success

Each instruction permits **360 controls**, the native `EP_LEN`. After every
control, the native task oracle tests the current task against the state
captured when that instruction started.

- Single-task case: success ends the episode; reaching 360 controls without
  success is a native timeout.
- Chain: a subtask success captures a new start state and continues in the same
  scene with the next instruction; the counter restarts at zero. The chain ends
  after the fifth success or at the first subtask that reaches 360 controls
  without success, as native `evaluate_sequence` does. The episode cap is
  therefore at most 1,800 controls.

These are execution limits, not a required number of model calls. A participant
that chooses a smaller external limit must distinguish that stop from a native
timeout. The interface declares no mandatory action prefix: an agent may issue
successive controls from one decision, and its driver owns action grouping.
Report the returned protocol identity.

## Scoring and result statistics

For single-task cases, the native output per case is task success and the
number of executed controls. Report success rates per task and overall, with the
number of evaluated cases.

For chains, the native output per chain is the completion depth: the number of
subtasks completed in a row, 0–5 (`completion_depth`; episode `success` means all
five). Report the native `count_success` rates, the fraction of chains with depth
≥ *n* for *n* = 1–5, and the average depth (`avg_seq_len`), with the number of
evaluated chains. Per-task counts follow native `print_and_save`: each completed
subtask counts as a success and the subtask that ended the chain as a failure.

Infrastructure errors and externally shortened attempts are distinct from native
task failures.

Optional interaction and video recording uses the
[shared recording settings](../../../docs/recording.md).

## Current integration limits

- Only the cases above are selectable.
- Native `rollout` calls `model.reset()` before every subtask. The service has no
  hook for that, so one policy session spans the whole chain; it sees the
  instruction change and owns its reaction.
- The pure-Python chain reproduction matches a retained copy of the native
  `get_sequences(1000)` output, but has not been cross-checked against a live
  NumPy/pyhash run of the pinned code. The block-placement seed follows
  pyfasthash 0.9.3 (`Hash.h`): on Linux x86-64 a Python 3 `str` is hashed as
  UTF-16-LE without a byte-order mark. CALVIN does not pin `pyhash`.
- In `max`, the public remaining-control count covers the whole chain
  (1,800 controls). The native 360-control limit per instruction is not shown to
  the policy, as in native CALVIN, which gives policies no budget.
- A voluntary task-complete stop ends the whole chain, not the current subtask;
  it is recorded as an external stop.
- Chain metrics after an infrastructure error or external stop still report the
  partial completion depth. Filter on `native_outcome` before averaging sequence
  length.
- `fast` keeps four resets per task; no fifth reset is pinned.
- The runtime reads only `validation/.hydra/merged_config.yaml` from the official
  `calvin_debug_dataset` and omits tactile rendering. That file (SHA-256
  `75c1c150…`) matches the same member of the official D→D archive
  `task_D_D.zip` by size and CRC-32, and declares scene `calvin_scene_D`; the ABC→D member was not
  compared. Construction rejects a dataset whose configuration declares another
  scene.
- The seven-input `[-1,1]` bounds are service validation. The native controller
  itself does not clip the first six inputs to that range.
- EGL/PyBullet requires a fresh, dedicated native process with simulator client
  0. Sharing that process with another simulator is unsupported.

Source revisions, configuration assets and runtime dependencies are documented
in [environment preparation](environment/README.md). Setup configuration, fixed
reset vectors and native scorer state never become actor inputs.
