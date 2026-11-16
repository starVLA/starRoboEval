# Add and evaluate an agentic policy

An agentic policy is evaluated as a complete method: its general-purpose models,
prompts, memory, tools, planning and action-generation behavior. Single-model,
fixed-prompt policies remain useful baselines. Publish comparisons within a
benchmark and protocol, with method differences explicit; this repository does
not yet define a cross-benchmark aggregate leaderboard.

## Add your policy

Create `AgentPolicies/<your_method>/` and keep the method's implementation,
configuration, dependencies and usage instructions together. The directory names
the method; it can use one model or several general-purpose models. Adding a
method normally leaves benchmark services and shared evaluation code unchanged.

A Python method can use this layout. Keep only the optional folders it needs:

```text
AgentPolicies/my_agent/
├── README.md       # Dependencies, configuration and launch command
├── __init__.py
├── run.py          # Trusted entrypoint connecting to a benchmark service
├── policy.py       # Observation-to-action decision logic
├── configs/        # Method configuration and prompts
├── tools/          # Optional method helpers
└── results/        # Local outputs by benchmark; Git-ignored
```

Install the method's dependencies, then invoke its own entrypoint from the
repository root, such as `python -m AgentPolicies.my_agent.run`. Its README must
document the required service endpoint, credential setup, case selection and
output arguments. The existing [agentic policies](../AgentPolicies/README.md#existing-clients)
provide working entrypoints for their own methods.

Choose the integration that fits your method:

- **Shared Python runner:** implement the [Policy interface](../benchkit/interfaces.py),
  construct your policy in `run.py`, and connect with
  [SimServerBenchmarkAdapter](../benchkit/sim_server/client.py).
  Call [EvaluationRunner](../benchkit/driver/runner.py) with the policy, client and
  an explicit `RunRequest` for the selected schedule and budgets. The runner
  handles execution, closure, counters and result files.
- **Your own driver:** implement the [service protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md)
  and [closed result format](result-format.md) in your chosen language or framework.
  Your method owns its decision loop and accounting.

### Optional profile loading

The Python profile loader reads `AgentPolicies/<id>/configs/profile.json` directly;
there is no central model list to edit. To use it, declare a factory within your
method's namespace, plus its config, configuration schema and prompt files.
Follow the [profile format](../benchkit/driver/model_profiles.py) and use a lowercase
identifier such as `my_agent`. Instantiating your policy directly does not require
these profile files.

Use your method's entrypoint to run evaluations. `rsi-bench run --policy` selects
infrastructure diagnostics; it does not launch arbitrary agentic policies.
`rsi-bench preflight-policy --model-profile <id>` supports profiles that implement the
optional readiness check.

Source-checkout use needs no packaging registration. To include a new Python
method in the repository's built wheel, also add its packages and configuration
files to [pyproject.toml](../pyproject.toml), which currently lists the supplied
profiles explicitly. Keep installation requirements in the method's README.

## Two control ends

- `benchmarks/simBenchmarks/<benchmark>/`: robot capabilities, native execution
  budget, fixed episode selection and native scoring.
- `AgentPolicies/<method>/`: actor implementation, trusted driver, models,
  prompts/configuration and `results/<benchmark>/`.
- `benchkit/`: shared transport, case leasing, data formats, optional recorders and reports;
  not a mandatory third process or a central model proxy.

Case selection and scheduling remain separate from policy decisions. See the
[evaluation workflow](evaluation.md#choose-a-workflow).

Direct control constrains environment access and robot execution, not internal
reasoning. A method may use several declared general-purpose models and tools
over permitted information. This does not allow oracle state, extra resets,
hypothetical simulator rollouts, a VLA/hybrid controller, a fallback task policy
or a server-side task solver. Fixed robot-only/native low-level execution remains
benchmark-owned. Tool/network availability and cross-episode memory restrictions
must still follow the selected protocol and declared deployment configuration.

Check the selected track before comparing methods. For example,
[SimplerEnv](../benchmarks/simBenchmarks/SimplerEnv/EVALUATION_PROTOCOL.md#agent-method-setting)
supports `interaction_mode="agent_method"` for multiple model calls and local
tools within a decision. Its default `single_response` setting has a different
request limit. Select and record the intended setting before evaluation.

Use benchmark-native execution conditions. Report inference requests, tokens,
latency and cost when available; do not invent unknown values. There is no new
universal reasoning/token/decision budget. Existing method-specific timeouts,
feedback-loop caps and protocol-specific limits remain explicit configuration,
not silently disabled. In particular the current
[`gpt6-astra-codex-native`](../AgentPolicies/gpt6_astra/README.md) and
[`claude-opus-messages-native`](../AgentPolicies/claude_opus/README.md) clients
require a finite decision-call cap to bound invalid-action feedback.

## Connect using the protocol

1. Obtain an existing service endpoint, private credential and declared case
   selection from its operator. If you also operate the service, follow the
   benchmark's setup guide and launch it with `rsi-bench serve --benchmark <id> ...`.
   Connecting a policy does not require installing the simulator on the agent host.
2. Connect from your trusted driver using the shared client or the
   [authenticated JSON protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md).
   `describe` supplies the actual observation/action contract.
   Claim each selected episode once; obey sequencing, native budgets,
   termination and uncertain-ACK/no-replay rules.
3. Expose only declared observations and robot actions to the actor. Do not give
   it the administrative client, credentials, private metrics or native handles.
4. Close/finalize every attempt and emit essential result records. Detailed
   interaction history is optional, default enabled where supported.

The [Bench Server protocol skill](bench-server-protocol/SKILL.md) provides optional
implementation notes and a single-case educational driver. Review and adapt that
example before using it; it implements a narrower execution and accounting path
than the shared runner.

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

Read [recording options](recording.md) for minimal/standard modes and
[result format](result-format.md) for the closed-result contract.
An external driver may emit that JSON layout without
importing the Python runner. Source hashes and deep audits remain optional
internal support, not public eligibility requirements. Failures, errors and the
preselected denominator must still be retained. Do not attribute all method
differences to the underlying model.
