# GPT6Astra agent methods

This directory owns model decisions, prompts, public-observation processing and
results. The benchmark server owns native execution and scoring. The actor sees
only declared RGB, robot state, action semantics and execution feedback; it never
receives simulator handles, object truth, scores or administrative credentials.
See [policy development boundaries](AGENTS.md).

## Choose a method

| Method | Behavior | Interface |
| --- | --- | --- |
| [`codex-native/v1`](docs/NATIVE_CONTROL.md) | Current observation and the last eight acknowledged action chunks; a bounded CLI request per decision, with declared pre-action transport recovery | Compatible declared numeric action vectors, including joint or delta-pose control |
| [`codex-direct/v3`](docs/DIRECT_CONTROL.md) | Persistent conversation, image/analysis tools, notes and generic observation–action feedback | Compatible declared numeric action vectors; no fixed robot or benchmark |
| [`codex-planned/v1`](docs/TOP_DOWN_POLICY.md) | Persistent conversation, structured subgoals, evidence checks and same-episode memory | Compatible declared numeric action vectors; no hardcoded robot or benchmark |

The factory defaults to **Native**. The server driver `run.py` retains its
explicit **Direct v3** default; select `--benchmark` and `--control-method` for every
new experiment. Planned is an experimental method, not a demonstrated improvement
over either baseline. None uses a VLA, task-solving fallback or local simulator.

Responses API, bounded-memory EEF v1/v2 and robot-specific Direct v1/v2 are no longer active methods.
Their code can be recovered from Git and their frozen evaluation packages.
There are no forwarding modules or implicit fallbacks to retired methods.
Existing results retain their original method, source, outcome and accounting.

## Directory guide

| Directory | Contains |
| --- | --- |
| `methods/` | Only the three selected policy implementations |
| `tools/` | Factory, shared persistent runtime, public observation/image helpers, local checks and diagnostics; not automatic robot skills |
| `transports/` | Codex CLI and persistent app-server communication |
| `prompts/` | One prompt for each active method |
| `configs/` | Three method presets plus `config.json`, the registry defaults/override declaration, not a fourth method |
| `docs/` | Method setup, recovery behavior and reference comparison |
| `checks/` | Offline regression fixtures, not capability evaluations |
| `results/` | Published reports; raw evidence and media remain Git-ignored |

The entrypoint and declarations remain at the package root. New internal source
captures use `model-source/v6` for this layout. Historical v1–v5 captures retain
their exact original file lists and factories; deleting an active entrypoint
does not invalidate a frozen record or rewrite its outcome.

## Setup and execution

Install the pinned Codex CLI **0.154.0** and the model-side Python dependencies:

```sh
pip install -e '.[gpt6-astra-codex]'
python -B -m benchkit preflight-policy --model-profile gpt6_astra \
  --policy-args '{"control_method":"codex-native/v1"}'
```

These methods use the existing Codex login, without a separate API key or SDK
fallback. Local preflight does not make an inference request, open a simulator
or establish model access. Native and persistent methods have different
permission/evidence limitations, documented in their respective guides.

Start the chosen benchmark server using its README, then connect
[`run.py`](run.py). Use the [Native sample](docs/NATIVE_CONTROL.md#one-task-sample)
or [Direct panel command](docs/DIRECT_CONTROL.md#run-a-predeclared-comparison),
with that service's declared action space, task schedule and native horizon.
Credentials belong only to the trusted driver and server, never the actor.

The policy owns action chunk length and reasoning. The server executes each
submitted action under native control and termination rules. Model-call recovery
is not permission to reset a case or replay an uncertain robot action.

## Results and recording

Keep outputs in `results/<benchmark>/` and name runs with their task and a short
description. Record decision calls, transport attempts, executed decisions and
controls separately; provider-internal requests and missing usage stay unknown.
Infrastructure interruptions are not native task failures. A recovered transient
error remains in the call receipt rather than ending the episode immediately.

Interaction history and media are optional, enabled by default. Changing
retention must not change actor inputs, action behavior or native scoring.
See [recording options](../../docs/recording.md) and the [result index](results/README.md).
The owner's attribution of earlier interactive trials does not supply model IDs
or usage evidence that those historical records never captured.
