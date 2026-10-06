"""Export a closed run's results without requiring interaction logs or source audits.

Any trusted driver may emit the documented JSON record contract. Python Policy,
model transcripts, event streams and source snapshots are not admission gates.
Validation here establishes record consistency, not native/provider attestation.
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

from benchkit.audits.closed_run import ClosedFiles, counter, require
from benchkit.methods import (USAGE_FIELDS, method_from_policy, normalize_method,
                             normalize_usage, normalize_component_usage, sum_component_usage)

SCHEMA = "starvla-rsi.basic-result/v1"
MAX_BYTES = 128 * 1024 * 1024
MAX_EPISODES = 10000


class _Files(ClosedFiles):
    def __init__(self, root):
        require(not Path(root).is_symlink(), "run root must not be a symlink")
        super().__init__(Path(root))
        self.sizes = {}
        self.total = 0

    def raw(self, relative):
        size = self.path(relative).stat().st_size
        require(self.total + size <= MAX_BYTES, "result input exceeds total byte limit")
        data = super().raw(relative)
        self.total += len(data)
        self.sizes[relative] = len(data)
        require(self.total <= MAX_BYTES, "result input exceeds total byte limit")
        return data

    def verify_unchanged(self):
        for relative, expected in self.hashes.items():
            path = self.path(relative)
            remaining = self.sizes[relative]
            require(path.stat().st_size == remaining, "record changed during export")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while remaining:
                    block = stream.read(min(65536, remaining))
                    require(bool(block), "record changed during export")
                    remaining -= len(block)
                    digest.update(block)
                require(not stream.read(1), "record changed during export")
            require(digest.hexdigest() == expected, "record changed during export")


def _object(value, label):
    require(type(value) is dict, label + " must be an object")
    return value


def _text(value, label, *, optional=False):
    if optional and value is None:
        return None
    require(isinstance(value, str) and 0 < len(value) <= 4096
            and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value),
            "invalid " + label)
    require(not value.startswith(("/", "~/", "\\\\"))
            and re.match(r"^[A-Za-z]:[\\/]", value) is None, "private path in " + label)
    return value


def _same(left, right):
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) is dict and type(right) is dict:
        return set(left) == set(right) and all(_same(left[k], right[k]) for k in left)
    if type(left) in (float, int) and type(right) in (float, int):
        return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
    return left == right


def _sum_usage(rows):
    out = dict.fromkeys(USAGE_FIELDS, 0)
    for row in rows:
        usage = normalize_usage(row.get("usage"))
        out = {key: None if out[key] is None or usage[key] is None else out[key] + usage[key]
               for key in USAGE_FIELDS}
    return out


def _metric_keys(values):
    require(isinstance(values, (tuple, list)) and len(values) <= 64, "invalid metric selection")
    require(all(isinstance(key, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", key)
                for key in values), "invalid metric key")
    require(len(values) == len(set(values)), "duplicate metric selection")
    return list(values)


def _public_contracts(manifest):
    result = {}
    for name, labels, lists in (("action_spec", ("mode", "frame", "rotation", "gripper"), ("names",)),
                                ("observation_spec", ("control_feedback_schema",),
                                 ("cameras", "state_names", "modalities"))):
        value = _object(manifest.get(name), name)
        row = {key: _text(value.get(key), key, optional=True) for key in labels}
        for key in lists:
            items = value.get(key, [])
            require(type(items) is list and len(items) <= 4096, "invalid contract list")
            row[key] = [_text(item, key) for item in items]
        if name == "action_spec":
            row["size"] = counter(value.get("size"), "action size")
            require(0 < row["size"] <= 4096, "invalid action size")
            require(not row["names"] or len(row["names"]) == row["size"], "action names/dimension mismatch")
            hz = value.get("control_hz")
            require(hz is None or type(hz) in (int, float) and math.isfinite(hz) and hz > 0,
                    "invalid control frequency")
            row["control_hz"] = hz
            for key in ("low", "high"):
                bound = value.get(key)
                require(bound is None or type(bound) is list and len(bound) == row["size"]
                        and all(type(v) in (int, float) and math.isfinite(v) for v in bound),
                        "invalid action bounds")
                row[key] = bound
            require((row["low"] is None) == (row["high"] is None), "unpaired action bounds")
            if row["low"] is not None:
                require(all(a <= b for a, b in zip(row["low"], row["high"])), "inverted action bounds")
        else:
            require(value.get("privileged") is False, "undeclared/private observation contract")
            row["privileged"] = False
        result[name] = row
    return result


def _recording(manifest):
    declaration = manifest.get("recording")
    if declaration is None:
        return {"availability": "not_declared", "configuration": None,
                "publication_requirement": False}
    value = _object(declaration, "recording")
    # Only known scalar settings, never paths, arbitrary metadata or receipts.
    allowed = {"mode", "preset", "schema_version", "scope", "source_capture"}
    settings = {key: _text(value[key], "recording " + key) for key in allowed if key in value}
    boolean_options = {"interactions", "model_io", "tool_traces", "images", "videos"}
    for key in boolean_options:
        if key in value:
            require(type(value[key]) is bool, "invalid recording option")
            settings[key] = value[key]
    if "agent_events_written" in value:
        settings["agent_events_written"] = counter(value["agent_events_written"], "agent event count")
    if "warnings" in value:
        warnings = value["warnings"]
        require(type(warnings) is list and len(warnings) <= 16
                and all(isinstance(item, str) and re.fullmatch(r"[a-z_]{1,128}", item) for item in warnings),
                "invalid recording warnings")
        settings["warnings"] = list(warnings)
    return {"availability": "declared_settings_only", "configuration": settings,
            "publication_requirement": False}


def _build_result(run_dir, metrics=()):
    metric_keys = _metric_keys(metrics)
    files = _Files(run_dir)
    status = _object(files.json("status.json"), "status")
    require(status.get("status") in {"completed", "completed_with_errors"}, "run is not closed")
    manifest = _object(files.json("manifest.json"), "manifest")
    require(manifest.get("schema_version") == "starvla-rsi.eval/v1", "unsupported run schema")
    protocol = _object(manifest.get("protocol"), "protocol")
    benchmark = _object(manifest.get("benchmark"), "benchmark")
    policy = _object(manifest.get("policy"), "policy")
    _text(policy.get("name"), "policy name")
    method = normalize_method(manifest["method"]) if "method" in manifest else method_from_policy(policy)
    public_benchmark = {key: _text(benchmark.get(key), key) for key in (
        "name", "version", "protocol_version", "source_revision")}
    contracts = _public_contracts(manifest)
    schedule = protocol.get("episode_ids")
    require(type(schedule) is list and 0 < len(schedule) <= MAX_EPISODES, "invalid episode schedule")
    for identifier in schedule:
        _text(identifier, "episode ID")
    require(len(schedule) == len(set(schedule)), "duplicate scheduled episode")
    rows = files.jsonl("episodes.jsonl")
    require(0 < len(rows) <= len(schedule)
            and len(rows) == counter(status.get("episodes_written"), "written episodes"), "closed episode count mismatch")
    episode_root = files.root / "episodes"
    require(episode_root.is_dir() and not episode_root.is_symlink(), "invalid episodes directory")
    paths = list(episode_root.glob("*/result.json"))
    require(len(paths) == len(rows), "episode directory/index count mismatch")
    indexed = {}
    for path in paths:
        row = _object(files.json(path.relative_to(files.root).as_posix()), "episode result")
        episode = _object(row.get("episode"), "episode")
        identifier = _text(episode.get("id"), "episode ID")
        require(identifier not in indexed, "duplicate episode result identity")
        indexed[identifier] = row
    public_rows = []
    component_usage = {row["id"]: dict.fromkeys(USAGE_FIELDS, 0) for row in method["models"]}
    max_steps = counter(protocol.get("max_steps"), "control budget")
    require(max_steps > 0, "control budget must be positive")
    max_calls = protocol.get("max_policy_calls")
    if max_calls is not None:
        require(counter(max_calls, "decision budget") > 0, "decision budget must be positive")
    for position, row in enumerate(rows):
        row = _object(row, "indexed result")
        require(row.get("schema_version") == "starvla-rsi.eval/v1", "unsupported episode result")
        episode = _object(row.get("episode"), "episode identity")
        identifier = _text(episode.get("id"), "episode ID")
        require(identifier == schedule[position] and indexed.get(identifier) == row,
                "episode index/schedule/result mismatch")
        seed = episode.get("seed")
        require(type(seed) is int, "invalid episode seed")
        counts = {key: counter(row.get(key, 0) if key == "rejected_actions" else row.get(key), key)
                  for key in ("policy_calls", "action_decisions", "environment_steps", "rejected_actions")}
        require(counts["action_decisions"] <= counts["policy_calls"]
                and counts["action_decisions"] <= counts["environment_steps"]
                and counts["rejected_actions"] <= counts["policy_calls"], "inconsistent episode counters")
        require(counts["environment_steps"] <= max_steps
                and (max_calls is None or counts["policy_calls"] <= max_calls), "declared budget exceeded")
        require(row.get("status") in {"completed", "error"}, "invalid episode status")
        completed = row["status"] == "completed"
        success = row.get("success")
        require(type(success) is bool if completed else success is None, "invalid success value")
        require(completed or success is None, "errored episode cannot declare success")
        private_metrics = _object(row.get("metrics"), "metrics")
        if completed:
            require(type(private_metrics.get("success")) is bool
                    and success == private_metrics["success"], "native/result success mismatch")
        error = row.get("error")
        require((error is None) == completed, "episode error/status mismatch")
        public_error = None
        if error is not None:
            _object(error, "error")
            require(error.get("category") in {"policy", "protocol", "infrastructure", "evaluation"}, "invalid error category")
            public_error = {"category": error["category"], "type": _text(error.get("type"), "error type")}
        selected_metrics = {}
        for key in metric_keys:
            number = private_metrics.get(key)
            require(number is None or type(number) in (bool, int, float) and math.isfinite(number),
                    "selected native metric must be a finite numeric/boolean scalar or null")
            selected_metrics[key] = number
        duration = row.get("duration_s")
        require(type(duration) in (int, float) and math.isfinite(duration) and duration >= 0,
                "invalid episode duration")
        component = normalize_component_usage(row.get("component_usage"), method)
        component_usage = sum_component_usage(component_usage, component, method)
        public_rows.append({"id": identifier, "task": _text(episode.get("task"), "task"), "seed": seed,
            "status": row["status"], "success": success,
            "termination_reason": _text(row.get("termination_reason"), "termination reason"),
            "counters": counts, "duration_s": duration, "usage": normalize_usage(row.get("usage")),
            "component_usage": component, "native_metrics": selected_metrics, "error": public_error,
            "recording": _recording(row)})
    completed = sum(row["status"] == "completed" for row in rows)
    successes = sum(row["status"] == "completed" and row["success"] is True for row in rows)
    require(type(protocol.get("fail_fast")) is bool, "invalid fail-fast setting")
    require(len(rows) == len(schedule) or protocol["fail_fast"] and rows[-1]["status"] == "error",
            "unexplained omitted scheduled episodes")
    require(status["status"] == ("completed" if completed == len(rows) else "completed_with_errors"),
            "run/episode status mismatch")
    summary = _object(files.json("summary.json"), "summary")
    require(summary.get("run_id") == manifest.get("run_id")
            and summary.get("benchmark") == benchmark["name"] and summary.get("policy") == policy.get("name"),
            "summary identity mismatch")
    expected = {"attempted": len(rows), "completed": completed, "errors": len(rows) - completed,
                "successes": successes, "policy_calls": sum(row["policy_calls"] for row in rows),
                "rejected_actions": sum(row.get("rejected_actions", 0) for row in rows)}
    for key, number in expected.items():
        require(counter(summary.get(key, 0) if key == "rejected_actions" else summary.get(key), key) == number,
                "summary counter mismatch: " + key)
    usage = _sum_usage(rows)
    require(_same(normalize_usage(summary.get("usage")), usage), "summary usage mismatch")
    if "component_usage" in summary:
        require(_same(normalize_component_usage(summary["component_usage"], method), component_usage),
                "summary component usage mismatch")
    outcome = {"scope": "client_selected_schedule", "planned": len(schedule),
               "unattempted": len(schedule) - len(rows), **expected,
               "action_decisions": sum(row["action_decisions"] for row in rows),
               "environment_steps": sum(row["environment_steps"] for row in rows),
               "success_rate": successes / completed if completed else None,
               "attempt_success_rate": successes / len(rows),
               "selected_success_rate": successes / len(schedule),
               "rate_denominators": {"success_rate": "completed_cases",
                                     "attempt_success_rate": "attempted_cases",
                                     "selected_success_rate": "selected_cases",
                                     "completion_rate": "attempted_cases"},
               "completion_rate": completed / len(rows)}
    for key in ("success_rate", "attempt_success_rate", "selected_success_rate", "completion_rate"):
        if key in summary:
            require(_same(summary[key], outcome[key]), "summary rate mismatch: " + key)
    public_protocol = {key: _text(protocol.get(key), key, optional=True) for key in
                       ("budget_mode", "primary_budget", "invalid_action_handling", "usage_accounting_version")}
    prefix = protocol.get("replan_interval")
    if prefix is not None:
        require(counter(prefix, "action prefix") > 0, "invalid action prefix")
    public_protocol.update(max_steps=max_steps, max_policy_calls=max_calls, replan_interval=prefix)
    method_origin = manifest.get("method_origin", "participant_declaration" if "method" in manifest
                                 else "legacy_policy_projection")
    require(method_origin in {"participant_declaration", "legacy_policy_projection"}, "invalid method origin")
    report = {"schema_version": SCHEMA, "run_id": _text(manifest.get("run_id"), "run ID"),
              "benchmark": public_benchmark, "method": method,
              "method_origin": method_origin,
              "configuration_availability": "participant_supplied" if method_origin == "participant_declaration"
                                            else "not_supplied_in_legacy_identity_projection",
              "identity_evidence": "participant_declaration_not_provider_attestation",
              "protocol": public_protocol, "contracts": contracts, "recording": _recording(manifest),
              "outcome": outcome, "usage": usage, "component_usage": component_usage,
              "episodes": public_rows, "selected_native_metrics": metric_keys,
              "record_check": "closed_result_index_and_summary_consistent",
              "limitations": ["Interaction recording is optional and is not a publication requirement.",
                  "No event, source, provider or native execution audit is implied by this presentation.",
                  "The denominator is the client-selected schedule, not necessarily the entire benchmark.",
                  "Missing usage is unknown, not zero; model composition and usage are reported declarations.",
                  "Native metrics are included only when explicitly selected; no media or raw traces are copied.",
                  "Review public method configuration and text before publishing; key filtering is not secret detection."]}
    files.verify_unchanged()
    return report, files


def build_result(run_dir: Path, *, metrics=()):
    """Read closed results only; interaction/source evidence is never required."""
    return _build_result(run_dir, metrics)[0]


def render_html(report):
    esc = lambda value: html.escape(str(value), quote=True)
    record = lambda value: "<pre>" + esc(json.dumps(value, indent=2, ensure_ascii=False)) + "</pre>"
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>Agent method evaluation result</title><style>',
             'body{max-width:1100px;margin:40px auto;padding:0 20px;font:16px/1.6 system-ui;color:#183044}',
             'pre{background:#f1f5f8;padding:16px;overflow-wrap:anywhere;white-space:pre-wrap}',
             'details{margin:16px 0}summary{cursor:pointer}table{border-collapse:collapse;width:100%}',
             'th,td{text-align:left;padding:8px;border-bottom:1px solid #ddd}</style>',
             '<h1>' + esc(report["method"]["id"]) + ' — ' + esc(report["benchmark"]["name"]) + '</h1>',
             '<p>Run ' + esc(report["run_id"]) + '. Method results, not a bare-model ranking.</p>',
             '<h2>Outcome</h2>',
             '<p><strong>' + esc(report["outcome"]["successes"]) + ' / '
             + esc(report["outcome"]["planned"]) + ' successes / selected cases</strong> ('
             + esc(format(report["outcome"]["selected_success_rate"], ".1%")) + '). '
             + esc(report["outcome"]["errors"]) + ' errors; '
             + esc(report["outcome"]["unattempted"]) + ' unattempted. '
             + 'This denominator is the selected schedule, not necessarily the full benchmark.</p>',
             record(report["outcome"]),
             '<h2>Method and resources</h2>',
             '<p>Configuration: ' + esc(report["configuration_availability"]) + '.</p>', record(report["method"]),
             record({"aggregate_usage": report["usage"], "component_usage": report["component_usage"]}),
             '<h2>Interaction recording</h2><p>Optional; recording availability does not affect publication eligibility.</p>',
             record(report["recording"]), '<h2>Episodes</h2>']
    for episode in report["episodes"]:
        parts += ['<details><summary>' + esc(episode["task"]) + ' · ' + esc(episode["id"])
                  + ' · ' + esc(episode["status"]) + '</summary>', record(episode), '</details>']
    parts += ['<details><summary>Benchmark, protocol and robot capabilities</summary>',
              record({key: report[key] for key in ("benchmark", "protocol", "contracts")}), '</details>',
              '<h2>Interpretation</h2><ul>']
    parts += ['<li>' + esc(item) + '</li>' for item in report["limitations"]]
    return "\n".join(parts + ['</ul></html>'])


def export_result(run_dir: Path, output_dir: Path, *, metrics=()):
    source = Path(run_dir).resolve(strict=True)
    output = Path(output_dir).absolute()
    require(not any(parent.is_symlink() for parent in (output, *output.parents)), "symlink in output path")
    require(not output.resolve().is_relative_to(source), "output must be outside source run")
    require(not output.exists(), "output directory must be new")
    report, files = _build_result(run_dir, metrics)
    encoded = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    page = render_html(report)
    files.verify_unchanged()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rsi-result-", dir=output.parent) as temporary:
        staged = Path(temporary) / "view"
        staged.mkdir()
        for name, payload in (("result.json", encoded), ("index.html", page)):
            with (staged / name).open("x", encoding="utf-8") as stream:
                stream.write(payload)
        files.verify_unchanged()
        output.mkdir(exist_ok=False)
        try:
            os.replace(staged, output)
        except OSError:
            output.rmdir()
            raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="explicit closed client-run directory")
    parser.add_argument("--output-dir", type=Path, required=True, help="new presentation outside the original run")
    parser.add_argument("--metric", action="append", default=[], help="explicit native numeric metric key; repeatable")
    args = parser.parse_args(argv)
    try:
        report = export_result(args.run_dir, args.output_dir, metrics=args.metric)
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        parser.exit(2, "Result export rejected: invalid, unsafe, changed or inconsistent closed records.\n")
    print(json.dumps({"run_id": report["run_id"], "episodes": len(report["episodes"]),
                      "files": ["result.json", "index.html"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
