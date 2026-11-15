# Shared communication and evaluation tools

`benchkit/` is the evaluator's shared toolkit: SIM communication, data and result
formats, recording, the optional trusted driver, service source snapshots,
audits and reports. It is not a mandatory per-action control process. Native
tasks and scorers live with each benchmark, and model decisions live with each
policy.

Used by both benchmark services and policies:

- `contracts.py` / `interfaces.py`: public observation, action and lifecycle types.
- `errors.py` / `validation.py`: the shared error classes and contract checks.
- `artifacts.py`: atomic writers, no-follow reads and runtime provenance.
- [`sim_server/`](sim_server/README.md): the only shared SIM communication
  implementation, covering transport, serialization and session lifecycle.

Driver side (`driver/`), used by policies, the general CLI and the evaluator
tools that read its records:

- `runner.py`: optional trusted driver; plays each episode through `Policy.act`
  and writes the run records.
- `recording.py`: default-on interaction and client retention preferences.
- `methods.py`: method composition and per-component usage declarations.
- `model_profiles.py`: reads each `AgentPolicies/<profile>/configs/profile.json`
  and validates configuration and factories; the factories stay with the profile.

Evaluator tools:

- `cli.py`: `rsi-bench`, the one command line. The service commands (`list`,
  `serve`, `gateway`, `remote-run`) come from `sim_server/cli.py`. `run` takes
  its benchmark only from a running service (`--sim-server`); `smoke` starts the
  synthetic service and runs through it; `probe` checks one service's
  connect-level readiness.
- `catalog/`: packaged benchmark declarations and their loader/validator.
- `source_snapshot.py`: bounded service source capture, limited to
  `SERVICE_SOURCE_FILES` plus benchmark-declared supplemental files.
- [`diagnostics/`](diagnostics/README.md): synthetic and fixed-action
  infrastructure fixtures, not participant models or task-solving baselines.
- `audits/`: offline record-consistency validation (`closed_run.py`), not source
  verification, native replay or provider attestation.
- [`reports/`](reports/README.md): run summaries, panel SR comparison,
  interaction views and named-model publication.

Native adapters and selection plans live under
[`benchmarks/simBenchmarks`](../benchmarks/simBenchmarks/README.md). Policies
and their results live under [`AgentPolicies`](../AgentPolicies/README.md).

```sh
python -m benchkit catalog --check
python -m benchkit policies
```

`python -m benchkit` is the same command as `rsi-bench`. `policies` shows the
diagnostic policies; `list` and `catalog` show the benchmarks. `make check` validates current catalog data, and `make smoke` runs
the dependency-free self-check through the synthetic service. Neither replaces
native simulator, model or hardware validation. Test and check files stay local
and untracked.
