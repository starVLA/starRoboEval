# Task plans and coverage

Task selection is benchmark-owned; attempt accounting is shared. See the
[execution guide](../../docs/evaluation.md) for prepare, run-case and summarize.

## Tasks, layouts and attempts

Describe an evaluation by its selected cases, not a mode label:

| Quantity | Meaning | Example |
| --- | --- | --- |
| Task / suite | The requested behavior and its benchmark grouping | A LIBERO suite and task index |
| Layout / initial state | A scene arrangement or released reset state | A RoboDojo layout ID; a LIBERO initial-state index |
| Variation | A benchmark-defined change in conditions | LIBERO-Plus viewpoint, instruction or object-layout variation |
| Seed | An input to native random generation | RoboTwin scene generation; it is not an explicit layout ID |
| Attempt | One execution of a selected case | One task/initial-state pair evaluated once |

Predeclare the selected tasks, applicable case identifiers, seeds and repetitions.
Five tasks with five initial states each gives 25 cases. Running one task five
times from the same state gives five attempts, not five different layouts.
Changing a seed can repeat a layout or have no layout effect at all; each
benchmark's protocol documents what its selector actually controls.

Only use selectors supported by the current service; the
[support matrix](SERVICE_SUPPORT.md) distinguishes interface availability from
the benchmark's native task universe. Do not invent an unimplemented sampler
by increasing `--episodes`. Planned repetitions are distinct from additional
attempts selected after seeing a failure.

## Where the schedule lives

Each service selects cases through its catalog or adapter, which enumerates
cases, declares task scopes and binds required runtime resources. There is no
central campaign layer.

Inspect the selected benchmark's protocol and the service's declared cases. A plan's task
list, an adapter's default selection and the native benchmark inventory are
different things. Neither a preselected sample nor a record of completed runs
defines the benchmark's task count.

## Immutable attempts

A case binds task identity, selected initial state, seed, protocol, public budgets
and policy configuration. Preparation is not an attempt. Execution creates a
permanent claim before starting the native process; a failed or timed-out claim
remains part of the record and is not silently reused.

A coverage expansion is an independent run: every selected task is a new
case, and no earlier run's attempt is carried forward. An earlier record
keeps its original attempt and identity as data. A new source revision is not
permission to repeat a completed task.

## Coverage report

Always state:

- declared schedule and selected denominator;
- attempted, completed, unattempted and running counts;
- native successes and failures among protocol-completed episodes;
- policy, protocol and infrastructure errors separately;
- unavailable scores and inference accounting, without replacing unknowns by zero.

Prepared manifests, environment diagnostics and unclaimed cases are not completed
capability evaluations. Keep both completed-episode and all-attempt success
rates. Do not merge incompatible policy versions, budgets, asset tracks or
native conditions into a homogeneous score.

Generic report tools are under `benchkit/reports/`, for example `panel_sr.py`
and `basic_result.py`. Use each tool's `--help` for its supported input schemas.
Old evidence is not rewritten to satisfy a newer reporter.

Maintain each model's task ledger, reports and indices in
`AgentPolicies/<profile>/results/<benchmark>/`. Raw runs and generated media are
Git-ignored. Internal progress, run counts and scheduling diaries belong in
`project_readmes/`, not benchmark specifications or public introduction tables.

## Protocol changes

Changes to cameras, controllers, horizons or success definitions require a
separate, explicit benchmark track. Changes to planning, prompts or voluntary
give-up rules require a new policy configuration. Freeze both prospectively.

The model can use only its declared observations. Operators must not reveal
private reset state, scoring information or another case's outcome through
endpoint names, actor labels or launch context. Unknown provider usage and
unenforced isolation remain disclosed limitations, not inferred guarantees.
