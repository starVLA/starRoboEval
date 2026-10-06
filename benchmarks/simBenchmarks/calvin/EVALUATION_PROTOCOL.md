# CALVIN evaluation protocol

Protocol: `calvin-fa03f01/debug-sequence0/rgb-relative7/prefix1/fast-v1`.
The executable adapter implements a bounded debug track; native SIM validation
is a separate acceptance gate. `evaluation_mode=full` is rejected.

## Native reference and scope

The [pinned native evaluator](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/calvin_agent/evaluation/evaluate_policy.py)
uses **1,000 sequences of five ordered subtasks** and **360 controls per subtask**.
The [task-oracle configuration](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/conf/callbacks/rollout/tasks/new_playtable_tasks.yaml)
defines **34 named predicates**; these are not 34 interchangeable independent
episode variants. Native aggregation is average completed sequence length and
success at each depth from one to five. The retained RSI integration uses its
fixed 1,000-row sequence file and removes tactile rendering for RGB evaluation.

This version selects row **0** of that retained file before any native run,
using its ordered five tasks and the native first language annotation. It does
not generate, rank, screen or retry seeds, sequences or initial states. The
original file SHA-256 is `c99e041c255df3408ebf3bbb4feea8b407e17e60e7c07d172a6ea7ba6680e8ca`.
The complete immutable private record is
[bench_server/protocol/frozen_sequence.json](bench_server/protocol/frozen_sequence.json).

| Depth | Predeclared task |
| --- | --- |
| 1 | `rotate_blue_block_right` |
| 2 | `move_slider_right` |
| 3 | `lift_red_block_slider` |
| 4 | `place_in_slider` |
| 5 | `turn_off_lightbulb` |

The service uses only the original config from the official **debug** dataset,
plus source-owned robot/table assets. It never reads demonstrations or dataset
state samples. A debug setup configuration has not been established equivalent
to the original full D validation input. Do not label this one sequence as a
1,000-sequence score, 34-task coverage, full evaluation or historical parity.

## Public interface

| Field | Frozen semantics |
| --- | --- |
| Observation | Current language; `rgb_static` 200×200×3 and `rgb_gripper` 84×84×3 uint8 RGB |
| Image processing | Copy original native RGB; no flip, resize, crop, overlay or RGB/BGR swap for the actor |
| Excluded | Depth, tactile, robot/scene state, object/goal poses, contacts, oracle internals, future language, reset state and private metadata |
| Action | `[dx,dy,dz,droll,dpitch,dyaw,gripper]`; all seven finite values restricted to `[-1,1]` by this development interface |
| Translation | World-coordinate additions to the previous **commanded** target position, 0.02 m per normalized unit |
| Rotation | Native additive Euler xyz increments to the previous commanded target orientation, 0.05 rad per unit |
| Gripper | Positive input → native `+1` open; zero/negative → native `-1` closed, matching retained evaluator conversion |
| Low-level controller | Unchanged native PyBullet numerical IK and joint motors; `use_ik_fast=False`, no object-aware planner or task skill |
| Frequency | 240-Hz physics, eight ticks per control, 30-Hz control |
| Replanning | Required prefix 1: one control, then current observation/language before another decision |

Native `relative_to_absolute` mutates action-array slices. The adapter supplies
a fresh writable float64 array; recorded normalized actions remain unchanged.
The native controller does not itself impose `[-1,1]` bounds on the first six
inputs; this bounded development track does. It is not a recovered clipping
rule or a claim that arbitrary historical policies used these limits.

## Reset and private scoring

One episode means **one complete sequence**, not five independent resets.
Native construction initializes its robot/scene; then one `env.reset` applies
the frozen 15D robot and 24D scene vectors and performs the native one-tick reset.
There is no expert rollout, planning-based feasibility check or reset resampling.
Construction/reset ticks are recorded separately from policy controls.

The frozen vectors were derived by AST-extracting only `temp_seed` and
`get_env_state_for_initial_condition` from the pinned
[native utility](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/calvin_agent/evaluation/utils.py),
then evaluating their pure NumPy 1.26.4 mathematics. The model/Torch/pyhash module
was not imported. Dictionary insertion order is preserved. The explicit hash
compatibility assumption is pyhash 0.9.3 commit
`0f9f51de7cb90956d507090c37af5c2807861085`: Python 3 Unicode passes UTF-16LE bytes
without a BOM to `fnv1_32`, whose default seed is zero. See its
[Unicode conversion](https://github.com/flier/pyfasthash/blob/0f9f51de7cb90956d507090c37af5c2807861085/src/Hash.h),
[FNV binding](https://github.com/flier/pyfasthash/blob/0f9f51de7cb90956d507090c37af5c2807861085/src/FNV1.h)
and [native arithmetic](https://github.com/flier/pyfasthash/blob/0f9f51de7cb90956d507090c37af5c2807861085/src/fnv/hash_32.c).
The resulting seed is `2138410836`. The frozen record contains the source hash,
exact representation, outputs and derivation scope. It establishes one explicit
reset state, not the unspecified historical pyhash environment or general parity.

For each subtask the evaluator records private `start_info`; after each native
control it invokes only `get_task_info_for_set(start_info,current_info,{task})`.
Success records that subtask's actual completion control, then captures the next
private baseline and exposes its next instruction. There is no SIM reset between
subtasks. The first unsuccessful 360-control subtask stops the whole sequence.
Depth five terminates successfully. Private info and future tasks never enter
`Observation` or the actor mailbox; scalar wrapper reward is an evaluator-only
encoding of native subtask completion, not a shaped task-solving signal.

The native model evaluator calls `model.reset()` per subtask. The current shared
`Policy` interface has only a sequence-level session, so policy state persists;
this declared difference prevents a native memory-reset parity claim. A future
generic reset hook needs its own explicit protocol review. Do not simulate one
with hidden model messages or expose the remaining task list.

## Budgets, errors and reporting

The total native ceiling is at most `5 × 360 = 1,800` controls; success can make
it substantially shorter. This is **not** a mandatory model-call allocation.
The evaluator may stop earlier at a declared smaller call/control cap and must
record that external truncation. No benchmark-level minimum-decision or ordinary
give-up rule exists. Prefix 1 serves the language-transition boundary only.

Record native completion depth 0–5, success-at-depth indicators, every completed
subtask's local/sequence control counts, started/completed/acknowledged controls,
completed physics ticks by construction/reset/control, and the exact stop/error.
Errors remain infrastructure/protocol errors, never silently native failures.
An errored native call is not replayed. Failed reset consumes the one attempt.
Partial reset, control and media failures retain their counters and artifacts.
`native_metrics.json` is finalized on close even after failed reset/step, when
the normal metrics RPC is no longer permitted. It records started and completed
ticks, started/completed/acknowledged controls and the final native/external stop
outcome, so artifact transfer does not depend on a successful metrics response.

Native sources are verified by each tree's own Git revision and actual tracked
file bytes. The pinned runtime checks dependency versions and selected PyBullet,
EGL and OpenCV binary bytes; driver and all transitive libraries are not thereby
attested. Fixed reset inputs, source/config pins, native events, exact RGB PNG
hashes and two 30-fps videos go into the model's result namespace. The service
records explicit close and disconnected client IDs. Tick tracing preserves native
arguments, returns and exceptions without adding ticks. Connection tracing also
records newly created clients; it rejects a nonzero/second client immediately
before native default-client APIs can run and retains that new ID for cleanup.
This requires a fresh, dedicated single-owner process: the native EGL plugin
uses default Bullet client 0 and the passive wrappers are process-scoped.
An existing client 0 or nested trace owner is rejected before native construction. Sharing this
process with other simulator owners or stepping threads is unsupported.
No scored attempt begins until independent review and a separately labelled
server/client infrastructure diagnostic pass.
