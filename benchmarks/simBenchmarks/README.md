# Simulation benchmarks

This directory contains the simulation benchmark integrations for
[starRoboEval](../../README.md). Each integration owns its environment, task
selection, robot interfaces and native scoring, and exposes a benchmark service
for compatible agent methods. Models, prompts, planning and action decisions
belong to the agent method.

The common service standardizes communication and lifecycle, not the robot's
capabilities: manipulation, humanoid control and navigation keep their own
sensors, actions and evaluation rules. Declared robot state is permitted;
object ground truth, private scoring and simulator handles are not agent inputs.

## Choose a benchmark

The table introduces the **native benchmarks** and their task organization.
Each guide explains the benchmark's
purpose and task organization, then its installation and service interface.
Protocols specify case selection, sensors, dimensional actions, budgets and
native scoring. Upstream sources and count definitions are linked in each guide.

| Benchmark | Native tasks and case organization | Guide and specification |
| --- | --- | --- |
| RoboDojo | 42 core simulation tasks in 5 capability categories; additional DLC entry and task-specific layout variation | [Guide](RoboDojo/README.md) · [Protocol](RoboDojo/EVALUATION_PROTOCOL.md) |
| SimplerEnv | 10 task categories for Google Robot / WidowX; Visual Matching and Variant Aggregation conditions | [Guide](SimplerEnv/README.md) · [Protocol](SimplerEnv/EVALUATION_PROTOCOL.md) |
| LIBERO | Spatial/Object/Goal: 10 tasks each; LIBERO-100: 90 + 10 split; 50 released initial states per task | [Guide](LIBERO/README.md) · [Protocol](LIBERO/EVALUATION_PROTOCOL.md) |
| RoboCasa365 | 365 kitchen tasks: 65 atomic + 300 composite; a defined 50-task target evaluation set | [Guide](Robocasa_365/README.md) · [Protocol](Robocasa_365/EVALUATION_PROTOCOL.md) |
| RoboTwin | 50 bimanual tasks; clean and randomized conditions, native feasible-seed sampling | [Guide](Robotwin/README.md) · [Protocol](Robotwin/EVALUATION_PROTOCOL.md) |
| RoboCasa Tabletop | 24 tasks in the referenced tabletop release; task-specific scene/layout and object/style conditions | [Guide](Robocasa_tabletop/README.md) · [Protocol](Robocasa_tabletop/EVALUATION_PROTOCOL.md) |
| VLA-Arena | 170 tasks across 11 suites; 60/55/55 tasks at L0/L1/L2, 50 saved states per task | [Guide](VLA-Arena/README.md) · [Protocol](VLA-Arena/EVALUATION_PROTOCOL.md) |
| MetaWorld | 50 manipulation task families; MT50 reference evaluates 50 goal configurations per task | [Guide](MetaWorld/README.md) · [Protocol](MetaWorld/EVALUATION_PROTOCOL.md) |
| CALVIN | 34 manipulation subtasks across 4 environments; standard evaluation uses 1,000 five-subtask sequences | [Guide](calvin/README.md) · [Protocol](calvin/EVALUATION_PROTOCOL.md) |
| DOMINO | 35 dynamic manipulation tasks with task-specific motion/difficulty settings | [Guide](DOMINO/README.md) · [Protocol](DOMINO/EVALUATION_PROTOCOL.md) |
| SIMPLE | 60 humanoid whole-body tasks across 50 indoor scenes; randomized object and robot conditions | [Guide](SIMPLE/README.md) · [Protocol](SIMPLE/EVALUATION_PROTOCOL.md) |
| LIBERO-Plus | 10,030 perturbation variants across 4 suites and 7 robustness dimensions | [Guide](LIBERO-plus/README.md) · [Protocol](LIBERO-plus/EVALUATION_PROTOCOL.md) |
| BEHAVIOR | BEHAVIOR-1K: 1,000 activities; 2026 challenge: 100 household tasks with public/hidden instance splits | [Guide](Behavior/README.md) · [Protocol](Behavior/EVALUATION_PROTOCOL.md) |
| VLN-CE | Instruction/route episodes in continuous scenes; R2R unseen-scene validation has 1,839 episodes across 11 scenes | [Guide](VLN-CE/README.md) · [Protocol](VLN-CE/EVALUATION_PROTOCOL.md) |

[Service support](SERVICE_SUPPORT.md) separately lists implemented selectors,
deployment requirements and current restrictions. Native inventory does not
imply that all cases can already be selected through this repository's service.
A task, layout, initial state, variation and seed are not
interchangeable: see [how to select cases](TASK_COVERAGE.md). A different seed
does not guarantee a different layout. The machine-readable catalog is
[`benchkit/catalog/benchmarks.json`](../../benchkit/catalog/benchmarks.json).

## Evaluate through a service

1. Select the benchmark, observation/action interface and cases before observing outcomes.
   Read its native budget, reset rules and scorer; do not copy another
   benchmark's camera set, action space or episode count.
2. Prepare the pinned native environment and authorized assets using its setup
   guide. Supply your runtime paths and device in operator-owned configuration.
3. Start its server using the documented launch command. The shared selector
   `rsi-bench list` / `rsi-bench serve --benchmark <id> ...` delegates to the
   benchmark's own entrypoint.
4. Connect a compatible agent's trusted driver. The agent chooses its reasoning,
   memory and action grouping; the service executes declared controls and
   delegates success to the native scorer.
5. Report all selected cases, native outcomes, controls, decisions and errors.
   A completed unsuccessful episode is a result; an infrastructure interruption
   is a separate outcome, not an excuse to discard an attempt.

Specify coverage directly: selected tasks, layouts or initial states, seeds and
attempts per case. For example, 5 tasks with 5 selected initial states each is
25 cases, not 25 different tasks. Planned repetitions are not retries selected
after failures. Configuration and sampling capabilities differ by benchmark;
use its documented selectors rather than assuming that `--episodes` creates
new layouts or repeats tasks.

## Responsibilities and documentation

| Location | Owns |
| --- | --- |
| `<benchmark>/README.md` | Native benchmark introduction, task/variation organization, setup and service use |
| `<benchmark>/EVALUATION_PROTOCOL.md` | Versioned observations/actions, sampling, native budgets, termination and scoring |
| `<benchmark>/bench_server/` | Public-to-native adapter and protocol definitions/catalogs |
| `<benchmark>/environment/` | Native runtime, workers, source/asset pins and readiness tools |
| [`AgentPolicies/`](../../AgentPolicies/README.md) | Agent implementations, prompts, client commands, method settings and results |
| [`benchkit/`](../../benchkit/README.md) | Shared communication, scheduling, records and reporting tools |

Benchmark guides describe conditions that apply to any compatible method. Model
launch recipes, strategy advice, token-accounting ledgers and individual run
diaries do not belong here. Interaction histories and media are optional,
default enabled where supported; they are not a participation requirement.
See [recording](../../docs/recording.md) for current capture/retention limitations.

For contributors: [service conventions](SERVICE_CONVENTIONS.md),
[native integration interface](INTERFACE.md), [agent interaction contract](POLICY_PROTOCOL.md)
and [wire protocol](SERVER_PROTOCOL.md). For operators:
[evaluation workflow](../../docs/evaluation.md).
