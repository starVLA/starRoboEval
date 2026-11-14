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

## Available service binding

The current service exposes **one fixed sequence with one fixed initial state**:

| Order | Task |
| --- | --- |
| 1 | `rotate_blue_block_right` |
| 2 | `move_slider_right` |
| 3 | `lift_red_block_slider` |
| 4 | `place_in_slider` |
| 5 | `turn_off_lightbulb` |

The evaluator-private [sequence definition](bench_server/protocol/selected_sequence.json)
contains the initial condition, exact 15-value robot and 24-value scene reset
vectors, ordered tasks and native language annotations. Changing the run seed
does not select another layout. Additional sequences and independent evaluation
of all 34 task definitions are not exposed by this service.

An episode resets once before the first subtask. The scene is not reset between
instructions, and initialization physics is separate from scored controls.

## Observations

The actor receives current task language and two native uint8 RGB views:
`rgb_static` at 200×200×3 and `rgb_gripper` at 84×84×3. Images are copied without
flipping, resizing, cropping or overlays. Robot/scene state, object/goal poses,
contacts, future instructions, reset data and scoring internals are not exposed.

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

Each subtask permits **360 controls**. After every control, the native task
oracle tests the current subtask against the state captured at that subtask's
start. On success, the evaluator records completion, captures the next baseline
and supplies the next instruction without a scene reset. An unsuccessful
360-control subtask ends the sequence; completing all five ends successfully.
The sequence ceiling is **5 × 360 = 1,800 controls**, often shorter when subtasks
complete early.

These are execution limits, not a required number of model calls. A participant
that chooses a smaller external limit must distinguish that stop from a native
timeout. Partial completion does not make the whole five-subtask sequence a
success.

The current `agent-grouping-v2` interface declares no mandatory action prefix.
An agent may issue successive controls from one decision. It receives the
current public instruction after every acknowledged control, including a new
instruction when a subtask completes. Its driver owns action grouping and when
to request another decision; the service does not require a model call at that
boundary. Future instructions and private subtask scores are not actor inputs.
Controller timing, the 360-control subtask limit, native checks and sequence
selection are unchanged. Report the returned protocol identity.

## Scoring and result statistics

The native outputs are:

- completed sequence depth, from 0 to 5;
- whether at least 1, 2, 3, 4 or 5 subtasks were completed;
- per-subtask and total executed controls.

Across a selected set of sequences, report mean completed depth and the fraction
reaching each depth, together with the number of evaluated sequences.
Infrastructure errors and externally shortened attempts are distinct from
native task failures.

Optional interaction and video recording uses the
[shared recording settings](../../../docs/recording.md).

## Current integration limits

- Only the fixed sequence and initial state above are selectable.
- The runtime uses the official `calvin_debug_dataset` setup configuration and
  omits tactile rendering. Its equivalence to D-validation setup is not established.
- The seven-input `[-1,1]` bounds are service validation. The native controller
  itself does not clip the first six inputs to that range.
- Native evaluation invokes a model-state reset per subtask; the current
  sequence-level agent session has no corresponding callback. Disclose memory
  behavior when comparing results.
- EGL/PyBullet requires a fresh, dedicated native process with simulator client
  0. Sharing that process with another simulator is unsupported.

Source revisions, configuration assets and runtime dependencies are documented
in [environment preparation](environment/README.md). Setup configuration, fixed
reset vectors and private scoring data never become additional actor inputs.
