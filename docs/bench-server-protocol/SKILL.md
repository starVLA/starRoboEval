---
name: bench-server-protocol
description: Build a participant-owned agent driver for this repository's Bench Server protocol, using its integration workflow and optional single-case Python template. Use when connecting a new method or adapting a trusted client, not for implementing benchmark adapters or solving robot tasks.
---

# Connect an agent method to Bench Server

Use this skill to implement the participant side of the service boundary. Keep
the resulting method and trusted driver under `AgentPolicies/<profile>/`.
The skill's [driver template](driver.py) is development material, not an
installed policy, registered model or general evaluator. Existing clients do not
import this skill at runtime.

## Establish the contract

Locate the repository root from the working checkout, not the skill's install
directory. Read its `AGENTS.md`, [architecture](../architecture.md),
[evaluation workflow](../evaluation.md) and
[wire protocol](../../benchmarks/simBenchmarks/SERVER_PROTOCOL.md).
Read the selected benchmark's README and `EVALUATION_PROTOCOL.md` for its actual
observations, action semantics, schedule and execution budget. If changing native
semantics, verify them against that benchmark's pinned native evaluator first.

Record the selected service/track, fixed cases and seeds, method/model composition,
and configuration before execution. Missing deployment details do not prevent
writing a client; leave them explicit instead of inventing a native-ready preset.
Creating or refactoring a client does not start an evaluation. Launch, claim or
reset cases only within the user's authorized evaluation scope.

The authenticated protocol is the integration boundary. Python `Policy`, the
profile registry and `EvaluationRunner` are optional. Use the shared SIM transport
and result writers where helpful; do not add a simulator, task solver or another
scheduler to the agent side. Current central campaign commands use a separate
frozen local-adapter path, not remote-service orchestration.

## Choose whether the template fits

Inspect the complete advertised schedule and contracts before a claim.
[driver.py](driver.py) supports only:

- Exactly one case in the entire service schedule; never truncate a named panel.
- Horizon mode with a finite, service-advertised control cap, plus any declared
  call cap. No guessed or extended native budget.
- One control per decision. Configured or required replan intervals greater than
  one are rejected before `open`; decision-budget tracks are unsupported.
- Declared language, RGB, robot state and control feedback. Privileged observations
  and other modalities are rejected; arbitrary observation metadata is excluded.
- Termination on invalid input, without feedback retries, resampling or replay.

These are template limits, not universal benchmark or agent constraints.
RoboDojo's five-/50-layout panels do not fit. For another contract, implement and
review an appropriate driver rather than weakening guards to force this example
to run. A method may choose action chunks and replan timing where the selected
protocol permits them; each service `step` still accepts one sequenced action.
Preserve existing decision-coupled budgets and required replan intervals.
For a driver that executes multiple controls per decision, count a decision once
when at least one control is acknowledged, and count each acknowledged control
separately. Do not carry over the template's equality between `action_decisions`
and `environment_steps`.

## Adapt the template into the method

If the contract fits, copy `driver.py` into the method's own source, for
example `AgentPolicies/my_method/tools/protocol_driver.py`. Import that copy from
the method entrypoint; do not import the template from `docs/` or restore the old example
package. Supply a reviewed bridge that implements the method's own decisions.

The following wiring assumes that the actual service URL, private token, selected
seed, method declaration and unused output path have already been supplied by the
trusted entrypoint. It is not a standalone evaluation preset:

```python
from benchkit.recording import RecordingOptions
from benchkit.sim_server.client import SimServerBenchmarkAdapter
from AgentPolicies.my_method.tools.protocol_driver import run_one
from AgentPolicies.my_method.actor_bridge import decide

client = SimServerBenchmarkAdapter(server_url, server_token)
run_one(
    client, decide,
    seed=selected_seed,
    method=method_declaration,
    output_dir=output_dir,
    run_id=run_id,
    recording=RecordingOptions(),
)
```

Declare actual known models, roles, prompts, memory and tools using the
[method contract](../agent-methods.md). Unknown provider/model attribution
stays unknown. New outputs belong in
`AgentPolicies/<profile>/results/<benchmark>/`; export directory names include
the date/round, canonical task ID, short English task description and case ID.
Use a new output directory, retaining previous failures and errors. A new run ID
does not itself authorize another attempt.

## Keep the actor boundary explicit

`decide(public_input)` receives a fresh dictionary with an opaque episode label,
instruction, declared images/state/control feedback, observation/action specs,
and acknowledged call/control counters. It receives no client, credentials,
server/session identity, reset seed, native episode ID, arbitrary task metadata,
reward, termination flags or scoring methods.

Return exactly one action or an explicit stop:

```python
{"action": native_action_vector, "usage": measured_usage,
 "component_usage": measured_component_usage, "note": optional_visible_note}
# Or:
{"stop": True, "reason": "give_up", "usage": measured_usage}
```

Usage and notes are optional. Missing usage stays unknown, not zero; aggregate
usage is never allocated among models without evidence. The method owns its
planning, memory and model composition within the selected protocol.

The callback is trusted bridge code. A Python function in the evaluator process
can inspect credentials, files and stack frames; a dictionary alone is not a
sandbox. For an untrusted actor, serialize only allowed inputs into a separately
isolated process/service with no evaluator credentials or private filesystem and
process access. The administrative SIM client remains with the trusted driver.

## Close and verify the integration

Preserve single-attempt claims, sequencing and native termination. A lost or invalid
control acknowledgement must retain the last acknowledged count, mark in-flight
execution uncertain and never replay the action. Collect private native metrics
only after the actor loop ends; do not feed scores back into an active policy.

The template writes the [closed result format](../result-format.md),
retaining infrastructure/protocol/policy errors separately from native outcomes.
Finalization errors remain visible; a closed result file does not prove confirmed
simulator cleanup. Storage failure can leave an incomplete record. Source capture
is not implemented by this template; do not claim verified source provenance.

Recording defaults on. `RecordingOptions("minimal")` changes optional client
retention, not actor inputs, execution, server capture or scoring. Callback event
files are educational JSONL, not full provider conversations or the reference
Policy-event ledger; the richer interaction viewer may reject them. Basic reports
can read closed runs using `python -m benchkit.reports.basic_result` as described
in the evaluation workflow.

Validate an adapted driver offline before authorized native use: exercise closure,
public-input projection, unsupported-contract rejection before `open`, and an
uncertain ACK without replay. Keep temporary debug checks outside tracked source,
under ignored `Projects_readmes/temp/` or a system temporary directory. Report
offline validation separately from actual native evaluations and provider claims.
