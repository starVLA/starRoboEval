# Native GPT-6-Astra Policy

This profile is the **Native GPT-6-Astra Policy**: GPT-6-Astra controls the robot
directly, with one generic setup and one prompt shared by every benchmark. It is
the baseline for what the model does before anything is tailored to a benchmark.
Records name it `gpt6-astra-codex-native`: the `gpt6_astra` profile with its
`codex_native.py` policy.

The model chooses numeric actions through one conversation per episode. The
benchmark service owns native control, task conditions and scoring.

## File layout

```text
gpt6_astra/
├── run.py                         # Trusted service client and evaluation entrypoint (start here)
├── codex_native.py                # CodexNativePolicy and factory create_policy
├── configs/
│   ├── codex_native_config.json   # Single method and registry configuration
│   ├── codex_native_prompt.txt    # Method prompt
│   ├── profile.json               # Client identity and factory registration
│   └── configuration.schema.json  # Parameter types and allowed overrides
├── tools/
│   ├── runner.py                  # Reusable execution loop and accounting
│   ├── persistent_runtime.py      # Conversation, execution feedback and recovery
│   ├── public_observation.py      # Public observations and image processing
│   ├── stagnation_review.py       # Optional repeated-command reminder
│   ├── json_io.py                 # Structured data handling
│   ├── codex_app_server.py        # App-server communication
│   ├── codex_config.py            # Codex launch settings and their verification
│   └── codex_runtime.py           # CLI installation, version and login checks
├── results/                       # Local results by Benchmark; Git-ignored
├── README.md                      # This guide
└── AGENTS.md                      # Development boundary
```

The general CLI also reuses `tools/runner.py`; stopping preferences remain
specific to each profile.

Reading order, following one evaluation from the top:

1. `run.py`: `main()` calls `run()`, which builds the policy, connects to the service and starts the runner.
2. `tools/runner.py`: `EvaluationRunner.run` writes the run; `_EpisodeRun.run` plays one episode.
3. `codex_native.py`: `CodexNativePolicy` defines what the model sees and how its reply becomes a decision.
4. `tools/persistent_runtime.py`: `PersistentRuntime.act` carries one call through the Codex conversation.

## Baseline configuration

The baseline is the checked-in [configuration](configs/codex_native_config.json)
and [prompt](configs/codex_native_prompt.txt), used unchanged on every benchmark.
It requests `gpt-6-astra` / `high` over `codex-app-server/v1`, with a chunk limit
of 5, a 900-second call timeout and image previews with a longest side of 480
pixels; original PNGs remain available. `reasoning_effort` is passed to Codex as
configured; Codex decides which values it accepts. Voluntary `safety_stop` and
`task_complete` are enabled, and the model decides whether to use them. The
stagnation review is disabled. Nothing in this setup is tuned to a benchmark or
its failure modes.

The schema bounds every override. `run.py` exposes `--image-max-edge`,
`--safety-stop`, `--allow-task-completion` and `--stagnation-*`; other settings,
including the chunk limit, change only by editing the configuration. A run that
changes any of these, or the prompt, is a different method: report it as its own
entry, not as the Native GPT-6-Astra Policy. Effective settings are recorded in
results. Each run separately declares a finite call cap and the service's
execution budget.

## Installation

Use the Codex CLI with an existing login. The policy was tested with Codex CLI
**0.154.0**; other versions are not refused, and each session records the version
in use.

```sh
pip install -e '.[gpt6-astra-codex]'
python -B -m benchkit preflight-policy --model-profile gpt6_astra
```

Preflight checks that the CLI runs and is logged in, and checks the configuration,
without starting model inference or a simulation. The policy uses the existing
Codex login through the app-server.

## Single-task integration example

Start the service with `rsi-bench serve --benchmark BENCHMARK_ID ...`, following
the selected Benchmark's README, then connect:

```sh
python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark BENCHMARK_ID \
  --seed SEED --episodes 1 \
  --max-policy-calls DECLARED_CALL_CAP \
  --output-dir AgentPolicies/gpt6_astra/results/BENCHMARK_ID/raw \
  --run-id DATE-TASK-short-description
```

Replace the uppercase placeholders. `--max-steps` and `--max-policy-calls` default
to the service's advertised horizon and call allowance; use the defaults for
reported runs. An explicit value overrides them, and the manifest records both
the service value and the override. The driver executes the whole chunk unless
the service declares a `required_replan_interval`, which then caps the chunk.
Pass the service token through `RSI_SIM_SERVER_TOKEN`; it stays in the driver
and never reaches the model.

For the checked-in LIBERO server example, use `--benchmark libero --seed 20260907
--episodes 1` (advertised horizon 520).

Startup runs in this order and stops at the first failure, before any case is
claimed:

1. Validate the local configuration against its schema. A `--method-file` is
   normalized and recorded.
2. Read the server's `describe` response and check interface, schedule and budget
   compatibility.
3. Probe the local Codex CLI and its configuration, without model inference.
4. Enter the evaluation runner and claim the selected case.

## Inputs and execution boundaries

The model receives public task text, RGB images, declared robot state and action
semantics, remaining control budget and acknowledged execution feedback. It gets
no administrative client, credentials, layout/seed metadata, private scores,
simulator handles or reset tools. The driver does not forward arbitrary
`control_feedback` payloads.

The model works in its own episode workspace: it can run code in a scratch
directory, view the received images and keep notes, and the workspace lasts only
for this episode. Its Codex session has web search turned off, no network
access from its shell, no MCP servers, no inherited shell environment, project
documents, hooks or memories, and file access limited to that workspace and the received
observations. The effective Codex configuration is checked before the first turn;
any extra capability stops the run. See the [development boundary](AGENTS.md).

`robot_act` submits numeric action vectors. The model chooses how many controls
to send (up to the configured chunk limit, 1–32) and how often to repeat them;
the service executes each control separately. An invalid action executes nothing
and comes back as correction feedback on the next call. Acknowledged prefixes
keep their actual counts, and uncertain controls are never replayed. Native
termination and budgets always apply.

The runner checks the public instruction in every acknowledged observation. If
it changes, the rest of that decision's actions are skipped and the next call
receives the new instruction and observation. Manifests record
`instruction_change_handling: "replan-after-ack/v1"`.

Voluntary `safety_stop` is enabled by default; `--no-safety-stop` disables it for
one run, and an empty-action safety stop is then rejected with correction
feedback. An explained safety stop ends the attempt without success. Ordinary
give-up is not available.

Model-declared completion (`actions=[]` with `stop_reason="task_complete"`) is
enabled by default; `--no-allow-task-completion` disables it for one run. A
declaration ends the episode without another control. The benchmark still scores
the episode with its own evaluator, and the declaration is recorded separately.

`--stagnation-review` (disabled by default) adds a reminder to the observation
after repeated acknowledged constant commands. `--stagnation-window` sets how
many decisions trigger it (2–32, default 4) and also enables the review. The
reminder takes no action and ends nothing; only acknowledged prefixes count.

## Recovery and results

Model-call recovery stays in the same conversation and never resets the task,
switches models or replays robot actions. A capacity error is retried only after
Codex closes the turn as failed with `serverOverloaded`; a network error that
Codex marks as retrying keeps the turn open. Recovery is bounded; when it is
exhausted, the episode ends with an infrastructure error, not a policy failure.
When the episode ends, the model's pending turn is interrupted, not continued.

Each run manifest records the git revision, dirty flag, profile ID and effective
configuration; no model source is copied into the run.

Write results under `results/<benchmark>/`, with the canonical task ID and a short
description in run names. Calls, recovery attempts, executed action decisions and
controls are recorded separately. Interaction and media recording default to
enabled and may be disabled without changing inputs, execution or scoring.
Essential results, denominators and errors remain available; failed runs are not
overwritten. The entire `results/` tree is local and Git-ignored. See
[recording options](../../docs/recording.md). For a compact outcome view of a
closed run, use `python -B -m benchkit.reports.basic_result --run-dir RUN_DIR
--output-dir REPORT_DIR`.

### Token usage

Codex reports token usage as a running total for the episode's conversation, and
it reports each response's tokens only after the next tool reply. Per-call usage
therefore lags one call: the first call is often unknown. At close, the policy
interrupts the unanswered final tool call, which makes Codex report the last
response's tokens without another model request. The runner then reconciles the
per-call sum with this episode total and records one `usage_reconciliation`
event; the episode's usage is the reconciled total. If the final report does not
arrive within 10 seconds, the total is kept as seen and marked incomplete
(`reported_complete: false`). Unknown usage or cost stays unknown. See the
[result format](../../docs/result-format.md) for the per-field rule.
