# Closed result format for any-language drivers

A trusted evaluation driver can produce these JSON files without implementing
Python `Policy`, using our SDK, or routing model requests through a central proxy.
The driver must still use the [benchmark service protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md):
claims, native execution, scoring and no-replay rules are unchanged. Model actors
must not receive the administrative client or private scoring data.

This is the existing `starvla-rsi.eval/v1` client-run contract, with optional
method and recording declarations. A conforming file is a **reported result**,
not independent proof of native execution or model/provider identity. The basic
exporter checks closed-record consistency; full integrity audits are separate.

## Files

```text
closed-run/
├── manifest.json
├── status.json
├── summary.json
├── episodes.jsonl
└── episodes/
    └── task-a-seed7/
        └── result.json
```

Each line of `episodes.jsonl` is one complete episode result object, in selected
schedule order. Each must have an identical object in exactly one
`episodes/<directory>/result.json`; matching uses `episode.id`, not the directory
name. Use safe descriptive directory names. Symlinked source files are rejected.

Interaction events, model/tool transcripts, videos, source snapshots and hashes
are **not required** for basic result export. Disabling them does not reduce
publication eligibility. Extra private files are neither scanned nor copied.

## Manifest

Required fields and their meanings:

| Field | Value |
| --- | --- |
| `schema_version` | `starvla-rsi.eval/v1` |
| `run_id` | Nonempty run identity, also used by the summary |
| `benchmark` | `name`, `version`, `protocol_version`, `source_revision`; copy recorded service declarations, do not infer from today's checkout |
| `policy` | At least a declared `name`; legacy `kind`, `model`, `provider`, `version` may also be present |
| `action_spec` | Service-declared `mode`, positive `size`, `names`, optional `low`/`high`, `control_hz`, `frame`, `rotation`, `gripper` |
| `observation_spec` | Service-declared `cameras`, `state_names`, `modalities`, `privileged: false`, optional `control_feedback_schema` |
| `protocol` | Selected `episode_ids`, positive `max_steps`, `max_policy_calls` (positive integer or null), `replan_interval` (positive integer or null), `fail_fast` (boolean); retain actual budget/track declarations. A horizon run may add the service's `service_environment_step_cap` (positive integer or null) and `max_steps_overridden` (boolean: no service cap, or `max_steps` differs from it) |

Optional public method declaration:

```json
{
  "method": {
    "schema_version": "starvla-rsi.method/v1",
    "id": "my-planner-reviewer",
    "version": "v1",
    "models": [
      {"id": "planner", "role": "planning", "provider": null, "model": null, "version": null},
      {"id": "reviewer", "role": "action review", "provider": null, "model": null, "version": null}
    ],
    "configuration": {"memory": "rolling", "parallel": false}
  },
  "method_origin": "participant_declaration"
}
```

These fields belong inside `manifest.json`. Component IDs are unique ASCII
letters/digits/dot/underscore/dash, beginning with a letter or digit. Unknown
provider/model/version stays null; unknown composition can be an empty list.
Configuration is bounded, explicitly **public JSON**, not a dump of runtime
settings. Do not include credentials, private paths or sensitive prompt content.
Credential-named fields and absolute paths are rejected, but validation is not
general secret detection: review before publication.

The reference runner projects old `PolicyDescriptor` identity when no method
file is supplied, using `method_origin: legacy_policy_projection`. Arbitrary
legacy parameters are not copied. The report labels that configuration as not
supplied, rather than claiming an empty object is a complete method definition.

For multi-call method accounting, the reference runner records
`protocol.usage_accounting_version: starvla-rsi.method-usage/v1`. This separates
robot decision-loop calls from model inference requests; it does not change a
benchmark's native execution budget.

## Episode result

One synthetic example, with no inference usage claimed:

```json
{
  "schema_version": "starvla-rsi.eval/v1",
  "episode": {"id": "task-a/seed7", "task": "task-a", "seed": 7,
              "instruction": "Perform the declared task.", "metadata": {}},
  "status": "completed",
  "success": false,
  "termination_reason": "environment:truncated",
  "policy_calls": 2,
  "action_decisions": 2,
  "environment_steps": 10,
  "rejected_actions": 0,
  "duration_s": 3.5,
  "reward_sum": 0.0,
  "usage": {"calls": null, "input_tokens": null, "output_tokens": null,
            "cached_input_tokens": null, "estimated_cost_usd": null, "latency_s": null},
  "metrics": {"success": false, "score": 40},
  "artifacts": {},
  "error": null
}
```

`completed` means an ordinary native outcome or policy stop, not success. Its
`success` must be boolean and match `metrics.success`. An errored episode uses
`status: error`, `success: null`, and an error object with a nonempty `type` plus
`category` equal to `policy`, `protocol`, `infrastructure` or `evaluation`.
The report omits error messages/tracebacks, arbitrary metrics, metadata and paths.
Never turn an infrastructure interruption into a completed task failure.

Counts are distinct: `policy_calls` counts driver decision calls;
`action_decisions` counts decisions with at least one acknowledged control;
`environment_steps` counts acknowledged native controls. `usage.calls` instead
counts reported inference requests and may exceed `policy_calls`.
The example's two decisions and ten controls illustrate a possible method-selected
chunk schedule, not a five-controls-per-decision requirement. Native physics
ticks are not added to `environment_steps`, and an unacknowledged in-flight
control must not be silently counted as either a confirmed action or zero motion.
Unknown usage fields remain null. Failed calls retain known accounting; do not
infer cost, tokens or component identity from missing evidence.

Optional `component_usage` maps declared model component IDs to the same six
usage fields. Missing components/fields are unknown, never zero or a share of
aggregate usage. The reference runner sums per-field values with unknown
propagation. `latency_s` is reported usage latency, while `duration_s` is episode
wall time; parallel models can have different latency and wall-time totals.

Optional `recording` uses the reference settings:

```json
{"schema_version":"starvla-rsi.recording/v2","mode":"minimal",
 "interactions":false,"model_io":false,"tool_traces":false,
 "images":false,"videos":false,"copy_server_media":false}
```

The manifest declares requested settings; each episode can additionally declare
`agent_events_written` and bounded warning codes. A setting being enabled does
not prove every provider exposed a transcript. See [recording options](recording.md).

## Closure and summary

`status.json` contains `status` (`completed` or `completed_with_errors`) and
`episodes_written`. All selected episodes must be present unless the declared
`fail_fast` setting stopped after an errored episode. Unattempted cases stay in
the manifest schedule and the report denominator; they are never silently
deleted or retried.

`summary.json` repeats `run_id`, `benchmark` (name), `policy` (name), and totals
for `attempted`, `completed`, `errors`, `successes`, `policy_calls`,
`rejected_actions`, and the six-field aggregate `usage` object. Optional
`component_usage` must agree with episode totals. Unknown propagates when
summing usage. When both are known, cached input tokens cannot exceed input
tokens. Optional `success_rate`, `attempt_success_rate`, `selected_success_rate`
and `completion_rate` must agree with the recorded counts; boolean rates are invalid.

The basic report prominently shows **successes / selected cases**
(`selected_success_rate`), retaining errors and unattempted selected cases in
that denominator. It also provides successes/completed (`success_rate`),
successes/attempted (`attempt_success_rate`) and explicit denominator labels.
For example, one success followed by one infrastructure error and one
fail-fast-unattempted case is 1/3 over selected, 1/2 over attempted and 1/1 over
completed—not an unqualified 100% result. None establishes that a client-selected
schedule covers the entire native benchmark.

## Export

```sh
python -B -m benchkit.reports.basic_result \
  --run-dir /absolute/closed-run \
  --output-dir AgentPolicies/my_method/results/my_benchmark/reports/my-run \
  --metric score
```

The destination must be new and outside the source run. The exporter writes
`result.json` and standalone `index.html`, without changing source files or
calling a model/simulator. Repeat `--metric KEY` to explicitly include additional
native numeric/boolean metrics; missing metrics are null. It does not select
arbitrary nested metric objects or copy media automatically. This publication
choice does not make private metrics available to the acting model.

Inputs reject duplicate JSON keys and nonfinite numbers, are bounded to 10,000
episodes, 64 MiB per file and 128 MiB of files read in total, and are checked
for changes during export.
The optional [interaction viewer](../benchkit/reports/interaction_history.py)
adds a timeline when compatible detailed events exist. Its absence does not
prevent the basic result above.
