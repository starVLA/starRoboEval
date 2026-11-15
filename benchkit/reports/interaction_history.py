"""Export an offline interaction view from one closed client run.

This checks the recorded lifecycle and action ledger, not source snapshots,
native execution, provider identity, or delivery of a request to a model.
Only explicitly projected fields leave the record boundary; artifact paths,
native information and provider receipts are never followed or copied.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import tempfile

from benchkit.audits.closed_run import (
    ClosedFiles, audit_episode, audit_usage, audit_validation_issue, counter,
    require, same_usage, sum_usage, USAGE_FIELDS,
)


SCHEMA = "starvla-rsi.interaction-history/v1"
MAX_EPISODES = 10000
MAX_EVENTS = 250000
MAX_BYTES = 128 * 1024 * 1024
ERROR_CATEGORIES = {"policy", "protocol", "infrastructure", "evaluation"}
USAGE_ORDER = ("calls", "input_tokens", "output_tokens", "cached_input_tokens", "estimated_cost_usd", "latency_s")
LIMITATIONS = [
    "Inputs are recorded as supplied to Policy.act; backend model consumption is not established.",
    "Acknowledged controls are distinct from proposed actions and from feedback delivered to the actor.",
    "A pending control at an error has no recorded attempt or acknowledgement; execution may be uncertain.",
    "Notes and supported structured outputs are recorded policy output, not a complete conversation or hidden reasoning.",
    "Generic records contain camera names, not pixels. This exporter does not include images or video.",
    "Unknown robot-feedback payloads are not published. Native private scores and metadata are omitted.",
    "Identity and usage are reported declarations, not independent provider verification; null means unavailable.",
    "Episode usage follows the policy's own total when it reports one; per-call usage need not sum to it.",
    "Planned and unattempted counts cover only the manifest's client-selected schedule, not a full service or native panel.",
    "Only record consistency is checked here. Source/model audits, native replay and asset verification are separate.",
    "A final ACK or outcome in this report does not imply a final model continuation or feedback delivery.",
]


class _Files(ClosedFiles):
    def __init__(self, root):
        require(not Path(root).is_symlink(), "run root must not be a symlink")
        super().__init__(root)
        self.total_bytes = 0
        self.sizes = {}

    def raw(self, relative):
        size = self.path(relative).stat().st_size
        require(self.total_bytes + size <= MAX_BYTES, "interaction input exceeds total byte limit")
        # Long closed episodes can exceed the base auditor's 64 MiB per-file
        # limit. This exporter has its own stricter aggregate allocation bound;
        # enforce that bound during the read as well as before/after it.
        with self.path(relative).open("rb") as stream:
            payload = stream.read(MAX_BYTES - self.total_bytes + 1)
        require(self.total_bytes + len(payload) <= MAX_BYTES,
                "interaction input exceeds total byte limit")
        self.hashes[relative] = hashlib.sha256(payload).hexdigest()
        self.total_bytes += len(payload)
        self.sizes[relative] = len(payload)
        require(self.total_bytes <= MAX_BYTES, "interaction input exceeds total byte limit")
        return payload

    def verify_unchanged(self):
        # Do not let a replaced/growing source evade the original read bounds
        # during the final verification passes.
        for relative, expected in self.hashes.items():
            path = self.path(relative)
            remaining = self.sizes[relative]
            require(path.stat().st_size == remaining, "artifact changed during interaction export")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    require(bool(chunk), "artifact changed during interaction export")
                    digest.update(chunk)
                    remaining -= len(chunk)
                require(not stream.read(1), "artifact changed during interaction export")
            require(digest.hexdigest() == expected, "artifact changed during interaction export")


def _object(value, label):
    require(type(value) is dict, f"{label} must be an object")
    return value


def _text(value, label, *, optional=False, limit=4096):
    if optional and value is None:
        return None
    require(isinstance(value, str) and len(value) <= limit
            and not any(0xD800 <= ord(c) <= 0xDFFF or (ord(c) < 32 and c not in "\n\r\t") for c in value),
            f"invalid {label} text")
    return value


def _label(value, label, *, optional=False):
    value = _text(value, label, optional=optional, limit=512)
    if value is not None:
        require(not value.startswith(("/", "~/", "\\\\"))
                and not re.match(r"^[A-Za-z]:[\\/]", value), f"private path in {label}")
    return value


def _strings(value, label):
    require(type(value) is list and len(value) <= 4096, f"invalid {label} list")
    return [_label(item, label) for item in value]


def _vector(value, label, size=None):
    require(type(value) is list and len(value) <= 4096
            and (size is None or len(value) == size), f"invalid {label} vector")
    require(all(type(item) in (int, float) and math.isfinite(item) for item in value),
            f"nonfinite/nonnumeric {label} vector")
    return list(value)


def _floats(vector, label):
    """Numeric value of a checked vector, as the runner's ledger records it."""
    try:
        values = [float(item) for item in vector]
    except OverflowError:
        values = None
    require(values is not None and all(math.isfinite(item) for item in values), f"nonfinite {label} vector")
    return values


def _usage(value):
    if value is None:
        return dict.fromkeys(USAGE_ORDER)
    checked = audit_usage(value)
    return {key: checked[key] for key in USAGE_ORDER}


def _contracts(manifest):
    obs = _object(manifest.get("observation_spec"), "observation specification")
    require(obs.get("privileged") is False, "only declared non-privileged observations may be exported")
    public_obs = {key: _strings(obs.get(key, []), key) for key in ("cameras", "state_names", "modalities")}
    public_obs["control_feedback_schema"] = _label(obs.get("control_feedback_schema"), "feedback schema", optional=True)
    action = _object(manifest.get("action_spec"), "action specification")
    size = counter(action.get("size"), "action dimension")
    require(0 < size <= 4096, "action dimension is outside the report bound")
    public_action = {key: _label(action.get(key), key, optional=True)
                     for key in ("mode", "frame", "rotation", "gripper")}
    public_action.update(size=size, names=_strings(action.get("names", []), "action names"))
    require(not public_action["names"] or len(public_action["names"]) == size, "action names/dimension mismatch")
    for key in ("low", "high"):
        public_action[key] = None if action.get(key) is None else _vector(action[key], key, size)
    hz = action.get("control_hz")
    require(hz is None or (type(hz) in (int, float) and math.isfinite(hz) and hz > 0), "invalid control frequency")
    public_action["control_hz"] = hz
    return {"observation": public_obs, "action": public_action}


def _observation(value, contracts, *, origin, expected_step):
    value = _object(value, "observation")
    step = counter(value.get("step"), "observation step")
    cameras = _strings(value.get("camera_names", []), "camera names")
    declared = contracts["observation"]
    require(len(cameras) == len(set(cameras)) and set(cameras) == set(declared["cameras"]),
            "observation cameras differ from declaration")
    state = value.get("state")
    if state is not None:
        state = _vector(state, "robot state", len(declared["state_names"]))
    else:
        require(not declared["state_names"], "declared robot state is missing")
    feedback = value.get("control_feedback")
    return {"origin": origin, "step": step, "acknowledged_controls": expected_step,
            "instruction": _text(value.get("instruction"), "task instruction"),
            "state": state, "camera_names": cameras, "images": "not_included",
            "robot_feedback": {"schema": declared["control_feedback_schema"],
                               "availability": "recorded_payload_not_projected" if feedback is not None else "not_recorded"}}


def _structured_output(event, action_size):
    """The accepted robot_act submission, never arbitrary metadata or provider text.

    Request IDs and receipt/accounting envelopes are intentionally not copied.
    Unknown shapes remain unavailable rather than becoming arbitrary JSON.
    ``action_size`` is the run's declared action dimension.
    """
    metadata = _object(event.get("metadata", {}), "decision metadata")
    value = metadata.get("structured_output")
    if value is None:
        return {"availability": "not_recorded", "content": None}
    if type(value) is not dict or set(value) != {"request_id", "actions", "reason", "stop_reason", "steps"}:
        return {"availability": "unsupported_record_shape", "content": None}
    require(value["reason"] == event.get("note") and value["stop_reason"] == event.get("stop_reason")
            and (value["stop_reason"] is not None) == event["stop"], "structured output differs from decision")
    require(type(value["actions"]) is list and len(value["actions"]) <= 10000, "invalid recorded output actions")
    content = {"actions": [_floats(_vector(v, "output action", action_size), "output action")
                           for v in value["actions"]],
               "reason": _text(value["reason"], "model explanation"),
               "stop_reason": _label(value["stop_reason"], "stop reason", optional=True),
               "steps": counter(value["steps"], "output chunk length")}
    require(content["steps"] == len(content["actions"]) == event["chunk_length"],
            "structured output chunk length mismatch")
    return {"availability": "recorded_projection", "content": content}


def _error(value):
    if value is None:
        return None
    value = _object(value, "recorded error")
    category = value.get("category")
    require(category in ERROR_CATEGORIES, "unsupported recorded error category")
    return {"category": category, "details": "recorded_privately"}


def _episode(result, events, contracts):
    calls, current, latest = [], None, None
    aftermath_errors = []
    last_terminal = False
    reconciliation = None
    for event in events[1:-1]:
        kind = event["event"]
        timestamp = _text(event.get("timestamp"), "event timestamp", optional=True, limit=64)
        if kind == "observation":
            latest = _observation(event["observation"], contracts, origin="reset", expected_step=0)
        elif kind == "policy_call_start":
            require(latest is not None, "policy call has no recorded input observation")
            current = {"policy_call": event["policy_call"], "timestamp": timestamp,
                       "input_to_policy": latest, "decision": None, "submitted_actions": None,
                       "actions_availability": "not_recorded", "maximum_executed_prefix": None,
                       "acknowledged_controls": [], "rejection": None, "error": None,
                       "usage": _usage(None), "unacknowledged_actions": []}
            calls.append(current)
            last_terminal = False
        elif kind == "policy_decision":
            current["decision"] = {"note": _text(event.get("note"), "model note", optional=True),
                "stop": event["stop"], "stop_reason": _label(event.get("stop_reason"), "stop reason", optional=True),
                "chunk_length": counter(event["chunk_length"], "proposed chunk length"),
                "structured_output": _structured_output(event, contracts["action"]["size"])}
            current["usage"] = _usage(event.get("usage"))
        elif kind == "action_chunk":
            require(len(event["actions"]) <= 10000, "action chunk exceeds report bound")
            current["submitted_actions"] = [_vector(v, "submitted action", contracts["action"]["size"])
                                            for v in event["actions"]]
            current["actions_availability"] = "recorded"
            current["maximum_executed_prefix"] = event["maximum_executed_prefix"]
            output = current["decision"]["structured_output"]["content"]
            if output is not None:
                require(output["actions"] == current["submitted_actions"], "output/action ledger mismatch")
        elif kind == "environment_step":
            latest = _observation(event["observation"], contracts, origin="acknowledged_control",
                                  expected_step=event["environment_step"])
            current["acknowledged_controls"].append({"control": event["environment_step"],
                "chunk_index": event["chunk_index"], "timestamp": timestamp,
                "action": _vector(event["action"], "acknowledged action", contracts["action"]["size"]),
                "observation": latest})
            last_terminal = event["terminated"] or event["truncated"]
        elif kind == "action_rejected":
            feedback = event["feedback"]
            audit_validation_issue(feedback["issue"])
            current["rejection"] = {"phase": event["phase"], "issue": dict(feedback["issue"]),
                "executed_controls": feedback["executed_steps"], "rejected_actions": feedback["rejected_actions"]}
            if event["usage_recorded_in"] == "action_rejected":
                current["usage"] = _usage(event["usage"])
        elif kind == "usage_reconciliation":
            # Audited before projection; an episode-level fact, not a policy call.
            reconciliation = {"policy_call_sum": _usage(event["policy_call_sum"]),
                              "reported_total": _usage(event["reported_total"]),
                              "reported_complete": event["reported_complete"],
                              "inconsistent_fields": list(event["inconsistent_fields"])}
        elif kind == "artifact_error":
            # Collection happens in finally, after the control loop. It must
            # not replace a primary failure or imply another attempted action.
            aftermath_errors.append({"stage": "artifact_collection", **_error(event["error"])})
        elif kind == "error":
            decision = current["decision"] if current is not None else None
            finished = current is not None and (last_terminal or current["rejection"] is not None
                or (decision is not None and decision["stop"])
                or (current["maximum_executed_prefix"] is not None and
                    len(current["acknowledged_controls"]) == current["maximum_executed_prefix"]))
            if current is None or finished:
                aftermath_errors.append({"stage": "before_policy_call" if current is None else "after_call",
                                         **_error(event["error"])})
                continue
            current["error"] = current["error"] or _error(event["error"])
            typed = event["error"]
            if typed.get("type") == "ActionRejected" and typed.get("action_rejection_phase") in {"policy_act", "session_step"}:
                audit_validation_issue(typed["issue"])
                current["rejection"] = {"phase": typed["action_rejection_phase"], "issue": dict(typed["issue"]),
                    "executed_controls": len(current["acknowledged_controls"]),
                    "rejected_actions": result["rejected_actions"]}
            if "usage" in event["error"] and current["decision"] is None:
                current["usage"] = _usage(event["error"]["usage"])
        if current is not None:
            current["_terminal"] = last_terminal

    for call in calls:
        terminal = call.pop("_terminal", False)
        actions = call["submitted_actions"]
        if actions is None:
            continue
        acknowledged = len(call["acknowledged_controls"])
        prefix = call["maximum_executed_prefix"]
        rejection = call["rejection"]
        for index in range(acknowledged, len(actions)):
            if index >= prefix:
                status = "not_selected_for_execution"
            elif rejection is not None and rejection["phase"] == "session_step" and index == acknowledged:
                status = "rejected_without_execution"
            elif terminal or rejection is not None:
                status = "not_attempted"
            elif call["error"] is not None and index == acknowledged:
                status = "execution_not_confirmed_attempt_not_recorded"
            else:
                status = "not_attempted"
            call["unacknowledged_actions"].append({"chunk_index": index, "status": status})
    spec = result["episode"]
    seed = spec.get("seed")
    require(seed is None or type(seed) is int, "invalid recorded seed")
    final_error = result.get("error")
    if final_error is not None:
        final_error = _object(final_error, "episode error")
        if final_error.get("type") == "CleanupError" or final_error.get("cleanup_errors"):
            aftermath_errors.append({"stage": "cleanup", "category": "infrastructure", "details": "recorded_privately"})
    return {"episode_id": _label(spec["id"], "episode ID"), "task": _label(spec["task"], "task"),
            "instruction": _text(spec.get("instruction"), "task instruction", optional=True),
            "seed": seed, "status": result["status"], "success": result["success"],
            "termination_reason": _label(result["termination_reason"], "termination reason"),
            "error": _error(final_error), "aftermath_errors": aftermath_errors,
            "counters": {"policy_calls": result["policy_calls"], "controls": result["environment_steps"],
                         "action_decisions": result["action_decisions"], "rejected_actions": result["rejected_actions"]},
            "usage": _usage(result["usage"]), "usage_reconciliation": reconciliation, "calls": calls,
            "media": {"images": "not_included", "video": "not_included"}}


def _build_history(run_dir):
    files = _Files(run_dir)
    status = _object(files.json("status.json"), "run status")
    require(status.get("status") in {"completed", "completed_with_errors"}, "only closed runs may be exported")
    manifest = _object(files.json("manifest.json"), "manifest")
    require(manifest.get("schema_version") == "starvla-rsi.eval/v1", "unsupported run schema")
    protocol = _object(manifest.get("protocol"), "protocol")
    policy = _object(manifest.get("policy"), "policy")
    _object(policy.get("parameters", {}), "policy parameters")
    descriptor = _object(manifest.get("benchmark"), "benchmark")
    contracts = _contracts(manifest)
    require(contracts["observation"]["control_feedback_schema"] == protocol.get("control_feedback_schema"),
            "public control channel binding mismatch")
    results = files.jsonl("episodes.jsonl")
    require(0 < len(results) <= MAX_EPISODES and len(results) == counter(status.get("episodes_written"), "written episodes"),
            "closed episode count mismatch")
    for row in results:
        _object(row, "episode result")
        _object(row.get("episode"), "episode identity")
        _object(row.get("metrics"), "episode metrics")
    ids = [row["episode"]["id"] for row in results]
    planned = protocol.get("episode_ids")
    require(type(planned) is list and 0 < len(planned) <= MAX_EPISODES and len(set(planned)) == len(planned),
            "invalid selected episode schedule")
    require(len(ids) == len(set(ids)) and ids == planned[:len(ids)], "episode index/schedule mismatch")
    episode_root = files.root / "episodes"
    require(episode_root.is_dir() and not episode_root.is_symlink(), "invalid episode directory")
    paths = sorted(episode_root.glob("*/result.json"))
    require(len(paths) == len(results), "episode directory/index count mismatch")
    found = {}
    for path in paths:
        relative = path.relative_to(files.root).as_posix()
        result = files.json(relative)
        identity = result["episode"]["id"]
        require(identity not in found, "duplicate episode directory identity")
        found[identity] = result, path.parent.relative_to(files.root).as_posix()
    episodes = []
    for indexed in results:
        require(indexed["episode"]["id"] in found, "indexed episode has no result")
        result, directory = found[indexed["episode"]["id"]]
        require(result == indexed, "episode index/result mismatch")
        events = files.jsonl(directory + "/events.jsonl")
        require(len(events) <= MAX_EVENTS, "episode event count exceeds report bound")
        for event in events:
            _object(event, "event")
            if event.get("event") in ("observation", "environment_step"):
                _object(event.get("observation"), "recorded observation")
            if event.get("event") in ("error", "artifact_error"):
                _object(event.get("error"), "recorded error")
        audit_episode(result, events, protocol)
        episodes.append(_episode(result, events, contracts))
    completed = sum(row["status"] == "completed" for row in results)
    require(status["status"] == ("completed" if completed == len(results) else "completed_with_errors"),
            "run/episode lifecycle mismatch")
    if len(results) != len(planned):
        require(protocol.get("fail_fast") is True and results[-1]["status"] == "error", "selected episodes silently omitted")
    summary = _object(files.json("summary.json"), "summary")
    require(summary.get("run_id") == manifest.get("run_id"), "summary/manifest run identity mismatch")
    require(summary.get("benchmark") == manifest.get("benchmark", {}).get("name")
            and summary.get("policy") == policy.get("name"), "summary/manifest benchmark or policy mismatch")
    counts = {"attempted": len(results), "completed": completed, "errors": len(results) - completed,
              "successes": sum(row["success"] is True for row in results),
              "policy_calls": sum(row["policy_calls"] for row in results)}
    for key, expected in counts.items():
        require(counter(summary.get(key), "summary " + key) == expected, "summary " + key + " mismatch")
    require(counter(summary.get("rejected_actions"), "summary rejections") == sum(row["rejected_actions"] for row in results),
            "summary rejected actions mismatch")
    usage = {key: 0 for key in USAGE_FIELDS}
    for result in results:
        usage = sum_usage(usage, audit_usage(result["usage"]))
    require("usage" in summary, "summary usage missing")
    require(same_usage(summary["usage"], usage), "summary usage mismatch")
    usage_incomplete = sum(result["usage_reported_complete"] is False or bool(result["usage_inconsistent_fields"])
                           for result in results)
    require(counter(summary.get("usage_incomplete_episodes"), "summary incomplete usage") == usage_incomplete,
            "summary incomplete usage count mismatch")
    public_protocol = {"invalid_action_handling": _label(protocol.get("invalid_action_handling"),
                                                         "invalid_action_handling", optional=True)}
    for key in ("max_steps", "max_policy_calls", "replan_interval"):
        public_protocol[key] = None if protocol.get(key) is None else counter(protocol[key], key)
    history = {"schema_version": SCHEMA, "run_id": _label(manifest.get("run_id"), "run ID"),
        "benchmark": {key: _label(descriptor.get(key), key, optional=True)
                      for key in ("name", "version", "protocol_version", "source_revision")},
        "policy": {key: _label(policy.get(key), key, optional=True)
                   for key in ("name", "kind", "version", "provider", "model")},
        "identity_evidence": "recorded_declaration_only", "contracts": contracts, "protocol": public_protocol,
        "outcome": {"scope": "client_selected_schedule", "planned": len(planned),
                    "unattempted": len(planned) - len(results), **counts},
        "usage": _usage(summary["usage"]), "usage_incomplete_episodes": usage_incomplete, "episodes": episodes,
        "record_check": "closed_lifecycle_and_episode_ledger_consistent",
        "limitations": list(LIMITATIONS)}
    files.verify_unchanged()
    return history, files


def render_html(history: dict) -> str:
    """Render a portable, script-free view; all recorded content is escaped."""
    def esc(value):
        return html.escape(str(value), quote=True)

    def record(value):
        return "<pre>" + esc(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)) + "</pre>"

    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">",
        "<title>Interaction history</title><style>body{font:16px system-ui;margin:2rem auto;padding:0 1rem;max-width:1000px;color:#17232b}",
        "article,section{border:1px solid #ccd5db;border-radius:8px;padding:1rem;margin:1rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:1rem}",
        "summary{cursor:pointer}h1,h2,h3{line-height:1.3}.muted{color:#51616c}</style>",
        "<h1>Interaction history</h1><p>" + esc(history["run_id"]) + "</p>",
        "<p class='muted'>Recorded policy inputs, proposed actions, acknowledged controls and task outcomes.</p>",
        "<h2>Client-selected schedule outcome</h2>", record(history["outcome"]),
        "<details><summary>Protocol, declared identity and action/state semantics</summary>",
        record({key: history[key] for key in ("benchmark", "protocol", "policy", "identity_evidence", "contracts", "usage")}), "</details>"]
    for episode in history["episodes"]:
        parts.extend(["<section><h2>" + esc(episode["task"]) + "</h2>",
            record({key: value for key, value in episode.items() if key != "calls"}),
            "<p class='muted'>Images and video are not included. Control observations below are execution records; only call inputs are supplied to Policy.act.</p>"])
        for call in episode["calls"]:
            parts.extend(["<article><h3>Policy call " + esc(call["policy_call"]) + "</h3>",
                "<details open><summary>Input supplied to Policy.act</summary>", record(call["input_to_policy"]), "</details>",
                "<details open><summary>Recorded output and submitted actions</summary>",
                record({key: call[key] for key in ("decision", "actions_availability", "submitted_actions", "maximum_executed_prefix")}), "</details>",
                "<details><summary>Acknowledged execution and feedback</summary>",
                record({key: call[key] for key in ("acknowledged_controls", "unacknowledged_actions", "rejection", "error", "usage")}),
                "</details></article>"])
        parts.append("</section>")
    parts.extend(["<h2>Coverage and evidence limits</h2><ul>"])
    parts.extend("<li>" + esc(item) + "</li>" for item in history["limitations"])
    parts.append("</ul></html>\n")
    return "\n".join(parts)


def export_history(run_dir: Path, output_dir: Path) -> dict:
    """Write a fresh presentation outside the source; never copy raw artifacts."""
    source = Path(run_dir).resolve(strict=True)
    output = Path(output_dir).absolute()
    for parent in (output, *output.parents):
        require(not parent.is_symlink(), "output path must not contain symlinks")
    require(not output.resolve().is_relative_to(source), "output must be outside the closed run")
    require(not output.exists(), "output directory must be new")
    history, files = _build_history(run_dir)
    encoded = json.dumps(history, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    page = render_html(history)
    files.verify_unchanged()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rsi-interaction-", dir=output.parent) as temporary:
        staged = Path(temporary) / "view"
        staged.mkdir()
        for name, payload in (("history.json", encoded), ("index.html", page)):
            with (staged / name).open("x", encoding="utf-8") as stream:
                stream.write(payload)
        files.verify_unchanged()
        # Claim a fresh destination, then replace only our own empty directory
        # with the completed view. A verification failure publishes no files.
        output.mkdir(exist_ok=False)
        try:
            os.replace(staged, output)
        except OSError:
            output.rmdir()  # Only the empty directory this invocation created.
            raise
    return history


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="explicit closed client-run root")
    parser.add_argument("--output-dir", type=Path, required=True, help="new presentation directory outside the run")
    args = parser.parse_args(argv)
    try:
        history = export_history(args.run_dir, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        parser.exit(2, "Interaction export rejected: invalid, unsafe, changed or inconsistent closed records.\n")
    print(json.dumps({"run_id": history["run_id"], "episodes": len(history["episodes"]),
                      "files": ["history.json", "index.html"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
