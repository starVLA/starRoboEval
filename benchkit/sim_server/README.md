# Shared benchmark service

This package implements the [SIM server protocol](../../benchmarks/simBenchmarks/SERVER_PROTOCOL.md).
New integrations follow the [RoboDojo-derived conventions](../../benchmarks/simBenchmarks/SERVICE_CONVENTIONS.md).
Each benchmark's `server.py` selects its native adapter; these shared modules
provide strict JSON transport, single-attempt sessions and artifact transfer.
They do not generate actions, call a model or run a separate scheduling service.

- `server.py` owns the administrative RPC lifecycle and serialized native calls.
- `wire.py` serializes the declared observations and evaluator-private transitions.
- `launch.py` supplies common launch mechanics to benchmark-owned entrypoints.
- `client.py` is an **administrative client for a trusted run driver**, not a
  model-facing tool. It can read schedules, deployment information, native
  metrics and finalized artifacts. Never give it, its endpoint or its bearer
  credential to the model actor.

An agent-owned trusted driver may use this client and pass only the declared
observation to its model. Returning an action does not give the model native
simulator access. The model owns target selection, memory and voluntary stopping;
the benchmark owns native control conversion, termination and scoring. Results
and videos belong under `AgentPolicies/<profile>/results/<benchmark>/`.

Reward and transition information are evaluator-private, not policy inputs.
The trusted driver may obtain cached metrics before closing the episode;
artifact downloads require finalized, closed-file inventory. Idle service time
does not step physics, lost acknowledgements do not replay controls, and a
failed attempt is not automatically replaced.

This is an ownership/protocol boundary, not OS-enforced isolation. A trusted
driver's administrative permissions are not safe capabilities for an untrusted
actor. If the actor itself must access a service, an independently reviewed
episode-scoped public control interface is required; this client does not
implement that interface. The selected Codex integration filters its model
request and child environment, but does not claim hard filesystem isolation.

## Ownership and source capture

`benchkit/sim_server/` is the sole implementation, not an import alias. Reusable
communication belongs here; task catalogs, native adapters and scoring belong
under `benchmarks/simBenchmarks/<benchmark>/`; decisions belong under `AgentPolicies/`.
This is a library used by the two control ends, not a third scheduling process.
The temporary `benchmarks/simBenchmarks/service/` package is removed, without
changing RPC version, fields, schedules, scoring, actions or artifact limits.
Old frozen campaigns and source bundles retain their original bytes and
verification rules. Generic contracts remain in `benchkit/contracts.py` and
`benchkit/interfaces.py`.

`python -B -m benchkit.sim_server` starts only the dependency-free synthetic
diagnostic service. It is not a native robot benchmark or capability evidence.
For a native benchmark, use its own
`benchmarks.simBenchmarks.<benchmark>.server` entrypoint.

New service snapshots capture the explicit shared-service runtime inventory and
the selected wrapper's supplemental files. Starting one service does not require
other benchmarks or model drivers. The agent/campaign evaluation snapshot remains
broader and separate; existing frozen inventories are unchanged.
Run only from a stable versioned source snapshot;
never update files inside an active or historical frozen run.

The standard CPU runner includes this package's cross-benchmark acceptance tests
as the `benchmark_service` group:

```sh
python -B -m benchkit.checks.run_regressions --group benchmark_service \
  --output /absolute/new-regression-report
```

These checks prohibit native initialization/model calls. They do not replace
the benchmark's own contract tests or native readiness and model-sample gates.
