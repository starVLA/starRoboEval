# Simulation benchmark catalog

This directory contains the original 13 embodied-agent evaluation targets plus
SIMPLE humanoid control. It is evaluation-only: training recipes and dataset registries do
not belong here.

New integrations follow the [RoboDojo-derived service conventions](SERVICE_CONVENTIONS.md):
one responsibility layout, common transport and acceptance sequence, with
benchmark-native actions, observations and scoring kept distinct.

Every benchmark directory owns its native side of the interface:

- `EVALUATION_PROTOCOL.md` is the agent-readable, versioned contract. It states
  what is verified, what remains unknown, and what must be recorded.
- environment/adapter material is isolated from historical model launchers;
  retired launchers stay in Git history or the local ignored `barks/` archive
  and are never loaded by the evaluation runtime.
- The adapter maps declared observations/actions and delegates native scoring;
  `environment/` owns native workers and benchmark-specific asset/runtime tools.
- All implemented services group adapters and any private worker client in
  `bench_server/`, with separate task catalogs/definitions in `bench_server/protocol/`
  where needed. A catalog defines
  the benchmark's fixed cases, seeds and horizons; deployment configuration
  selects a named panel and supplies operator runtime paths. See its
  [directory guide](RoboDojo/README.md#directory-responsibilities).
- `server.py` independently serves the native adapter in implemented benchmarks.
  The evaluator connects through the shared client, never by giving the model
  a simulator handle. See [server lifecycle and transport](SERVER_PROTOCOL.md).
- `bench_server/protocol/plan.py`, where implemented, owns frozen campaign selection.
  SimplerEnv, LIBERO, SIMPLE and both RoboCasa integrations supply plans there.
  None of the implemented services retains root adapter shims or old `evaluation/`
  entrypoints. DOMINO and BEHAVIOR 2026 have bounded development services;
  native validation remains a separate gate. VLN-CE remains deferred pending
  authorized navigation assets.
  Standalone servers may first support explicit fast selections without claiming
  campaign or native-full support. RoboDojo's catalog provides `fast` (five
  layouts) and `full` (50 layouts) for `classify_objects`, each once. Full
  support for other tasks and benchmarks must be verified separately.

Shared record and report tools live in [`benchkit/`](../../benchkit/README.md), while model
behavior and results live under [`AgentPolicies/`](../../AgentPolicies/README.md). Benchmark
code must not select a model's actions, inject task-solving hints or impose that
model's voluntary-stop preferences as native rules.

The simulator-facing implementation guide is [INTERFACE.md](INTERFACE.md), and
the shared policy contract is [POLICY_PROTOCOL.md](POLICY_PROTOCOL.md). The
service rollout and remaining native gates are in [SERVICE_SUPPORT.md](SERVICE_SUPPORT.md).
The machine-readable list and migration status live in
[`benchkit/catalog/benchmarks.json`](../../benchkit/catalog/benchmarks.json).

`protocol_draft` does not mean the benchmark is runnable through
`starvla-eval run`; it means the native integration is catalogued and the
remaining parity work is explicit. A development adapter also does not establish
native-full parity or an independently verified model score.
