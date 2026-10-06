# Own your decision loop: a small protocol example

This is educational trusted-driver code, **not a registered model, a capability
baseline, a general runner or a RoboDojo panel evaluator**. It contains no actor,
fixed robot actions, provider backend or model configuration. Its offline tests
use a fake loopback service only; no native/model result is claimed.

[`driver.run_one`](driver.py) demonstrates that a participant can own the loop
without implementing `Policy`, calling `EvaluationRunner`, or registering a
profile. It reuses the existing SIM transport and result writers rather than
implementing another server or scheduler. Existing central case scheduling is
unchanged: a trusted operator/scheduler preselects and launches the service;
this driver refuses anything except its entire one-case schedule.

## Deliberately narrow supported interface

- Exactly one case in the complete service schedule; no truncating a named panel.
- Horizon mode with a finite, service-advertised control cap. No guessed budget.
- One native control per callback; any required/configured prefix greater than
  one is rejected before `open`. Decision-budget tracks are not supported here.
- Declared RGB, robot state, language and robot-control feedback. Arbitrary
  observation metadata is not forwarded. Methods requiring additional metadata
  or capabilities need their own reviewed projection, not an expanded default.
- Invalid input stops this example; no feedback retry, resampling or replay.
- A lost/invalid control acknowledgement preserves the last acknowledged count,
  marks in-flight execution uncertain and never repeats the physical action.

RoboDojo's five-/50-layout panels do **not** fit this example. The guards are
teaching-example scope, not new benchmark rules or universal agent constraints.

## Supply your own trusted bridge

Only a separately authorized evaluation should execute code such as:

```python
import os
from pathlib import Path
from benchkit.sim_server.client import SimServerBenchmarkAdapter
from benchkit.recording import RecordingOptions
from AgentPolicies.protocol_example.driver import run_one
from my_method import decide  # Your implementation; none is bundled here.

client = SimServerBenchmarkAdapter(
    "http://127.0.0.1:8765", os.environ["RSI_SIM_SERVER_TOKEN"])
run_one(client, decide, seed=7,
        method={"schema_version": "starvla-rsi.method/v1",
                "id": "my_method", "version": "v1", "models": [], "configuration": {}},
        output_dir=Path("AgentPolicies/my_method/results/my_benchmark/raw/task-single-case"),
        run_id="task-single-case", recording=RecordingOptions())
```

Use the actual declared method/model composition rather than copying an empty
declaration when identities are known. Supply the service's exact selected seed;
the snippet is not a native-ready preset or permission to evaluate a task.

`decide(public_input)` receives a fresh plain dictionary containing:

- An opaque episode label, instruction and declared robot images/state/feedback.
- Observation/action specifications and acknowledged call/control counters.

It receives **no client, credentials, server/session identity, reset seed, native
episode ID, task metadata, reward, termination flags or scoring methods**.
Responses are plain dictionaries:

```python
{"action": native_action_vector, "usage": reported_usage,
 "component_usage": reported_component_usage, "note": optional_visible_note}
# Or:
{"stop": True, "reason": "give_up", "usage": reported_usage}
```

Usage is optional; omitted data stays unknown, not zero. The callback can own
its planning, model composition and memory. The driver does not infer component
identity or allocate aggregate usage between models.

The callback must be **trusted, reviewed bridge code**. A function in the same
Python process is not an OS sandbox: it can inspect environment variables,
filesystem or stack frames. To use an untrusted code agent, the bridge must
serialize only the projected public input into an appropriately isolated actor
process/service, excluding evaluator credentials and private filesystem/process
access. Merely passing a dictionary does not enforce that deployment isolation.

## Results and recording

The driver writes the [closed result format](../../docs/result-format.md), retains
errors as errors, and calls native scoring only after the actor loop has ended.
It never turns an infrastructure interruption into a task failure or a success.
The result's counters cover acknowledged controls, not uncertain in-flight motion.
Client finalization errors remain visible; a closed result file is not proof of
confirmed simulator cleanup. A storage failure may leave an incomplete record.

Recording defaults on. `RecordingOptions("minimal")` disables optional callback
and robot events and limits client artifact copies; it does not change actor
input, action execution, native server capture or score. The example records
callback summaries, **not full provider conversations or hidden reasoning**.
Its event files are educational JSONL, not the reference Policy-event ledger.
The richer reference interaction viewer may therefore reject them; basic result
publication remains available without detailed logs or source snapshots:

```sh
python -m benchkit.reports.basic_result \
  --run-dir /absolute/closed-example-run \
  --output-dir /absolute/new-example-report
python -B -m unittest benchkit.checks.test_protocol_example -q
```

No command-line actor/plugin loader is added. Importing the example does not
connect, open, reset or call a model. The tests exercise this boundary through
the actual shared client and a fake service, not a simulator.
