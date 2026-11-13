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
│   └── configuration.schema.json  # Parameter types and allowed overrides
├── tools/
│   ├── runner.py                  # Reusable execution loop and accounting
│   ├── persistent_runtime.py      # Conversation, execution feedback and recovery
│   ├── public_observation.py      # Public observations and image processing
│   ├── stagnation_review.py       # Optional acknowledged-command reminder, not a task solver
│   ├── json_io.py                 # Structured data handling
│   ├── codex_app_server.py        # App-server communication
│   └── codex_runtime.py           # CLI installation, version and login checks
├── results/                       # Local results by Benchmark; Git-ignored
├── README.md                      # This guide
└── AGENTS.md                      # Development boundary
```

The general CLI also reuses `tools/runner.py`; stopping preferences remain
specific to each profile.

## Configuration

Edit the [method parameters](configs/codex_native_config.json) and
[prompt](configs/codex_native_prompt.txt). There is one method and one default
configuration; its schema bounds every override. `run.py` exposes `--image-max-edge`,
`--safety-stop`, `--allow-task-completion` and `--stagnation-*`; other settings,
including the chunk limit, change only by editing the configuration. Effective settings are
recorded in results. Defaults request `gpt-6-astra` / `xhigh` over
`codex-app-server/v1`, with a chunk limit of 5, a 900-second call timeout and image
previews with a longest side of 480 pixels. `reasoning_effort` is passed to Codex
as configured; Codex decides which values it accepts. Voluntary `safety_stop` and
`task_complete` are enabled; the model decides whether to use them.
Original PNGs remain available.
Each run separately declares a finite call cap and the service's execution budget.

## Installation

Use the pinned Codex CLI **0.154.0** with an existing login:

```sh
pip install -e '.[gpt6-astra-codex]'
python -B -m benchkit preflight-policy --model-profile gpt6_astra
```

Preflight starts neither model inference nor simulation, and does not prove model
access or native environment readiness. The client uses Codex login through
app-server and requires the existing ChatGPT login in this source version;
there is no API-key runtime profile or SDK fallback in this checkout.

## Single-task integration example

Start the service following the selected Benchmark's README, then connect:

```sh
python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark BENCHMARK_ID \
  --seed SEED --episodes 1 \
  --max-policy-calls DECLARED_CALL_CAP \
  --output-dir AgentPolicies/gpt6_astra/results/BENCHMARK_ID/raw \
  --run-id DATE-TASK-short-description-native-v2-once
```

Replace the uppercase placeholders and confirm the complete task schedule, seed,
episode count and advertised horizon before running. `--max-steps` defaults to the
service's advertised horizon; an explicit value overrides it, and the manifest
records the service horizon (null if none) and whether the value was overridden.
The shared server does not check the client's value. A smaller override departs
from the native budget; some adapters still truncate at their own horizon. The method is
always `codex-native/v2`; the chunk limit comes from the method config.
By default the driver executes the whole chunk; a service-declared
`required_replan_interval` becomes the executed prefix and narrows the chunk the
method offers. Supply the token to the trusted
driver through `RSI_SIM_SERVER_TOKEN`, never through model inputs.

This client requires a service configured with `budget_mode: "horizon"`, not a
decision-coupled execution track. For the checked-in LIBERO server example,
use `--benchmark libero --seed 20260907 --episodes 1` (advertised horizon 520) and
choose the method's call cap.

Startup separates local configuration from service discovery and runtime readiness:

1. Validate the local policy configuration against its schema and check source origins.
   A failure stops before contacting the benchmark or starting a runtime probe. A
   `--method-file` is normalized and recorded as declared, not compared with the policy.
2. Read the server's `describe` response and check interface, schedule and budget
   compatibility. This does not claim or initialize an episode.
3. Probe the local CLI and its temporary configuration session. This may create
   subprocesses and temporary files, but does not start model inference.
4. Only after those checks, enter the evaluation runner and claim the selected case.

A failed readiness check leaves the case unclaimed. These are this driver's
startup stages, not extra requirements imposed by the benchmark on other agents.

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

The reference runner checks the public instruction in every acknowledged
observation. If it changes, the remaining actions from that decision are not
executed; the next policy call receives the new instruction and observation.
This uses no private subtask status or score, and does not reset policy memory.
Unchanged language permits the method's selected multi-control prefix. New run
manifests record `instruction_change_handling: "replan-after-ack/v1"`; this is
reference-driver behavior, not a server-imposed inference frequency.

Voluntary `safety_stop` is enabled by default; ordinary give-up is not available.
`--no-safety-stop` disables safety stops for one run. When disabled,
an empty-action safety stop is rejected with correction feedback. When enabled, an explained
stop ends the attempt without awarding success. This does not disable hardware protection.

Model-declared completion (`actions=[]` with `stop_reason="task_complete"`) is also
enabled by default; `--no-allow-task-completion` disables it for one run.
An enabled declaration ends normally without another control or verification
cycle. It records the model's judgment, never native success: the benchmark still
reports its own score and outcome, even when these disagree with the declaration.

`--stagnation-review` enables an advisory after repeated acknowledged constant
commands (`--stagnation-window 4`, configurable from 2 to 32 decisions; giving
a window also enables the review).
This is disabled by default and does not infer a stall, enforce a motion change,
stop the episode or query hidden scores. Repeated velocity commands may be useful.
Only acknowledged prefixes count; rejected or uncertain actions do not create
new evidence. The optional completion operation does not depend on this reminder.

## Recovery and results

Model-call recovery stays in the same conversation; it cannot reset a task, switch
models or replay robot actions. Capacity recovery requires an explicitly failed,
closed turn with `serverOverloaded`; an error notification alone is insufficient.
Recovery is bounded, and exhaustion remains an infrastructure error, not native
failure. Native termination cancels the model without an unmetered final continuation.
Explicitly retrying network notifications keep the current turn pending; they do
not authorize another action or a new task. Inherited MCP services are checked
and disabled before any inference, with the effective configuration verified.

This flattened client preserves the local Direct v4 completion/review options
while exposing only `codex-native/v2`. Each run manifest records the git
revision, dirty flag, profile ID and effective configuration; no model source is
copied into the run. Historical bounded Native, Direct and Planned methods keep
their original names and results as data; no old entrypoint forwards to this method.

Write results under `results/<benchmark>/`, with the canonical task ID and a short
description in run names. Calls, recovery attempts, executed action decisions and
controls are recorded separately; unknown usage or cost stays unknown. Interaction
and media recording default to enabled and may be disabled without changing inputs,
execution or scoring. Essential results, denominators and errors remain available;
failed runs are not overwritten. The entire `results/` tree is local and Git-ignored.
See [recording options](../../docs/recording.md). Historical scores retain their
original method identities; offline checks prove neither native success nor provider identity.
