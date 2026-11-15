#!/usr/bin/env python3
"""Offline runner-record consistency audit; never imports or queries a simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from benchkit.contracts import episode_step_limit


class AuditError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise AuditError(f"nonfinite JSON constant: {value}")


def finite_float(value: str) -> float:
    number = float(value)
    require(math.isfinite(number), "nonfinite JSON number")
    return number


def decode(payload: str):
    return json.loads(payload, object_pairs_hook=unique_object,
                      parse_constant=reject_constant, parse_float=finite_float)


class ClosedFiles:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        self.hashes: dict[str, str] = {}

    def path(self, relative: str) -> Path:
        path = Path(relative)
        require(not path.is_absolute() and ".." not in path.parts, "unsafe artifact path")
        target = self.root
        for part in path.parts:
            target = target / part
            require(not target.is_symlink(), f"symlink in artifact path: {relative}")
        require(target.resolve().is_relative_to(self.root) and target.is_file(),
                f"missing/outside artifact: {relative}")
        return target

    def raw(self, relative: str) -> bytes:
        path = self.path(relative)
        require(path.stat().st_size <= 64 * 1024 * 1024, "audit input exceeds 64 MiB")
        payload = path.read_bytes()
        self.hashes[relative] = hashlib.sha256(payload).hexdigest()
        return payload

    def json(self, relative: str):
        return decode(self.raw(relative).decode("utf-8"))

    def jsonl(self, relative: str) -> list:
        return [decode(line) for line in self.raw(relative).decode("utf-8").splitlines() if line]

    def verify_unchanged(self) -> None:
        for relative, digest in self.hashes.items():
            require(hashlib.sha256(self.path(relative).read_bytes()).hexdigest() == digest,
                    f"artifact changed during audit: {relative}")


def counter(value, label: str) -> int:
    require(type(value) is int and value >= 0, f"invalid {label} counter")
    return value


REJECTION_VERSION = "starvla-rsi.action-rejection-feedback/v1"
USAGE_COUNTERS = {"calls", "input_tokens", "output_tokens", "cached_input_tokens"}
USAGE_FIELDS = USAGE_COUNTERS | {"estimated_cost_usd", "latency_s"}


def finite_number(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def audit_usage(value) -> dict:
    """Mirror the data contract independently, retaining unknown rather than zero."""
    require(type(value) is dict and set(value) == USAGE_FIELDS, "missing/invalid call usage")
    for key, number in value.items():
        require(number is None or ((type(number) is int if key in USAGE_COUNTERS
                                     else finite_number(number)) and number >= 0),
                f"invalid usage component: {key}")
    return value


def sum_usage(left: dict, right: dict) -> dict:
    return {key: None if left[key] is None or right[key] is None else left[key] + right[key]
            for key in USAGE_FIELDS}


def same_usage(actual: dict, expected: dict) -> bool:
    audit_usage(actual)
    return all(actual[key] is None if expected[key] is None else (
        actual[key] is not None and (actual[key] == expected[key] if key in USAGE_COUNTERS
        else math.isclose(actual[key], expected[key], rel_tol=1e-12, abs_tol=1e-9)))
        for key in USAGE_FIELDS)


def reconcile_usage(summed: dict, reported: dict) -> tuple[dict, dict, list]:
    """Independent copy of the runner rule: unknown total keeps the call sum,
    unknown sum takes the total, total >= sum takes the total, and a total
    below the sum makes the field unknown and inconsistent."""
    final, adjustment, inconsistent = {}, {}, []
    for key in sorted(USAGE_FIELDS):
        left, right = summed[key], reported[key]
        if left is None or right is None:
            final[key], adjustment[key] = (left if right is None else right), None
        elif right < left and not (key not in USAGE_COUNTERS and
                                   math.isclose(right, left, rel_tol=1e-12, abs_tol=1e-9)):
            final[key] = adjustment[key] = None
            inconsistent.append(key)
        else:
            final[key], adjustment[key] = right, right - left
    return final, adjustment, inconsistent


def audit_usage_reconciliation(event: dict, usage_total: dict) -> dict:
    require(set(event) == {"event", "timestamp", "policy_call_sum", "reported_total", "reported_complete",
                           "adjustment", "inconsistent_fields", "usage"}, "invalid usage reconciliation fields")
    require(type(event["reported_complete"]) is bool, "invalid usage reconciliation completeness")
    require(same_usage(event["policy_call_sum"], usage_total), "logged/reconciled call usage mismatch")
    expected, adjustment, inconsistent = reconcile_usage(usage_total, audit_usage(event["reported_total"]))
    recorded = event["adjustment"]
    require(type(recorded) is dict and set(recorded) == USAGE_FIELDS and all(
        recorded[key] is None if adjustment[key] is None else (
            type(recorded[key]) in (int, float) and math.isclose(recorded[key], adjustment[key],
                                                                 rel_tol=1e-12, abs_tol=1e-9))
        for key in USAGE_FIELDS), "usage reconciliation adjustment mismatch")
    require(type(event["inconsistent_fields"]) is list
            and all(type(key) is str for key in event["inconsistent_fields"]) and sorted(event["inconsistent_fields"]) == inconsistent, "usage reconciliation inconsistency mismatch")
    require(same_usage(event["usage"], expected), "usage reconciliation rule mismatch")
    return expected


def audit_validation_issue(issue) -> None:
    # Closed public DTO, deliberately independent of live Python modules.
    codes = {"invalid_json", "unexpected_fields", "invalid_type", "invalid_length", "non_finite",
             "out_of_bounds", "quaternion_not_unit", "translation_limit", "rotation_limit",
             "gripper_binary_required", "invalid_stop", "invalid_action"}
    fields = {"action", "response", "steps", "memory", "note", "safety_stop", "stop_reason", "left", "right",
              "left.pose", "right.pose", "left.opening", "right.opening", "left.translation_m",
              "right.translation_m", "left.rotation_rad", "right.rotation_rad",
              "left.quaternion_norm", "right.quaternion_norm"}
    require(type(issue) is dict and set(issue) == {"code", "field", "actual", "limit", "action_index"},
            "invalid rejection issue fields")
    require(type(issue["code"]) is str and issue["code"] in codes
            and type(issue["field"]) is str and issue["field"] in fields,
            "unknown rejection issue code/field")
    require(all(issue[key] is None or finite_number(issue[key]) for key in ("actual", "limit")),
            "unsafe rejection issue values")
    require(issue["action_index"] is None or (type(issue["action_index"]) is int
            and 0 <= issue["action_index"] <= 2**31 - 1), "invalid rejection component index")


def audit_episode(result: dict, events: list, protocol: dict) -> dict:
    require(protocol.get("usage_accounting_version") == "starvla-rsi.method-usage/v2",
            "unknown method usage accounting version")
    require(events and events[0]["event"] == "episode_start" and events[-1]["event"] == "episode_end",
            "episode event boundaries missing")
    require(sum(e["event"] == "episode_start" for e in events) == 1
            and sum(e["event"] == "episode_end" for e in events) == 1, "duplicate episode boundary")
    require(events[0]["episode"] == result["episode"] and events[-1]["result"] == result,
            "episode boundary/result mismatch")
    calls = counter(result["policy_calls"], "policy")
    controls = counter(result["environment_steps"], "control")
    step_limit = episode_step_limit(protocol["max_steps"], result["episode"]["metadata"])  # runner's per-episode cap
    require(controls <= step_limit, "control budget exceeded")
    require(protocol["max_policy_calls"] is None or calls <= protocol["max_policy_calls"],
            "policy-call budget exceeded")
    completed = result["status"] == "completed"
    require(protocol.get("execution_feedback_version") == "starvla-rsi.execution-feedback/v1",
            "unknown execution feedback contract")
    require(protocol.get("instruction_change_handling") == "replan-after-ack/v1",
            "unknown instruction-change handling")
    control_schema = protocol.get("control_feedback_schema")
    if control_schema is not None:
        require(isinstance(control_schema, str) and 1 <= len(control_schema) <= 128
                and protocol.get("control_acknowledgement_version") == "starvla-rsi.control-acknowledgement/v1",
                "unbound public control acknowledgement extension")
    else:
        require("control_acknowledgement_version" not in protocol, "undeclared public control channel")
    rejection_mode = protocol.get("invalid_action_handling")
    require(rejection_mode in ("terminate", "feedback"), "unknown invalid-action handling")
    recover_rejections = rejection_mode == "feedback"
    if recover_rejections:
        require(protocol.get("action_rejection_feedback_version") == REJECTION_VERSION,
                "unbound rejection feedback extension")
        require(type(protocol["max_policy_calls"]) is int and protocol["max_policy_calls"] > 0,
                "rejection feedback requires a finite positive integer call cap")
        require(type(protocol["max_steps"]) is int and protocol["max_steps"] > 0
                and (protocol["replan_interval"] is None or (type(protocol["replan_interval"]) is int
                     and protocol["replan_interval"] > 0)), "invalid feedback-mode control/prefix budget")
    else:
        require("action_rejection_feedback_version" not in protocol,
                "rejection feedback extension requires feedback mode")
    require(completed or result["status"] == "error", "unknown episode status")
    require((type(result["success"]) is bool and result["error"] is None
             and result["metrics"].get("success") == result["success"]) if completed
            else (result["success"] is None and isinstance(result["error"], dict)),
            "result success/error semantics disagree")

    call = step = 0
    decision = chunk = None
    played = 0
    decisions = chunks = stops = 0
    terminal = False
    last_control = None
    reward = 0.0
    executed_calls = set()
    rejected = False
    rejections = rejected_acts = rejected_specs = 0
    observed = False
    metered_calls = set()
    usage_total = {key: 0 for key in USAGE_FIELDS}
    errors_seen = 0
    control_acks = []
    latest_instruction = decision_instruction = None
    instruction_changed = False
    # A policy usage report is read after end_episode, so its reconciliation
    # is the single event directly before episode_end.
    body = events[1:-1]
    reconciliation = body.pop() if body and body[-1]["event"] == "usage_reconciliation" else None
    for event in body:
        kind = event["event"]
        if kind == "policy_call_start":
            require(not terminal, "decision after terminal event")
            require(not recover_rejections or observed, "policy call without initial observation")
            if call:
                require(rejected or (chunk is not None and (
                    played == chunk["maximum_executed_prefix"] or instruction_changed)),
                        "new decision before preceding prefix completed")
            require(observed and isinstance(latest_instruction, str),
                    "instruction-aware decision has no public input instruction")
            decision_instruction = latest_instruction
            instruction_changed = False
            call += 1
            require(counter(event["policy_call"], "event policy") == call, "decision-start order mismatch")
            decision = chunk = None
            played = 0
            control_acks = []
            rejected = False
        elif kind == "policy_decision":
            require(call > 0 and decision is None and event["policy_call"] == call and not rejected
                    and (not recover_rejections or not terminal),
                    "unscheduled/duplicate policy decision")
            require(type(event["stop"]) is bool, "invalid stop flag")
            if recover_rejections:
                counter(event["policy_call"], "returned policy")
                counter(event["chunk_length"], "returned chunk length")
            decision = event
            decisions += 1
            reported = audit_usage(event.get("usage"))
            require(call not in metered_calls, "duplicate call accounting")
            metered_calls.add(call)
            usage_total = sum_usage(usage_total, reported)
            if event["stop"]:
                require(event["chunk_length"] == 0, "stop contains an action chunk")
                stops += 1
                terminal = True
        elif kind == "action_chunk":
            require(not terminal and not rejected and decision is not None and chunk is None
                    and event["policy_call"] == call, "unscheduled/duplicate action chunk")
            if recover_rejections:
                counter(event["policy_call"], "chunk policy")
            actions = event["actions"]
            require(isinstance(actions, list) and len(actions) == decision["chunk_length"] > 0,
                    "decision/action chunk length mismatch")
            expected = min(len(actions), step_limit - step)
            if protocol["replan_interval"] is not None:
                expected = min(expected, protocol["replan_interval"])
            require(counter(event["maximum_executed_prefix"], "prefix") == expected,
                    "executed-prefix budget mismatch")
            chunk = event
            chunks += 1
        elif kind == "environment_step":
            require(not terminal and not rejected and chunk is not None and event["policy_call"] == call,
                    "control outside active action chunk")
            require(not instruction_changed, "control after a changed public instruction without replanning")
            if recover_rejections:
                counter(event["policy_call"], "control policy")
                counter(event["chunk_index"], "control prefix index")
            require(event["chunk_index"] == played and played < chunk["maximum_executed_prefix"],
                    "control prefix index mismatch")
            require(event["action"] == chunk["actions"][played], "executed action differs from prefix")
            step += 1
            executed_calls.add(call)
            played += 1
            require(counter(event["environment_step"], "event control") == step, "control order mismatch")
            require(type(event["terminated"]) is bool and type(event["truncated"]) is bool,
                    "invalid environment terminal flags")
            terminal = event["terminated"] or event["truncated"]
            last_control = event
            public = event.get("observation", {})
            latest_instruction = public.get("instruction")
            require(isinstance(latest_instruction, str), "ACK lacks a public instruction")
            instruction_changed = latest_instruction != decision_instruction
            if control_schema is not None:
                payload = public.get("control_feedback")
                require(type(payload) is dict and payload.get("schema") == control_schema
                        and type(payload.get("control_target")) is int and payload["control_target"] == step
                        and type(public.get("step")) is int and public["step"] == step,
                        "uncorrelated public control acknowledgement")
                control_acks.append({"environment_step": step, "observation_step": step, "payload": payload})
            else:
                require("control_feedback" not in public, "undeclared public control payload")
            if recover_rejections:
                require(finite_number(event["reward"]), "invalid acknowledged reward")
            reward += event["reward"]
        elif kind == "action_rejected":
            require(recover_rejections, "action rejection without declared feedback extension")
            require(set(event) == {"event", "timestamp", "policy_call", "phase", "feedback", "usage",
                                   "usage_recorded_in", "metadata"}, "invalid rejection event fields")
            require(not terminal and not rejected and call > 0
                    and counter(event["policy_call"], "rejected policy") == call,
                    "unscheduled/duplicate action rejection")
            phase, feedback = event["phase"], event["feedback"]
            require(type(feedback) is dict and set(feedback) == {
                "schema_version", "issue", "policy_calls", "action_decisions", "environment_steps",
                "executed_steps", "rejected_actions"} | ({"control_acks"} if control_schema is not None else set())
                and feedback["schema_version"] == REJECTION_VERSION,
                "invalid rejection feedback schema")
            if control_schema is not None:
                require(type(feedback["control_acks"]) is list and
                        json.dumps(feedback["control_acks"], sort_keys=True, allow_nan=False) ==
                        json.dumps(control_acks, sort_keys=True, allow_nan=False),
                        "rejection receipt differs from acknowledged control prefix")
            audit_validation_issue(feedback["issue"])
            rejections += 1
            for key, expected in (("policy_calls", call), ("action_decisions", len(executed_calls)),
                                  ("environment_steps", step), ("executed_steps", played),
                                  ("rejected_actions", rejections)):
                require(counter(feedback[key], "rejection " + key) == expected,
                        "rejection feedback counter mismatch: " + key)
            reported = audit_usage(event["usage"])
            require(type(event["metadata"]) is dict and len(json.dumps(event["metadata"], allow_nan=False,
                    separators=(",", ":")).encode("utf-8")) <= 16 * 1024,
                    "invalid rejection receipt metadata")
            if phase == "policy_act":
                require(decision is None and chunk is None and played == 0
                        and event["usage_recorded_in"] == "action_rejected"
                        and call not in metered_calls, "invalid policy-act rejection lifecycle/accounting")
                usage_total = sum_usage(usage_total, reported)
                metered_calls.add(call)
                rejected_acts += 1
            else:
                require(decision is not None and not decision["stop"] and call in metered_calls
                        and event["usage_recorded_in"] == "policy_decision"
                        and all(value is not None and value == 0 for value in reported.values()),
                        "post-decision rejection must not add provider usage")
                if phase == "action_spec":
                    require(chunk is None and played == 0, "invalid action-spec rejection lifecycle")
                    rejected_specs += 1
                else:
                    require(phase == "session_step" and chunk is not None
                            and played < chunk["maximum_executed_prefix"],
                            "invalid session-step rejection lifecycle")
            rejected = True
        elif kind == "observation":
            require(call == 0 and step == 0, "unexpected extra observation event")
            require(not recover_rejections or not observed, "duplicate initial observation")
            observed = True
            latest_instruction = event.get("observation", {}).get("instruction")
            require(isinstance(latest_instruction, str), "reset lacks a public instruction")
            require(event.get("observation", {}).get("control_feedback") is None,
                    "reset reused a previous control acknowledgement")
        elif kind in ("error", "artifact_error"):
            require(not completed, "completed result contains an error event")
            recorded_error = event.get("error")
            require(type(recorded_error) is dict, "invalid recorded error object")
            if recover_rejections and kind == "error":
                require(errors_seen == 0, "duplicate terminal error event")
                errors_seen += 1
            if kind == "error":
                if recorded_error.get("type") == "ActionRejected":
                    audit_validation_issue(recorded_error.get("issue"))
                phase = recorded_error.get("action_rejection_phase")
                if phase is not None:
                    require(recorded_error.get("type") == "ActionRejected" and call > 0 and not terminal
                            and not rejected, "unscheduled terminal action rejection")
                    if phase == "policy_act":
                        require(decision is None and chunk is None and played == 0
                                and counter(recorded_error.get("policy_call"), "terminal rejected policy") == call,
                                "invalid terminal policy-act rejection")
                        audit_usage(recorded_error.get("usage"))
                        require(not recover_rejections, "recoverable rejection mislabeled as terminal")
                    else:
                        require(phase == "session_step" and not recover_rejections and decision is not None
                                and not decision["stop"] and chunk is not None
                                and played < chunk["maximum_executed_prefix"],
                                "invalid terminal session-step rejection")
                    rejections += 1
            if kind == "error" and "usage" in recorded_error:
                require(call > 0 and call not in metered_calls
                        and counter(recorded_error.get("policy_call"), "failed policy") == call,
                        "duplicate/unscheduled failed-call accounting")
                usage_total = sum_usage(usage_total, audit_usage(recorded_error["usage"]))
                metered_calls.add(call)
            terminal = True
        elif kind == "usage_reconciliation":
            raise AuditError("usage reconciliation is not the single event before episode_end")
        else:
            raise AuditError(f"unsupported event kind: {kind}")

    require(call == calls and step == controls, "logged/result counters disagree")
    require(counter(result.get("rejected_actions"), "rejected actions") == rejections,
            "logged/result rejection counters disagree")
    require(metered_calls == set(range(1, calls + 1)), "unmetered policy call")
    reported_complete = result.get("usage_reported_complete", "missing")
    inconsistent_fields = result.get("usage_inconsistent_fields", "missing")
    require(reported_complete is None or type(reported_complete) is bool, "invalid result usage completeness")
    require((reconciliation is None) == (reported_complete is None),
            "usage reconciliation event/result completeness mismatch")
    if reconciliation is not None:
        usage_total = audit_usage_reconciliation(reconciliation, usage_total)
        require(reconciliation["reported_complete"] == reported_complete
                and inconsistent_fields == reconciliation["inconsistent_fields"],
                "usage reconciliation event/result mismatch")
    else:
        require(inconsistent_fields is None, "usage inconsistency without reconciliation")
    require(same_usage(result.get("usage"), usage_total), "logged/result usage mismatch")
    if recover_rejections:
        require(finite_number(result["reward_sum"]), "invalid total acknowledged reward")
    require(counter(result.get("action_decisions"), "executed action decisions") == len(executed_calls),
            "action-decision count differs from executed controls")
    require(math.isclose(reward, result["reward_sum"], rel_tol=1e-12, abs_tol=1e-9),
            "logged/result reward sum mismatch")
    if completed:
        require(decisions + rejected_acts == calls and chunks + stops + rejected_specs == decisions,
                "completed decision coverage incomplete")
        require(not chunk or terminal or rejected or instruction_changed
                or played == chunk["maximum_executed_prefix"],
                "completed result has an unexplained partial prefix")
        if stops:
            require(result["termination_reason"] == f"policy:{decision['stop_reason']}", "stop reason mismatch")
        else:
            # Match runner.py precedence: native termination, native
            # truncation, the step cap, then the policy-call cap.
            call_limit = protocol["max_policy_calls"]
            calls_exhausted = call_limit is not None and call >= call_limit
            steps_exhausted = step >= step_limit
            if last_control is not None and last_control["terminated"]:
                expected_reason = "environment:terminated"
            elif last_control is not None and last_control["truncated"]:
                expected_reason = "environment:truncated"
            elif steps_exhausted:
                expected_reason = "runner:step_limit"
            elif calls_exhausted:
                expected_reason = "runner:policy_call_limit"
            else:
                raise AuditError("completed episode has no applicable termination condition")
            require(result["termination_reason"] == expected_reason, "termination reason mismatch")
    else:
        # Failed act/validation/step/cleanup may leave one incomplete final turn.
        require(calls - decisions - rejected_acts in (0, 1), "multiple missing decisions hidden by error")
        require(result["termination_reason"] == f"error:{result['error']['category']}",
                "error termination reason mismatch")
    row = {"episode_id": result["episode"]["id"], "status": result["status"],
            "success": result["success"], "controls": controls, "decisions_started": calls,
            "decisions_returned": decisions, "action_chunks": chunks, "stop_decisions": stops,
            "termination_reason": result["termination_reason"],
            "action_decisions": len(executed_calls), "rejected_actions": rejections}
    return row


def audit_run(run: Path) -> dict:
    files = ClosedFiles(run)
    status = files.json("status.json")
    require(status.get("status") in ("completed", "completed_with_errors"), "only closed runs may be audited")
    manifest = files.json("manifest.json")
    require(manifest["schema_version"] == "starvla-rsi.eval/v1", "unsupported run schema")
    require(manifest.get("observation_spec", {}).get("control_feedback_schema") ==
            manifest["protocol"].get("control_feedback_schema"), "public control channel binding mismatch")
    results = files.jsonl("episodes.jsonl")
    require(results and len(results) == status["episodes_written"], "closed episode count mismatch")
    ids = [row["episode"]["id"] for row in results]
    require(len(ids) == len(set(ids)), "duplicate result episode IDs")
    require(ids == manifest["protocol"]["episode_ids"][:len(ids)], "result order differs from selection")
    paths = sorted((files.root / "episodes").glob("*/result.json"))
    require(len(paths) == len(results), "episode directory/index count mismatch")
    found = {}
    for path in paths:
        relative = path.relative_to(files.root).as_posix()
        result = files.json(relative)
        episode_id = result["episode"]["id"]
        require(episode_id not in found, "duplicate episode directory identity")
        found[episode_id] = (result, path.parent.relative_to(files.root).as_posix())
    rows = []
    for indexed in results:
        require(indexed["episode"]["id"] in found, "indexed episode has no result")
        result, directory = found[indexed["episode"]["id"]]
        require(result == indexed, "episode index/result mismatch")
        rows.append(audit_episode(result, files.jsonl(directory + "/events.jsonl"), manifest["protocol"]))
    completed = sum(row["status"] == "completed" for row in rows)
    require(status["status"] == ("completed" if completed == len(rows) else "completed_with_errors"),
            "run/episode lifecycle mismatch")
    if len(rows) != len(manifest["protocol"]["episode_ids"]):
        require(manifest["protocol"]["fail_fast"] and results[-1]["status"] == "error",
                "selected episodes silently omitted")
    summary = files.json("summary.json")
    for key, expected in {"attempted": len(rows), "completed": completed, "errors": len(rows) - completed,
                          "successes": sum(row["success"] is True for row in rows),
                          "policy_calls": sum(row["decisions_started"] for row in rows)}.items():
        require(summary[key] == expected, f"summary {key} mismatch")
    require(counter(summary.get("rejected_actions"), "summary rejected actions") ==
            sum(row["rejected_actions"] for row in rows), "summary rejected actions mismatch")
    usage = {key: 0 for key in USAGE_FIELDS}
    for result in results:
        usage = sum_usage(usage, audit_usage(result.get("usage")))
    require(same_usage(summary.get("usage"), usage), "summary usage mismatch")
    require(counter(summary.get("usage_incomplete_episodes"), "summary incomplete usage") == sum(
        result["usage_reported_complete"] is False or bool(result["usage_inconsistent_fields"])
        for result in results), "summary incomplete usage count mismatch")
    files.verify_unchanged()
    report = {"schema_version": "starvla-rsi.closed-record-audit/v2", "source_run": str(files.root),
            "record_consistency": "passed", "episodes": rows,
            "read_file_sha256": files.hashes,
            "limitations": ["Read-only runner-record consistency, not native benchmark parity or execution attestation.",
                            "Does not follow video or native asset paths; independent artifact audit is separate.",
                            "No OS isolation or trusted model/provider/usage attestation.",
                            "A consistent error or failed task is not a successful task.",
                            "Checks the generic call/ACK ledger only; policy-private receipts are not audited here."]}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new evaluator-private report outside the closed run")
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.run_dir.resolve()), "report must be outside the closed run")
    report = audit_run(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
