# Policy interface

This is the participant-facing contract for the `mailbox` development transport.
The benchmark service itself uses the [shared SIM wire protocol](../../../SERVER_PROTOCOL.md)
through [server.py](../../server.py) and [bench_server/adapter.py](../adapter.py).
The trusted agent driver holds that administrative client; a mailbox actor
receives only the permitted observation/action contract below, never SIM credentials.
Use [README.md](../../README.md) to install and launch it, and
[EVALUATION_PROTOCOL.md](../../EVALUATION_PROTOCOL.md) to choose the evaluation track.
The simulator is owned by `SimplerEnvBenchmarkAdapter`, never by the policy.
The selected [interaction mode](../../EVALUATION_PROTOCOL.md#interaction-modes)
also applies: `single_response` preserves the historical provider-request
restriction; explicit `agent_method` permits declared internal inference/local
tools on public data. Both submit one response per scheduled observation and
retain the same sensor, control and no-replay boundaries.

## One observation, one response

1. The evaluator supplies a fresh opaque mailbox root. Poll only its `ready.json`.
2. When `status` is `pending`, read its `observation_path` and the PNG files
   explicitly referenced by that observation. Copy its exact `request_id`.
3. Produce one action chunk or one stop response. Write a temporary file beside
   `response_path`, then atomically rename it to that path.
4. Wait for a **new** pending request. Do not modify or resubmit an old response.
5. `episode_closed` ends the episode. `failed` means the decision failed; do not
   retry it. `idle`, `episode_started`, and `consumed` are not requests for action.

Current wire `starvla-rsi.mailbox/v3` uses paths **relative to the mailbox root**, including
`ready.json`'s observation/response paths and every `images.*.path`. Resolve them
against that root, not against the observation's parent directory. Request IDs
are random, independent of the evaluator's path and reset seed. The operator
must supply a stable seed/task-independent parent and an opaque endpoint; do not
hand an actor a date-, seed-, or task-labeled evaluator directory. Use
`python -m AgentPolicies.anonymous_code_agent.tools.new_mailbox --root <stable-root>`
for standalone runs, or the frozen campaign CLI's `prepare --mailbox-root`.
Wire v2 also uses relative paths; v3 adds policy-owned constraints and confirmed
execution feedback. Old v1/v2 records remain under their original schema.

Files from older requests are not extra observations. The actor may retain its
own within-episode observation/action history, but must reset it between episodes.
The `history: current_observation_only` field describes the current payload,
not a claim that the transport erases the model's memory.

## Observation fields

| Field | Meaning |
| --- | --- |
| `request_id` | Opaque identifier to echo; do not infer scene configuration from it. |
| `step` | Number of controlled environment steps already executed. |
| `instruction` | Current native language instruction. |
| `images` | Declared camera names mapped to PNG path, dimensions, RGB encoding and SHA-256. |
| `state` | `null` in RGB-only; joint encoders only in the separately labeled RGB-qpos track. |
| `observation_spec` | Declared cameras, modalities and state names. |
| `action_spec` | Action dimensions, units, bounds, controller frame and gripper convention. |
| `budgets` | Maximum environment steps, policy decisions, executed prefix, chunk size and response timeout. |
| `policy_constraints` | This policy's optional persistence/stop preference, separate from benchmark rules. |
| `control_feedback` | Confirmed executed action decisions and controls, not submitted chunks or native scoring. |
| `prompt` | The selected model policy's frozen instructions, not task-specific simulator assistance. |

Google Robot exports `overhead_camera` RGB, 512×640. WidowX exports
`3rd_view_camera` RGB, 480×640. No extra camera requests are available.
The optional qpos track exposes 11 Google or 8 WidowX joint encoders, not object
poses, end-effector pose or camera calibration.

Forbidden policy inputs include reset seeds and variant IDs, depth, segmentation,
object poses, simulator `extra`/`info`, reward, native success, contacts, scorer
code, evaluator artifacts, and arbitrary simulator queries. A policy must not
import the simulator or control it through another channel.

## Action response

Each action is `[dx_m, dy_m, dz_m, rx_rad, ry_rad, rz_rad, gripper]`.
Translation is in meters; rotation is an axis-angle rotation vector in radians,
not Euler angles. The supplied action spec is authoritative.

| Embodiment | Target convention | Gripper | Control frequency |
| --- | --- | --- | --- |
| Google Robot | `ee_align`, measured-pose delta | +1 close, −1 open, 0 hold target | 3 Hz |
| WidowX | `ee_align2`, accumulated-target delta | +1 open, −1 close, 0 intermediate opening | 5 Hz |

Schema illustration only; this vector is not a universal task-solving action:

```json
{
  "request_id": "exact-current-request-id",
  "actions": [[0, 0, 0.01, 0, 0, 0, 1]],
  "usage": null,
  "note": "Small upward motion."
}
```

Or stop the episode, without claiming success:

```json
{
  "request_id": "exact-current-request-id",
  "stop": true,
  "stop_reason": "Unable to make further visual progress within the contract.",
  "usage": null
}
```

Use numbers, not numeric strings or booleans. Every action in a chunk is checked
for dimension, finite values and bounds, including actions beyond the executed
prefix. Unknown/duplicate JSON keys, excessive chunks, replayed request IDs,
symlinks, oversized files and malformed output fail the decision. No automatic
repair request or retry is made. `note` is optional and describes the final
action briefly; private reasoning is not required.

Before the atomic submission, a client can locally check its proposed vector
lengths and numeric bounds against the already supplied `action_spec`; this
does not request a new observation or evaluator feedback. Include the gripper
component: a six-value pose vector is not a valid seven-value robot action.
Do not silently pad, truncate or reinterpret malformed actions. In the default
historical fail-fast track, a submitted rejected response consumes the failed
decision and ends that attempt; it cannot be repaired and resubmitted. Local
validation is not permission for an extra provider request in a
one-request-per-decision track.

The service's explicitly selected `action_rejection_feedback=true` track has
a distinct `/action-feedback` protocol component before any `/agent-method`
component and the final `/v1`. A compatible trusted driver
may give the next normal counted call the bounded public validation error and
the same last acknowledged observation. No invalid action executes, no new
image is acquired and no within-call service follow-up is allowed. Rejections still
consume the finite call budget; transport uncertainty is fatal, not replayable.
This optional track is not automatically enabled for the legacy mailbox route.
See [the benchmark protocol](../../EVALUATION_PROTOCOL.md#optional-rejected-action-feedback).

## Budgets, execution counts and policy preferences

- `max_steps` counts native control actions, not physics substeps or model calls.
- `max_policy_calls` counts calls to `Policy.act`, including failed calls and stop
  responses. A stop consumes a decision but executes no control action.
- `action_decisions` counts non-stop decisions with at least one actually
  executed control. It is not inferred from submitted chunks or request numbers.
- Provider request/token usage is separate. The historical `single_response`
  track requires one provider request at most per decision; its method must
  declare enforcement evidence. The `agent_method` track permits declared
  internal inference and tools without that request limit. This file transport
  and the benchmark service cannot verify hidden provider activity in either mode.

Only the declared prefix of a returned chunk is executed before the next
observation. Shorter chunks use fewer steps but still consume one decision.
In the `horizon` track, the first exhausted step/decision limit ends
the attempt. In the `decisions` track, decisions are the primary budget and
the declared safety cap is `max_policy_calls × replan_interval`. For example,
the fast campaign's 200 decisions with an executed prefix of at most 5 permit up to 1000 controlled
steps. Short chunks do not buy extra decisions. Task termination, explicit stop
or an error may still end the attempt earlier. A response timeout is
a policy error, not an invitation to request another observation.

Use `usage: null` when provider accounting is unavailable, as with an external
actor without trusted provider telemetry. If measured, use an object such as
`{"calls":1,"input_tokens":123,"output_tokens":45}`. Never invent zero usage.
Client-reported totals are not trusted-provider enforcement. Missing provider
telemetry remains an explicit limitation, not evidence of zero inference or a
new participation restriction in the agent-method track.

`native_horizon` retains the upstream reference. `evaluation_horizon` is the
predeclared actual TimeLimit. A multiplier of 2 selects a distinct extended track,
not a hidden continuation after a failed native-budget trial. See the evaluation
protocol for H/2H checkpoint interpretation.

The 200-decision ceiling is a fast evaluation setting, not a native full
benchmark budget. Record actual decisions, steps and first-success timing.
Do not change budgets within an attempt. Decision-limited and horizon-limited
results have distinct protocol IDs and must not be pooled as the same score.

An optional minimum-action count before give-up is a model policy preference,
published under `policy_constraints`. It is not imposed by the benchmark.
`control_feedback` reports confirmed counters only: policy calls, executed action
decisions, environment steps and the last executed prefix length. It contains
no native scores, rewards, contacts or simulator metadata. Policy-side rules
must not delay native end, hard limits, errors or justified safety stops.

## Process lifecycle

The benchmark-owned HTTP service retains each claimed native environment while
the trusted agent driver waits for a policy decision. No control/physics step
advances while waiting. Only the service executes acknowledged action prefixes;
completion closes the environment and saves artifacts. The service owns native
reset, task selection and scoring, not model prompts or task-solving behavior.

The older in-process mailbox/campaign route remains available: its task-scoped
evaluator owns the same adapter and the frozen campaign coordinator starts each
selected case in a separate child process. This compatibility path is distinct
from the server deployment. Neither route requires a model-training server.
Keep evaluator logs and scores private while a policy is acting.

## Isolation and audit

The mailbox is an auditable transport, **not an OS security sandbox**. Formal
submissions need a process/container permission boundary exposing only the
mailbox to the policy. Evaluator logs, videos and native scores are private while
the episode is active; an independent reviewer may inspect closed artifacts
afterward through the shared closed-record and mailbox-artifact audits listed
in [README.md](../../README.md#results-and-offline-review). Audit acceptance is bounded
record consistency, not proof of trusted provider activity or native parity.
