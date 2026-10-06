#!/usr/bin/env python3
"""Snapshot participant campaign coverage; infrastructure diagnostics have no score here."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re


def local_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = local_module("coverage_record_audit", "../audits/closed_run.py")
progress = local_module("coverage_progress", "progress.py")

FIELDS = (
    "case_index", "task", "protocol_version", "reference_horizon", "reference_horizon_source",
    "decision_limit", "control_limit", "replan_prefix", "attempt_status", "record_consistency", "episode_status",
    "native_final_success", "controls", "decisions", "first_success_control",
    "first_success_decision", "complete_step_coverage", "termination_reason", "issue", "evidence_caveats",
)


def bounded_text(value, limit: int) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not any(0xD800 <= ord(char) <= 0xDFFF for char in value))


def same_json(left, right) -> bool:
    """Keep boolean, integer and floating-point declarations distinct."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def infrastructure_diagnostic(manifest: dict) -> bool:
    policy = manifest.get("policy", {})
    policy = policy if isinstance(policy, dict) else {}
    parameters = policy.get("parameters", {})
    parameters = parameters if isinstance(parameters, dict) else {}
    return (manifest.get("purpose") == "infrastructure_validation_only"
            or parameters.get("purpose") == "infrastructure_validation_only"
            or policy.get("name") == "constant-action-diagnostic")


def bind_policy(source: dict, manifest: dict) -> None:
    """Compare retained declarations, without loading a model or rewriting old schemas."""
    expected, actual = manifest.get("policy"), source.get("policy")
    audit.require(isinstance(expected, dict) and isinstance(actual, dict), "missing campaign/run policy identity")
    for key in ("name", "kind"):
        audit.require(isinstance(expected.get(key), str) and bool(expected[key].strip())
                      and same_json(actual.get(key), expected[key]), f"campaign/run policy {key} mismatch")
    # Old campaigns do not declare the transport version; only bind optional
    # fields they actually contain. Missing model/provider remains unknown.
    for key in (set(expected) | {"model", "provider"}) - {"name", "kind", "parameters"}:
        audit.require(same_json(actual.get(key), expected.get(key)), f"campaign/run policy {key} mismatch")
    declared, parameters = expected.get("parameters", {}), actual.get("parameters", {})
    audit.require(isinstance(declared, dict) and isinstance(parameters, dict), "invalid campaign/run policy parameters")
    for key, value in declared.items():
        audit.require(key in parameters and same_json(parameters[key], value),
                      f"campaign/run policy parameter {key} mismatch")
    audit.require(same_json(parameters.get("purpose"), declared.get("purpose")),
                  "campaign/run policy diagnostic purpose mismatch")
    audit.require(not infrastructure_diagnostic(source),
                  "infrastructure diagnostic run cannot count as participant coverage")
    for key in ("model_profile", "policy_stop_rule"):
        if key in manifest or key in parameters:
            audit.require(isinstance(manifest.get(key), dict) and isinstance(parameters.get(key), dict)
                          and same_json(parameters[key], manifest[key]), f"campaign/run {key} mismatch")
    if "policy_prompt" in manifest or "policy_prompt_sha256" in manifest:
        prompt_hash = manifest.get("policy_prompt_sha256")
        if "policy_prompt" in manifest:
            prompt = manifest["policy_prompt"]
            audit.require(isinstance(prompt, str), "invalid campaign policy prompt")
            computed = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            audit.require(prompt_hash is None or prompt_hash == computed, "campaign policy prompt digest mismatch")
            prompt_hash = computed
        audit.require(isinstance(prompt_hash, str) and re.fullmatch(r"[0-9a-f]{64}", prompt_hash)
                      and parameters.get("prompt_sha256") == prompt_hash, "campaign/run policy prompt mismatch")
    if "policy_parameters" in manifest:
        settings = manifest["policy_parameters"]
        audit.require(isinstance(settings, dict), "invalid campaign policy configuration")
        for key, value in settings.items():
            recorded = (parameters.get("policy_stop_rule", {}) if key == "min_action_decisions_before_give_up"
                        else parameters)
            audit.require(isinstance(recorded, dict) and key in recorded and same_json(recorded[key], value),
                          f"campaign/run policy configuration {key} mismatch")
    # Historical v1 stopping metadata stays in its original protocol domain.
    protocol = source["protocol"]
    for key in ("min_action_decisions_before_give_up", "stop_constraint_version", "early_policy_stop_exception"):
        if key in manifest or key in protocol:
            default = 0 if key == "min_action_decisions_before_give_up" else None
            audit.require(same_json(protocol.get(key, default), manifest.get(key, default)),
                          f"campaign/run historical policy configuration {key} mismatch")


def attach_caveats(rows: list[dict], campaign: Path, campaign_digest: str,
                   source: Path | None) -> dict | None:
    """Attach operator annotations without changing a result or following evidence links."""
    if source is None:
        return None
    source = source.absolute()
    audit.require(not source.resolve().is_relative_to(campaign), "caveat source must be outside campaign")
    files = audit.ClosedFiles(source.parent)
    payload = files.raw(source.name)
    audit.require(len(payload) <= 1024 * 1024, "caveat source exceeds 1 MiB")
    document = audit.decode(payload.decode("utf-8"))
    audit.require(isinstance(document, dict) and set(document) == {
        "schema_version", "campaign_sha256", "entries"}, "invalid caveat document fields")
    audit.require(document["schema_version"] == "starvla-rsi.evidence-caveats/v1",
                  "unsupported caveat schema")
    audit.require(document["campaign_sha256"] == campaign_digest, "caveat campaign mismatch")
    entries = document["entries"]
    audit.require(isinstance(entries, list) and len(entries) <= len(rows) * 16,
                  "invalid caveat entry list")
    seen = set()
    for entry in entries:
        audit.require(isinstance(entry, dict) and set(entry) == {
            "case_index", "category", "note", "declared_evidence"}, "invalid caveat entry fields")
        index, category = entry["case_index"], entry["category"]
        audit.require(type(index) is int and 0 <= index < len(rows), "invalid caveat case index")
        audit.require(rows[index]["attempt_status"] in ("completed", "infrastructure_or_policy_error"),
                      "caveats require a validated terminal outcome; active/unattempted/invalid cases are not annotated")
        audit.require(isinstance(category, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", category),
                      "invalid caveat category")
        audit.require((index, category) not in seen, "duplicate case/category caveat")
        seen.add((index, category))
        audit.require(len(rows[index]["evidence_caveats"]) < 16, "too many caveats for one case")
        audit.require(bounded_text(entry["note"], 2048),
                      "invalid caveat note")
        evidence = entry["declared_evidence"]
        audit.require(isinstance(evidence, list) and 0 < len(evidence) <= 16, "invalid caveat evidence list")
        for item in evidence:
            audit.require(isinstance(item, dict) and set(item) == {"reference", "sha256"},
                          "invalid declared evidence fields")
            audit.require(bounded_text(item["reference"], 512),
                          "invalid declared evidence reference")
            audit.require(isinstance(item["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                          "invalid declared evidence hash")
        # Deliberately never merge arbitrary input keys into the score/counter row.
        rows[index]["evidence_caveats"].append(entry)
    files.verify_unchanged()
    return {"path": str(files.root / source.name), "sha256": files.hashes[source.name],
            "entries": len(entries), "annotated_cases": len({index for index, _ in seen}),
            "interpretation": "Operator annotations only; evidence references/hashes are declared, not followed or verified here; no score or denominator is changed."}


def closed_case(files, case: dict, manifest: dict, digest: str) -> dict:
    directory = case["case_id"]
    attempt = files.json(f"{directory}/attempt.json")
    audit.require(attempt["case_index"] == case["index"] and attempt["attempt"] == 1
                  and attempt["campaign_sha256"] == digest, "attempt/campaign mismatch")
    outcome = files.json(f"{directory}/outcome.json")
    audit.require(outcome["case_index"] == case["index"], "outcome case mismatch")
    audit.require(outcome["status"] in ("completed", "infrastructure_or_policy_error"),
                  "unsupported terminal outcome")
    row = {"attempt_status": outcome["status"], "record_consistency": "unavailable"}
    run = files.root / directory / "run"
    status_path = run / "status.json"
    if not status_path.exists():
        audit.require(outcome["status"] != "completed", "completed outcome has no closed run")
        return {**row, "issue": "terminal error has no closed runner record; attempt retained"}
    status = files.json(f"{directory}/run/status.json")
    audit.require(isinstance(status, dict), "closed runner status must be a JSON object")
    if status.get("status") not in ("completed", "completed_with_errors"):
        audit.require(outcome["status"] != "completed", "completed outcome has an unclosed run")
        return {**row, "issue": "terminal error has an incomplete runner record; attempt retained"}

    checked = audit.audit_run(run)
    for relative, expected in checked["read_file_sha256"].items():
        bound = f"{directory}/run/{relative}"
        files.raw(bound)
        audit.require(files.hashes[bound] == expected, "closed evidence changed after audit")
    records = files.jsonl(f"{directory}/run/episodes.jsonl")
    audit.require(len(records) == 1 and records[0]["episode"] == case["episode"],
                  "run episode differs from frozen case")
    source = files.json(f"{directory}/run/manifest.json")
    bind_policy(source, manifest)
    audit.require(source["benchmark"] == case["descriptor"]
                  and source["benchmark"]["name"] == manifest["benchmark"], "benchmark descriptor mismatch")
    for key in ("seed", "budget_mode", "max_policy_calls", "replan_interval", "max_steps"):
        audit.require(source["protocol"][key] == manifest[key], f"frozen {key} mismatch")
    audit.require(source["harness_source"]["inventory_sha256"] ==
                  manifest["harness_source"]["inventory_sha256"], "campaign/run source mismatch")
    summary = files.json(f"{directory}/run/summary.json")
    audit.require(outcome["summary"] == summary, "outcome/run summary mismatch")
    expected = (outcome["returncode"] == 0 and not outcome["timed_out"] and summary["errors"] == 0)
    audit.require((outcome["status"] == "completed") == expected, "outcome lifecycle mismatch")

    timing = progress.summarize_progress(run)["episodes"]
    audit.require(len(timing) == 1 and timing[0]["episode"] == records[0]["episode"],
                  "progress episode mismatch")
    timing = timing[0]
    record = records[0]
    return {**row, "record_consistency": "passed", "episode_status": record["status"],
            "native_final_success": record["success"], "controls": record["environment_steps"],
            "decisions": record["policy_calls"],
            "first_success_control": timing["first_native_success_step"],
            "first_success_decision": timing["policy_call_at_first_native_success"],
            "complete_step_coverage": timing["complete_step_coverage"],
            "termination_reason": record["termination_reason"],
            "record_auditor_sha256": checked["auditor"]["sha256"]}


def summarize(campaign: Path, caveats: Path | None = None) -> dict:
    # An external reporter may intentionally use campaign-frozen audit modules.
    # Record the actual loaded locations instead of assuming one repository root.
    tool_paths = {"benchkit/audits/closed_run.py": Path(audit.__file__).resolve(),
                  "benchkit/reports/progress.py": Path(progress.__file__).resolve(),
                  "benchkit/reports/coverage.py": Path(__file__).resolve()}
    tool_hashes = {relative: hashlib.sha256(path.read_bytes()).hexdigest()
                   for relative, path in tool_paths.items()}
    files = audit.ClosedFiles(campaign)
    manifest = files.json("campaign.json")
    digest = files.hashes["campaign.json"]
    audit.require(files.json("campaign_digest.json")["sha256"] == digest, "campaign digest mismatch")
    audit.require(manifest["schema_version"] in {"starvla-rsi.campaign/v1", "starvla-rsi.campaign/v2", "starvla-rsi.campaign/v3"}, "unsupported campaign")
    audit.require(not infrastructure_diagnostic(manifest),
                  "participant coverage does not accept infrastructure diagnostic campaigns; preserve their raw records separately")
    cases = manifest["cases"]
    audit.require(len(cases) == manifest["planned_cases"] and len(cases) > 0, "denominator mismatch")
    audit.require([case["index"] for case in cases] == list(range(len(cases))), "case order mismatch")
    audit.require([case["case_id"] for case in cases] == [f"case-{i:03d}" for i in range(len(cases))],
                  "unsafe or mismatched case identity")
    audit.require(not {p.name for p in files.root.glob("case-*")} - {c["case_id"] for c in cases},
                  "unplanned case claim outside frozen denominator")
    rows = []
    for case in cases:
        row = {key: None for key in FIELDS}
        row["evidence_caveats"] = []
        metadata = case["episode"].get("metadata", {})
        row.update(case_index=case["index"], task=case["episode"]["task"],
                   protocol_version=case["descriptor"]["protocol_version"],
                   reference_horizon=metadata.get("native_horizon", metadata.get("reference_native_horizon")),
                   reference_horizon_source=metadata.get("native_horizon_source"),
                   decision_limit=manifest["max_policy_calls"], control_limit=manifest["max_steps"],
                   replan_prefix=manifest["replan_interval"])
        directory = files.root / case["case_id"]
        if not directory.exists() and not directory.is_symlink():
            row.update(attempt_status="unattempted", record_consistency="not_checked")
        elif directory.is_symlink() or not directory.is_dir():
            row.update(attempt_status="invalid_evidence", record_consistency="failed",
                       issue="case claim is not a plain directory")
        elif not (directory / "outcome.json").exists() and not (directory / "outcome.json").is_symlink():
            # No episode/event reads while the attempt may still be active.
            row.update(attempt_status="claimed_without_terminal_outcome", record_consistency="not_checked")
        else:
            try:
                row.update(closed_case(files, case, manifest, digest))
            except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
                row.update(attempt_status="invalid_evidence", record_consistency="failed",
                           issue=f"{type(exc).__name__}: {exc}")
        rows.append(row)
    caveat_source = attach_caveats(rows, files.root, digest, caveats)
    files.verify_unchanged()
    for relative, digest_now in tool_hashes.items():
        audit.require(hashlib.sha256(tool_paths[relative].read_bytes()).hexdigest() == digest_now,
                      "reporting tool changed during snapshot")
    counts = {name: sum(row["attempt_status"] == name for row in rows) for name in (
        "completed", "infrastructure_or_policy_error", "claimed_without_terminal_outcome",
        "unattempted", "invalid_evidence")}
    counts.update(planned=len(rows),
                  native_successes=sum(row["native_final_success"] is True for row in rows),
                  native_failures=sum(row["native_final_success"] is False for row in rows))
    return {"schema_version": "starvla-rsi.coverage-snapshot/v1",
            "created_at": datetime.now(timezone.utc).isoformat(), "campaign": str(files.root),
            "campaign_sha256": digest, "benchmark": manifest["benchmark"], "counts": counts,
            "tool_source_paths": {relative: str(path) for relative, path in tool_paths.items()},
            "cases": rows, "read_file_sha256": files.hashes,
            "caveat_source": caveat_source,
            "tool_sha256": tool_hashes,
            "limitations": [
                "Non-atomic live-campaign snapshot: unattempted/active cases may advance after inspection.",
                "Only terminal closed runner records are inspected; no simulator, scorer, mailbox or video is read.",
                "Declared policy identity, profile, prompt and stopping settings are bound to the campaign; mailbox/timeout/chunk settings require a separate policy/artifact audit.",
                "Full frozen denominator retained; invalid or incomplete evidence is not a retry or exclusion.",
                "Optional caveats preserve raw native outcomes; missing/empty caveats do not certify clean evidence or rendering quality.",
                "First success is diagnostic, not final scoring; null is unknown or no logged success, never zero.",
                "No named provider score, native parity, OS isolation or actor-context blinding attestation."]}


def csv_value(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = str(value)
    # Spreadsheet formula prevention; exact original strings remain in JSON.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def write_snapshot(report: dict, output: Path) -> None:
    audit.require(not output.resolve().is_relative_to(Path(report["campaign"]).resolve()),
                  "snapshot directory must be outside the source campaign")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "coverage.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (output / "tasks.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({key: csv_value(row.get(key)) for key in FIELDS} for row in report["cases"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path, help="new private directory outside source campaign")
    parser.add_argument("--caveats", type=Path, help="optional external campaign-bound operator annotations; never score edits")
    args = parser.parse_args()
    report = summarize(args.campaign, args.caveats)
    write_snapshot(report, args.output_dir)
    print(json.dumps(report["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
