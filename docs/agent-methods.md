# Evaluate an agent method

The unit of evaluation is a complete method: its general-purpose models,
prompts, memory, tools, planning and action-generation behavior. Single-model,
fixed-prompt policies remain useful baselines. Publish comparisons within a
benchmark and protocol, with method differences explicit; this repository does
not yet define a cross-benchmark aggregate leaderboard.

## Two control ends

- `benchmarks/simBenchmarks/<benchmark>/`: robot capabilities, native execution
  budget, fixed episode selection and native scoring.
- `AgentPolicies/<method>/`: actor implementation, trusted driver, models,
  prompts/configuration and `results/<benchmark>/`.
- `benchkit/`: shared transport, case leasing, data formats, optional recorders and reports;
  not a mandatory third process or a central model proxy.

Scheduling organizes selected cases, not the agent's thoughts or actions.
Central campaign scheduling is not part of this version. See
[workflow choices](evaluation.md#choose-a-workflow).

Direct control constrains environment access and robot execution, not internal
reasoning. A method may use several declared general-purpose models and tools
over permitted information. This does not allow oracle state, extra resets,
hypothetical simulator rollouts, a VLA/hybrid controller, a fallback task policy
or a server-side task solver. Fixed robot-only/native low-level execution remains
benchmark-owned. Tool/network availability and cross-episode memory restrictions
must still follow the selected protocol and declared deployment configuration.

Check the selected track before comparing methods. Some existing benchmark
documents, notably SimplerEnv's single-request track, still specify
narrower interaction or evidence conditions. The open-method framework does not
retroactively relax those conditions or relabel their results. Reconciling that
track requires an explicit version decision before an agentic-method comparison;
it is not achieved by changing a prompt or this general guide.

Use benchmark-native execution conditions. Report inference requests, tokens,
latency and cost when available; do not invent unknown values. There is no new
universal reasoning/token/decision budget. Existing method-specific timeouts,
feedback-loop caps and protocol-specific limits remain explicit configuration,
not silently disabled. In particular the current
[`gpt6-astra-codex-native` client](../AgentPolicies/gpt6_astra/README.md) requires
a finite decision-call cap to bound invalid-action feedback.

## Connect using the protocol

1. Install the benchmark's documented native environment and assets. Choose the
   protocol and fixed schedule, then launch `rsi-bench serve --benchmark <id> ...`.
2. Implement the [authenticated JSON protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md)
   in your trusted driver. `describe` supplies the actual observation/action
   contract. Claim each selected episode once; obey sequencing, native budgets,
   termination and uncertain-ACK/no-replay rules.
3. Expose only declared observations and robot actions to the actor. Do not give
   it the administrative client, credentials, private metrics or native handles.
4. Close/finalize every attempt and emit essential result records. Detailed
   interaction history is optional, default enabled where supported.

Any language or framework can implement this protocol. The Python remote client,
`Policy` interface and `AgentPolicies/gpt6_astra/tools/runner.py` are optional SDK
conveniences. They are not prerequisites for participating. A new method does not
require a copy of the simulator or a new benchmark server.

For development-time integration guidance, use the
[Bench Server protocol skill](bench-server-protocol/SKILL.md).
It provides the workflow and a copyable single-case driver template, rather than
an `AgentPolicies` runtime package. The template owns a loop without the profile
registry or Python `Policy` and writes basic-result-compatible records. Copy it
into your method namespace when adapting it; it bundles no actor or registered model.
It deliberately accepts only a complete single-case service schedule with horizon
mode and prefix one. These are template boundaries, not general protocol limits
or support for a RoboDojo panel. No native/model result is claimed.

### Administrative access is not an actor tool

| Capability | Trusted driver / operator | Model actor |
| --- | --- | --- |
| Select and claim a fixed case; reset once | Yes, according to the predeclared schedule | No reset, resampling or branch-rollout tool |
| Receive declared RGB, robot state, instruction and execution feedback | Project only the selected protocol's allowed fields | Yes; state provenance and units remain benchmark-specific |
| Submit robot actions | Validate/forward and account for ACKs | Choose actions through the declared action interface |
| Read native metrics, private artifacts, credentials or deployment configuration | Keep private; collect outcomes for reporting | Never passed as observations or tools |

The current service token authorizes administrative operations; it is not an
actor-scoped token. A same-process callback or separate directory alone is not a
sandbox. Review the driver and deploy untrusted code with separate filesystem,
process and credential permissions. The framework does not attest that isolation.

## Declare composition, not just a model label

The reference driver accepts a JSON `--method-file`; the reusable Python runner
accepts `RunRequest(method=...)`. A declaration looks like:

```json
{
  "schema_version": "starvla-rsi.method/v1",
  "id": "visual_planner_controller",
  "version": "v1",
  "models": [
    {"id": "planner", "role": "planning", "provider": null, "model": null, "version": null},
    {"id": "controller", "role": "action_generation", "provider": null, "model": null, "version": null}
  ],
  "configuration": {
    "memory": "episode_local",
    "prompt_revision": "v1",
    "tools": ["local_image_analysis"],
    "decision_call_cap": 240
  }
}
```

Replace unknown identifiers with what is actually requested/known. This is a
participant declaration, not provider attestation or an automatic multi-model
implementation: your method must implement the composition. Do not put secrets,
private paths or evaluator information in public configuration. Report prompt,
memory, tool and inference settings sufficient to explain the comparison.

Without a method file the reference runner derives a limited identity from the
legacy policy descriptor. This does **not** establish a complete method
configuration; use an explicit declaration for reproducible comparisons. Legacy
`policy` fields remain in raw records, and historical anonymous results are not
relabeled as verified named-model outcomes.

## Usage and decisions are different counters

`policy_calls` counts invocations of the reference decision boundary, including
stop/rejected/failed calls. `action_decisions` counts decisions with at least one
acknowledged control. `environment_steps` counts acknowledged controls. Native
physics ticks and provider inference requests are separate quantities.

The method chooses how many actions, including repeated targets, to send before
another decision. Its trusted driver submits successive single-action `step`
requests and accounts for each ACK; the server does not run a model-specific
repeat loop. Native timing, physics substeps, end conditions and total execution
budget remain benchmark-owned. A method's five-control example is not a universal
benchmark rule. A service's declared `required_replan_interval` must still
match.

Records declare `usage_accounting_version: starvla-rsi.method-usage/v2`:
one decision may contain several model requests. The current auditor rejects a
record without that marker; older runs remain data.

The Python SDK accepts optional `component_usage` in decision or typed-error
metadata, keyed by the declared model component ID, with the normal `Usage`
fields (`calls`, tokens, latency and estimated cost). Record measured increments,
not repeatedly accumulated totals. Missing component accounting remains unknown;
aggregate usage is never divided among models or filled in as zero. Optional
malformed component accounting produces a warning, not a different robot action.
Aggregate `Usage` remains the validated reference runner contract.

A policy whose provider reports usage late or only cumulatively may implement
`episode_usage()`. The runner reads it once after `end_episode` and reconciles
the episode total with the per-call sum, recording any contradiction instead of
clamping it; see [result format](result-format.md#episode-result).

## Results are independent of detailed logging

Read [recording and basic results](recording.md) for minimal/standard modes and
the closed-result contract. An external driver may emit that JSON layout without
importing the Python runner. Source hashes and deep audits remain optional
internal support, not public eligibility requirements. Failures, errors and the
preselected denominator must still be retained. Do not attribute all method
differences to the underlying model.
