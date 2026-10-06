# Benchmark service conventions

RoboDojo is the reference for **service organization and acceptance**, not a
universal robot controller. New integrations extend that validated design rather
than introduce a separate model/simulator workflow. All implemented
services use this layout; draft integrations are listed in [SERVICE_SUPPORT.md](SERVICE_SUPPORT.md).

## Stable responsibilities

```text
benchmarks/simBenchmarks/<benchmark>/
├── README.md                  # preparation, service launch, supported scope
├── EVALUATION_PROTOCOL.md     # native semantics, tracks, scores and limits
├── server.py                  # import-safe factory + main(argv=None)
├── server.example.json        # explicit operator paths and selected track
├── bench_server/
│   ├── adapter.py             # declared observation/action and native bridge
│   ├── protocol/              # dependency-light catalogs and interface rules
│   └── native_worker_client.py  # only when a private worker is needed
├── environment/               # native workers, setup, pins and readiness
└── checks/                    # benchmark-specific conformance regressions

AgentPolicies/<agent>/                # model-owned decisions, prompts, config, results
benchkit/sim_server/             # shared communication and session mechanics
benchkit/                       # also records, source capture, audits, reports
```

Use the existing transport under `benchkit/sim_server/`. The model
actor receives only the declared observation and execution feedback. The trusted
driver holds service credentials and administrative/result methods; it must not
give these capabilities to the model. Only benchmark-owned code touches the SIM.
The service must not import a model implementation or legacy campaign entrypoint.

Register implemented services in `benchkit/sim_server/cli.py`: `rsi-bench list`
and `rsi-bench serve --benchmark <id> ...` delegate to the existing wrapper.
Do not construct a second factory path that bypasses its source inventory,
cache exclusions or complete-schedule rules. Availability is not native readiness.
Public reports identify the complete method and its outcomes; optional histories
show recorded inputs, outputs, actions and acknowledged feedback. Recording is
default on, not a participation/publication gate. Hash/source checks remain internal support;
recorded upstream/environment/asset provenance can support reproducibility.

An in-process native adapter inside the service is permitted; a second worker
process is needed only for runtime isolation. Do not add empty layers or duplicate
servers merely to make file lists identical. Migrated integrations use only
`bench_server/adapter.py` and, when needed, `bench_server/protocol/plan.py`.
Do not retain old root adapter shims or duplicate `evaluation/` packages solely
for compatibility. Update current callers, packaging and source inventories
together; frozen historical packages retain their own original sources.

## Invariants shared with RoboDojo

1. `server.main(argv=None)` supplies its benchmark factory and declared source
   inventory to the common launcher. Import, construction and `describe` must not
   reset an environment, call a model or move a robot.
2. Configuration is validated before native initialization. Select only supported
   tracks/tasks; freeze the resolved schedule and budgets before the first claim.
   Deployment paths are operator inputs, not unreviewed protocol overrides.
3. Each selected case is claimed once, including failed initialization. No hidden
   retries, reset search, branch rollouts or replay after an uncertain control ACK.
4. The declared public observation is an allowlist. Robot state is permitted when
   specified; object truth, reset metadata, native scoring and private logs stay
   evaluator-side. Models select actions; fixed low-level execution never solves
   the task on their behalf.
5. Record calls, executed action decisions and native controls separately. Invalid
   actions never execute. Declare feedback versus fail-fast behavior per versioned
   track; uncertainty about native execution remains terminal.
6. Native scoring remains authoritative. Keep task failures, policy stops and
   infrastructure errors distinct; preserve all attempts and unknown accounting.
7. Source inventories include the service, protocol and required worker code.
   Shared service capture is scoped separately from campaign/agent capture;
   declare the selected benchmark's complete supplemental inventory without
   relying on another benchmark or model file being incidentally captured.
   Paired client/server records, native outcomes and media belong under the model's
   results namespace. Only closed artifacts are exported and audited.

These are responsibility and protocol boundaries, not an OS sandbox or provider
identity attestation. Apply deployment isolation separately.

## Differences that must remain benchmark-owned

| Aspect | Common rule | Do not copy blindly from RoboDojo |
| --- | --- | --- |
| Observation/action | Declared, versioned, validated | EEF16, three cameras, robot ACK payload |
| Native runtime | Service-owned and lazily initialized | Isaac Sim, worker topology, fixed IK |
| Schedule | Frozen selected cases, each once | Five-layout fast / 50-layout full panels |
| Budget | Explicit units and resolved caps | 1100 controls, number of ticks per control |
| Scoring | Native rule, never model self-report | Dojo's success conjunction or 0–100 score |
| Rejection | Never execute invalid input | A track's feedback/fail-fast selection |

Dojo requires its complete named panel. Other services currently allow an explicit
fast subset fixed at startup; this is not native-full support. Do not enable
`require_complete_schedule` without defining the benchmark's complete schedule.
SimplerEnv retains final-step scoring and separately selected rejection feedback;
LIBERO retains its selected task/init-state contract; SIMPLE retains its native
36-value robot/controller commands. No cleanup silently changes these conditions.

For future real-robot backends, reuse these declared capability boundaries, not
the simulator's paused-time/reset assumptions. Hardware adapters require their
own timing, watchdog, safety, calibration and scoring validation. See
[real-robot status](../realRobots/README.md).

## One acceptance sequence for every integration

| Gate | Required evidence | Does not establish |
| --- | --- | --- |
| Source/contract review | Native evaluator pins, task inventory, sensor/action/scorer mapping | A working environment |
| Offline regression | Import-safe entrypoint; no-reset startup; captured source; shared lifecycle/error tests plus native contract fixtures | Rendering or task success |
| Native readiness | Separate authorized no-model check of reset, RGB, one valid control and cleanup through the service | Model capability |
| Model sample | Preselected task/case once through the same server, with score, counts, errors and declared optional recording | Whole-suite SR or native-full parity |
| Expansion | Independent review, fixes, regression; then predeclare broader coverage | Permission to silently retry failures |

The cross-benchmark entrypoint regression is
[`benchkit/sim_server/checks/test_benchmark_conventions.py`](../../benchkit/sim_server/checks/test_benchmark_conventions.py); benchmark-specific tests and the
shared service tests remain required. Model samples must be separately authorized;
structural refactoring and offline tests do not start one. A valid completed
failure is useful acceptance evidence, not a reason to rewrite the scorer.

See [the wire protocol](SERVER_PROTOCOL.md) and [support matrix](SERVICE_SUPPORT.md)
for current implementation limits. A passing conformance test is not a claim that
all native, sensor, provider or full-schedule gates have passed.
