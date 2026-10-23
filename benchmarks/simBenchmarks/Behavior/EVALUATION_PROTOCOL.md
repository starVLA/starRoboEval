# BEHAVIOR 2026 evaluation protocol

- Tracks: historical radio `behavior-2026-default-rgb-proprio-debug/v1`;
  corrected selected-task extension `behavior-2026-default-rgb-proprio-debug/v3`.
  Frozen selected-task v2 runs retain their original identity and cap.
- Native source: v3.9.2, `b1979916ec1549b10a4e65e630bc6504a9af1b00`.
- Evidence: the historical radio HTTP smoke check is documented in
  [verified scope](README.md#verified-scope). Adding a task to the catalog does
  not establish native readiness or a model score for that task.
- Public entrypoint: `benchmarks.simBenchmarks.Behavior.server`.

## Fixed selected schedule and budgets

Select one task per server deployment. Each supported task currently has one
fixed fast case: public index 0 → native instance 301, rollout 0. Attempt it
once, preserving failure or infrastructure error. Native evaluation seed is 0;
the run seed records identity and does not silently replace the native seed.
The four-task validation order is trash → desk → honey → brisket.
Tasks 22 and 34 are separately selected single-case extensions; they do not rerun that
four-task panel or change its recorded results.

| Task | Catalog name | Mean human length | Native timeout parameter | Service control cap | Track |
| --- | --- | ---: | ---: | ---: | --- |
| Turning On Radio (historical) | `turning_on_radio` | 2149.64 | 3224 | 3224 (legacy) | v1 |
| Task 1: Picking Up Trash | `picking_up_trash` | 5267.75 | 7901 | 7902 | v3 |
| Task 29: Clean Up Your Desk | `clean_up_your_desk` | 21417.875 | 32126 | 32127 | v3 |
| Task 83: Store Honey | `store_honey` | 6766.84 | 10150 | 10151 | v3 |
| Task 51: Cook A Brisket | `cook_a_brisket` | 7334.995 | 11002 | 11003 | v3 |
| Task 22: Putting Shoes On Rack | `putting_shoes_on_rack` | 7726.145 | 11589 | 11590 | v3 |
| Task 34: Hanging Pictures | `hanging_pictures` | 2387.415 | 3581 | 3582 | v3 |

Task labels follow the [2026 task gallery](https://behavior.stanford.edu/challenge/tasks/index.html).
The native timeout parameter is `H = int(mean_human_length * 1.5)`, not a
model-decision limit. In the pinned implementation, `Timeout._step` checks
`env.episode_steps >= H` **before** `Environment._post_step` increments the
counter, which starts at zero. Without earlier termination, native timeout is
therefore returned on executed control **H + 1**. Selected-task v3 declares that
effective control cap; it does not change the native timeout parameter, inject a
terminal flag, or grant an arbitrary extra budget. The trusted driver must use
the service-declared control cap for `--max-steps`.

Historical radio v1 and selected-task v2 incorrectly equated H with the native
terminal control count. Their frozen records are not rewritten. Radio retains
its legacy cap and must not be described as validated native-timeout parity.
The v2 trash run exposed the mismatch after executing control 7901: the worker
rejected its nonterminal result, leaving 7900 client acknowledgements. That is
an engineering interruption, not a completed native failure. A corrected run
requires a new identity; no uncertain action or closed episode is replayed.

Native metadata `task.jsonl` SHA256:
`7dbb5f7f00a2e06c693dfbb3045e5c28e627b6179e775f1ad93ca4b61f08e6dc`.
One action means one native 30 Hz control, normally four 120 Hz physics ticks.
Measured clock mismatches are infrastructure errors, not repaired controls.
Decisions, controls, physics and initialization are separate. Diagnostic limits
do not alter the native cap. No benchmark model-call cap or give-up preference.

The 2026 challenge reports 100 tasks with public indices 0–9 once each. Pinned
native source exposes 20 public indices 0–19 and 20 hidden indices. One selected
case per supported task is neither the complete public split nor challenge matrix. Full evaluation
is not implemented. Historical `tasks.jsonl` and `behavior-2025-starvla-draft`
retain their old meaning.

## Sensors and direct controls

Native `DefaultWrapper` supplies three 224×224 uint8 RGBA cameras. Strip alpha
explicitly and expose head, left_wrist, right_wrist RGB without resizing or
annotations, measured 61-value robot proprioception, and the selected task's
language instruction. Trash, desk, shoe-rack and hanging-pictures instructions come from pinned native
`docs/challenge/task_data.json`. Honey and brisket use benchmark-authored,
goal-only language based on the pinned BDDL problem; their provenance is recorded
in the catalog. These instructions do not expose current goal predicates,
object coordinates or a task-solving plan.
Exact state order/units and action slices are in
[NATIVE_CONTRACT.md](environment/NATIVE_CONTRACT.md) and
[`bench_server/protocol`](bench_server/protocol/__init__.py).

Accept exactly 23 finite values: 3 base body-frame velocity inputs; 4 absolute
torso targets; 7 left joints + 1 gripper; 7 right joints + 1 gripper. Torso/arms are
radians, not normalized/delta commands. Gripper -1 closes/+1 opens. Retain native
input scaling, motor limits, smooth grippers and `assisted` grasping. No extra
server motion guards, clipping, task controller or EEF planner. Invalid format
does not execute; shared pre-execution rejection feedback applies. Uncertain
execution is terminal, never replayed. Each sequenced action RPC executes one
native control; this does not require one model inference per RPC.

This debugging wrapper is **not official RGBDFullResWrapper** (head 720²,
wrists 480² plus metric depth). No full RGBD parity claim. Camera poses, numeric
task IDs, global robot pose, object truth, reset metadata, goal predicates and
intermediate scoring never enter actor observations. Measured joint/FK state has
real-robot counterparts; native reset/paused-time semantics need not.

## 推理次数与执行步数：节奏由策略决定

当前 v3（以及历史 v2）不规定“一次推理只能执行一步”。Agent 可以一次生成多个动作，或重复
同一动作，再由策略客户端按顺序逐步提交；也可以只执行一小段就重新观察、
推理。动作段长度、何时重新观察以及方法自身的长度上限，都归策略配置，
不是 benchmark server 的要求。

例如，在视野清楚的移动或搜索阶段，策略可以选择较长的动作段；接近物体、
抓取、放置或需要纠偏时，可以缩短动作段、增加观察频率。这只是通用的方法
建议，不是强制规则或保证成功的控制器。长动作段会减少重新观察的机会；
策略应根据已公开的 RGB 和机器人状态自行判断。

Server 仍按原生 30 Hz 控制语义执行，每个控制步通常对应四个物理步；没有
后台自主行动、自动导航或抓取规划。每步仍检查原生终止条件和剩余执行预算，
不能为了完成一个动作段而越过 horizon。拒绝的动作不执行；执行结果不确定
时不得重放动作。

报告应分别记录模型调用次数、实际执行的决策数、原生控制步数与物理步数，
并披露策略的动作段配置。它们不必是 1:1；推理耗时也不等于仿真时间。
历史 radio v1 的 prefix=1 保持不变，不回写旧协议或旧结果。选定的扩展任务
不继承这一限制；v3 修正了原生 timeout 参数与实际执行上限的对应关系，
原生结束条件、timeout 配置与评分规则均未改变。

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
