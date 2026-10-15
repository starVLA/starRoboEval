# codex_native: a Bench Server validation client

This profile provides **`codex_native` (`codex-native/v2`)**, a client for validating
Bench Server integration, observation/action contracts and result recording.
It selects numeric actions through a conversation that persists within each episode.
The Benchmark service owns native control, task conditions and scoring;
interface compatibility alone does not establish native benchmark performance.

## File layout

```text
gpt6_astra/
├── run.py                         # Trusted service client and evaluation entrypoint
├── codex_native.py                # CodexNativePolicy and factory create_policy
├── configs/
│   ├── codex_native_config.json   # Single method and registry configuration
│   ├── codex_native_prompt.txt    # Method prompt
│   ├── profile.json               # Client identity and factory registration
│   ├── configuration.schema.json  # Parameter types and allowed overrides
│   └── dependencies.json          # Pinned source dependencies
├── tools/
│   ├── runner.py                  # Reusable execution loop and accounting
│   ├── stop_rules.py              # Optional policy stopping preferences
│   ├── persistent_runtime.py      # Conversation, execution feedback and recovery
│   ├── public_observation.py      # Public observations and image processing
│   ├── json_io.py                 # Structured data handling
│   ├── codex_app_server.py        # App-server communication
│   └── codex_runtime.py           # CLI installation, version and login checks
├── results/                       # Results organized by Benchmark
├── README.md                      # This guide
└── AGENTS.md                      # Development boundary
```

The general CLI and anonymous mailbox workflow also reuse `tools/runner.py` and
`tools/stop_rules.py`; stopping preferences remain specific to each profile.

## Configuration

Edit the [method parameters](configs/codex_native_config.json) and
[prompt](configs/codex_native_prompt.txt). There is one method and one default
configuration; the schema controls allowed CLI overrides. Effective settings are
recorded in results. Defaults request `gpt-6-astra` / `xhigh` over
`codex-app-server/v1`, with a chunk limit of 5, a 900-second call timeout and image
previews with a longest side of 480 pixels. Original PNGs remain available.
Each run separately declares a finite call cap and the service's execution budget.

## Installation

Use the pinned Codex CLI **0.154.0** with an existing login:

```sh
pip install -e '.[gpt6-astra-codex]'
python -B -m benchkit preflight-policy --model-profile gpt6_astra
```

Preflight starts neither model inference nor simulation, and does not prove model
access or native environment readiness. The client uses Codex login through
app-server, with no additional API key or SDK fallback.

## Single-task integration example

Start the service following the selected Benchmark's README, then connect:

```sh
python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark BENCHMARK_ID \
  --seed SEED --episodes 1 --max-steps ADVERTISED_HORIZON \
  --max-policy-calls DECLARED_CALL_CAP --replan-interval 5 \
  --budget-mode horizon --invalid-action-handling feedback \
  --output-dir AgentPolicies/gpt6_astra/results/BENCHMARK_ID/raw \
  --run-id DATE-TASK-short-description-native-v2-once
```

Replace the uppercase placeholders and confirm the complete task schedule, seed,
episode count and advertised horizon before running. `--control-method` is optional
and accepts only `codex-native/v2`. The service's `required_replan_interval` must
match; incompatible contracts fail before a claim. Supply the token to the trusted
driver through `RSI_SIM_SERVER_TOKEN`, never through model inputs. This method uses
the service entrypoint; the retained local `campaigns prepare` path does not support
its horizon/feedback contract.

## Inputs and execution boundaries

The model receives public task text, RGB images, declared robot state and action
semantics, remaining control budget and acknowledged execution feedback. It gets
no administrative client, credentials, layout/seed metadata, private scores,
simulator handles or reset tools. The driver does not forward arbitrary
`control_feedback` payloads; the model does not read arbitrary Benchmark files.
Notes remain within the episode.
Local permission checks are not OS isolation; see the [development boundary](AGENTS.md).

`robot_act` submits numeric action vectors. The method chooses chunks (configurable
from 1–32) and repetitions; the service executes each control separately. Invalid
actions execute nothing and return correction feedback on the next counted call.
Acknowledged prefixes retain their actual counts; uncertain controls are never
replayed. The client does not repair actions, solve tasks through fallbacks or
automatically generate return trajectories. Native termination and budgets always apply.

Ordinary give-up and voluntary `safety_stop` are disabled by default.
`--safety-stop` enables voluntary stops; `--no-safety-stop` disables them. When disabled,
an empty-action safety stop is rejected with correction feedback. When enabled, an explained
stop ends the attempt without awarding success. This does not disable hardware protection.

## Recovery and results

Model-call recovery stays in the same conversation; it cannot reset a task, switch
models or replay robot actions. Capacity recovery requires an explicitly failed,
closed turn with `serverOverloaded`; an error notification alone is insufficient.
Recovery is bounded, and exhaustion remains an infrastructure error, not native
failure. Native termination cancels the model without an unmetered final continuation.

Write results under `results/<benchmark>/`, with the canonical task ID and a short
description in run names. Calls, recovery attempts, executed action decisions and
controls are recorded separately; unknown usage or cost stays unknown. Interaction
and media recording default to enabled and may be disabled without changing inputs,
execution or scoring. Essential results, denominators and errors remain available;
failed runs are not overwritten. See [recording options](../../docs/recording.md) and
the [historical results index](results/README.md). Historical scores retain their
original method identities; offline checks prove neither native success nor provider identity.
