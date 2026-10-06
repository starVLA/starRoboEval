"""Build a small, hash-bound public result view from one closed raw run.

Raw evaluator evidence remains immutable and local.  This module publishes only
portable result facts plus selected videos under the model-owned result root.  It
does not start a benchmark, select cases, retry an episode, or rescore a result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from benchkit.artifacts import atomic_write_json
from benchkit.audits.closed_run import audit_run
from benchkit.reports.panel_sr import summarize_panel


PUBLICATION_SCHEMA = "starvla-rsi.result-publication/v1"
INDEX_SCHEMA = "starvla-rsi.result-index/v1"
EPISODE_SCHEMA = "starvla-rsi.published-episode/v1"
MAX_METADATA_BYTES = 64 * 1024 * 1024
CAMERA_ARTIFACTS = {
    "video_cam_head": "cam_head",
    "video_cam_left_wrist": "cam_left_wrist",
    "video_cam_right_wrist": "cam_right_wrist",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> bytes:
    _require(path.is_file() and not path.is_symlink(), f"missing regular file: {path}")
    size = path.stat().st_size
    _require(size <= MAX_METADATA_BYTES, f"metadata exceeds {MAX_METADATA_BYTES} bytes: {path}")
    payload = path.read_bytes()
    _require(len(payload) == size, f"metadata changed while reading: {path}")
    return payload


def _decode(payload: bytes, name: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"duplicate JSON key in {name}: {key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"nonfinite JSON value in {name}: {value}")

    return json.loads(payload.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)


def _json(path: Path):
    return _decode(_read(path), str(path))


def _jsonl(path: Path):
    payload = _read(path)
    return [_decode(line, str(path)) for line in payload.splitlines() if line.strip()]


def _sha(path: Path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    _require(bool(value) and value not in {".", ".."}, "empty or unsafe publication name")
    return value


def _relative_file(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative), "artifact path must be a nonempty string")
    candidate = (root / relative).resolve()
    resolved = root.resolve()
    _require(candidate != resolved and resolved in candidate.parents, "artifact path escapes its episode")
    _require(candidate.is_file() and not candidate.is_symlink(), f"missing regular artifact: {relative}")
    return candidate


def _write_identical(path: Path, payload):
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if path.exists():
        _require(path.is_file() and path.read_bytes() == encoded, f"refusing to replace different publication file: {path}")
        return
    atomic_write_json(path, payload, overwrite=False)


def _materialize(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _require(destination.is_file() and _sha(destination) == _sha(source),
                 f"refusing to replace different media: {destination}")
        if not os.path.samefile(source, destination):
            return
    temporary = destination.with_name("." + destination.name + ".tmp")
    _require(not temporary.exists(), f"temporary media path already exists: {temporary}")
    shutil.copyfile(source, temporary)
    _require(_sha(temporary) == _sha(source), f"media copy verification failed: {destination}")
    os.replace(temporary, destination)
    _require(not os.path.samefile(source, destination), "published media must not share an inode with raw evidence")


def _source_root(raw_run: Path) -> Path:
    client = raw_run / "client"
    return client if client.is_dir() else raw_run


def _description_map(values):
    result = {}
    for value in values:
        _require("=" in value, "task descriptions use TASK=SHORT-ENGLISH-DESCRIPTION")
        task, description = value.split("=", 1)
        task, description = _slug(task), _slug(description)
        _require(task not in result, f"duplicate task description: {task}")
        result[task] = description
    return result


def _validate_panel(summary, rows, report, plan, declaration, manifest):
    completed = sum(row.get("status") == "completed" for row in rows)
    successes = sum(row.get("status") == "completed" and row.get("success") is True for row in rows)
    errors = len(rows) - completed
    expected = {"attempted": len(rows), "completed": completed, "successes": successes, "errors": errors}
    for key, value in expected.items():
        _require(type(summary.get(key)) is int and summary[key] == value, f"summary {key} mismatch")
    recomputed = summarize_panel(plan, rows)
    recorded = {key: value for key, value in report.items() if key != "inputs"}
    _require(recorded == recomputed, "stored panel report differs from an independent recomputation")
    cases = plan["cases"]
    _require(manifest.get("protocol", {}).get("episode_ids") == cases,
             "manifest episode schedule differs from the panel plan")
    layouts = [row.get("episode", {}).get("metadata", {}).get("layout_id") for row in rows]
    _require(all(type(value) is int for value in layouts) and len(set(layouts)) == len(layouts),
             "published panel requires unique integer layout IDs")
    _require(declaration.get("selected_layouts") == layouts and declaration.get("attempts_per_layout") == 1,
             "panel declaration differs from closed episode layouts")
    return recomputed


def _portable(value, name="publication"):
    if isinstance(value, dict):
        for key, item in value.items():
            _require(isinstance(key, str), f"{name} contains a non-string key")
            _portable(item, f"{name}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _portable(item, f"{name}[{index}]")
    elif isinstance(value, str):
        _require(not value.startswith(("/", "~/", "\\\\"))
                 and not re.match(r"^[A-Za-z]:[\\/]", value),
                 f"{name} contains an absolute path")
        _require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value),
                 f"{name} contains invalid Unicode")
    return value


def _bind_server(raw_run: Path, source: Path, manifest: dict, rows: list[dict], evidence: dict):
    declared = manifest.get("benchmark_service")
    if declared is None:
        return {"status": "not_declared"}
    _require(isinstance(declared, dict), "benchmark service declaration must be an object")
    server = raw_run / "server"
    _require(server.is_dir(), "declared benchmark service requires the paired server evidence")
    service_path = server / "service.json"
    service_payload = _read(service_path)
    service = _decode(service_payload, "server/service.json")
    _require(service == declared, "client manifest and server service declaration differ")
    evidence["server/service.json"] = {"sha256": hashlib.sha256(service_payload).hexdigest(),
                                       "bytes": len(service_payload)}
    bindings = []
    for row in rows:
        case_id = row.get("episode", {}).get("id")
        _require(isinstance(case_id, str), "episode ID is required for server binding")
        candidates = [path for path in (source / "episodes").iterdir() if path.is_dir()
                      and (path / "result.json").is_file()
                      and _json(path / "result.json").get("episode", {}).get("id") == case_id]
        _require(len(candidates) == 1, f"cannot bind client receipt directory: {case_id}")
        receipt_path = candidates[0] / "artifacts" / "sim_server_receipt.json"
        receipt_payload = _read(receipt_path)
        receipt = _decode(receipt_payload, str(receipt_path))
        session = receipt.get("session_id")
        _require(isinstance(session, str) and bool(session), "SIM receipt session ID is required")
        _require(receipt.get("protocol") == "starvla-rsi.sim-server/v1", "unsupported SIM receipt protocol")
        _require(receipt.get("server") == service, "SIM receipt and server service declaration differ")
        finish = receipt.get("finish")
        _require(isinstance(finish, dict) and finish.get("session_id") == session,
                 "SIM receipt has no matching finish record")
        inventory = finish.get("files")
        _require(isinstance(inventory, list) and bool(inventory), "SIM receipt artifact inventory is required")
        by_path = {}
        for item in inventory:
            _require(isinstance(item, dict) and set(item) == {"path", "size_bytes", "sha256"},
                     "invalid SIM receipt artifact entry")
            name = item["path"]
            _require(isinstance(name, str) and name not in by_path, "duplicate/invalid receipt artifact path")
            _require(type(item["size_bytes"]) is int and item["size_bytes"] >= 0
                     and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None,
                     "invalid receipt artifact digest")
            by_path[name] = item
        claim_path = server / "episodes" / _slug(session) / "claim.json"
        claim_payload = _read(claim_path)
        claim = _decode(claim_payload, str(claim_path))
        _require(claim == {"episode_id": case_id, "session_id": session}, "server claim differs from client receipt")
        artifact_root = candidates[0] / "artifacts" / "sim_server_files"
        server_episode = server / "episodes" / _slug(session)
        required = {"claim.json", "native_result.json", "native_events.jsonl",
                    "cam_head.mp4", "cam_left_wrist.mp4", "cam_right_wrist.mp4"}
        _require(required <= set(by_path), "SIM receipt omits required outcome/media artifacts")
        for name in sorted(required):
            client_file = _relative_file(artifact_root, name)
            server_file = _relative_file(server_episode, name)
            expected = {"sha256": by_path[name]["sha256"], "bytes": by_path[name]["size_bytes"]}
            _require(_sha(client_file) == expected and _sha(server_file) == expected,
                     f"client/server artifact differs from receipt: {name}")
        native = _json(artifact_root / "native_result.json")
        metrics = row.get("metrics") or {}
        _require(all(metrics.get(key) == value for key, value in native.items()),
                 "client result metrics differ from the native server outcome")
        _require(row.get("success") == native.get("success"),
                 "client success differs from the native server outcome")
        receipt_key = f"client/episodes/{candidates[0].name}/artifacts/sim_server_receipt.json"
        claim_key = f"server/episodes/{session}/claim.json"
        evidence[receipt_key] = {"sha256": hashlib.sha256(receipt_payload).hexdigest(),
                                 "bytes": len(receipt_payload)}
        evidence[claim_key] = {"sha256": hashlib.sha256(claim_payload).hexdigest(),
                               "bytes": len(claim_payload)}
        bindings.append({"case_id": case_id, "session_id_sha256": hashlib.sha256(session.encode()).hexdigest(),
                         "receipt": receipt_key, "claim": claim_key})
    _require(isinstance(service.get("server_id"), str), "server ID is required")
    return {"status": "outcome_bound", "server_id_sha256": hashlib.sha256(service["server_id"].encode()).hexdigest(),
            "episodes": bindings}


def _episode(row, descriptions, media_root: Path, run_id: str, episode_root: Path):
    episode = row.get("episode")
    metrics = row.get("metrics")
    _require(isinstance(episode, dict) and isinstance(metrics, dict), "episode and metrics objects are required")
    case_id, task = episode.get("id"), episode.get("task")
    _require(isinstance(case_id, str) and isinstance(task, str), "episode id and task are required")
    _require(task in descriptions, f"missing short English description for task: {task}")
    _require(row.get("status") in {"completed", "error"}, "only closed episode results can be published")
    if row["status"] == "completed":
        _require(type(row.get("success")) is bool and row.get("error") is None,
                 "completed episode must contain a boolean success and no error")
    else:
        _require(row.get("success") is None and isinstance(row.get("error"), dict),
                 "error episode must retain a structured error")

    layout_id = (episode.get("metadata") or {}).get("layout_id")
    case_tail = case_id[len(task) + 1:] if case_id.startswith(task + "/") else case_id
    case_suffix = _slug(case_tail.replace("/", "-"))
    directory = f"{_slug(task)}-{descriptions[task]}-{case_suffix}"
    public_media = []
    artifacts = row.get("artifacts") or {}
    source_artifacts = episode_root / _slug(case_id.replace("/", "_")) / "artifacts"
    # Some runs use the exact slash-free directory generated by the runner.
    if not source_artifacts.is_dir():
        matches = [path for path in episode_root.iterdir() if path.is_dir()
                   and (path / "result.json").is_file()
                   and _json(path / "result.json").get("episode", {}).get("id") == case_id]
        _require(len(matches) == 1, f"cannot bind episode artifact directory: {case_id}")
        source_artifacts = matches[0] / "artifacts"
    for artifact, camera in CAMERA_ARTIFACTS.items():
        if artifact not in artifacts:
            continue
        source = _relative_file(source_artifacts, artifacts[artifact])
        relative = Path("media") / run_id / directory / f"video_{camera}.mp4"
        destination = media_root / relative.relative_to("media")
        _materialize(source, destination)
        public_media.append({"camera": camera, "path": str(relative), **_sha(destination)})

    error = row.get("error")
    public_error = None if error is None else {
        "category": error.get("category"),
        "code": error.get("code"),
        "message_recorded_privately": error.get("message") is not None,
    }
    return {
        "schema_version": EPISODE_SCHEMA,
        "case_id": case_id,
        "task": task,
        "task_description": descriptions[task],
        "seed": episode.get("seed"),
        "layout_id": layout_id,
        "status": row["status"],
        "success": row.get("success"),
        "termination_reason": row.get("termination_reason"),
        "error": public_error,
        "counters": {
            "policy_calls": row.get("policy_calls"),
            "action_decisions": row.get("action_decisions"),
            "controls": row.get("environment_steps"),
            "rejected_actions": row.get("rejected_actions"),
            "first_native_success_control": metrics.get("first_native_success_control_target",
                                                        metrics.get("first_native_success_control")),
        },
        "native_scores": {
            "benchmark": metrics.get("native_benchmark_score"),
            "process": metrics.get("native_process_score"),
            "scale": metrics.get("native_benchmark_score_scale"),
        },
        "usage": row.get("usage"),
        "media": public_media,
    }


def publish(raw_run: Path, results_root: Path, task_descriptions: dict,
            *, verify_closed_record: bool = True) -> dict:
    raw_run, results_root = raw_run.resolve(), results_root.resolve()
    source = _source_root(raw_run)
    if verify_closed_record:
        audit = audit_run(source)
        _require(audit.get("record_consistency") == "passed", "closed-record audit did not pass")
    metadata_names = ("summary.json", "status.json", "manifest.json", "episodes.jsonl",
                      "panel_declaration.json", "panel_plan.json", "panel_report.json")
    payloads = {name: _read(source / name) for name in metadata_names}
    decoded = {name: _decode(payload, name) for name, payload in payloads.items() if name != "episodes.jsonl"}
    rows = [_decode(line, "episodes.jsonl") for line in payloads["episodes.jsonl"].splitlines() if line.strip()]
    summary, status, manifest = decoded["summary.json"], decoded["status.json"], decoded["manifest.json"]
    declaration, plan, panel = (decoded["panel_declaration.json"], decoded["panel_plan.json"],
                                decoded["panel_report.json"])
    run_id = _slug(summary.get("run_id", ""))
    benchmark = _slug(summary.get("benchmark", ""))
    _require(raw_run.name == run_id, "raw run directory and declared run ID differ")
    _require(status.get("status") in {"completed", "completed_with_errors"}
             and status.get("episodes_written") == len(rows), "raw run is not closed")
    _require(manifest.get("run_id") == run_id, "manifest run ID mismatch")
    _require(manifest.get("benchmark", {}).get("name") == benchmark, "manifest benchmark mismatch")
    _require(declaration.get("run_id") == run_id, "panel declaration run ID mismatch")
    panel = _validate_panel(summary, rows, panel, plan, declaration, manifest)
    _require(results_root.name == benchmark, "results root must be the selected benchmark directory")

    evidence = {"client/" + name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
                for name, payload in payloads.items()}
    policy = manifest.get("policy") or {}
    benchmark_service = manifest.get("benchmark_service") or {}
    parameters = benchmark_service.get("parameters") or {}
    _require(policy.get("kind") != "infrastructure-diagnostic"
             and manifest.get("purpose") != "infrastructure_validation_only"
             and parameters.get("diagnostic") is not True,
             "infrastructure diagnostics cannot be published as model capability results")
    profile_id = results_root.parents[1].name
    profile = (policy.get("parameters") or {}).get("model_profile")
    _require(isinstance(profile, dict) and profile.get("id") == profile_id,
             "manifest model profile differs from the selected result namespace")
    for name in ("profile_sha256", "config_sha256", "dependencies_sha256", "prompt_sha256",
                 "source_inventory_sha256"):
        _require(re.fullmatch(r"[0-9a-f]{64}", str(profile.get(name, ""))) is not None,
                 f"model profile {name} is missing or invalid")
    server_binding = _bind_server(raw_run, source, manifest, rows, evidence)
    protocol = manifest.get("benchmark") or {}
    accepted = panel["complete_panel"]

    # All metadata, profile and paired-server checks run before any public files
    # are materialized.  A rejected source must leave no partial publication.
    report_dir = results_root / "reports" / run_id
    media_root = results_root / "media"
    episodes = [_episode(row, task_descriptions, media_root, run_id, source / "episodes") for row in rows]
    _require(len({row["case_id"] for row in episodes}) == len(episodes), "duplicate episode IDs")
    publication = {
        "schema_version": PUBLICATION_SCHEMA,
        "run_id": run_id,
        "benchmark": benchmark,
        "accepted": accepted,
        "created_at": manifest.get("created_at"),
        "model": {
            "profile": profile_id,
            "profile_sha256": profile["profile_sha256"],
            "config_sha256": profile["config_sha256"],
            "policy": policy.get("name"),
            "provider": policy.get("provider"),
            "model": policy.get("model"),
            "method": policy.get("version"),
            "identity_evidence": (policy.get("parameters") or {}).get("model_identity_evidence"),
        },
        "protocol": {
            "version": protocol.get("protocol_version"),
            "benchmark_version": protocol.get("version"),
            "benchmark_source_revision": protocol.get("source_revision"),
            "official_full_protocol": declaration.get("official_full_protocol"),
            "automatic_retry": declaration.get("automatic_retry"),
            "attempts_per_layout": declaration.get("attempts_per_layout"),
            "selected_layouts": declaration.get("selected_layouts"),
            "control_method": declaration.get("control_method"),
            "native_control_limit": declaration.get("native_controls"),
            "image_max_edge": declaration.get("image_max_edge"),
        },
        "source": {
            "tree": declaration.get("source_tree"),
            "client_commit": declaration.get("local_commit"),
            "server_commit": declaration.get("remote_commit"),
            "raw_evidence": evidence,
            "server_binding": server_binding,
            "raw_evidence_location": "local barks archive; not part of the public result",
        },
        "outcome": {
            "planned": panel["counts"].get("planned"),
            "recorded": panel["counts"].get("recorded"),
            "completed": summary.get("completed"),
            "successes": summary.get("successes"),
            "native_failures": panel["counts"].get("native_failures"),
            "policy_failures": panel["counts"].get("policy_failures"),
            "infrastructure_errors": panel["counts"].get("infrastructure_errors"),
            "success_rate": panel.get("full_panel_success_rate"),
            "successful_over_planned": panel.get("successful_over_planned"),
            "policy_calls": summary.get("policy_calls"),
            "rejected_actions": summary.get("rejected_actions"),
        },
        "usage": summary.get("usage"),
        "reference": {
            "declaration": plan.get("reference"),
            "url": plan.get("reference_url"),
            "same_conditions_verified": (panel.get("comparison") or {}).get("same_conditions_verified"),
            "statistical_equivalence_established": (panel.get("comparison") or {}).get("statistical_equivalence_established"),
        },
        "episodes_file": "episodes.json",
        "media_manifest_file": "media.json",
        "caveats": panel.get("caveats"),
    }
    media = [item for episode in episodes for item in episode["media"]]
    media_manifest = {"schema_version": "starvla-rsi.media-manifest/v1", "run_id": run_id,
                      "files": media}
    _portable(publication)
    _portable(episodes)
    _portable(media_manifest)
    _write_identical(report_dir / "result.json", publication)
    _write_identical(report_dir / "episodes.json", {"schema_version": EPISODE_SCHEMA,
                                                      "run_id": run_id, "episodes": episodes})
    _write_identical(report_dir / "media.json", media_manifest)

    index_path = results_root / "index.json"
    entry = {"run_id": run_id, "accepted": accepted, "report": f"reports/{run_id}/result.json",
             "episodes": len(episodes), "successes": summary.get("successes"),
             "success_rate": panel.get("full_panel_success_rate"), "protocol": protocol.get("protocol_version")}
    if index_path.exists():
        index = _json(index_path)
        _require(index.get("schema_version") == INDEX_SCHEMA and index.get("benchmark") == benchmark,
                 "existing result index is incompatible")
        found = [row for row in index.get("runs", []) if row.get("run_id") == run_id]
        _require(not found or found == [entry], "existing index contains a different run entry")
        runs = [row for row in index.get("runs", []) if row.get("run_id") != run_id] + [entry]
        latest = run_id if accepted else index.get("latest_accepted_run")
    else:
        runs = [entry]
        latest = run_id if accepted else None
    index = {"schema_version": INDEX_SCHEMA, "benchmark": benchmark,
             "latest_accepted_run": latest, "runs": runs}
    _portable(index)
    atomic_write_json(index_path, index, overwrite=True)
    return {"result": publication, "episodes": episodes, "media": media, "index": index}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-run", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--task-description", action="append", default=[], metavar="TASK=SHORT-DESCRIPTION")
    args = parser.parse_args(argv)
    output = publish(args.raw_run, args.results_root, _description_map(args.task_description))
    print(json.dumps({"run_id": output["result"]["run_id"],
                      "episodes": len(output["episodes"]), "media": len(output["media"]),
                      "result": str(args.results_root / "reports" / output["result"]["run_id"] / "result.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
