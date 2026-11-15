# Benchmark and robot integration entrypoints

`benchmarks/` owns the task world and its public contract, not model training or
policy implementations. Shared record and report tools live in [`benchkit/`](../benchkit/README.md);
model behavior, prompts and results belong under [`AgentPolicies/`](../AgentPolicies/README.md).

| Area | Purpose | Current execution status |
| --- | --- | --- |
| [simBenchmarks](simBenchmarks/README.md) | Native task/environment adapters, setup, inventories, selection plans and scoring contracts | Eleven benchmark families have development services; three remain drafts/deferred |
| Git history and local `barks/` | Retired model-serving, old evaluation-loop and training references | Not part of the public runtime or package |

Within an integrated simulation benchmark, adapters own native I/O and scoring,
and `environment/` owns workers/assets/setup. All eleven implemented services group
adaptation in `bench_server/`; separate task definitions, catalogs and available
selection plans live in `bench_server/protocol/`. Do not create an empty protocol
package where no separate definitions are needed. The top-level `server.py`
remains the public launch entrypoint; old root adapters and `evaluation/`
packages are removed without compatibility shims. Keep benchmark-specific auditing beside the benchmark; generic
record/media auditing lives under `benchkit/`.

Fast development plans attempt each selected case once. Native max schedules
remain separate and must be implemented from verified upstream protocols, not
by automatically retrying failures. Model planning, provider calls and voluntary
give-up rules never belong in the native benchmark adapter.

Retained historical launchers may depend on the original StarVLA training/model
repository and are not runnable merely because their files remain here. Do not
execute a legacy launcher to claim the unified policy boundary was evaluated.
Preserve original run records, results and native reference evidence.
