# Agent-method interaction contract

Current method declaration: `starvla-rsi.method/v1`. Historical frozen packages
retain their original `starvla-rsi.policy/v1-draft` definitions; this guide does
not upgrade their evidence or change any benchmark's native interface version.

StarVLA-RSI evaluates complete agent methods through declared robot capabilities.
Participants own model composition, prompts, memory, tools and planning. The
service owns environment access, native execution and scoring. Direct control
restricts that external boundary, not how many internal reasoning or model
steps the method uses. Report results per benchmark/protocol/method/configuration.

The repository evaluates direct control by general-purpose models. VLA-assisted
hybrid control, learned action proposals, fallback task policies and automatic
task-solving skill services are out of scope. Retained legacy material or an
external comparison does not enable these methods in the current framework.

## Protocol-first integration; optional Python loop

A trusted driver can implement the [service wire protocol](SERVER_PROTOCOL.md)
in any language or framework. It holds management credentials privately and
exposes only declared sensors/actions to the actor. The reusable Python loop is
one convenient implementation: at each replan boundary it calls `Policy.act`:

```text
Observation(t) -> Policy.act -> PolicyDecision(action chunk or stop)
                                      |
                                      v
                              simulator executes
                                      |
                                      v
                              Observation(t + k)
```

One decision may use several declared model components, local tools, planning
and memory over permitted information. It does not grant extra sensors, reset
search, simulator rollouts or private scores. Tool/network availability remains
part of the declared method and deployment isolation, not new server authority.
Single-model, fixed-prompt, one-request policies remain valid controlled
baselines. Their extra constraints are method settings, not global requirements.

The model response may contain private reasoning if the provider supports it,
but only the final structured decision crosses the policy boundary. Hidden
chain-of-thought is neither required nor stored.

The currently implemented file mailbox is an **experimental development
transport**, not a trusted provider-request meter.
It enforces scheduled observation/action exchange, but cannot count hidden
provider activity or sandbox an actor's filesystem. Orchestrated code-agent
trials report unavailable provider usage as `null`, retain observable decision
counts, without claiming provider identity, complete usage measurement or
enforced filesystem isolation. Missing usage is not a participation ban.

In the current development campaigns the frozen public prompt explicitly
permits remembering earlier observations/actions from the same episode. The
mailbox's `history: current_observation_only` describes payload delivery, not a
claim that the external actor is stateless. Its conversation memory and provider
context length are not metered; no cross-episode memory is allowed in that
mailbox track. Disclose method-specific history/context settings; enforce any
limits required by the selected track, not a new universal inference budget.

## Direct policies and diagnostics

The shared `Policy` interface can host:

1. a multimodal foundation model producing structured action vectors;
2. a fixed program or generated policy that was frozen before scored episodes;
3. scripted policies used only for environment and adapter validation.

Diagnostics are not model capability scores. Conventional-policy legacy files
are retained references, not an enabled hybrid-control path.
The method family and exact construction must be declared. Code generation,
planning and tool use inside the method are method differences to disclose,
not an automatic change to the benchmark's execution protocol.

## Observation contract

Each call contains only channels declared by `ObservationSpec`:

- the current task instruction;
- named camera frames at protocol-fixed resolution and encoding;
- named proprioceptive values when the track permits them;
- a fixed-length frame/action history only when explicitly declared;
- non-privileged timing or episode metadata required by the protocol.

Private simulator state, object poses, segmentation, reward, success predicates,
oracle plans and scorer internals are forbidden. A proposed privileged track is
not an enabled exception in this framework. Permitted robot proprioception must
already be declared by the selected benchmark protocol; a method cannot add it
because an external example has access to it. The evaluator, model and provider
may not retain cross-episode state unless the released protocol says so.

## Action contract

A non-stop response contains an `ActionChunk`: one or more vectors matching the
benchmark's declared `ActionSpec`. The specification freezes component order,
bounds, units, coordinate frame, rotation representation, gripper convention,
and control frequency.

The runner validates every vector and rejects invalid actions; it does not
silently clip them. A fixed `replan_interval` determines how much of a chunk is
executed before the next observation. Protocol-fixed image conversion, units,
joint order, interpolation and native low-level control belong to the benchmark
adapter. They must remain identical within a comparable track. Model-specific
planning, grasp heuristics, motion generation or auxiliary IK belong to the
policy under `AgentPolicies/<profile>/`, are declared and frozen as part of that method,
and may use only policy-permitted observations. Native protocol-fixed control
conversion is permitted; an extra autonomous skill service is outside the
direct-control scope, not an adapter implementation detail.

A stop response only ends policy execution. It never awards success; the native
benchmark scorer remains authoritative.

Persistence and voluntary give-up preferences also belong to the policy. A
model may opt into a declared minimum-action-decision rule through its strategy
configuration; another model is not required to adopt it. The neutral
optional agent-side runner records actual executed decisions/control steps and enforces
public resource limits, but does not select a model's persistence preference.
No persistence setting overrides native termination, hard limits or safety.
Historical floor50 trials retain their frozen records without becoming a new
benchmark-wide rule.

## Budgets

Use benchmark-native execution budgets and reset/termination rules. Disclose
all extra method or selected-track limits; do not impose one global inference
budget across otherwise different methods. Distinguish:

- maximum simulator steps and wall time;
- optional decision-call safety cap (including the reference feedback loop cap);
- measured provider requests and per-component usage, or unknown;
- declared input/output token limits and provider reasoning settings, if selected;
- action chunk length and executed replan prefix;
- timeout, retry, and invalid-response handling.

Legacy one-attempt campaigns do not retry infrastructure or policy errors.
The explicit `invalid_action_handling=feedback` extension instead rejects a
confirmed invalid action without executing it, then returns a bounded public
issue at the next normal, counted `Policy.act` call. No new sensor capture,
hidden inference, internal retry, replacement control or reset occurs. Every
call retains usage and consumes the declared finite call budget. A previously
ACKed valid prefix remains executed. Native/transport uncertainty and forbidden
tools remain terminal, not recoverable input errors. Old frozen attempts keep
their original outcome and handling. See the [service extension](SERVER_PROTOCOL.md#pre-execution-action-rejection-extension).

`fast` and `full` are evaluation plans, not policy behavior: fast selects tasks
and one fixed state/attempt each; full follows the native task/variant/seed and
per-task episode schedule. Planned native repetition is not failure-triggered
retrying. Both retain failures/errors. Unified full presets remain unimplemented
until their exact native schedules and execution conditions are verified.

## Essential results and optional history

Every result identifies:

- benchmark, protocol, simulator, asset, task/scene, and seed identities;
- method identity/configuration, declared models and roles (unverified or unknown
  identity remains explicit), protocol and available source/environment origins;
- decision calls, executed decisions, controls, termination and selected denominator;
- available inference usage/latency/cost, aggregate and per component where measured;
- native task outcomes, without treating partial task score as success rate;
- typed policy, protocol, and infrastructure errors.

Detailed interactions, visible model IO, tool traces, images and videos are
optional, enabled by default where supported. They are not participation or
publication gates. [Minimal recording](../../docs/recording.md) retains essential
results; the independent basic reporter needs neither event logs nor source
snapshots. Existing deeper audits can require more evidence and keep that scope.
Credentials, secrets, evaluator-private inputs and hidden chain-of-thought are
excluded. User-visible records still require review before sharing.

## Roles and isolation

For the anonymous code-agent profile, coordinators should send its exact
[actor instructions](../../AgentPolicies/anonymous_code_agent/prompts/actor_instructions.txt)
with only host/opaque mailbox substitution, never hand-retype alternative JSON
keys. Its minimal examples are regression-tested against the frozen mailbox
parser. Operator-written examples must use that exact schema: an incorrect field
can invalidate an otherwise useful response. The tests are schema checks, not
actor-access or provider-call attestation.

A code agent helping implement an adapter is a developer, not the policy under
test. During scored episodes the evaluated model can write only its declared
response or policy scratch artifact; it cannot modify the benchmark, protocol,
adapter, episode matrix, scorer, or prior results.

Isolation covers operator-provided context as well as mailbox JSON. Use a fresh
actor context and an independently random, opaque orchestration task name; do
not encode benchmark, suite, task ordinal, seed, date or outcome in an actor
name, display label, launch message or scratch-directory label. Give the actor
only its transport host, opaque endpoint and shared interaction instructions.
Evaluator/reviewer context must not be inherited. An opaque endpoint alone does
not blind identifying text elsewhere in the actor's conversation.

If such context has already reached an actor, retain and disclose the affected
attempt; do not relabel it as fully blinded or retry it. A prospective operator
correction must record its cutover separately from immutable runtime/prompt/
budget manifests. See [task plans and coverage](TASK_COVERAGE.md) for the shared
accounting rules.
