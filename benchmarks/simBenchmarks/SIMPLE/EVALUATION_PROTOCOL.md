# SIMPLE evaluation protocol

The `simple_humanoid` adapter evaluates high-level sensor-driven control through native SIMPLE environments and fixed low-level whole-body controllers. [bench_server/adapter.py](bench_server/adapter.py) and the private [native worker](environment/native_worker.py) own benchmark mechanics. Policies, prompts, voluntary-stop rules and results belong under [AgentPolicies](../../../AgentPolicies/README.md).

The stable service entrypoint is [server.py](server.py). Its `bench_server/`
package contains the adapter, private worker client, service source inventory
and `protocol/` task inventory; the private native runtime remains under
`environment/`. The same frozen observations, actions,
reset selection, budgets and native scoring apply through the remote service.
Directory relocation does not change protocol identities or historical results.

The current executable interface is **v2**. Unlike v1, it does not reject a
finite joint target solely because it exceeds a MuJoCo physical joint range.
That check was an RSI worker addition, not the pinned native command interface.
Frozen v1 source and results remain unchanged and must be reported separately.

## Scope and reset

SIMPLE revision `5e3d6f84e85343e34e9bca8d157f0d7813231185` is pinned. The [inventory](bench_server/protocol/simple_released_tasks.json) binds 12 task registrations, AMO/SONIC backends, source metadata and exact released reset hashes. [RELEASED_TASK_SCOPE.md](bench_server/protocol/RELEASED_TASK_SCOPE.md) lists all tasks and reference horizons.

Fast mode selects each task once with seed 20260907, DR0 and released episode index 0. The default adapter opens BendPickMP only; the default campaign selects BendPickMP and OpenFaucetTeleop. Explicit `task_scope="released-12"` permits the 12-task inventory, one task per adapter, with RGB+qpos31 and the decision-200/prefix-5 track. Existing machine IDs containing `pilot` or `development` remain compatibility identities.

**Native-aligned full evaluation is not implemented.** It requires a declared released episode/DR schedule and task-specific timing/horizon alignment. Twelve tasks sampled once is not full evaluation. Preserve failures; do not retry or search easier resets.

Source, runtime inventory, compatibility patches, controller weights, robot assets, released metadata and scene-repair identities are checked and recorded. A mismatch or initial native success is an error before policy control, not a reason to resample.

## Native timing

A private worker hosts one episode/backend using the pinned source's `.venv/bin/python`. One public control is 20 ms at 50 Hz:

| Backend | Physics per public control |
| --- | --- |
| AMO native `g1_wholebody` | 10 × 2 ms |
| SONIC native decoupled WBC | 4 × 5 ms |

AMO initialization uses 60 standing controls. SONIC preserves controller history and stabilizes for at most 300 controls; unstable initialization is an error. Initialization controls are outside policy budgets and recorded separately.

## Observation allowlist

- Exact native released task language.
- One uint8 RGB image, `head_stereo_left`, shape 360 × 640 × 3, without resize, crop or color changes.
- By default, 31 ordinary measured joint encoders in radians, ordered as action slots 0–30.

An explicit RGB-only track exists for the default task scope and must be reported separately. Do not expose depth/stereo extras, world/root or end-effector pose, object ground truth, maps, goal poses, reset metadata, reward/success, demonstration actions or training statistics. Public execution counters are accounting only.

Episode metadata trims outer instruction whitespace; native/public observations preserve it. Audit observation transport against the exact released string.

## Physical 36-dimensional action

| Slice | Meaning and order |
| --- | --- |
| `[0:7]` | Left hand: thumb 0/1/2, middle 0/1, index 0/1 |
| `[7:14]` | Right hand: thumb 0/1/2, index 0/1, middle 0/1 |
| `[14:21]` | Left arm: shoulder pitch/roll/yaw, elbow, wrist roll/pitch/yaw |
| `[21:28]` | Right arm in the same order |
| `[28:31]` | Waist roll/pitch/yaw |
| `[31]` | Base height in meters |
| `[32:34]` | Native forward/lateral velocity commands |
| `[34]` | AMO turning flag or SONIC turning gate, not continuous yaw rate |
| `[35]` | Target heading in radians |

Joint targets are physical radians, not normalized outputs. Reject invalid
dimensions, booleans and non-finite values. Version 2 passes valid finite targets
unchanged to the pinned native controller: RSI adds neither joint-target range
rejection nor clipping. Physical joint ranges and native torque/actuator behavior
remain owned by the simulator and controller; a physical range is not an added
command-validity limit. Optional target/motion guards belong to agent code.
No IK or heuristic action substitution is allowed.

For AMO, the pinned `src/simple/robots/g1_wholebody.py` evaluation branch accepts
joint targets directly: hand targets enter its native PD calculation and torque
limiting; arm targets go to native actuator controls, and waist targets follow
the native waist path. This service does not remove or bypass any such native
control. SONIC likewise receives the original finite upper-body targets through
its unchanged native WBC goal conversion. This is SIM behavior, not permission
to send arbitrary targets to hardware.

The service's existing generic pre-execution rejection keeps malformed vectors
from reaching the worker and reports bounded validation feedback without a
control or sequence advance. Unexpected native/runtime failures remain terminal.
The private evaluator-only `diagnostic_hold` helper retains its historical
bounded hold construction; it is not a public RPC or a policy action filter and
is not used by public raw-encoder service diagnostics.

AMO receives `[vx,target_yaw,vy,height-0.75,torso_yaw,torso_pitch,torso_roll,turn]`. Preserve stabilized torso orientation from AMO's controller state; policy waist targets are separate commands. SONIC receives current WBC observations, upper-body targets, `[vx,vy,turn,target_yaw]` and height through native `ActionCmd("decoupled_wbc")`, preserving native waist/switch settings.

## Budget and native scoring

The implemented decision track fixes 200 maximum policy calls, prefix cap 5 and a separate 1000-control cap. A shorter chunk executes fewer controls; a stop-only response uses one policy call but no action decision. No hidden 16/30-control repetition is permitted.

Native reference horizons are 400, 800, 1000 or 1200. The 1000-control track extends some tasks and shortens the 1200-control task; record both values and the difference. The default task scope also offers `budget_mode="horizon"`. These tracks must not be pooled as identical native conditions.

Consume success from the native step's reward/`_success` path without an extra scorer query: some predicates, including faucet behavior, are stateful. Native success/termination, evaluator caps and errors remain authoritative. Minimum actions before voluntary give-up is a policy preference, not a SIMPLE rule.

Record policy calls, action decisions, actual controls, initialization controls, physics timing, reference horizon and first-success control/call index. Do not derive decisions by dividing controls by five. Distinguish native failure, policy stop, timeout and environment error.

## Evidence and limits

Retain source/controller/asset/reset provenance, task/backend and sensor/action specifications, native logs, delivered observations, actions/executed prefixes, per-control metrics, errors and decodable video under the selected model's `results/simple_humanoid/` namespace.

Inventory checks do not certify all transitive USD/texture/object dependencies, every task reset or GPU isolation. Runtime/asset portability is incomplete; see [setup](README.md). CPU checks and zero-policy diagnostics are infrastructure evidence, not capability scores or native-full parity.
