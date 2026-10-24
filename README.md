<p align="center">
  <img src="assets/logo.svg" alt="StarVLA-RSI" width="10%">
</p>

# StarVLA-RSI

Evaluate **agent methods** across embodied benchmarks in simulation and,
eventually, real robots. Bring your own decision loop, prompts, memory, tools
and one or more general-purpose models. Each benchmark service owns its robot
interface, native execution budget and success criteria. Compare declared
methods within the same benchmark/protocol, not an unexplained model-name score.
RoboDojo is one integration, not a separate framework.

This is an evaluation framework, not a model-training repository.
Direct control limits environment access and the robot interface, not how the
agent reasons internally. No VLA-assisted hybrid controller or fallback task
policy is inserted between a method and its benchmark. Fixed-prompt, single-model
policies remain useful controlled baselines, not the only permitted methods.

> Status: experimental. There are 13 simulation service entrypoints; supported
> tasks and case selectors vary by benchmark. VLN-CE and unified real-robot
> services are not implemented yet. Native simulators and licensed assets must
> be installed separately.

## Quick start

Use Python 3.10 or newer, from a repository checkout:

```sh
pip install -e .
rsi-bench list
rsi-bench serve --benchmark robodojo --help
```

First [choose a benchmark and its tasks/cases](benchmarks/simBenchmarks/README.md).
The selector delegates to the benchmark's existing server; it does not install
its simulator or change its sensors, actions or task schedule. Follow that
benchmark's setup guide, then launch with a fixed configuration, seed and fresh
output directory. See [service startup and interaction history](docs/evaluation.md).

For dependency-free infrastructure checks (no native robot or model request):

```sh
python -B -m benchkit catalog --check
python -B -m benchkit list
python -B -m benchkit smoke --episodes 3 --seed 7
```

The smoke check is a dependency-free synthetic fixture, not a robot capability
score. It writes records under `results/rsi-smoke/`. Install the environment
described by the selected benchmark before attempting a native task.

- [Declare and connect an agent method](docs/agent-methods.md)
- [Agent driver integration skill and template](docs/bench-server-protocol/SKILL.md)
- [Optional interaction recording and basic results](docs/recording.md)
- [Run an evaluation](docs/evaluation.md)
- [Architecture and ownership](docs/architecture.md)
- [Bench Server visual introduction](assets/bench_server/index.html)
- [Add a benchmark server](docs/benchmark-server-guide.md)
- [Policy interaction protocol](benchmarks/simBenchmarks/POLICY_PROTOCOL.md)
- [Simulator adapter interface](benchmarks/simBenchmarks/INTERFACE.md)
- [Run SIMs as independent servers](benchmarks/simBenchmarks/SERVER_PROTOCOL.md)
- [Build your own agent method](AgentPolicies/README.md#add-your-own-method)
- [Real-robot integration status](benchmarks/realRobots/README.md)

## Repository structure

```text
benchkit/                              shared communication and result/output tools
  sim_server/                         service selector, transport and session lifecycle
  reports/interaction_history.py       closed-run interaction HTML / JSON export
  reports/basic_result.py              outcome view without required interaction logs
  methods.py / recording.py            method declarations and optional record helpers
  campaigns/                          central fixed-plan/case scheduling and progress
  catalog/                            benchmark metadata, not native adapters
  diagnostics/                        non-capability infrastructure diagnostics
benchmarks/
  simBenchmarks/<benchmark>/           environment, tasks, adapter and native protocol
    server.py                          benchmark-owned independent SIM entrypoint
    bench_server/protocol/             task definitions and sample plans, where needed
  realRobots/                          hardware references; unified adapters pending
AgentPolicies/
  <method-profile>/                    policy, model composition, prompts and dependencies
    run.py                             model-owned trusted evaluation entrypoint, where implemented
    results/<benchmark>/               local evaluation outputs; Git-ignored
  gpt6_astra/tools/                    reusable runner and optional policy stop rules
docs/                                 public design and usage guides
  bench-server-protocol/
    SKILL.md                           agent driver integration workflow
    driver.py                          optional single-case driver template
```

Directory-specific `README.md` files explain the code beside them. `docs/`
contains shared architecture, usage guides and integration skills with their
templates.

The benchmark answers “what happens when this action executes?” The policy
answers “what action should I take?” Its trusted driver communicates with the
service through `benchkit/sim_server` and uses the other `benchkit` record/report tools. Planning and
voluntary-stop preferences belong to the policy, not the native benchmark.
The actor never receives the driver's administrative client or credentials.
Use your own trusted driver or the supplied
[reference client](AgentPolicies/gpt6_astra/README.md). Agent-specific commands,
prompts, configuration and runtime dependencies are documented with that agent.

Central task scheduling remains in this version. Current campaign commands
coordinate frozen local cases; they are not yet integrated with remote service
campaigns. Use the [workflow guide](docs/evaluation.md#choose-a-workflow) to choose
the service/driver path or retained campaign path, rather than combining them.
Automatic plugins, expanded scheduling, a comprehensive CLI and cross-benchmark
rankings are planned extensions, not claims of current support.

## Available integrations

The [simulation benchmark overview](benchmarks/simBenchmarks/README.md#choose-a-benchmark)
introduces each benchmark's native tasks, layouts, initial states and variations,
with setup and protocol links. LIBERO evaluates language-conditioned manipulation,
SIMPLE evaluates humanoid loco-manipulation, and RoboDojo covers multiple
manipulation capabilities. They retain different robot interfaces and sample
distributions.

See [deployment requirements](benchmarks/simBenchmarks/SERVICE_SUPPORT.md) for
current service coverage, assets and runtime restrictions, and [real-robot status](benchmarks/realRobots/README.md)
for hardware integrations. No task count or service entrypoint implies that its
native environment is already installed.

## Evaluation guarantees and limits

- Freeze tasks, initial states, seeds, action/observation contracts, budgets and
  model configuration before execution.
- State selected tasks, layouts/initial states, seeds and attempts per case
  explicitly. A seed is not necessarily a different layout; planned repetitions
  are not retries chosen after failure.
- Keep failures and errors. Report attempted and completed denominators
  separately; never turn infrastructure errors into hidden missing samples.
- Record policy calls, executed action decisions and control steps separately.
  One action decision can execute several controls.
- Use native success and scoring. Policies receive only declared observations,
  not simulator object state, reward predicates or evaluator internals.
- Interaction recording is optional and enabled by default. Disabling it does
  not prevent participation or result publication; essential outcomes, method
  configuration, denominators, counters and errors remain available.
- Report inference usage when available, per model component when measured;
  unknown usage stays unknown. No universal inference budget is imposed.
- Keep useful recorded protocol, upstream revision, environment and asset
  provenance. Content hashes and source snapshots remain internal integrity
  support; viewing an interaction history does not require a full source audit.
- Preserve original events and results; never rewrite an outcome or silently
  rerun a task to improve its presentation.

Each [agent method](AgentPolicies/README.md) documents its own model connection,
decision behavior, usage accounting and limitations. Reports identify the actual
method and configuration used; a changed prompt or control strategy is not
merely a model-name change. Unknown model attribution or usage remains unknown.

## Development

The core does not import native simulator SDKs. To validate the current catalog:

```sh
make check
```

The former regression scripts and test fixtures are no longer included in the
active source tree; recover their matching versions from Git history when needed.
Catalog checks do not establish native evaluation or model capability.

To add a benchmark, implement [BenchmarkAdapter and EpisodeSession](benchkit/interfaces.py)
under its `benchmarks/` directory, pin the native evaluator and provide explicit
contracts and selection plans. To add a method, implement the service protocol
in your trusted driver and declare its configuration/model composition. The
Python `Policy` interface and reference loop are optional conveniences, not a
required framework or language.
See [AGENTS.md](AGENTS.md) for repository safety and contribution boundaries.

Internal working notes under `project_readmes/` are local and Git-ignored.
Public usage must not depend on them. All method evaluation outputs, including
reports and indices, are local and Git-ignored, as are credentials and local
environment artifacts. Publish selected result summaries in documentation or
the website.

The grouped [.gitignore](.gitignore) excludes generated artifacts and local
check/test files as well as the runtime data described above.
`git status --short --ignored` marks ignored paths with `!!`;
`git check-ignore -v -- PATH` identifies the matching rule.
Ignored files can remain on disk. Editors may show them dimmed rather than hide
them; that display is independent of whether Git will track them.

## Attribution

Derived from [StarVLA](https://github.com/starVLA/starVLA), retaining its MIT
license and citation metadata. Original model-training implementations remain
in the upstream project and Git history, not the active evaluation surface here.
