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

> Status: experimental. Development SIM services and protocol drafts coexist;
> inspect the per-benchmark support matrix before use.
> Native-aligned full evaluation presets, verified provider integrations and
> unified real-robot adapters are not yet complete. Adapter availability does
> not imply the simulator or licensed assets are installed.

## Quick start

Use Python 3.10 or newer, from a repository checkout:

```sh
pip install -e .
rsi-bench list
rsi-bench serve --benchmark robodojo --help
```

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
- [Optional interaction recording and basic results](docs/recording.md)
- [Run an evaluation](docs/evaluation.md)
- [Architecture and ownership](docs/architecture.md)
- [Bench Server visual introduction](assets/bench_server/index.html)
- [Add a benchmark server](docs/benchmark-server-guide.md)
- [Policy interaction protocol](benchmarks/simBenchmarks/POLICY_PROTOCOL.md)
- [Simulator adapter interface](benchmarks/simBenchmarks/INTERFACE.md)
- [Run SIMs as independent servers](benchmarks/simBenchmarks/SERVER_PROTOCOL.md)
- [Implement a policy](AgentPolicies/README.md)
- [Real-robot integration status](benchmarks/realRobots/README.md)

## Repository structure

Upgrading an existing checkout? See the [package migration notes](docs/package-migration.md)
for the `examples` → `benchmarks` and `harness` → `benchkit` changes.

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
    bench_server/protocol/             task definitions and sample plans, where migrated
  realRobots/                          hardware references; unified adapters pending
AgentPolicies/
  <method-profile>/                    policy, model composition, prompts and dependencies
    run.py                             model-owned trusted evaluation entrypoint, where implemented
    results/<benchmark>/               reports, indices and ignored raw runs/media
  policy_support/                      reusable agent-side loop and policy behavior
docs/                                 public design and usage guides
```

The benchmark answers “what happens when this action executes?” The policy
answers “what action should I take?” Its trusted driver communicates with the
service through `benchkit/sim_server` and uses the other `benchkit` record/report tools. Planning and
voluntary-stop preferences belong to the policy, not the native benchmark.
The actor never receives the driver's administrative client or credentials.
The model-owned client driver currently starts with
[`AgentPolicies/gpt6_astra/run.py`](AgentPolicies/gpt6_astra/run.py). Its implementations,
transports, presets and guides are grouped by role. Fixed-plan tools use
`python -m benchkit.campaigns`; no old `benchkit.runner` or `benchkit.campaign`
forwarding modules are retained. Import the optional runner from
`AgentPolicies.policy_support.runner`.

Central task scheduling remains in this version. Current campaign commands
coordinate frozen local cases; they are not yet integrated with remote service
campaigns. Use the [workflow guide](docs/evaluation.md#choose-a-workflow) to choose
the service/driver path or retained campaign path, rather than combining them.
Automatic plugins, expanded scheduling, a comprehensive CLI and cross-benchmark
rankings are planned extensions, not claims of current support.

## Available integrations

| Family | Current status | Entry point |
| --- | --- | --- |
| SimplerEnv | Development adapter | [Setup and protocol](benchmarks/simBenchmarks/SimplerEnv/README.md) |
| LIBERO | Development adapter | [Setup and protocol](benchmarks/simBenchmarks/LIBERO/README.md) |
| SIMPLE | Development adapter | [Setup and protocol](benchmarks/simBenchmarks/SIMPLE/README.md) |
| RoboCasa365 | Development adapter | [Setup and protocol](benchmarks/simBenchmarks/Robocasa_365/README.md) |
| RoboCasa Tabletop | Development adapter | [Setup and protocol](benchmarks/simBenchmarks/Robocasa_tabletop/README.md) |
| RoboDojo | Qualified development adapter; portable setup incomplete | [Scope and limitations](benchmarks/simBenchmarks/RoboDojo/README.md) |
| MetaWorld MT50 | Standalone development SIM server | [Setup and protocol](benchmarks/simBenchmarks/MetaWorld/README.md) |
| LIBERO-Plus | Separate variation-aware development SIM server | [Setup and protocol](benchmarks/simBenchmarks/LIBERO-plus/README.md) |
| RoboTwin | Two-task clean direct-joint development SIM server | [Setup and protocol](benchmarks/simBenchmarks/Robotwin/README.md) |
| DOMINO | One-task fixed-manifest direct-joint development SIM server; native validation pending | [Setup and protocol](benchmarks/simBenchmarks/DOMINO/README.md) |
| BEHAVIOR 2026 | One-task RGB/proprioception debug SIM server; one-case native smoke passed, full challenge parity pending | [Setup and protocol](benchmarks/simBenchmarks/Behavior/README.md) |
| VLA-Arena | Level-0 direct-control development SIM server | [Setup and protocol](benchmarks/simBenchmarks/VLA-Arena/README.md) |
| CALVIN | Debug-assets sequence development SIM server | [Setup and protocol](benchmarks/simBenchmarks/calvin/README.md) |
| VLN-CE | Deferred pending authorized navigation assets | [Catalog](benchmarks/simBenchmarks/README.md) |

The catalog contains the original 13 simulation families plus SIMPLE. The
[service support matrix](benchmarks/simBenchmarks/SERVICE_SUPPORT.md) distinguishes
entrypoint availability, setup requirements and native validation. No standalone
development server implies native full parity. Environment assets and their
licenses are separate from this repository; VLN-CE is deferred until authorized
navigation datasets are available.

## Evaluation guarantees and limits

- Freeze tasks, initial states, seeds, action/observation contracts, budgets and
  model configuration before execution.
- `fast` plans select tasks with one attempt each. A future `full` preset must
  follow the verified native task/variant/episode schedule; it is not a retry loop.
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

The current `anonymous_code_agent` profile uses an experimental file mailbox.
It does not authenticate the actor's provider/model identity, meter hidden
provider requests or enforce OS isolation. Unknown usage is recorded as
`null`. [`gpt6_astra`](AgentPolicies/gpt6_astra/README.md) offers several versioned
methods; its server driver uses generic persistent Direct v3 with an explicit benchmark. The
Native baseline (the factory default) and Planned method use declared numeric
action interfaces. The three methods have distinct compatibility and evidence;
retired API/EEF methods remain only in Git and frozen records.
A passing offline check is not a new capability score.
Declared model identity is distinct from provider receipts and
from historical owner-reported attribution. `opus` remains unconfigured.

## Development

The core does not import native simulator SDKs. Lightweight checks are organized
beside the code they protect:

```sh
make check
# Use an environment with NumPy, Pillow and PyAV for media fixtures:
python -B -m benchkit.checks.run_regressions --jobs 3 --output /absolute/new/check-report
```

To add a benchmark, implement [BenchmarkAdapter and EpisodeSession](benchkit/interfaces.py)
under its `benchmarks/` directory, pin the native evaluator and provide explicit
contracts and selection plans. To add a method, implement the service protocol
in your trusted driver and declare its configuration/model composition. The
Python `Policy` interface and reference loop are optional conveniences, not a
required framework or language.
See [AGENTS.md](AGENTS.md) for repository safety and contribution boundaries.

Internal working notes under `project_readmes/` are local and Git-ignored.
Public usage must not depend on them. Raw runs, generated media, credentials and
local environment artifacts are also excluded from Git; lightweight model
reports and provenance indices may be tracked.

The grouped [.gitignore](.gitignore) keeps generated artifacts out of Git, not
source, tests or published results. `git status --short --ignored` marks ignored
paths with `!!`; `git check-ignore -v -- PATH` identifies the matching rule.
Ignored files can remain on disk. Editors may show them dimmed rather than hide
them; that display is independent of whether Git will track them.

## Attribution

Derived from [StarVLA](https://github.com/starVLA/starVLA), retaining its MIT
license and citation metadata. Original model-training implementations remain
in the upstream project and Git history, not the active evaluation surface here.
