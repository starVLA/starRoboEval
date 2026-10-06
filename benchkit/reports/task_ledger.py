#!/usr/bin/env python3
"""Offline full-scope continuation coverage; preserve each original protocol."""

from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path


def load_coverage():
    path = Path(__file__).parent / "coverage.py"
    spec = importlib.util.spec_from_file_location("ledger_execution_coverage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


coverage = load_coverage()
audit = coverage.audit
FIELDS = ("selection_index", "disposition", "task_group", "source_campaign",
          "source_campaign_sha256", "selected_protocol_version") + coverage.FIELDS


def counts(rows: list[dict]) -> dict:
    result = {status: sum(row["attempt_status"] == status for row in rows)
              for status in ("completed", "infrastructure_or_policy_error",
                             "claimed_without_terminal_outcome", "unattempted", "invalid_evidence")}
    result.update(planned=len(rows),
                  native_successes=sum(row["native_final_success"] is True for row in rows),
                  native_failures=sum(row["native_final_success"] is False for row in rows))
    return result


def frozen_helper_names(files, manifest: dict) -> tuple[str, str]:
    """Select the campaign's captured layout, never a mutable compatibility shim.

    Campaign/v3 spans historical harness and current benchkit layouts.
    Its hash-bound source index, not today's installed modules or model version,
    determines which pair belongs to the immutable campaign.
    """
    schema = manifest.get("schema_version")
    audit.require(schema in ("starvla-rsi.campaign/v1", "starvla-rsi.campaign/v2", "starvla-rsi.campaign/v3"),
                  "unsupported campaign schema for frozen ledger helpers")
    if schema != "starvla-rsi.campaign/v3":
        audit.require("runtime_namespace" not in manifest, "legacy runtime namespace override")
        return ("starVLA.evaluation.campaign", "starVLA.evaluation.campaign_coverage")
    namespace = manifest.get("runtime_namespace", "harness")
    audit.require(namespace in ("harness", "benchkit"), "unsupported campaign runtime namespace")
    source = manifest.get("harness_source")
    audit.require(isinstance(source, dict) and source.get("path") == "harness_source/index.json",
                  "unsupported frozen harness source layout")
    index = files.json(source["path"])
    audit.require(files.hashes[source["path"]] == source.get("index_sha256"), "frozen source index digest mismatch")
    audit.require(isinstance(index, dict) and index.get("schema_version") == "starvla-rsi.harness-source/v2",
                  "unsupported frozen harness index schema")
    rows = index.get("files") if isinstance(index, dict) else None
    audit.require(isinstance(rows, list) and all(isinstance(row, dict) and isinstance(row.get("path"), str)
                                               for row in rows), "invalid frozen source index")
    by_path = {row["path"]: row for row in rows}
    audit.require(len(by_path) == len(rows), "duplicate frozen source identity")
    layouts = (("benchkit.campaigns.workflow", "benchkit.reports.campaign_coverage"),
               ("harness.campaigns.workflow", "harness.reports.campaign_coverage"),
               ("harness.campaign", "harness.campaign_coverage"))
    selected = [layout for layout in layouts if all(name.replace(".", "/") + ".py" in by_path for name in layout)]
    known = {name.replace(".", "/") + ".py" for layout in layouts for name in layout}
    audit.require(len(selected) == 1 and len(known & by_path.keys()) == 2,
                  "missing, mixed or ambiguous frozen campaign helper layout")
    audit.require(all(name.startswith(namespace + ".") for name in selected[0]),
                  "frozen helper layout differs from campaign runtime namespace")
    for name in selected[0]:
        relative = name.replace(".", "/") + ".py"
        payload = files.raw("frozen/" + relative)
        audit.require(len(payload) == by_path[relative].get("size_bytes")
                      and files.hashes["frozen/" + relative] == by_path[relative].get("sha256"),
                      "frozen helper changed before import")
    return selected[0]


def summarize(campaign: Path) -> dict:
    # The external reporting script stays outside the immutable campaign, but
    # imports the exact frozen coordinator/helper via the caller's PYTHONPATH.
    # Refuse a mutable import instead of implying it was frozen automatically.
    audit.require(not campaign.is_symlink(), "campaign root must not be a symlink")
    files = audit.ClosedFiles(campaign)
    manifest = files.json("campaign.json")
    # Import the campaign's own historical package name, never an alias shim or
    # the current coordinator pretending to be the old frozen implementation.
    helper_names = frozen_helper_names(files, manifest)
    coordinator, continuation = [importlib.import_module(name) for name in helper_names]
    frozen = files.root / "frozen"
    for module, name in zip((coordinator, continuation), helper_names):
        audit.require(Path(module.__file__).resolve() ==
                      (frozen / (name.replace(".", "/") + ".py")).resolve(),
                      "invoke from campaign frozen cwd with PYTHONPATH pointing there")
    own_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    campaign_hash = files.hashes["campaign.json"]
    audit.require(files.json("campaign_digest.json")["sha256"] == campaign_hash,
                  "campaign digest mismatch")
    coordinator.verify_frozen_package(files.root, manifest)
    continuation.verify_coverage(files.root, manifest)
    ledger = manifest["coverage_ledger"]
    current = coverage.summarize(files.root)
    audit.require(current["campaign_sha256"] == campaign_hash, "campaign changed during reporting")
    sources = [current]
    prior_binding = ledger["carry_forward"]
    prior = None
    if prior_binding is not None:
        prior = coverage.summarize(Path(prior_binding["campaign"]))
        audit.require(prior["campaign_sha256"] == prior_binding["campaign_sha256"],
                      "prior campaign changed during reporting")
        audit.require(all(prior_binding["file_sha256"].get(path) == digest
                          for path, digest in prior["read_file_sha256"].items()),
                      "prior records differ from the verified carry-forward binding")
        sources.append(prior)

    current_by_id = {case["case_id"]: row for case, row in zip(manifest["cases"], current["cases"])}
    carried_by_id = {} if prior_binding is None else {
        row["source_case_id"]: row for row in prior_binding["attempts"]}
    rows = []
    for entry in ledger["entries"]:
        carried = entry["disposition"] == "carried_attempt"
        if carried:
            binding = carried_by_id[entry["source_case_id"]]
            original = prior["cases"][binding["source_case_index"]]
            audit.require(original["attempt_status"] == binding["attempt_status"]
                          and original["native_final_success"] is binding["native_final_success"]
                          and original["protocol_version"] == binding["original_descriptor"]["protocol_version"],
                          "carried outcome or original protocol mismatch")
            source = prior
        else:
            original = current_by_id[entry["case_id"]]
            source = current
        audit.require(original["task"] == entry["task"], "ledger/source task mismatch")
        row = copy.deepcopy(original)
        metadata = entry["selected_episode"]["metadata"]
        row.update(selection_index=entry["selection_index"], disposition=entry["disposition"],
                   task_group=metadata.get("task_set", metadata.get("native_backend")),
                   source_campaign=source["campaign"], source_campaign_sha256=source["campaign_sha256"],
                   selected_protocol_version=entry["selected_descriptor"]["protocol_version"])
        rows.append(row)
    audit.require(len(rows) == ledger["selected_total"] == manifest["selected_total"],
                  "full selected denominator mismatch")
    files.verify_unchanged()
    coordinator.verify_frozen_package(files.root, manifest)
    audit.require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == own_hash,
                  "ledger reporting tool changed during snapshot")
    return {"schema_version": "starvla-rsi.task-ledger-snapshot/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "campaign": str(files.root), "campaign_sha256": campaign_hash,
            "benchmark": manifest["benchmark"], "task_scope": manifest["task_scope"],
            "selected_total": len(rows), "carried_attempts": manifest["carried_attempts"],
            "planned_new_cases": manifest["planned_new_cases"], "counts": counts(rows), "cases": rows,
            "by_original_protocol": {protocol: counts([r for r in rows if r["protocol_version"] == protocol])
                                     for protocol in sorted({r["protocol_version"] for r in rows})},
            "by_task_group": {group: counts([r for r in rows if r["task_group"] == group])
                              for group in sorted({r["task_group"] for r in rows if r["task_group"] is not None})},
            "source_snapshots": sources,
            "tool_sha256": {"task_ledger.py": own_hash, **current["tool_sha256"]},
            "verified_frozen_helper_sha256": {Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                                               for m in (coordinator, continuation)},
            "limitations": [
                "Counts describe coverage and raw native outcomes, not a homogeneous score or a success-rate leaderboard.",
                "Original pilot and new protocol identities stay separate; selected_protocol_version does not relabel a carried result.",
                "Non-atomic live snapshot: active/unattempted tasks can advance; no active episode/event/observation files are read.",
                "Carry-forward validation hashes retained prior artifact bytes, but does not decode video/NPY, rerender, import a simulator or query a scorer.",
                "New execution rows inherit the source reporter's policy-binding limitations; carried metadata is checked by the frozen continuation helper.",
                "No external caveat overlay is applied here; retain source campaign context/review caveats separately. Absence of annotations does not certify clean evidence.",
                "Invalid/missing carry-forward evidence aborts reporting, never authorizes retry or removing a task.",
                "No provider/model/usage, native parity, current filesystem execution, or OS-isolation attestation."]}


def write_snapshot(report: dict, output: Path) -> None:
    for source in report["source_snapshots"]:
        audit.require(not output.resolve().is_relative_to(Path(source["campaign"]).resolve()),
                      "snapshot output must be outside every source campaign")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "coverage.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (output / "tasks.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({key: coverage.csv_value(row.get(key)) for key in FIELDS} for row in report["cases"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.campaign)
    write_snapshot(report, args.output_dir)
    print(json.dumps(report["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
