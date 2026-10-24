# Agent-method interaction contract

Method declaration: `starvla-rsi.method/v1`.

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

Declare how the method retains delivered observations/actions and measures
provider usage. Current-observation delivery does not imply a stateless method:
it may remember previously delivered inputs within the allowed episode scope.
Unmeasured usage remains unknown, not zero. A transport connection alone proves
neither provider identity nor filesystem isolation. Client-specific transport,
memory and recovery behavior belongs in the method's own documentation.

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
because an external example has access to it. The evaluated method must not
carry task-dependent memory across episodes unless the selected protocol permits
it. This does not forbid evaluator bookkeeping or claim control over provider
storage; disclose the method's effective context and any isolation limitations.

## Action contract

A non-stop response contains an `ActionChunk`: one or more vectors matching the
benchmark's declared `ActionSpec`. The specification freezes component order,
bounds, units, coordinate frame, rotation representation, gripper convention,
and control frequency.

Invalid actions are rejected without execution or silent clipping. The method
chooses chunk length and when to replan; the trusted driver submits controls
individually and stops on native termination or the declared budget. Some
existing tracks additionally require a fixed replan interval or couple it to
their execution cap; those versioned constraints remain binding until explicitly
migrated. Protocol-fixed image conversion, units,
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

Task, layout/initial-state and seed selection belong to the benchmark's sample
schedule, not the policy's reasoning strategy. Declare selected cases and
attempts before execution, retain failures/errors and report the denominator.
Planned repetitions are not failure-triggered retries.

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

The trusted driver owns administrative claims, credentials and result access.
The model actor receives only the selected protocol's declared observations and
execution feedback. Use the method's documented input/output schema; validating
that schema is not proof of actor isolation or provider identity.

A code agent helping implement an adapter is a developer, not the policy under
test. During scored episodes the evaluated model can write only its declared
response or policy scratch artifact; it cannot modify the benchmark, protocol,
adapter, episode matrix, scorer, or prior results.

Isolation covers operator-provided context as well as transport payloads. Do
not pass evaluator/reviewer context, private reset metadata or scorer outputs
through actor launch messages, filenames or logs. Follow the selected track's
episode-identity and memory rules; an opaque endpoint alone is not isolation.
Preserve and disclose an affected attempt if private context leaks. A later
correction does not rewrite its conditions or authorize an automatic retry.

See [task plans and coverage](TASK_COVERAGE.md) for accounting and
[agent-method integration](../../docs/agent-methods.md) for client construction.
