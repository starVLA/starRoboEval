# End-effector control runtime

This document binds the only public RoboDojo server implementation to the
reference Direct-control behavior at commit
`8f3d362b077d8efb77e2a7274d5b2c20e2243846`. Matching numerical execution does
not by itself prove identical model context, assets, rendering or success rate.

## Fixed scope

- Task: `classify_objects`
- Layout selections: 0–4 (5 cases) or 0–49 (50 cases), once each
- Native horizon: 1100 controls
- Cameras: head, left wrist and right wrist, original 640×480 RGB
- Public state: six measured joints and one last commanded gripper opening per
  arm (14 values), followed by the two measured link6 poses (14 values)
- Public action: absolute dual-arm EEF16 in world coordinates
- Execution: robot-only numerical Jacobian DLS, no cuRobo planner
- Feedback: mandatory `robodojo.robot-control-feedback/v1`

The worker sets the native execution count to one selected reset while retaining
the upstream configured count and 55-layout inventory. The
50-layout selection matches this task's 50 configured native episodes; the
five-layout selection chooses its first five cases.
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

## Deployment validation

Each deployment requires the readiness gate in [README.md](README.md): verify
the pinned assets/runtime, reset, public sensors, fixed control conversion,
native accounting and cleanup. Previous runs or passing CPU checks do not
certify rendering and control on another machine. Method scores and individual
run evidence belong with the evaluated agent, not this runtime specification.
