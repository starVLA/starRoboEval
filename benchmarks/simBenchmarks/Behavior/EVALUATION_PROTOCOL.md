# BEHAVIOR 2026 evaluation protocol

- Implemented track: `behavior-2026-default-rgb-proprio-debug/v1`.
- Native source: v3.9.2, `b1979916ec1549b10a4e65e630bc6504a9af1b00`.
- Status: **one fixed-case, two-control HTTP native smoke check passed**;
  see [verified scope](README.md#verified-scope). No model/full-challenge score.
- Public entrypoint: `benchmarks.simBenchmarks.Behavior.server`.

## Fixed selected schedule and budgets

Exactly one fast case: `turning_on_radio`, public index 0 → native instance 301,
rollout 0. Attempt it once, preserving failure or infrastructure error. Native
evaluation seed is 0; the harness seed records run identity and does not silently
replace the native seed.

Native horizon is **3224 controls**, `int(2149.64 * 1.5)`, from mean human
demonstration length. Native metadata `task.jsonl` SHA256:
`7dbb5f7f00a2e06c693dfbb3045e5c28e627b6179e775f1ad93ca4b61f08e6dc`.
One action means one native 30 Hz control, normally four 120 Hz physics ticks.
Measured clock mismatches are infrastructure errors, not repaired controls.
Decisions, controls, physics and initialization are separate. Diagnostic limits
do not alter the native cap. No benchmark model-call cap or give-up preference.

The 2026 challenge reports 100 tasks with public indices 0–9 once each. Pinned
native source exposes 20 public indices 0–19 and 20 hidden indices. This single
case is neither the complete public split nor challenge matrix. Full evaluation
is not implemented. Historical `tasks.jsonl` and `behavior-2025-starvla-draft`
retain their old meaning.

## Sensors and direct controls

Native `DefaultWrapper` supplies three 224×224 uint8 RGBA cameras. Strip alpha
explicitly and expose head, left_wrist, right_wrist RGB without resizing or
annotations, measured 61-value robot proprioception, and “Turn on the radio.”
Exact state order/units and action slices are in
[NATIVE_CONTRACT.md](environment/NATIVE_CONTRACT.md) and
[`bench_server/protocol`](bench_server/protocol/__init__.py).

Accept exactly 23 finite values: 3 base body-frame velocity inputs; 4 absolute
torso targets; 7 left joints + 1 gripper; 7 right joints + 1 gripper. Torso/arms are
radians, not normalized/delta commands. Gripper -1 closes/+1 opens. Retain native
input scaling, motor limits, smooth grippers and `assisted` grasping. No extra
server motion guards, clipping, task controller or EEF planner. Invalid format
does not execute; shared pre-execution rejection feedback applies. Uncertain
execution is terminal, never replayed. Prefix length is one control.

This debugging wrapper is **not official RGBDFullResWrapper** (head 720²,
wrists 480² plus metric depth). No full RGBD parity claim. Camera poses, numeric
task IDs, global robot pose, object truth, reset metadata, goal predicates and
intermediate scoring never enter actor observations. Measured joint/FK state has
real-robot counterparts; native reset/paused-time semantics need not.

## Native execution and scoring

An isolated worker constructs the exact native Evaluator lazily. Only
`load_policy` is replaced by a strict one-slot external-action bridge: each
`Evaluator.step` consumes one externally selected action, with no inference or
fallback. Preserve native robot/render/transition rules and
`reset → load_task_instance(301) → reset`. The 25 explicit settling ticks are
only part of initialization; clock samples are recorded without guessing total
startup ticks.

Binary success is native `env.task.success`. Native metric aggregates,
including partial final `q_score`, remain evaluator-private. Q is not SR.
Early diagnostic exit reports `native_episode_complete: false`, not a native
horizon failure. Nonfinite native metric values use explicit tagged JSON:
`{"native_nonfinite":"+inf"}`, `"-inf"`, or `"nan"`, never zero/null or invalid
JSON. Retain controls, errors, deployment identity, loaded contract, private
outcome, all three videos and cleanup receipts.

No automatic retry, hidden-state action generation, training bridge, full-suite
claim or model capability result follows from offline conformance.
