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
runtime scratch inputs live until episode closure. Runs record the git revision,
dirty flag, model profile and effective configuration; the closed-run audit checks
record consistency, separate from public result eligibility.

Action chunk length, repeated controls per decision and replan timing belong to
the policy method and its trusted driver, not a universal server-side prefix.
The current service accepts one action per sequenced `step`; the driver may send
successive controls from one decision, subject to action validity, native control,
termination and the declared total execution budget. Native physics substeps and
protocol-fixed interpolation are not policy-adjustable repeats. Decision-budget
tracks couple call/prefix settings to execution caps.
Current SIMPLE defaults to task-horizon mode; CALVIN and DOMINO no longer
declare a mandatory prefix. The reference agent discards a remaining chunk
after an ACK changes the public instruction, with an explicit record marker.
A service may still declare `required_replan_interval` (Behavior does by
default), and shared tooling honours it. Do not claim every selectable track is
decoupled, or use hidden subtask state to trigger agent replanning.

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
`AgentPolicies/<profile>/`. The reusable `runner.py` lives under
`AgentPolicies/gpt6_astra/tools/`; the general CLI reuses it. Old paths do not
retain forwarding modules.
Benchmark adapters, native runtime/asset helpers,
task inventories and evaluation plans belong beside their protocols under
`benchmarks/simBenchmarks/<benchmark>/`; shared SIM transport lives in
`benchkit/sim_server/`, which owns reusable communication and lifecycle mechanics,
not model decisions or native task semantics. `benchkit/` also supplies result/data
formats, recording, service source capture, audits and reporting tools. Report
tools belong in `benchkit/reports` and benchmark metadata in `benchkit/catalog`.
Import the optional runner directly from `AgentPolicies.gpt6_astra.tools.runner`.
Benchmark code owns task selection and native success; the model owns decisions.
Preserve the uncertain-ACK/no-replay rule when extending scheduling.
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
`AgentPolicies/<model-profile>/`; reusable execution utilities belong under
`AgentPolicies/gpt6_astra/tools/`, with preferences declared by each profile.
New reports, coverage lists and videos use the model's `results/<benchmark>/`
namespace. Historical anonymous trials remain data, not verified named-model
scores. Preserve original run records and result bytes; relocation indexes and
byte-checked presentation copies are allowed.
Keep all method `results/` directories local and Git-ignored, including reports,
indices and result READMEs. Publish selected summaries in documentation or the
website without changing the underlying records.

User-facing rollout export directory names must include the canonical task ID
and a short English task description, in addition to date/round/case identifiers.
Do not use only names such as `2026-09-07-round2-case000`. For example:
`2026-09-07-stack_bowls-bowl-stacking-round2-case000/video_cam_head.mp4`.
Keep camera identity in video filenames. New video exports go under the model's
result namespace.
Separate reset-only and no-policy
diagnostic exports under `rollouts/archive/` and label their purpose. Never
rename original run identities or overwrite original results to tidy exports;
record relocations in the rollout README and preserve original artifact bytes.

Live code supports only the current formats, schema versions, CLI spellings and
benchmark IDs. Drop compatibility aliases, forwarding modules and branches for
earlier versions instead of extending them. Older records are kept as data; live
code need not read them, and removing support never rewrites or deletes them.

Local commits are allowed. Never run `git push` or otherwise change remote Git
state.

Persistence and voluntary give-up rules are policy behavior, not benchmark
rules. A policy declares any persistence preference in its own versioned
configuration/prompt; the shared harness only records execution feedback and
enforces declared public hard limits. Never silently turn one model's
persistence setting into a requirement on all models. Native success/termination,
exhausted limits, errors and explicit safety stops must not be delayed to meet a
policy's persistence target. Historical runs keep their original results; an old
policy rule neither changes benchmark definitions nor authorizes another attempt.

Describe evaluation selections by native task, layout/initial state, variation,
seed and attempts rather than product tiers. Existing machine keys such as
`fast`/`full` do not certify native protocol equivalence: preserve their current
meaning until an explicit selector migration. Never label task-only coverage
as a complete native evaluation or infer episode counts. Refactoring never
starts an evaluation or authorizes success-seeking retries.
