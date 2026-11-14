"""Report a predeclared once-per-case panel without loading a policy or SIM.

Plan JSON has exactly these required fields::

    {"schema_version": "starvla-rsi.panel-plan/v1", "cases": ["episode-id"]}

An optional ``reference`` ``{"successes": 1, "episodes": 1}`` enables the
comparison fields; optional ``reference_url`` and ``operator_notes`` are strings.
Reference values are operator declarations, not independently verified or
evidence of identical conditions. Case IDs are unique, nonempty strings matched
exactly to episode.id.

Each JSONL row is a closed ``starvla-rsi.eval/v1`` result with ``episode.id``,
``status`` (completed/error), ``success``, ``metrics`` and ``error``. Completed
rows require matching boolean success and metrics.success, with error=null.
Error rows require success=null and an error object; the policy category is a
behavioral failure, while other/missing categories remain infrastructure or
ambiguous failures. Artifact/cleanup errors also make a panel incomplete,
including when attached to a primary policy failure. Those two counts can
overlap. Arbitrary metadata is not scanned. Additional finite JSON fields and
all original error rows are retained.

Counters are optional nonnegative integers (null means unknown). Only existing
top-level environment_steps/policy_calls/action_decisions and explicitly
normalized metrics.controls/first_native_success_control are summarized; no
benchmark-specific field names, scorer heuristics or counter inference are used.
An earlier success counter never overrides the final native success boolean.

Only a complete panel (all planned rows, no infrastructure/ambiguous errors)
gets a full-panel SR. Otherwise successful/planned is a coverage lower bound;
completed-native SR always has a separate explicit denominator. This tool cannot
attest predeclaration timing, source closure, protocol equivalence or statistical
equivalence. It never starts, selects, retries, filters or edits an episode.
Absent rows are missing_closed_result, not evidence that a case was unattempted:
an executed process can fail or disappear before writing its closed result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

from benchkit.artifacts import atomic_write_json
from benchkit.contracts import ensure_jsonable

PLAN_SCHEMA = "starvla-rsi.panel-plan/v1"
RESULT_SCHEMA = "starvla-rsi.eval/v1"
REPORT_SCHEMA = "starvla-rsi.panel-sr/v1"
MAX_INPUT_BYTES = 64 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, name):
    _require(isinstance(value, str) and bool(value.strip()), name + " must be a nonempty string")
    _require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), name + " contains invalid Unicode")
    return value


def _integer(value, name, minimum=0):
    _require(type(value) is int and value >= minimum, name + " must be a nonnegative integer" if minimum == 0
             else name + " must be a positive integer")
    return value


def _plan(plan):
    _require(isinstance(plan, dict), "plan must be an object")
    required = {"schema_version", "cases"}
    _require(required <= set(plan) <= required | {"reference", "reference_url", "operator_notes"},
             "invalid plan fields")
    _require(plan["schema_version"] == PLAN_SCHEMA, "unsupported plan schema")
    cases = plan["cases"]
    _require(isinstance(cases, list) and bool(cases), "cases must be a nonempty list")
    for case in cases:
        _text(case, "case ID")
        _require(case == case.strip() and not any(ord(c) < 32 for c in case), "case IDs cannot have surrounding whitespace/control characters")
    _require(len(set(cases)) == len(cases), "duplicate planned case ID")
    if "reference" in plan:
        reference = plan["reference"]
        _require(isinstance(reference, dict) and set(reference) == {"successes", "episodes"},
                 "invalid reference fields")
        _integer(reference["episodes"], "reference episodes", 1)
        _integer(reference["successes"], "reference successes")
        _require(reference["successes"] <= reference["episodes"], "reference successes exceed episodes")
    for name in ("reference_url", "operator_notes"):
        if name in plan:
            _text(plan[name], name)
    return ensure_jsonable(plan)


def _row(record):
    _require(isinstance(record, dict), "episode result must be an object")
    required = {"schema_version", "episode", "status", "success", "metrics", "error"}
    _require(required <= set(record), "episode result missing required fields")
    _require(record["schema_version"] == RESULT_SCHEMA, "unsupported episode result schema")
    _require(isinstance(record["episode"], dict) and "id" in record["episode"], "episode.id is required")
    case = _text(record["episode"]["id"], "episode.id")
    _require(isinstance(record["metrics"], dict), "metrics must be an object")
    _require(record["status"] in ("completed", "error"), "only closed completed/error results are accepted")
    category, policy_failure, issues = None, False, []
    if record["status"] == "completed":
        _require(record["error"] is None, "completed result has an error")
        _require(type(record["success"]) is bool and type(record["metrics"].get("success")) is bool,
                 "completed result requires boolean native success")
        _require(record["success"] == record["metrics"]["success"], "success disagrees with native metrics.success")
        outcome = "native_success" if record["metrics"]["success"] else "native_failure"
    else:
        _require(record["success"] is None and isinstance(record["error"], dict), "error result requires success=null and error object")
        error = record["error"]
        category = error.get("category")
        if category is not None:
            _text(category, "error category")
        policy_failure = category == "policy"
        if not policy_failure:
            issues.append("primary_infrastructure_or_ambiguous_error")
        if error.get("artifact_error") is not None:
            issues.append("artifact_error")
        if error.get("cleanup_errors"):
            issues.append("cleanup_errors")
        outcome = "policy_failure" if policy_failure else "infrastructure_or_ambiguous_error"
    counters = {}
    for name in ("environment_steps", "policy_calls", "action_decisions"):
        if record.get(name) is not None:
            counters[name] = _integer(record[name], name)
    for name in ("controls", "first_native_success_control"):
        if record["metrics"].get(name) is not None:
            counters[name] = _integer(record["metrics"][name], "metrics." + name)
    if "controls" in counters and "first_native_success_control" in counters:
        _require(counters["first_native_success_control"] <= counters["controls"], "first native success exceeds recorded controls")
    return {"case_id": case, "outcome": outcome, "policy_failure": policy_failure,
        "has_infrastructure_error": bool(issues), "infrastructure_issues": issues,
        "error_category": category, "counters": counters}


def summarize_panel(plan: dict, records: list[dict]) -> dict:
    """Return an immutable-input summary; reject duplicate/unplanned records."""
    plan = _plan(plan)
    _require(isinstance(records, list), "records must be a list of closed results")
    records = ensure_jsonable(records)
    expected = set(plan["cases"])
    by_case = {}
    for index, record in enumerate(records):
        row = _row(record)
        case = row["case_id"]
        _require(case in expected, "unplanned episode ID: " + case)
        _require(case not in by_case, "duplicate episode ID: " + case)
        by_case[case] = {**row, "record_index": index}
    cases = [by_case.get(case, {"case_id": case, "outcome": "missing_closed_result", "record_index": None})
             for case in plan["cases"]]
    successes = sum(row["outcome"] == "native_success" for row in cases)
    completed = sum(row["outcome"] in ("native_success", "native_failure") for row in cases)
    policy_failures = sum(row.get("policy_failure", False) for row in cases)
    infrastructure = sum(row.get("has_infrastructure_error", False) for row in cases)
    planned, recorded = len(cases), len(records)
    complete = recorded == planned and infrastructure == 0
    rate = successes / planned
    reference = plan.get("reference")
    compared = complete and reference is not None
    reference_rate = reference["successes"] / reference["episodes"] if reference is not None else None
    return {"schema_version": REPORT_SCHEMA, "plan": plan, "records": records, "cases": cases,
        "complete_panel": complete,
        "counts": {"planned": planned, "recorded": recorded, "completed_native": completed,
            "successes": successes, "native_failures": completed - successes,
            "policy_failures": policy_failures, "infrastructure_errors": infrastructure,
            "missing_closed_results": planned - recorded},
        "successful_over_planned": {"successes": successes, "episodes": planned, "rate": rate,
            "interpretation": "full_panel_success_rate" if complete else "coverage_lower_bound_only"},
        "full_panel_success_rate": rate if complete else None,
        "completed_native_success_rate": {"successes": successes, "episodes": completed,
            "rate": successes / completed if completed else None, "secondary_denominator_only": True},
        "reference": None if reference is None else {**reference, "rate": reference_rate,
                                                     "operator_declared_not_verified": True},
        "comparison": {"eligible_full_panel_sr": complete,
            "rate_difference": rate - reference_rate if compared else None,
            "same_numeric_rate": successes * reference["episodes"] == reference["successes"] * planned if compared else None,
            "same_conditions_verified": False, "statistical_equivalence_established": False},
        "caveats": ["Policy failures remain in the planned denominator.",
            "Infrastructure-error case counts may overlap primary policy-failure counts; neither is dropped.",
            "Missing closed results do not establish whether a case was attempted or executed.",
            "Completed-native SR excludes error/missing-result rows and is only a secondary statistic.",
            "Reference values and plan timing are declarations; this reporter does not verify equivalent conditions or statistical equivalence."]}


def _decode(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite JSON value")
    return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)


def _read_closed(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_INPUT_BYTES, "input must be a regular file of at most 64 MiB")
        data = stream.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = os.stat(path, follow_symlinks=False)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    _require(len(data) <= MAX_INPUT_BYTES and identity(before) == identity(after) == identity(current), "input changed while reading")
    return data, {"path": str(path.absolute()), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new JSON file; existing paths are never replaced")
    args = parser.parse_args(argv)
    plan_bytes, plan_source = _read_closed(args.plan)
    episode_bytes, episode_source = _read_closed(args.episodes)
    rows = [_decode(line) for line in episode_bytes.decode("utf-8").splitlines() if line.strip()]
    report = summarize_panel(_decode(plan_bytes.decode("utf-8")), rows)
    report["inputs"] = {"plan": plan_source, "episodes": episode_source}
    atomic_write_json(args.output, report, overwrite=False)
    print(json.dumps({"output": str(args.output), "complete_panel": report["complete_panel"], "counts": report["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
