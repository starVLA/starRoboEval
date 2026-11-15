# Evaluation workflow

Start with the selected benchmark's README and `EVALUATION_PROTOCOL.md`.
Installing this package does not install native simulators or grant asset licenses.

## Choose a workflow

Choose the path that matches your purpose; the rows below are not consecutive
setup steps.

| Purpose | Entry point | Current boundary |
| --- | --- | --- |
| Service-based evaluation | `rsi-bench serve` → your trusted agent driver → result report | Recommended integration path; native runtime stays behind the benchmark server |
| Inspect closed results | `benchkit.reports.basic_result`, optional interaction history | Reads records; never runs, retries or changes a task |

The public service path is: select the protocol/schedule and deployment → start
the service → connect a method → inspect its results. The actor receives only
declared observations and robot feedback, never the driver's administrative client.
Shared `benchkit` communication and output tools are not another per-action process.
Central multi-service scheduling is not implemented in this version.

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

Without a console-script installation, use `python -B -m benchkit`
instead of `rsi-bench`. The token is supplied privately through
`RSI_SIM_SERVER_TOKEN`, never through the model prompt. See the
[wire protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md) for authentication
and remote forwarding. List and help do not start/reset a native environment.

The selector forwards launch arguments to the existing benchmark-owned entrypoint.
There is no universal EEF control space. A named route identifies an implemented
service; its setup guide specifies the required assets and supported tasks.
The per-benchmark `python -m ...server` entrypoint is also supported.

## Select tasks and cases

Describe the evaluation by tasks, layouts or initial states, variations, seeds
and attempts per case. These quantities are different: five seeds do not
necessarily generate five layouts. Read the selected benchmark's task table
and sampling interface, then fix the case list before any outcomes are known.
See [task selection](../benchmarks/simBenchmarks/TASK_COVERAGE.md).

RoboDojo declares its schedules in
[`bench_server/protocol/task_catalog.json`](../benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/task_catalog.json).
Its server configuration selects layouts 0–4 (`fast`) or the first 50
reset-stable layouts of a reset-stability manifest (`max`) for
`classify_objects`, each once. These are two sample counts for the same task.
The catalog is protocol data; runtime
assets belong to `environment/`, and deployment paths/GPU selection belong to
the operator's server configuration. Use `rsi-bench serve --benchmark robodojo`;
the delegated benchmark-owned wrapper remains
`benchmarks.simBenchmarks.RoboDojo.server`, with its adapter in `bench_server/`.

Inspect the service's declared schedule and the run manifest for the exact
denominator. Native planned repetitions are samples, not retries triggered by failure.

If development budgets differ from native conditions, label that track explicitly.
Do not treat different sample distributions or execution budgets as identical conditions.
Policy persistence preferences are a separate model configuration.

## Connect an agent method

Select a complete agent method, not just a model label. The protocol-first path
supports your own driver and decision loop; Python `Policy` is optional. Declare
all model components/roles and configuration using the
[method contract](agent-methods.md). The reference driver accepts `--method-file`.
Additional inference/planning does not expand the robot or environment interface.

Use your own compatible driver or the supplied
[reference client](../AgentPolicies/gpt6_astra/README.md). Profile dependencies,
credentials, inference settings and voluntary-stop behavior are documented with
the selected agent, separately from benchmark installation. Select them before
the attempt. A method's completion claim never substitutes for native success.

Start the server following the selected benchmark's guide, then connect the
chosen driver using the declared sensors, action space, schedule and budgets.
Changing the agent method does not change the benchmark interface. Never copy
one robot's end-effector space or execution budget to another robot.

An independent driver can implement the [wire protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md)
without a reference model profile or Python `Policy`.
Keep claims, metrics, finalization and credentials on the trusted side; project
only protocol-allowed inputs to the actor. See [method integration](agent-methods.md).
The optional `rsi-bench run --sim-server` command uses the same agent-side runner,
not a separate benchmark-control implementation. It requires `--sim-server` and
takes a diagnostic `--policy` (see `rsi-bench policies`), not a model profile; run a
model profile such as `gpt6_astra` with its own driver.

Check a running service's readiness without a policy:

```sh
python -B -m benchkit probe --sim-server http://127.0.0.1:8765 --benchmark <descriptor.name>
```

It describes the service, claims and resets one episode, closes it and prints a
JSON summary; it sends no action. Probe a dedicated launch, because the claim is
permanent. See the [readiness probe](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md#readiness-probe).

For local diagnostics without a benchmark or request:

```sh
python -B -m benchkit preflight-policy --model-profile gpt6_astra
```

It runs a profile's declared runtime preflight, checking dependencies and
credential presence in the same Python environment, and reports a bounded
status/error code only. It does not validate provider access, model permissions
or network/native readiness.

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
The chunk limit belongs to the method config, not a server requirement to execute
a fixed number of controls per decision. A shorter chunk or
native end can execute fewer. Native physics substeps and the total execution
budget remain benchmark-owned. The reference driver stops the remaining chunk
when the next acknowledged observation changes the public instruction and
replans from that observation; it never uses private scores for this decision.
A service's declared `required_replan_interval` still requires matching
configuration; no current service declares one. Services advertise their
native execution horizon.

Model-call recovery is separate from case scheduling and belongs to the method.
Record such recovery and available usage without inventing executed controls.
It cannot reset a case or replay a robot command whose execution is uncertain.

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
the original record. It checks closed event/result consistency, not source
integrity or provider identity. It accepts the generic client-run schema, not an
arbitrary server parent directory; unsupported or inconsistent records
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

For video-linked review of explicitly selected closed episodes, use
`python -B -m benchkit.reports.episode_viewer build --config /private/viewer.json
--output /new/presentation/directory`, then
`python -B -m benchkit.reports.episode_viewer serve --directory /new/presentation/directory`.
The private config supplies `tasks`, each with `id`, `title`, `task`, `run_id`,
`client_dir` and explicit `videos`. A video entry supplies `camera`, `run_id`,
`task`, absolute MP4 `path`, `bytes`, `sha256`, `fps`, `frames` and
`mapping: initial_frame_then_one_per_control`. This mapping requires prior
native recording/decoding evidence; it is not guessed from video duration.
Currently each selected client run must contain one episode.

The viewer retains every recorded call and its input, submitted actions, and
first/last ACK; intermediate ACK observations are explicitly omitted. It exposes
only `metrics.native_benchmark_score` as a separately labelled post-evaluation
score, not actor input. Recorded notes are not a complete conversation or hidden
reasoning. Video time represents control frames, not model latency.
The loopback-only server supports seeking, verifies media hashes at startup,
and allowlists the page and explicit MP4s; it does not serve raw directories or
its private `.media-map.json`. Forward its port over SSH or VS Code. Videos remain
in their original server directories; no duplicate video is produced. Ignore
generated `data.js` and `.media-map.json` if retaining the page sources in Git.

Report the selected denominator, attempted/completed/unattempted counts, successes,
policy/protocol errors and infrastructure errors. Preserve every original failure.
Report available usage/latency and mark unavailable provider accounting as unknown.
Typed policy-call failures retain known usage and bounded receipt metadata without
becoming successful decisions or controls. Request-attempt counts are not proof
of completed inference. Record audits check consistency, not provider attestation.
Do not merge different budgets, asset tracks or model identities into one score.

### Internal integrity tools

For internal integrity and maintenance, keep `manifest.json`, lifecycle status,
episode results/events and referenced artifacts. The manifest records the git
revision, dirty flag, model profile and effective configuration. Use the generic
offline tools under `benchkit/audits/` and `benchkit/reports/`; the closed-run
audit checks record consistency, not source files. A consistency check is not a
native replay.

## Storage and portability

An environment directory on shared storage can still contain a Python symlink
or base prefix on node-local storage. Before moving a service, verify the resolved
interpreter, `pyvenv.cfg`, native libraries and asset mount on the destination
node. An SSH alias or matching absolute path alone does not establish the same
machine or filesystem. Preserve old environments and evidence when rebuilding;
installation recovery does not authorize repeating a claimed task.

Maintain reports and indices under the selected model's `results/<benchmark>/`.
Keep raw runs and media outside Git. Export video directories with task IDs and
short descriptions, not opaque case numbers alone. Do not rename original evidence
to improve presentation; use explicit hash-bound indices or copies.

Repository-based editable installation is the documented workflow. When installing
a wheel, explicitly choose a writable output directory rather than a default
under site-packages. `catalog --check` validates a complete source checkout;
the wheel packages active runtime components, not all benchmark documentation.
Internal `project_readmes/` notes are not required for public operation.
