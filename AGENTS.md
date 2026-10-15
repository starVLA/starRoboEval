# StarVLA-RSI agent instructions

This repository evaluates complete agent methods, not only bare model names,
and is not a model-training repository. Participants may compose multiple
general-purpose models and own their planning, memory, tools and decision loop.
Direct control limits environment permissions and robot execution interfaces,
not internal reasoning. Protocol-first integration is primary; Python Policy and
the reference loop are optional. Keep method/model roles and configuration
explicit; report measured usage without inventing missing attribution.

Preserve native benchmark execution budgets. Existing method/track safety caps
remain declared, not universal limits on inference. Interaction/media recording
is optional, default enabled, and never a publication prerequisite. Essential
results, denominators, counters, configuration and errors survive minimal mode.
Retention options must not change actor inputs, controls, lifecycle or scoring;
runtime scratch inputs live until episode closure. Internal hashes/source audits
remain support tools, separate from public result eligibility.

Action chunk length, repeated controls per decision and replan timing belong to
the policy method and its trusted driver, not a universal server-side prefix.
The current service accepts one action per sequenced `step`; the driver may send
successive controls from one decision, subject to action validity, native control,
termination and the declared total execution budget. Native physics substeps and
protocol-fixed interpolation are not policy-adjustable repeats. Legacy
decision-budget tracks still couple call/prefix settings to execution caps, and
some interfaces declare `required_replan_interval`; preserve those contracts
until an explicit migration. Do not claim all existing tracks are decoupled.

The product scope is direct control by general-purpose models across many
benchmarks. Do not add VLA-assisted/hybrid control, learned action proposals,
fallback task policies, or automatic task-solving skill services. The model
must select the actions through the declared observation-to-decision interface.
Only pinned native low-level control and protocol-fixed action conversion may
execute them; they must not plan the task for the model. External reports are
design references, not permission to expand observations or control capabilities.

Use a multi-agent implementation -> independent review -> regression validation
-> correction loop for framework changes. Assign non-overlapping implementation
files, review cross-layer effects independently, and test a stable source snapshot
before applying changes to the evaluation checkout. A passing unit test is not
evidence of native evaluation, provider attestation or complete benchmark parity.

Before changing evaluation code or protocols:

1. Read `docs/architecture.md` and `docs/evaluation.md`. Internal
   `project_readmes/` notes, if present, are local context, not required public docs.
2. Read the target benchmark's `EVALUATION_PROTOCOL.md` and its native evaluator.
3. Treat the pinned upstream evaluator as the source of truth. Do not guess action
   semantics, success criteria, episode counts, seeds, or observation layouts.
4. Record verified evidence separately from migration TODOs.

New benchmark integrations must use the contracts under `benchkit/`,
delegate task success to the native benchmark, and add a dependency-light test.
Training recipes and dataset registries do not belong under
`benchmarks/simBenchmarks`.

Evaluation artifacts must identify the benchmark and protocol versions, policy
and model, seed and episode, action contract, source revision, token/cost/latency
usage when available, and all errors. Infrastructure errors must not be silently
counted as policy failures.

The primary control architecture has two ends, not a mandatory harness middle
layer. Model-specific trusted evaluation entrypoints belong under
`AgentPolicies/<profile>/`. The reusable `runner.py` and `stop_rules.py` live
under `AgentPolicies/gpt6_astra/tools/`; the general CLI and anonymous mailbox
workflow reuse them. Old paths do not retain forwarding modules.
Benchmark adapters, native runtime/asset helpers,
task inventories and evaluation plans belong beside their protocols under
`benchmarks/simBenchmarks/<benchmark>/` (future hardware adapters under
`benchmarks/realRobots/`); shared SIM transport lives in
`benchkit/sim_server/`, which owns reusable communication and lifecycle mechanics,
not model decisions or native task semantics. `benchkit/` also supplies result/data
formats, recording, source capture, audits and reporting tools. Fixed-plan
assembly belongs in `benchkit/campaigns`, report import/coverage tools in
`benchkit/reports`, and benchmark metadata in `benchkit/catalog`. Relocated modules
do not keep old-entrypoint forwarding shells. Import the optional runner directly
from `AgentPolicies.gpt6_astra.tools.runner`. Do not rewrite frozen old packages.
Benchmark code owns task selection and native success; the model owns decisions.
Central task scheduling is retained in this version: coordinating fixed plans,
case claims, launches and progress is distinct from making robot decisions.
Current campaign commands use their frozen local execution path; do not describe
them as remote-service orchestration or distributed recovery. Preserve the
single-attempt and uncertain-ACK/no-replay rules when extending scheduling.
Plugin discovery, a comprehensive unified CLI and cross-benchmark leaderboards
are long-term goals, not requirements to build in every cleanup iteration.
An explicitly reviewed trusted agent driver may hold the administrative SIM
client for fixed claims and result collection. The model actor must receive
only declared observations/counters, never that client, its credentials or
management/scoring methods. An administrative client is not actor-safe merely
because its file moved to another directory. No native simulator imports in
model drivers or policies.
Shared fixed-action infrastructure fixtures belong under `benchkit/diagnostics/`,
not `AgentPolicies/`. They may implement `Policy` only for explicit non-capability
diagnostics; no model inference or task-solving strategy belongs there.
Benchmark-specific native readiness tools remain under its `environment/`.

Model-specific policy code/configuration and evaluation results belong under
`AgentPolicies/<model-profile>/`; reusable execution and stop-rule utilities
belong under `AgentPolicies/gpt6_astra/tools/`, with preferences declared by each
profile. New reports, coverage lists and videos use the model's
`results/<benchmark>/` namespace. Historical anonymous trials must not be renamed
as verified named-model scores. Preserve frozen original campaigns and result
bytes; relocation indexes and byte-checked presentation copies are allowed.

User-facing rollout export directory names must include the canonical task ID
and a short English task description, in addition to date/round/case identifiers.
Do not use only names such as `2026-09-07-round2-case000`. For example:
`2026-09-07-stack_bowls-bowl-stacking-round2-case000/video_cam_head.mp4`.
Keep camera identity in video filenames. New video exports go under the model's
result namespace, not examples; old examples paths may retain compatibility links.
Separate reset-only and no-policy
diagnostic exports under `rollouts/archive/` and label their purpose. Never
rename frozen campaign identities or overwrite original results to tidy exports;
record relocations in the rollout README and preserve original artifact bytes.

Local commits are allowed. Never run `git push` or otherwise change remote Git
state.

Persistence and voluntary give-up rules are policy behavior, not benchmark
rules. A policy may explicitly configure a minimum number of executed action
decisions in its own versioned configuration/prompt; the shared harness only
records execution feedback and enforces declared public hard limits. Never
silently turn one model's persistence setting into a requirement on all models.
Native success/termination, exhausted limits, errors and explicit safety stops
must not be delayed to meet a policy's persistence target. Historical runs retain
their original frozen implementation and results; an old policy rule neither
changes benchmark definitions nor authorizes another attempt.

`fast` means a preselected subset with one attempt per selected task. `full`
means the native protocol's declared task/variant/seed/episode schedule, not
success-seeking retries. Both retain failures and errors. Full presets are not
yet implemented for all benchmarks: never label task-only coverage as native
full evaluation or guess its episode count. Refactoring never starts an evaluation.
