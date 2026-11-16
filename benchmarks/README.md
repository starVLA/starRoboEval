# Benchmark integrations

This directory contains the benchmark services used by
[starRoboEval](../README.md). Each integration owns its task environment, robot
interface, native execution and scoring.

## Simulation benchmarks

The [simulation benchmark directory](simBenchmarks/README.md) includes
**14 service integrations** covering manipulation, household tasks, whole-body
control and navigation. Each benchmark guide describes its native setup and
service usage; the [service support table](simBenchmarks/SERVICE_SUPPORT.md)
lists available task selections and deployment requirements.

Use `rsi-bench list` to inspect the integrations and
`rsi-bench serve --benchmark <id> ...` to launch a selected service.
Real-robot services are a planned extension.

## Integration structure

```text
simBenchmarks/<Benchmark>/
├── README.md                  # Setup, task scope and service usage
├── EVALUATION_PROTOCOL.md     # Observations, actions, sampling and native scoring
├── server.py                 # Service entrypoint
├── server.example.json       # Deployment configuration, where provided
├── bench_server/             # Service adapter and benchmark-specific contracts
└── environment/              # Native runtime, assets and installation
```

Protocol packages and separate native workers are added where the integration
needs them. Each benchmark retains its own sensors, action semantics, execution
budgets and native evaluator.

Agent implementations and their results belong in
[`AgentPolicies/`](../AgentPolicies/README.md). Shared service transport,
execution utilities and report tools live in [`benchkit/`](../benchkit/README.md).

To add a benchmark, follow the
[integration guide](../docs/benchmark-server-guide.md) and
[service conventions](simBenchmarks/SERVICE_CONVENTIONS.md).
To connect an agent to an existing service, follow the
[agent integration guide](../docs/agent-methods.md#add-your-policy).
