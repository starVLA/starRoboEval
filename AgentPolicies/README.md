# AgentPolicies: agent methods and their results

This directory holds the methods being evaluated and their trusted evaluation
drivers, not native benchmark implementations. Each profile owns its policy
factory, non-secret configuration, prompt, dependency declaration, evaluation
entrypoint and `results/<benchmark>/` namespace. A profile identifies a complete
method, which may compose multiple general-purpose models with declared roles.
It need not correspond to one model name or inherit a particular Python class.
See [protocol-first method integration](../docs/agent-methods.md).

- `anonymous_code_agent/`: runnable experimental mailbox policy; actual provider
  and model identity remain unknown. Its mailbox implementation lives here.
- [`gpt6_astra/`](gpt6_astra/README.md): Native, generic persistent Direct v3 and Planned
  Codex methods; compatibility and evidence are method-specific.
- `opus/`: unconfigured label, not a runnable provider integration.
- `policy_support/`: reusable agent-side decision loop and policy behavior,
  including persistence / voluntary-stop rules selected by a policy's own configuration.
- [`protocol_example/`](protocol_example/README.md): small independent trusted-driver
  example with no bundled actor or registered model; fake-service tests only.

Action planning, auxiliary control and decisions to keep trying or give up belong
to the model/method and must use only declared observations. No policy may obtain
a simulator handle, private scoring/state or change native task conditions.

[`benchkit/`](../benchkit/README.md) provides shared communication, result, source, audit and reporting tools;
it is not a mandatory control middle layer. Benchmark servers, adapters,
environment tools, tasks and protocols belong under [`benchmarks/`](../benchmarks/simBenchmarks/README.md).
Generic profile validation/source capture belongs to `benchkit/model_profiles.py`,
while actual model factories remain here.
The server-only [`gpt6_astra/run.py`](gpt6_astra/run.py) entrypoint uses a trusted
driver to retain fixed-schedule/admin/record access, distinct from the model
actor. The actor receives only allowed observations and counters, never that
client or credential. Moving an administrative client does not make it actor-safe.
Shared fixed-action diagnostic fixtures belong to
[`benchkit/diagnostics/`](../benchkit/diagnostics/README.md), not the model namespace.
Add future reusable provider transports on the policy side when implemented;
there is no separate active `providers/` wrapper in the current layout.

Keep compact reports and optional provenance indices tracked; ignore raw runs,
generated media and mailbox traffic. Interaction recording is optional, default
on, and not a publication gate; [recording options](../docs/recording.md) preserve
essential outcomes when detailed logs are off. Never rewrite historical outcomes or relabel anonymous trials as
provider-verified named-model scores. Explicit owner-reported attribution notes
may coexist with unchanged original identity and accounting fields.

## Namespace and preserved results

The repository-root Python package and result directory were renamed from
`starVLA/` to `AgentPolicies/`. New commands use, for example,
`python -m AgentPolicies.gpt6_astra.run`; there is no old import alias or symlink.
The repository/distribution name `starVLA-RSI` and upstream project references
are unchanged.

All existing result trees move with this directory, including ignored raw runs
and videos. Their original reports, hashes, source files and identities are not
rewritten. For a historical repository-root path, replace only the leading
`starVLA/` with `AgentPolicies/` to locate the same artifact today. Do not apply
that substitution inside a frozen package: its captured `starVLA/` modules and
commands remain historical evidence, not current import entrypoints. Relative
links within a moved result tree keep their depth and layout.

New model-source bundles use schema `starvla-rsi.model-source/v6`; GPT's three
active methods are under `methods/`, their helpers under `tools/`, and transports,
configs and prompts in separate directories. Auditors still validate v1/v2 under
`starVLA`, v3 under flat `AgentPolicies`, and the earlier grouped v4/v5 layouts with
their exact historical allowlists. These are frozen-source versions,
not current import aliases. Reorganization does not upgrade an old score,
authorize a retry or attest the model provider.
