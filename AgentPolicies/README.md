# AgentPolicies: agent methods and their results

This directory holds the methods being evaluated and their trusted evaluation
drivers, not native benchmark implementations. Each profile owns its policy
factory, non-secret configuration, prompt, evaluation entrypoint and
`results/<benchmark>/` namespace, declared in a self-describing
`configs/profile.json`. A profile identifies a complete
method, which may compose multiple general-purpose models with declared roles.
It need not correspond to one model name or inherit a particular Python class.
See [protocol-first method integration](../docs/agent-methods.md).

## Add your own method

Create `AgentPolicies/<your_method>/`, for example `AgentPolicies/my_agent/`,
to build your own agent method and its Bench Server client. Keep its code,
configuration and usage instructions together in that directory.

A suggested Python layout is shown below; use only the files and folders your
method needs:

```text
AgentPolicies/my_agent/
├── README.md       # Dependencies, configuration and how to run
├── run.py          # Trusted entrypoint connecting to a Benchmark service
├── policy.py       # Your observation-to-action decision logic
├── configs/        # Model settings, prompts and method configuration
├── tools/          # Optional method helpers
└── results/        # Generated local outputs; Git-ignored
```

Document how to install dependencies, configure the method and run it against a
selected benchmark. Declare the models, prompts, tools and memory your method
uses. Connect through the [Bench Server protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md),
using the service's declared observations, actions and execution feedback.
Keep service credentials and administrative operations in the trusted driver.

You can own the decision loop and use any language or framework; Python `Policy`
and profile-registry integration are optional. The existing
[`gpt6_astra` client](gpt6_astra/README.md) is one reference implementation.

## Existing clients

- [`gpt6_astra/`](gpt6_astra/README.md): one Bench Server validation client,
  `codex_native` (`codex-native/v2`), preserving persistent Direct control and its
  optional completion and repeated-command settings;
  no alternate active methods or method-selection step.
- `gpt6_astra/tools/runner.py`: reusable execution loop, also used by the
  general CLI. Each profile keeps its own behavior settings.

The [Bench Server protocol skill](../docs/bench-server-protocol/SKILL.md)
provides development-time integration guidance and a copyable single-case driver
template. It lives outside `AgentPolicies` and is not a registered profile or
installed runtime package. The template deliberately requires a complete
single-case schedule, horizon mode and prefix one; these are template boundaries,
not general protocol limits. No native/model result is claimed.

Action planning, auxiliary control and decisions to keep trying or give up belong
to the model/method and must use only declared observations. No policy may obtain
a simulator handle, private scoring/state or change native task conditions.

[`benchkit/`](../benchkit/README.md) provides shared communication, result, audit and reporting tools;
it is not a mandatory control middle layer. Benchmark servers, adapters,
environment tools, tasks and protocols belong under [`benchmarks/`](../benchmarks/simBenchmarks/README.md).
Generic profile validation belongs to `benchkit/model_profiles.py`,
while actual model factories remain here.
The server-only [`gpt6_astra/run.py`](gpt6_astra/run.py) entrypoint uses a trusted
driver to retain fixed-schedule/admin/record access, distinct from the model
actor. The actor receives only allowed observations and counters, never that
client or credential. Moving an administrative client does not make it actor-safe.
Shared fixed-action diagnostic fixtures belong to
[`benchkit/diagnostics/`](../benchkit/diagnostics/README.md), not the model namespace.
Add future reusable provider transports on the policy side when implemented;
there is no separate active `providers/` wrapper in the current layout.

Keep the entire `results/` tree local and Git-ignored, including reports,
indices and generated media. Publish selected summaries in project documentation
or the website. Interaction recording is optional, default
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

Existing result trees remain available locally and are excluded from source
checkouts. Their original reports, hashes, source files and identities are not
rewritten. For a historical repository-root path, replace only the leading
`starVLA/` with `AgentPolicies/` to locate the same artifact today. Do not apply
that substitution inside an old run's captured source: its `starVLA/` modules and
commands remain historical data, not current import entrypoints. Relative
links within a moved result tree keep their depth and layout.

The sole `codex_native.py` policy/factory lives beside `run.py`. The single
`codex_native_config.json`, prompt and profile declarations live under
`configs/`; runtime/transport helpers live under `tools/`. Runs record the
profile ID, effective configuration and client git revision instead of a
model-source bundle; historical bundles remain data that live code does not
read. The retired `anonymous_code_agent` mailbox and `opus` label, like other
retired methods and their old guides, remain recoverable from Git history.
Historical anonymous trials remain data, not verified named-model scores.
The [client README](gpt6_astra/README.md) documents the current
client; development notes are kept locally. Reorganization
does not rename an old score, authorize a retry or attest the model provider.
