# DOMINO benchmark server

DOMINO measures manipulation of moving objects. This integration exposes one
fixed-manifest `click_bell` case through the shared bench-server interface.
Native dynamic control and SR/MS scoring stay server-side; agents receive RGB
and honestly labeled commanded robot targets and submit direct joint targets.

The bounded interface is implemented and offline-tested. Native fixed-manifest
preparation, rendering and closed service validation remain acceptance gates.
This is **not yet a successful SIM run or full-suite support claim**.

- [Protocol, observations/actions and 400-target horizon](EVALUATION_PROTOCOL.md)
- [Owned deployment and readiness](environment/README.md)
- [Operator configuration](server.example.json)
- [Shared wire protocol](../SERVER_PROTOCOL.md)

## Responsibilities

`server.py` is the public entrypoint. `bench_server/adapter.py` owns the public
allowlist and lifecycle; `bench_server/protocol/` fixes semantics. `environment/`
owns private runtime, deployment and native-scoring-order helpers. `checks/`
contains offline regressions, not model policy. No root adapter, training script
or task-solving service is retained.

## Launch a prepared deployment

Use an operator configuration with verified deployment and manifest SHA256s.
Replace both all-zero example digests with real verified hashes; the placeholders
permit description only and cannot pass native readiness.
The manifest is a trusted local administrative artifact: never load untrusted
pickle or accept a policy-provided manifest upload. Supply the bearer token to
the trusted service/evaluator only, outside JSON and model context.

```sh
PYTHONDONTWRITEBYTECODE=1 python -B -m benchmarks.simBenchmarks.DOMINO.server \
  --parameters /absolute/domino-parameters.json \
  --seed 20260921 --episodes 1 --port 8765 \
  --output-dir /absolute/new-domino-run/server
```

Use the declared compatibility runtime and verified renderer overlay on
`PYTHONPATH`; installing RSI does not install the SIM. Import, construction and
describe do not reset or actuate. Each selected case is claimed once; the
service performs no online expert screening or automatic retries.

```sh
python -B -m unittest discover -s benchmarks/simBenchmarks/DOMINO/checks -v
```

Checks cover sensor filtering, commanded-state provenance, validity, claims and
mocked native post-action scoring order. They do not replace native validation.
