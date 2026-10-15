# Evaluation workflow

Start with the selected benchmark's README and `EVALUATION_PROTOCOL.md`.
Installing this package does not install native simulators or grant asset licenses.

## Choose a workflow

Central task scheduling is retained. Choose the path that is actually implemented;
the two execution paths below are **alternatives**, not consecutive setup steps.

| Purpose | Entry point | Current boundary |
| --- | --- | --- |
| Service-based evaluation | `rsi-bench serve` → your trusted agent driver → result report | Recommended integration path; native runtime stays behind the benchmark server |
| Central case scheduling | `python -m benchkit.campaigns prepare/run-case/summarize` | Five registered plans; fixed local-adapter execution, not remote service orchestration |
| Inspect closed results | `benchkit.reports.basic_result`, optional interaction history | Reads records; never runs, retries or changes a task |

The public service path is: select the protocol/schedule and deployment → start
the service → connect a method → inspect its results. The actor receives only
declared observations and robot feedback, never the driver's administrative client.
Shared `benchkit` communication and output tools are not another per-action process.

[Central scheduling](#central-case-scheduling) remains available for its existing
frozen execution path. It has not yet been integrated with remote server
`prepare/run-case`. Do not substitute it for a service-based run while claiming
the same isolation or provenance.

## Select and launch a service

```sh
rsi-bench list
rsi-bench serve --benchmark simpler_env --help
# After following SimplerEnv's installation guide and setting the token:
rsi-bench serve --benchmark simpler_env \
  --parameters /absolute/benchmark-parameters.json \
  --seed 7 --episodes 1 --port 8765 \
  --output-dir /absolute/new-run/server
```

Without a console-script installation, use `python -B -m benchkit.sim_server.cli`
instead of `rsi-bench`. The token is supplied privately through
`RSI_SIM_SERVER_TOKEN`, never through the model prompt. See the
[wire protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md) for authentication
and remote forwarding. List and help do not start/reset a native environment.

The selector forwards launch arguments to the existing benchmark-owned entrypoint.
There is no universal EEF control space or `--full` switch. A named route means
an implemented development service, not installed assets or a validated full
benchmark. The original per-benchmark `python -m ...server` remains valid.

## Choose a plan, not a retry strategy

| Plan | Sample schedule | Status |
| --- | --- | --- |
| Fast | A preselected subset of cases, one attempt per selected case | Current campaign preparation records `evaluation_mode: fast`; service schedules are benchmark-specific |
| Full | Verified native suite, variants, seeds, resets and episodes per task | Benchmark-specific presets only; no universal full-schedule selector |

RoboDojo declares its schedules in
[`bench_server/protocol/task_catalog.json`](../benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/task_catalog.json).
Its server configuration selects `panel: fast` (five layouts) or `panel: full`
(50 layouts) for `classify_objects`, each once. This full panel covers that task,
not the complete RoboDojo task suite. The catalog is protocol data; runtime
assets belong to `environment/`, and deployment paths/GPU selection belong to
the operator's server configuration. Use `rsi-bench serve --benchmark robodojo`;
the delegated benchmark-owned wrapper remains
`benchmarks.simBenchmarks.RoboDojo.server`, with its adapter in `bench_server/`.

The current campaign CLI has benchmark-specific default cases and selected
`--task-scope` expansions. It does not accept an arbitrary `--mode full` switch.
Inspect the benchmark's declared plan module and generated manifest for the exact
denominator. SimplerEnv, LIBERO, SIMPLE, RoboCasa365 and RoboCasa Tabletop keep the plan at
`bench_server/protocol/plan.py`; their old `evaluation` packages are removed.
Native planned repetitions are samples, not retries triggered by failure.

If development budgets differ from native conditions, label that track explicitly.
Do not compare task-only coverage or a longer horizon with a native full score.
Policy persistence preferences are a separate model configuration.

## Connect an agent method

Select a complete agent method, not just a model label. The protocol-first path
supports your own driver and decision loop; Python `Policy` is optional. Declare
all model components/roles and configuration using the
[method contract](agent-methods.md). The reference driver accepts `--method-file`.
Additional inference/planning does not expand the robot or environment interface.

`anonymous_code_agent` is an external mailbox with unknown provider/model identity.
[`gpt6_astra`](../AgentPolicies/gpt6_astra/README.md) supplies one Bench Server
validation client, `codex_native` (`codex-native/v2`). It retains the former Direct v3
behavior; use its driver with an explicitly selected benchmark, without a method
selection step. Optional `--control-method` accepts only `codex-native/v2`.
Numeric-interface compatibility is not native validation or universal robot capability. `opus` is an unconfigured placeholder.
Profile dependencies and credentials are separate from benchmark installation.

For the mailbox profile, the actor receives only its opaque endpoint and permitted protocol context.
Do not provide campaign directories, native workers, evaluator state or private
scoring data. Mailbox-only instructions are not a substitute for enforced process
isolation or a trusted provider-request meter.

Start the server following the selected benchmark's guide, then use the current
[current client command](../AgentPolicies/gpt6_astra/README.md#single-task-integration-example).
Historical Native, Direct and Planned commands require their original frozen
package or source from Git; the active factory does not select those methods. The existing RoboDojo **server protocol** still uses
its original Direct-v2 interface identity; a model-method upgrade does not rename
that server protocol. Use its matching seed and named panel; a separately selected
one-case development sample is not a full-panel score. Never copy its EEF space or
budget to another robot. Select method and recording options before execution.

An independent driver can implement the [wire protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md)
without joining the reference factory registry or using Python `Policy`.
Keep claims, metrics, finalization and credentials on the trusted side; project
only protocol-allowed inputs to the actor. See [method integration](agent-methods.md).
The optional `benchkit run --sim-server` command uses the same agent-side runner,
not a separate benchmark-control implementation.

The [Bench Server protocol skill](bench-server-protocol/SKILL.md)
provides development-time integration steps and a copyable single-case driver
template, including its own loop and essential result records. It is not an
`AgentPolicies` runtime package or registered profile. The template accepts only
a complete single-case service schedule with horizon mode and prefix one; these
are template boundaries, not protocol-wide limits. Use the benchmark-compatible
method driver for full panels and other control contracts.

Calls, executed decisions, controls and native physics ticks are different
counters. Invalid-action feedback, motion guards and model network continuation
are versioned method/track behavior; consult the
[client README](../AgentPolicies/gpt6_astra/README.md) and
[action validation contract](../benchmarks/simBenchmarks/RoboDojo/ACTION_VALIDATION.md).
No path automatically retries a physical action after an uncertain ACK.

The method chooses a chunk and its trusted driver sends each control separately.
`--replan-interval 5` in a method example is a configured prefix ceiling, not a
server requirement to execute five controls per decision. A shorter chunk or
native end can execute fewer. Native physics substeps and the total execution
budget remain benchmark-owned. Existing decision-coupled tracks and any declared
`required_replan_interval` still require matching configuration; do not silently
override them when selecting a different method.

The client's model-call recovery is separate from case scheduling. A definitively
closed `serverOverloaded` turn can continue in the same thread after 30 seconds,
up to nine continuations between valid action submissions. Error notification
alone does not authorize recovery; existing network continuation is separate.
No executed decision/control is added until an action actually executes. Preserve
recovery attempts and available usage; exhaustion remains an infrastructure error,
not native failure or permission to reset a case or replay uncertain robot action.

## Inspect and report

Interaction recording is optional and enabled by default. The reference driver
accepts `--recording-mode minimal` and granular overrides such as
`--no-record-videos`. See [recording settings](recording.md) for client retention,
runtime scratch and native capture limitations. Do not change options mid-run.

By default, retained native videos stay in the service's output directory; the
client keeps their server/session/path references, not duplicate downloads.
Keep that server directory durable alongside the client result. Client
`--copy-server-media` opts into another local copy. `--no-record-videos` affects
client retention and does not disable native capture or delete server videos.
Standalone frames are normally temporary; missing/incomplete video evidence or
failed native close preserves them with a warning. See [media ownership](recording.md#one-canonical-visual-record).

Generate a basic result even when no trajectory/video/source snapshot is available:

```sh
python -B -m benchkit.reports.basic_result \
  --run-dir /absolute/closed-run/client \
  --output-dir AgentPolicies/my_method/results/my_benchmark/report/my-run
```

This validates closed essential records, not provider identity or native replay.
It preserves all selected attempts and failures; optional `--metric KEY` exposes
an explicitly selected finite native scalar. Do not compare different protocols
or method configurations as if they were only model changes. No aggregate
cross-benchmark leaderboard is implied.

When sufficient interaction events were retained, an optional richer view is
available for an explicitly selected **closed client run**:

```sh
python -B -m benchkit.reports.interaction_history \
  --run-dir /absolute/closed-run/client \
  --output-dir AgentPolicies/my_profile/results/my_benchmark/interaction/my-run
```

The destination must be new and outside the source run. Open its `index.html`
directly in a browser; `history.json` contains the same structured view.
The exporter performs no model request, simulation or retry and does not edit
the original record. It checks closed event/result consistency, not full source
integrity or provider identity. It accepts the generic client-run schema, not an
arbitrary server/campaign parent directory; unsupported or inconsistent records
fail explicitly. Redacted/incomplete histories may not satisfy its stronger
event audit; use the basic result view instead. This is not a publication failure.

Each call shows the recorded policy input, note/output, proposed actions,
acknowledged controls, rejection/errors and episode outcome. Calls, action
decisions and controls remain distinct. Planned/unattempted counts refer only to
the client-selected schedule; a larger server/native panel needs a separate
denominator record. Camera names do not prove retained
pixels; this first exporter copies no media and cannot reconstruct missing
actions or raw chat. It does not prove backend consumption or final ACK delivery.
Review recorded task text and notes before sharing. Benchmark-specific score,
environment/asset provenance and video publication stay in their existing tools;
they are not guessed from arbitrary nested metadata.

Report the selected denominator, attempted/completed/unattempted counts, successes,
policy/protocol errors and infrastructure errors. Preserve every original failure.
Report available usage/latency and mark unavailable provider accounting as unknown.
Typed policy-call failures retain known usage and bounded receipt metadata without
becoming successful decisions or controls. Request-attempt counts are not proof
of completed inference. Record audits check consistency, not provider attestation.
Do not merge different budgets, asset tracks or model identities into one score.

## Central case scheduling

This case-level coordinator is retained, not just a historical reader. It assembles
benchmark-owned plans, performs declared preflight, claims a case permanently,
launches its frozen local entrypoint and summarizes status. SimplerEnv, LIBERO,
SIMPLE, RoboCasa365 and RoboCasa Tabletop currently have registered plans.

The operator supplies the case index and device. There is no automatic resource
allocator, remote bench-server binding or interrupted-service reconciliation.
Future extensions must preserve selected conditions, all failed/error attempts
and no replay after uncertain execution. A fresh directory or run ID does not
authorize another attempt. Agent methods still own their decision loops.

These commands use internal source freezing and the reference profile registry.
Neither is a prerequisite for protocol-first participation or basic result
publication. Do not run the example commands below as additional steps of a
service-based evaluation.

### Prepare and inspect

From the repository root, the following prepares the SimplerEnv fast plan without
starting an environment or making a model request:

```sh
python -B -m benchkit.campaigns prepare \
  --benchmark simpler_env \
  --model-profile anonymous_code_agent \
  --prompt-file AgentPolicies/anonymous_code_agent/prompts/control_guidance.txt \
  --mailbox-root /absolute/stable/policy-endpoints \
  --output-dir AgentPolicies/anonymous_code_agent/results/simpler_env/raw/my-fast-run/campaign
```

Replace placeholder paths with writable locations. Use a new output directory.
The endpoint root must be independent of task, date, seed and model identity.
Campaign preparation freezes cases, budgets, source inventories, effective prompt
and future endpoint addresses; it does not prove the native environment is ready.

The current `gpt6_astra` client (`codex-native/v2`) uses the service driver
`python -m AgentPolicies.gpt6_astra.run`, not this local campaign preparation path.
`campaigns prepare` rejects that method before creating outputs: the retained
local path does not satisfy its horizon/feedback contract. Use the
[current client command](../AgentPolicies/gpt6_astra/README.md#single-task-integration-example)
and a fresh path under `AgentPolicies/gpt6_astra/results/<benchmark>/` for an
explicitly selected service run.

Historical direct-profile campaigns retain their captured local implementation,
method and preflight declaration. Where declared, `run-case` checks the frozen
model's dependencies and credential presence in the same Python environment
before the permanent case claim. Failure leaves the case unattempted, with no
outcome or policy call. This does not validate provider access, model permissions
or network/native readiness. Do not select the current method to reinterpret or
restart one of those frozen campaigns.

For local diagnostics without a benchmark or request:

```sh
python -B -m benchkit preflight-policy --model-profile gpt6_astra
```

The command reports a bounded status/error code only; it does not make the
current client compatible with local campaign preparation. The retained campaign
preflight, where declared by the frozen package, discards child output, times out
after 60 seconds and rechecks the frozen plan/source before its atomic claim.
Direct `benchkit run` also checks before constructing the benchmark. Runtime state
can still change afterward; post-claim errors remain permanent attempts.
Historical packages without a captured `runtime_preflight` declaration retain
their original behavior and do not acquire this check retroactively.

Before running, inspect `campaign.json`: selected tasks/states, planned cases,
seed, action/observation conditions, control prefix, policy-call limits and policy
parameters. Changing a frozen plan requires a new run identity, not an edit.
Use the benchmark's separate no-policy diagnostics to verify environment readiness.
Such diagnostics are not capability attempts.

### Execute an unattempted case

Only after environment readiness and actor setup:

```sh
python -B -m benchkit.campaigns run-case \
  --output-dir AgentPolicies/anonymous_code_agent/results/simpler_env/raw/my-fast-run/campaign \
  --case-index 0 --device-index 0
```

The command claims that case once and runs its frozen entrypoint. A failure or
timeout does not authorize another claim. Run additional preselected indices
explicitly; preparation alone is not coverage. Concurrency must use separate
case identities, native processes and actor contexts.

The runner may execute several controls from an action chunk before the next
policy call; the service still returns an observation after each acknowledged
control. Record policy calls, executed action decisions, controls and native
physics ticks separately. Ordinary policy stop does not award success; the native
benchmark remains the scorer.

For retained campaign summaries:

```sh
python -B -m benchkit.campaigns summarize \
  --output-dir AgentPolicies/anonymous_code_agent/results/simpler_env/raw/my-fast-run/campaign
```

### Internal integrity tools

For internal integrity and maintenance, keep `manifest.json`, lifecycle status, episode results/events, source indices and
referenced artifacts. Use the generic offline tools under `benchkit/audits/` and
`benchkit/reports/`; benchmark-specific auditors may require their matching
source/schema version. A consistency check is not a native replay.

## Storage and portability

An environment directory on shared storage can still contain a Python symlink
or base prefix on node-local storage. Before moving a service, verify the resolved
interpreter, `pyvenv.cfg`, native libraries and asset mount on the destination
node. An SSH alias or matching absolute path alone does not establish the same
machine or filesystem. Preserve old environments and evidence when rebuilding;
installation recovery does not authorize repeating a claimed task.

Maintain reports and indices under the selected model's `results/<benchmark>/`.
Keep raw runs and media outside Git. Export video directories with task IDs and
short descriptions, not opaque case numbers alone. Do not rename frozen evidence
to improve presentation; use explicit hash-bound indices or copies.

Repository-based editable installation is the documented workflow. When installing
a wheel, explicitly choose a writable output directory rather than a default
under site-packages. `catalog --check` validates a complete source checkout;
the wheel packages active runtime components, not all benchmark documentation.
Internal `project_readmes/` notes are not required for public operation.
