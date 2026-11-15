# Native Claude Opus Policy

This profile is the **Native Claude Opus Policy**: Claude Opus controls the robot
directly, with one generic setup and one prompt shared by every benchmark. It is
the baseline for what the model does before anything is tailored to a benchmark.
Records name it `claude-opus-messages-native`: the `claude_opus` profile with its
`messages_native.py` policy.

The model chooses numeric actions through one conversation per episode. The
benchmark service owns native control, task conditions and scoring.

## File layout

```text
claude_opus/
├── run.py                            # Trusted service client and evaluation entrypoint (start here)
├── messages_native.py                # ClaudeOpusPolicy and factory create_policy
├── configs/
│   ├── messages_native_config.json   # Single method and registry configuration
│   ├── messages_native_prompt.txt    # Method prompt
│   ├── profile.json                  # Client identity and factory registration
│   └── configuration.schema.json     # Parameter types and allowed overrides
├── tools/
│   ├── messages_runtime.py           # Conversation, execution feedback, recovery and usage
│   ├── public_observation.py         # Public observations and image processing
│   ├── stagnation_review.py          # Optional repeated-command reminder
│   └── json_io.py                    # Structured data handling
├── results/                          # Local results by Benchmark; Git-ignored
├── README.md                         # This guide
└── AGENTS.md                         # Development boundary
```

The execution loop is the shared `benchkit/driver/runner.py`, also used by the general
CLI; stopping preferences remain specific to each profile. This profile shares
no code with other policies.

Reading order, following one evaluation from the top:

1. `run.py`: `main()` calls `run()`, which builds the policy, connects to the service and starts the runner.
2. `benchkit/driver/runner.py`: `EvaluationRunner.run` writes the run; `_EpisodeRun.run` plays one episode.
3. `messages_native.py`: `ClaudeOpusPolicy` defines what the model sees and how its reply becomes a decision.
4. `tools/messages_runtime.py`: `MessagesRuntime.act` carries one call through the Messages conversation.

## Baseline configuration

The baseline is the checked-in [configuration](configs/messages_native_config.json)
and [prompt](configs/messages_native_prompt.txt), used unchanged on every benchmark.
It requests `claude-opus-5-5` with effort `medium` over `anthropic-messages/v1`,
with adaptive thinking, at most 32000 output tokens per response (thinking
included), a chunk limit of 5, a 900-second request timeout and image
attachments with a longest side of 480 pixels; original PNGs are kept for the
audit export. Voluntary `safety_stop` and `task_complete` are enabled, and the
model decides whether to use them. The stagnation review is disabled. Nothing in
this setup is tuned to a benchmark or its failure modes.

Long episodes use server-side context editing (`clear_tool_uses_20250919`): once
a request exceeds 80000 input tokens, the API clears the oldest robot_act results
from what the model sees, keeps the 8 most recent and clears at least 30000
tokens at a time. Tool inputs are kept. The client sends the full conversation
every time and never edits it; each cleared span is recorded.

The schema bounds every override. `run.py` exposes `--effort`, `--max-tokens`,
`--image-max-edge`, `--safety-stop`, `--allow-task-completion` and
`--stagnation-*`; other settings, including the chunk limit and context editing,
change only by editing the configuration. A run that changes any of these, or
the prompt, is a different method: report it as its own entry, not as the Native
Claude Opus Policy. Effective settings are recorded in results. Each run
separately declares a finite call cap and the service's execution budget.

## Installation

Use the official `anthropic` Python SDK with an API key in the environment.

```sh
pip install -e '.[claude-opus]'
export ANTHROPIC_API_KEY=...   # the only credential source; never written to configuration or records
python -B -m benchkit preflight-policy --model-profile claude_opus
```

Preflight checks the dependencies and that `ANTHROPIC_API_KEY` is set, then sends
one token-count request with the episode's model, system prompt, tool and
settings. Token counting generates nothing and starts no simulation. The client
takes only `ANTHROPIC_API_KEY` as a credential; SDK settings such as
`ANTHROPIC_BASE_URL` still apply from the environment.

## Single-task integration example

Start the service with `rsi-bench serve --benchmark BENCHMARK_ID ...`, following
the selected Benchmark's README, then connect:

```sh
python -B -m AgentPolicies.claude_opus.run \
  --sim-server http://127.0.0.1:8765 --benchmark BENCHMARK_ID \
  --seed SEED --episodes 1 \
  --max-policy-calls DECLARED_CALL_CAP \
  --output-dir AgentPolicies/claude_opus/results/BENCHMARK_ID/raw \
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
3. Check the dependencies and API key, then count tokens for the request shape,
   without model inference.
4. Enter the evaluation runner and claim the selected case.

## Inputs and execution boundaries

The model receives public task text, RGB images, declared robot state and action
semantics, remaining control budget and acknowledged execution feedback. It gets
no administrative client, credentials, layout/seed metadata, private scores,
simulator handles or reset tools. The driver does not forward arbitrary
`control_feedback` payloads.

Every observation arrives inside the conversation: the packet as JSON text and
the images as inline image blocks. The model's only tool is `robot_act`; it has
no files, code execution, web search, MCP servers or server tools, and nothing
persists beyond the episode. See the [development boundary](AGENTS.md).

`robot_act` submits numeric action vectors. The model chooses how many controls
to send (up to the configured chunk limit, 1–32) and how often to repeat them;
the service executes each control separately. The tool is strict, so its input
always has the declared fields and types; the policy itself checks request IDs,
chunk length, vector size, bounds and stops. An invalid action executes nothing
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
switches models or replays robot actions. A failed request is sent again with
the same messages: after a connection error, timeout or server error up to 20
times in a row, 10 seconds apart, and after a rate-limit or overload answer
(429/529) up to 9 times in a row, 30 seconds apart. A response that ends
without a `robot_act` call, including one cut off at `max_tokens`, is continued
with the same packet up to 2 times per episode; a cut-off call is answered as
not executed. When recovery is exhausted, or on an authentication or request
error, the episode ends with an infrastructure error, not a policy failure. A
model refusal (`stop_reason: "refusal"`) ends the episode as a policy error:
the model declined while the transport worked. Any other stop reason, such as
`pause_turn`, is an infrastructure error.
When the episode ends, the final `robot_act` call stays unanswered and no
further request is sent.

Each run manifest records the git revision, dirty flag, profile ID and effective
configuration; no model source is copied into the run. Records carry the
request settings, responses and stop reasons; thinking, its signatures and image
bytes are kept only as digests, a refusal only by its category, and no request
headers or keys are recorded.

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

Each Messages response reports its own token usage, so per-call usage is exact:
input tokens include cache reads and cache writes, and cached input tokens are
the cache reads. The raw counters (`input_tokens`, `output_tokens`,
`cache_read_input_tokens`, `cache_creation_input_tokens`) are kept in each
receipt. The episode total is the sum over all responses, and the runner's
`usage_reconciliation` finds it equal to the per-call sum. If a stream breaks
after it started, that call's tokens are unknown and the episode total is marked
incomplete (`reported_complete: false`). Cost is not estimated. See the
[result format](../../docs/result-format.md) for the per-field rule.
