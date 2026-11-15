# Benchmark service conventions

RoboDojo is the reference for **service organization and acceptance**, not a
universal robot controller. New integrations extend that validated design rather
than introduce a separate model/simulator workflow. All implemented
services use this layout; draft integrations are listed in [SERVICE_SUPPORT.md](SERVICE_SUPPORT.md).

## Stable responsibilities

```text
benchmarks/simBenchmarks/<benchmark>/
├── README.md                  # preparation, service launch, supported scope
├── EVALUATION_PROTOCOL.md     # tasks, cases, sensors/actions, budgets and scoring
├── server.py                  # import-safe factory + main(argv=None)
├── server.example.json        # operator paths and task/interface selection
├── bench_server/
│   ├── adapter.py             # declared observation/action and native bridge
│   ├── protocol/              # dependency-light catalogs and interface rules
│   └── native_worker_client.py  # only when a private worker is needed
└── environment/               # native workers, setup, pins and readiness

AgentPolicies/<agent>/                # model-owned decisions, prompts, config, results
benchkit/sim_server/             # shared communication and session mechanics
benchkit/                       # also records, source capture, audits, reports
```

Use the existing transport under `benchkit/sim_server/`. The model
actor receives only the declared observation and execution feedback. The trusted
driver holds service credentials and administrative/result methods; it must not
give these capabilities to the model. Only benchmark-owned code touches the SIM.
The service must not import a model implementation.

Register implemented services in `benchkit/sim_server/cli.py`: `rsi-bench list`
and `rsi-bench serve --benchmark <id> ...` delegate to the existing wrapper.
Do not construct a second factory path that bypasses its source inventory,
cache exclusions or complete-schedule rules. Availability is not native readiness.
Public reports identify the complete method and its outcomes; optional histories
show recorded inputs, outputs, actions and acknowledged feedback. Recording is
default on, not a participation/publication gate. Service source snapshots remain internal support;
recorded upstream/environment/asset provenance can support reproducibility.

A native adapter running inside the service process is permitted; a second worker
process is needed only for runtime isolation. Do not add empty layers or duplicate
servers merely to make file lists identical. Migrated integrations use only
`bench_server/adapter.py` and, when needed, protocol data under `bench_server/protocol/`.
Do not retain old root adapter shims or duplicate `evaluation/` packages solely
for compatibility. Update current callers, packaging and source inventories
together; historical records keep their original sources as data.

## Public documentation contract

Write benchmark documentation for any compatible agent, not for a particular
model or evaluation run. Use this division consistently:

- `README.md`: introduce what the benchmark measures and its native task,
  scene and variation organization first; then explain environment prerequisites
  and service use. Keep current integration constraints in a separate section.
- `EVALUATION_PROTOCOL.md`: pinned native sources, exact selection rules,
  observations/actions, units, native budgets, termination and scoring. Mark
  deviations from the native evaluator and unknowns explicitly.
- `environment/README.md` and technical protocol notes: installation, asset
  authorization, runtime pins, interface details and readiness checks.
- `AgentPolicies/<agent>/`: client commands, prompts, planning/memory choices,
  optional guards, inference settings, results and method-specific limitations.

Introduce the native benchmark separately from this checkout's supported scope.
Task counts, cases per task and evaluation repeats are different quantities.
The public overview describes the benchmark's own task universe, not the number
of cases that this project has evaluated or currently wired into an adapter.
Use [SERVICE_SUPPORT.md](SERVICE_SUPPORT.md) for implementation availability.
Evaluation progress, observed scores, run counts and engineering diaries belong
in internal `project_readmes/` notes; they must not define a benchmark's scope.
Do not link ignored internal notes as prerequisites for public users.
Link implementation and source evidence for exact claims. Describe selection by
task, layout/initial state, variation, seed and attempts, not evaluation-tier labels.
Do not infer a reset distribution from a task-name list or a successful diagnostic.

A new user's reading path should answer, in order: what can I evaluate; which
tasks and cases can I select; what must I install; what observations and actions
does my agent use; how do I start the service; how is the result scored? Keep
action dimensions, component order, units, coordinate frames, relative/absolute
semantics, gripper conventions and control timing explicit. A dimension alone
does not define an action. Put engineering acceptance and migration notes in
contributor documentation, not the benchmark introduction.

Keep dated run diaries, personal paths, account details and local token ledgers
out of benchmark guides. Native dependency versions and source references belong
here even when a source repository also contains model code: provenance is not
a requirement to use that model. Shared lifecycle rules may be linked rather
than copied into every guide.

If documentation review reveals a code/protocol mismatch, describe the actual
implemented constraint and record the proposed engineering change separately.
Editing prose must not silently redefine a runtime contract or historical result.

## Invariants shared with RoboDojo

1. `server.main(argv=None)` supplies its benchmark factory and declared source
   inventory to the common launcher. Import, construction and `describe` must not
   reset an environment, call a model or move a robot.
2. Configuration is validated before native initialization. Select only supported
   tracks/tasks; freeze the resolved schedule and budgets before the first claim.
   Deployment paths are operator inputs, not unreviewed protocol overrides.
   One `evaluation_mode` key selects the schedule: `fast` (the default when
   omitted) is the documented evaluation subset, `max` is the benchmark's
   official scope, and `example` is one episode, the first of `fast`. Any other
   value is a configuration error, and a guide marks a `max` scope that the
   service rejects as not implemented. Remaining selectors, such as one task per
   service, only narrow the chosen mode. The protocol identity names the mode:
   `<benchmark>-<upstream pin>/<selection>/<observation-action>/<mode>/v1`.
   Step caps are the simulator's native horizons, never an evaluation budget;
   when they differ by task, each episode's metadata carries its own
   `environment_step_cap` and the described budget is the maximum.
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
   The agent side captures no source; declare the selected benchmark's complete supplemental inventory without
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
| Schedule | Fixed selected cases, each once | Dojo's 5-layout `fast` and 50-layout `max` |
| Budget | Explicit units and resolved caps | 1100 controls, number of ticks per control |
| Scoring | Native rule, never model self-report | Dojo's success conjunction or 0–100 score |
| Rejection | Never execute invalid input | A track's feedback/fail-fast selection |

Dojo requires the complete schedule of its selected mode. Other services allow
`--episodes` or `--episode-id` to narrow the schedule fixed at startup. Do not enable
`require_complete_schedule` without defining the benchmark's complete schedule.
SimplerEnv retains final-step scoring and separately selected rejection feedback;
LIBERO retains its selected task/init-state contract; SIMPLE retains its native
36-value robot/controller commands. No cleanup silently changes these conditions.

For future real-robot backends, reuse these declared capability boundaries, not
the simulator's paused-time/reset assumptions. Hardware adapters require their
own timing, watchdog, safety, calibration and scoring validation.

## One acceptance sequence for every integration

| Gate | Required evidence | Does not establish |
| --- | --- | --- |
| Source/contract review | Native evaluator pins, task inventory, sensor/action/scorer mapping | A working environment |
| Offline regression | Import-safe entrypoint; no-reset startup; captured source; local lifecycle/error checks against native contracts | Rendering or task success |
| Native readiness | Separate authorized [readiness probe](SERVER_PROTOCOL.md#readiness-probe) through the service: describe, claim, reset, RGB and cleanup, with no model or action | Control execution or model capability |
| Model sample | Preselected task/case once through the same server, with score, counts, errors and declared optional recording | Scores for tasks or cases not evaluated |
| Expansion | Independent review, fixes, regression; then predeclare broader coverage | Permission to silently retry failures |

Offline validation should cover benchmark entrypoints, observation boundaries,
session lifecycle, execution counters and error handling. These checks stay
local and untracked. Model samples must be separately
authorized; structural refactoring and offline checks do not start one. A valid completed
failure is useful acceptance evidence, not a reason to rewrite the scorer.

See [the wire protocol](SERVER_PROTOCOL.md) and [support matrix](SERVICE_SUPPORT.md)
for current implementation limits. A passing conformance check is not a claim that
all native, sensor, provider or sampling checks have passed.
