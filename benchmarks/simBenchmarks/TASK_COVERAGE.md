# Task plans and coverage

Task selection is benchmark-owned; attempt accounting is shared. See the
[execution guide](../../docs/evaluation.md) for prepare, run-case and summarize.

## Fast and full

A fast plan preselects a task/state subset with one attempt per selected task.
Failure does not trigger a retry or replacement sample. The current campaign
implementation explicitly records `evaluation_mode: fast`.

Full means the declared native suite's tasks, variations, initial states, seeds
and episodes per task, with matching execution and aggregation rules. Native
scheduled repetitions are not success-seeking retries. Full presets and a
unified mode selector remain unimplemented; never infer full coverage from a
task-only list or fabricate an episode count.

## Where the schedule lives

Each integrated benchmark owns `evaluation/plan.py` beside its protocol.
Plans enumerate cases, declare task scopes and bind required runtime resources.
The common `benchkit.campaigns` prepares an immutable manifest and source package.

Current plans differ deliberately: SimplerEnv enumerates its 15 canonical
development subtasks; LIBERO enumerates 130 suite-task entries, which are not
130 distinct task definitions. Other adapters expose fixed subsets and, where
implemented, explicit expansions such as RoboCasa365 `target50` or SIMPLE
`released-12`. Inspect the selected benchmark's protocol and generated cases.
Do not confuse an adapter's standalone default selection with its campaign plan.

## Immutable attempts

A case binds task identity, selected initial state, seed, protocol, public budgets
and policy configuration. Preparation is not an attempt. Execution creates a
permanent claim before starting the native process; a failed or timed-out claim
remains part of the record and is not silently reused.

Carry-forward is only available for explicitly supported coverage expansions.
It preserves the original attempt and identity rather than evaluating that case
again. A new source package is not permission to repeat a completed task.

## Coverage report

Always state:

- declared schedule and selected denominator;
- attempted, completed, unattempted and running counts;
- native successes and failures among protocol-completed episodes;
- policy, protocol and infrastructure errors separately;
- missing artifacts, source-verification failures and accounting limitations.

Frozen manifests, environment diagnostics and unclaimed cases are not completed
capability evaluations. Keep both completed-episode and all-attempt success
rates. Do not merge incompatible policy versions, budgets, asset tracks or
native conditions into a homogeneous score.

Generic report tools are under `benchkit/reports/`: `coverage.py`,
`task_ledger.py` and `progress.py`. Use each tool's `--help` for its supported
input schemas. A report must use the source/schema matching the recorded run;
old frozen evidence is not rewritten to satisfy a newer reporter.

Maintain each model's task ledger, reports and indices in
`AgentPolicies/<profile>/results/<benchmark>/`. Raw runs and generated media are
Git-ignored. Internal scheduling diaries are not benchmark specifications.

## Protocol changes

Changes to cameras, controllers, horizons or success definitions require a
separate, explicit benchmark track. Changes to planning, prompts or voluntary
give-up rules require a new policy configuration. Freeze both prospectively.

The model can use only its declared observations. Operators must not reveal
private reset state, scoring information or another case's outcome through
endpoint names, actor labels or launch context. Unknown provider usage and
unenforced isolation remain disclosed limitations, not inferred guarantees.
