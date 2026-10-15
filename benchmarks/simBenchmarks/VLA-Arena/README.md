# VLA-Arena

A benchmark-owned, independent SIM server for RGB-to-physical-action evaluation.
The pinned upstream release contains **170 non-LIBERO tasks** across four domains,
11 suites and three difficulty levels. This first executable integration accepts
explicit **L0 fast** selections: one attempt per selected task, native first
initial state, no reset retry. It does not implement or claim native full scores.

The standalone service has passed a bounded **no-model native diagnostic**:
one reset, ten fixed setup controls, two fixed diagnostic controls, both RGB
streams and videos, and clean shutdown. This verifies the service/control/media
path for the selected L0 example, not task coverage or model capability. Its
incomplete task and partial cost are not a model failure score.

- [Evaluation protocol and task matrix](EVALUATION_PROTOCOL.md)
- [Native setup and read-only preflight](environment/README.md)
- [Exact task names, instructions and initialization pins](bench_server/protocol/task_catalog.json)
- [Server parameters](server.example.json) and [entrypoint](server.py)

## Directory responsibilities

`server.py` is the public factory/launch entrypoint; `bench_server/adapter.py`
owns the sensor/action/scoring bridge. `bench_server/protocol/task_catalog.json`
is immutable benchmark data, not a deployment configuration. `environment/`
owns native setup, runtime verification and source pins, including
`native_source_pin.json`. There is no root adapter compatibility shim. This organization preserves the existing
protocol, task schedule, action semantics and native scorer.

The actor receives only the current instruction and two RGB cameras, and returns
seven native normalized OSC/Panda-gripper controls. Native state, object poses,
task predicates, success and cost remain evaluator-private. No learned policy,
API client, task planner or expert fallback runs in this benchmark package.

Primary success means **native task success**. Cost and safety-qualified success
are separate metrics; unsafe success is not silently relabelled or combined with
another track's success rate. Failures and incomplete costs remain visible.

Connect through the common [SIM-server interface](../SERVER_PROTOCOL.md). Keep agent
configuration, transcripts, results and videos under `AgentPolicies/<agent>/`;
infrastructure-only checks belong under `benchkit/diagnostics/`. Retired StarVLA
integration code remains in Git history, not an import or launch dependency of
this service.
