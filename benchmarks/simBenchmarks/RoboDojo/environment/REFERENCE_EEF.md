# Direct v2 EEF runtime binding

This document binds the only public RoboDojo server implementation to the
reference Direct-control behavior at commit
`8f3d362b077d8efb77e2a7274d5b2c20e2243846`. Matching numerical execution does
not by itself prove identical model context, assets, rendering or success rate.

## Fixed scope

- Task: `classify_objects`
- Named panels: `fast` uses layouts 0–4; `full` uses layouts 0–49, once each
- Native horizon: 1100 controls
- Cameras: head, left wrist and right wrist, original 640×480 RGB
- Public state: measured joint14 plus measured link6 EEF14
- Public action: absolute dual-arm EEF16 in world coordinates
- Execution: robot-only numerical Jacobian DLS, no cuRobo planner
- Feedback: mandatory `robodojo.robot-control-feedback/v1`

The worker sets the native execution count to one selected reset while retaining
the upstream configured count and full 55-layout inventory as provenance. The
five-layout `fast` panel is the reference comparison. The `full` panel matches
this task's 50 configured native episodes; it does not cover all RoboDojo tasks.
Both schedules are fixed in [../bench_server/protocol/task_catalog.json](../bench_server/protocol/task_catalog.json).

## Numerical execution

Input quaternions use `wxyz` and must be unit length within `1e-4`. The worker
converts to SciPy `xyzw`, computes the bounded DLS update from measured robot
state, intersects native soft limits with the per-control measured-joint bound,
casts the 14-value joint command to float32 and calls native `take_action` once.
Each command produces ten physics ticks and one native reward/end check.

No object state, collision-aware plan, learned support policy, hypothetical
rollout or success query selects the target. Target-size and chunk preferences
belong to the model implementation.

## Runtime binding

[reference_eef_runtime.py](reference_eef_runtime.py) verifies the immutable
deployment manifest against [reference_eef_snapshot.json](reference_eef_snapshot.json).
It validates source revision, exact runtime package versions, the full asset
inventory, classify layouts and external IsaacLab/cuRobo bindings before reset.
The worker repeats critical checks after native setup and retains the used-USD
dependency audit.

Use [server.example.json](../server.example.json) with the manifest path and
SHA-256 emitted by preparation. The server configuration selects a named `panel`
and a GPU. Arbitrary layout subsets, `--episodes` truncation and protocol
selectors are rejected.

```sh
python -B -m benchmarks.simBenchmarks.RoboDojo.server \
  --parameters /absolute/robodojo-direct-v2.json \
  --seed 20260907 --port 8765 \
  --output-dir /absolute/new-run/server
```

Use a fresh output directory. Starting the service does not reset Isaac. Once a
layout is claimed, any failed reset or uncertain action is retained and cannot
be replaced automatically.

## Native validation status

The 2026-09-20 five-layout Direct v2 run exercised this service boundary and
retained paired server/client evidence. That result is model-owned under
`AgentPolicies/gpt6_astra/results/robodojo/`; it does not convert CPU tests into a
portable fresh-machine certification. A new deployment still requires the
readiness gate in [README.md](README.md).
