"""Build a small, hash-bound public result view from closed raw runs.

The unit is one closed client run, or a remote-run output directory whose
``plan.json`` names the planned cases (the denominator) and whose first
attempt per case is that case's outcome. Raw evaluator evidence
remains immutable and local. This module publishes only portable result facts
plus selected videos under the model-owned result root. It does not start a
benchmark, select cases, retry an episode, or rescore a result.
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
from benchkit.contracts import ensure_jsonable
from benchkit.reports.panel_sr import PLAN_SCHEMA, summarize_panel
from benchkit.reports.run_summary import summarize_run
from benchkit.sim_server.remote_run import COMPLETION_KEYS, PLAN_SCHEMA as REMOTE_PLAN_SCHEMA, case_directory

PUBLICATION_SCHEMA = "starvla-rsi.result-publication/v2"
INDEX_SCHEMA = "starvla-rsi.result-index/v1"
EPISODE_SCHEMA = "starvla-rsi.published-episode/v2"
MAX_METADATA_BYTES = 64 * 1024 * 1024
OUTCOME_FILES = ("claim.json", "native_result.json", "native_events.jsonl")
RUN_FILES = ("summary.json", "status.json", "manifest.json", "episodes.jsonl")


def _videos(artifacts: dict) -> dict:
    """Named MP4 artifacts of one episode."""
    return {name: path for name, path in artifacts.items()
            if isinstance(path, str) and path.lower().endswith(".mp4")}


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


def _evidence(path: Path, key: str, evidence: dict):
    """Read a metadata file and record its digest under a portable key."""
    payload = _read(path)
    evidence[key] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    return payload


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


def _encode(path: Path, payload) -> bytes:
    # Mirror atomic_write_json's encoding so an idempotent re-publish matches
    # byte-for-byte whatever text the payload contains.
    return (json.dumps(ensure_jsonable(payload, str(path)), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _media_temporary(destination: Path) -> Path:
    return destination.with_name("." + destination.name + ".tmp")


def _materialize(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not os.path.samefile(source, destination):
        return  # Checked identical before any write.
    temporary = _media_temporary(destination)
    shutil.copyfile(source, temporary)
    _require(_sha(temporary) == _sha(source), f"media copy verification failed: {destination}")
    os.replace(temporary, destination)
    _require(not os.path.samefile(source, destination), "published media must not share an inode with raw evidence")


def _description_map(values):
    result = {}
    for value in values:
        _require("=" in value, "task descriptions use TASK=SHORT-ENGLISH-DESCRIPTION")
        task, description = value.split("=", 1)
        task, description = _slug(task), _slug(description)
        _require(task not in result, f"duplicate task description: {task}")
        result[task] = description
    return result


def _reference(value: str) -> dict:
    match = re.fullmatch(r"([0-9]+)/([0-9]+)", value)
    _require(match is not None, "reference uses SUCCESSES/EPISODES")
    return {"successes": int(match[1]), "episodes": int(match[2])}


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


def _load_run(source: Path, key: str, evidence: dict, verify: bool) -> dict:
    """Read one closed client run whose summary agrees with its episode rows."""
    if verify:
        audit = audit_run(source)
        _require(audit.get("record_consistency") == "passed", f"closed-record audit did not pass: {key}")
    payloads = {name: _evidence(source / name, f"{key}/{name}", evidence) for name in RUN_FILES}
    summary, status, manifest = (_decode(payloads[name], f"{key}/{name}") for name in RUN_FILES[:3])
    rows = [_decode(line, f"{key}/episodes.jsonl")
            for line in payloads["episodes.jsonl"].splitlines() if line.strip()]
    run_id = _slug(summary.get("run_id", ""))
    _require(manifest.get("run_id") == run_id, f"manifest run ID mismatch: {key}")
    _require(status.get("status") in {"completed", "completed_with_errors"}
             and status.get("episodes_written") == len(rows), f"raw run is not closed: {key}")
    _require(manifest.get("benchmark", {}).get("name") == summary.get("benchmark"),
             f"manifest benchmark mismatch: {key}")
    completed = sum(row.get("status") == "completed" for row in rows)
    successes = sum(row.get("status") == "completed" and row.get("success") is True for row in rows)
    expected = {"attempted": len(rows), "completed": completed, "successes": successes,
                "errors": len(rows) - completed}
    for name, value in expected.items():
        _require(type(summary.get(name)) is int and summary[name] == value, f"summary {name} mismatch: {key}")
    directories = {}
    episodes = source / "episodes"
    for path in sorted(episodes.iterdir()) if episodes.is_dir() else ():
        if path.is_dir() and (path / "result.json").is_file():
            episode_id = _json(path / "result.json").get("episode", {}).get("id")
            _require(episode_id not in directories, f"two episode directories claim {episode_id}: {key}")
            directories[episode_id] = path
    return {"run_id": run_id, "key": key, "manifest": manifest, "rows": rows, "episode_dirs": directories}


def _identity(manifest: dict, profile_id: str) -> dict:
    """Manifest facts a publication states; every case of a panel must share them.

    Policy parameters stay opaque apart from the framework's model-profile keys.
    """
    policy = manifest.get("policy") or {}
    parameters = policy.get("parameters") or {}
    service = manifest.get("benchmark_service") or {}
    _require(policy.get("kind") != "infrastructure-diagnostic"
             and manifest.get("purpose") != "infrastructure_validation_only"
             and (service.get("parameters") or {}).get("diagnostic") is not True,
             "infrastructure diagnostics cannot be published as model capability results")
    _require(parameters.get("model_profile") == profile_id,
             "manifest model profile differs from the selected result namespace")
    _require(re.fullmatch(r"[0-9a-f]{64}", str(parameters.get("preset_sha256", ""))) is not None,
             "policy preset_sha256 is missing or invalid")
    git = (manifest.get("runtime") or {}).get("git") or {}
    _require(re.fullmatch(r"[0-9a-f]{40}", str(git.get("revision", ""))) is not None
             and type(git.get("dirty")) is bool,
             "manifest lacks the client Git revision and dirty flag")
    benchmark, protocol = manifest.get("benchmark"), manifest.get("protocol")
    _require(isinstance(benchmark, dict) and isinstance(protocol, dict), "manifest benchmark and protocol are required")
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return {
        "benchmark": benchmark,
        "policy": {key: policy.get(key) for key in ("name", "kind", "model", "provider", "version")},
        "policy_parameters_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "preset_sha256": parameters["preset_sha256"],
        "method": manifest.get("method"),
        "method_origin": manifest.get("method_origin"),
        "protocol": {key: value for key, value in protocol.items() if key != "episode_ids"},
        "client_git": {"revision": git["revision"], "dirty": git["dirty"],
                       "diff_sha256": (git.get("diff") or {}).get("sha256")},
    }


def _receipt(episode_dir: Path, row: dict, service: dict, evidence: dict, key: str):
    """Check one SIM receipt against the client record; return session, digests and videos.

    Every file the receipt says the client kept must be present and match it.
    A completed episode must hold the full native outcome, equal to the
    client's metrics and success. An error row is checked for receipt and file
    integrity only: an episode that never finished may lack the receipt, its
    finish record or its native outcome, and then returns None.
    """
    failed = row.get("status") == "error"
    path = episode_dir / "artifacts" / "sim_server_receipt.json"
    if failed and not (path.exists() or path.is_symlink()):
        return None
    receipt = _decode(_evidence(path, key, evidence), key)
    session = receipt.get("session_id")
    _require(isinstance(session, str) and bool(session), "SIM receipt session ID is required")
    _require(receipt.get("protocol") == "starvla-rsi.sim-server/v1", "unsupported SIM receipt protocol")
    _require(receipt.get("server") == service, "SIM receipt and service declaration differ")
    _require(isinstance(service.get("server_id"), str), "server ID is required")
    finish = receipt.get("finish")
    if failed and finish is None:
        return session, {}, {}
    _require(isinstance(finish, dict) and finish.get("session_id") == session,
             "SIM receipt has no matching finish record")
    inventory = finish.get("files")
    _require(isinstance(inventory, list) and (failed or bool(inventory)), "SIM receipt artifact inventory is required")
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
    _require(failed or set(OUTCOME_FILES) <= set(by_path), "SIM receipt omits required outcome artifacts")
    named = finish.get("artifacts")
    _require(isinstance(named, dict) and all(path in by_path for path in named.values()),
             "SIM receipt artifact names must point into its inventory")
    kept = (receipt.get("client_retention") or {}).get("selected_paths")
    _require(isinstance(kept, list) and all(path in by_path for path in kept)
             and (failed or "native_result.json" in kept),
             "SIM receipt must list the client copies, including native_result.json")
    case_videos = _videos(named)
    artifact_root = episode_dir / "artifacts" / "sim_server_files"
    expected, copies = {}, {}
    for name in sorted({*(name for name in OUTCOME_FILES if name in by_path), *case_videos.values()}):
        expected[name] = {"sha256": by_path[name]["sha256"], "bytes": by_path[name]["size_bytes"]}
        if name in kept:
            copies[name] = _relative_file(artifact_root, name)
            _require(_sha(copies[name]) == expected[name], f"client artifact differs from receipt: {name}")
    if not failed:
        native = _json(copies["native_result.json"])
        metrics = row.get("metrics") or {}
        _require(isinstance(native, dict) and all(metrics.get(name) == value for name, value in native.items()),
                 "client result metrics differ from the native server outcome")
        _require(row.get("success") == native.get("success"), "client success differs from the native server outcome")
    return session, expected, {artifact: (path, copies.get(path)) for artifact, path in case_videos.items()}


def _bind_paired_server(server: Path, run: dict, declared: dict, evidence: dict):
    """Bind each episode of a single run to its paired server record; return videos per case."""
    service = _decode(_evidence(server / "service.json", "server/service.json", evidence), "server/service.json")
    _require(service == declared, "client manifest and server service declaration differ")
    bindings, videos = [], {}
    for row in run["rows"]:
        case_id = row["episode"]["id"]
        episode_dir = run["episode_dirs"].get(case_id)
        _require(episode_dir is not None, f"cannot bind client receipt directory: {case_id}")
        receipt_key = f"client/episodes/{episode_dir.name}/artifacts/sim_server_receipt.json"
        bound = _receipt(episode_dir, row, service, evidence, receipt_key)
        if bound is None:
            bindings.append({"case_id": case_id, "receipt": None})
            videos[case_id] = {}
            continue
        session, expected, case_videos = bound
        server_episode = server / "episodes" / _slug(session)
        claim_key = f"server/episodes/{session}/claim.json"
        claim = _decode(_evidence(server_episode / "claim.json", claim_key, evidence), claim_key)
        _require(claim == {"episode_id": case_id, "session_id": session}, "server claim differs from client receipt")
        for name, digest in expected.items():
            _require(_sha(_relative_file(server_episode, name)) == digest, f"server artifact differs from receipt: {name}")
        videos[case_id] = {artifact: _relative_file(server_episode, path) for artifact, (path, _) in case_videos.items()}
        bindings.append({"case_id": case_id, "session_id_sha256": hashlib.sha256(session.encode()).hexdigest(),
                         "receipt": receipt_key, "claim": claim_key})
    return ({"status": "outcome_bound", "server_id_sha256": hashlib.sha256(service["server_id"].encode()).hexdigest(),
             "episodes": bindings}, videos)


def _client_receipt(run: dict, row: dict, service: dict, evidence: dict):
    """Bind one episode to its client-held SIM receipt; return the binding and its videos.

    A video without a client copy is published as its receipt reference.
    """
    case_id = row["episode"]["id"]
    episode_dir = run["episode_dirs"].get(case_id)
    _require(episode_dir is not None, f"cannot bind client receipt directory: {case_id}")
    receipt_key = f"{run['key']}/episodes/{episode_dir.name}/artifacts/sim_server_receipt.json"
    bound = _receipt(episode_dir, row, service, evidence, receipt_key)
    if bound is None:
        return {"case_id": case_id, "receipt": None}, {}
    session, expected, case_videos = bound
    videos = {artifact: copy if copy is not None else {"server_path": path, **expected[path]}
              for artifact, (path, copy) in case_videos.items()}
    return {"case_id": case_id, "session_id_sha256": hashlib.sha256(session.encode()).hexdigest(),
            "server_id_sha256": hashlib.sha256(service["server_id"].encode()).hexdigest(),
            "receipt": receipt_key}, videos


def _local_videos(row: dict, episode_dir: Path | None) -> dict:
    """Without a benchmark service, publish the run's own MP4 artifacts."""
    named = _videos(row.get("artifacts") or {})
    if not named:
        return {}
    _require(episode_dir is not None, f"cannot bind episode artifact directory: {row['episode']['id']}")
    return {name: _relative_file(episode_dir / "artifacts", path) for name, path in named.items()}


def _single_run(raw_run: Path, profile_id: str, evidence: dict, verify: bool):
    client = raw_run / "client"
    source = client if client.is_dir() else raw_run
    run = _load_run(source, "client", evidence, verify)
    _require(raw_run.name == run["run_id"], "raw run directory and declared run ID differ")
    identity = _identity(run["manifest"], profile_id)
    planned = run["manifest"]["protocol"].get("episode_ids")
    _require(isinstance(planned, list), "manifest protocol lacks its episode schedule")
    service = run["manifest"].get("benchmark_service")
    entries = []
    if service is None:
        binding = {"status": "not_declared"}
        for row in run["rows"]:
            entries.append((row, _local_videos(row, run["episode_dirs"].get(row["episode"]["id"]))))
    elif (raw_run / "server").is_dir():
        _require(isinstance(service, dict), "benchmark service declaration must be an object")
        binding, server_videos = _bind_paired_server(raw_run / "server", run, service, evidence)
        entries = [(row, server_videos[row["episode"]["id"]]) for row in run["rows"]]
    else:
        # Without its server pair a run binds to its client-held receipts, like a remote case.
        _require(isinstance(service, dict), "benchmark service declaration must be an object")
        bindings = []
        for row in run["rows"]:
            episode_binding, videos = _client_receipt(run, row, service, evidence)
            bindings.append(episode_binding)
            entries.append((row, videos))
        binding = {"status": "client_receipt_only", "episodes": bindings}
    recorded = {row["episode"]["id"] for row, _ in entries}
    schedule = {"source": "run_manifest", "profile": None, "panel": None, "complete_schedule_required": None,
                "cases": [{"case_id": case, "episode_id": case, "closed": case in recorded, "attempts": None,
                           "attempt_leases": None} for case in planned]}
    return run["run_id"], identity, planned, entries, schedule, binding


def _closed_rows(run_dir: Path):
    """Rows of a closed client run; None when its client crashed or never closed it."""
    status, rows = run_dir / "status.json", run_dir / "episodes.jsonl"
    if not (status.is_file() and rows.is_file()):
        return None
    closed = _json(status)
    if not isinstance(closed, dict) or closed.get("status") not in {"completed", "completed_with_errors"}:
        return None
    return [_decode(line, str(rows)) for line in _read(rows).splitlines() if line.strip()]


def _attempts(record: Path, case_id: str):
    """Leases of one case whose client closed a row that is not an infrastructure error, oldest first.

    run.py exits 1 on a policy error, so such an attempt has no completion
    record yet still is the case's outcome. A client that crashed, never
    started or closed only infrastructure errors made no attempt.
    """
    found = []
    for path in sorted(record.glob("*/lease.json")):
        client = path.parent / "client"
        runs = [run for run in client.iterdir() if run.is_dir()] if client.is_dir() else []
        _require(len(runs) <= 1, f"lease holds more than one client run: {case_id}")
        rows = _closed_rows(runs[0]) if runs else None
        if not rows or all(row.get("status") == "error" and (row.get("error") or {}).get("category") != "policy"
                           for row in rows):
            continue
        created = _json(runs[0] / "manifest.json").get("created_at")
        _require(isinstance(created, str), f"client manifest lacks created_at: {case_id}")
        found.append((created, path.parent, runs[0]))
    found.sort(key=lambda item: item[0])
    _require(len({created for created, _, _ in found}) == len(found), f"cannot order the attempts of {case_id}")
    return [(attempt, run) for _, attempt, run in found]


def _remote_run(root: Path, profile_id: str, evidence: dict, verify: bool):
    """The first attempt per case of a remote-run plan is its outcome; open cases stay missing."""
    plan = _decode(_evidence(root / "plan.json", "plan.json", evidence), "plan.json")
    _require(isinstance(plan, dict)
             and set(plan) == {"schema_version", "profile", "panel", "complete_schedule_required", "case_ids"}
             and plan["schema_version"] == REMOTE_PLAN_SCHEMA and isinstance(plan["profile"], str)
             and isinstance(plan["panel"], str) and type(plan["complete_schedule_required"]) is bool
             and isinstance(plan["case_ids"], list) and plan["case_ids"]
             and len(set(plan["case_ids"])) == len(plan["case_ids"]),
             "invalid remote-run plan")
    prefix = plan["profile"] + ":"
    _require(all(isinstance(case, str) and case.startswith(prefix) and len(case) > len(prefix)
                 for case in plan["case_ids"]), "plan case IDs must name the planned profile")
    directories = {case_directory(case): case for case in plan["case_ids"]}
    # No cases/ directory yet means no recorded case; stray files are ignored.
    cases_dir = root / "cases"
    found = {path.name for path in cases_dir.iterdir() if path.is_dir()} if cases_dir.is_dir() else set()
    _require(found <= set(directories), "remote-run records contain unplanned cases")
    identity, entries, cases, bindings = None, [], [], []
    for case_id in plan["case_ids"]:
        episode_id = case_id[len(prefix):]
        record = cases_dir / case_directory(case_id)
        key = f"cases/{record.name}"
        leases = sorted(path.parent.name for path in record.glob("*/lease.json"))
        completion_path = record / "completion.json"
        if completion_path.exists():
            completion = _json(completion_path)
            _require(isinstance(completion, dict) and set(completion) == set(COMPLETION_KEYS)
                     and completion["case_id"] == case_id and completion["lease_id"] in leases
                     and completion["client_returncode"] == 0 and completion["cleanup"] == "verified"
                     and type(completion["episodes_opened"]) is int and completion["episodes_opened"] > 0,
                     f"invalid completion record: {case_id}")
        attempts = _attempts(record, case_id)
        cases.append({"case_id": case_id, "episode_id": episode_id, "closed": bool(attempts),
                      "attempts": len(attempts), "attempt_leases": [attempt.name for attempt, _ in attempts]})
        if not attempts:
            continue
        # The first attempt is the case's outcome; later attempts are listed only.
        attempt, run_dir = attempts[0]
        lease = _decode(_evidence(attempt / "lease.json", f"{key}/{attempt.name}/lease.json", evidence), "lease.json")
        _require(lease.get("case_id") == case_id and lease.get("episode_id") == episode_id,
                 f"lease differs from the planned case: {case_id}")
        run = _load_run(run_dir, f"{key}/{attempt.name}/client/{run_dir.name}", evidence, verify)
        _require(run_dir.name == run["run_id"], f"client run directory and run ID differ: {case_id}")
        _require(run["manifest"]["protocol"].get("episode_ids") == [episode_id]
                 and [row.get("episode", {}).get("id") for row in run["rows"]] == [episode_id],
                 f"client run does not hold exactly the planned episode: {case_id}")
        case_identity = _identity(run["manifest"], profile_id)
        _require(identity is None or case_identity == identity,
                 f"cases come from different benchmarks, policies, protocols or sources: {case_id}")
        identity = case_identity
        # Server evidence stays on the bench host: bind to the client-held receipt only.
        service = run["manifest"].get("benchmark_service")
        _require(isinstance(service, dict), f"remote case lacks its benchmark service declaration: {case_id}")
        binding, videos = _client_receipt(run, run["rows"][0], service, evidence)
        entries.append((run["rows"][0], videos))
        bindings.append(binding)
    _require(identity is not None, "remote run has no closed case to publish")
    schedule = {"source": "remote_run_plan", "profile": plan["profile"], "panel": plan["panel"],
                "complete_schedule_required": plan["complete_schedule_required"], "cases": cases}
    binding = {"status": "client_receipt_only", "episodes": bindings}
    return _slug(root.name), identity, [case["episode_id"] for case in cases], entries, schedule, binding


def _source_identity(publication: dict):
    """What a publication was built from: its source directory and planned cases."""
    schedule = publication.get("schedule") or {}
    return ((publication.get("source") or {}).get("directory"), schedule.get("source"), schedule.get("profile"),
            schedule.get("panel"), [case.get("case_id") for case in schedule.get("cases") or []])


def _episode(row, descriptions, publication_id: str, videos: dict):
    """Public record of one closed episode, plus the media copies it needs."""
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

    case_tail = case_id[len(task) + 1:] if case_id.startswith(task + "/") else case_id
    case_suffix = _slug(case_tail.replace("/", "-"))
    directory = f"{_slug(task)}-{descriptions[task]}-{case_suffix}"
    # `video_<camera>` names the camera; a bare name such as `video` uses the file stem.
    cameras = {artifact: _slug(artifact[len("video_"):] if artifact.startswith("video_")
                               else Path(source["server_path"] if isinstance(source, dict) else source).stem)
               for artifact, source in videos.items()}
    _require(len(set(cameras.values())) == len(cameras), f"video artifact names collide: {case_id}")
    public_media, copies = [], []
    for artifact, source in sorted(videos.items()):
        camera = cameras[artifact]
        if isinstance(source, dict):
            public_media.append({"camera": camera, "location": "server", **source})
            continue
        relative = Path("media") / publication_id / directory / f"video_{camera}.mp4"
        copies.append((source, relative))
        public_media.append({"camera": camera, "location": "published", "path": str(relative), **_sha(source)})

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
        "usage_reported_complete": row.get("usage_reported_complete"),
        "usage_inconsistent_fields": row.get("usage_inconsistent_fields"),
        "media": public_media,
    }, copies


def publish(raw_run: Path, results_root: Path, task_descriptions: dict, *,
            reference: dict | None = None, verify_closed_record: bool = True) -> dict:
    raw_run, results_root = raw_run.resolve(), results_root.resolve()
    profile_id = results_root.parents[1].name
    evidence = {}
    remote = (raw_run / "plan.json").is_file()
    load = _remote_run if remote else _single_run
    publication_id, identity, planned, entries, schedule, binding = load(
        raw_run, profile_id, evidence, verify_closed_record)
    benchmark = _slug(identity["benchmark"].get("name", ""))
    _require(results_root.name == benchmark, "results root must be the selected benchmark directory")
    rows = [row for row, _ in entries]
    plan = {"schema_version": PLAN_SCHEMA, "cases": planned}
    if reference is not None:
        plan["reference"] = reference
    panel = summarize_panel(plan, rows)
    totals = summarize_run(publication_id, benchmark, identity["policy"]["name"], rows)
    accepted = panel["complete_panel"]

    episodes, copies = [], []
    for row, videos in entries:
        record, media_copies = _episode(row, task_descriptions, publication_id, videos)
        episodes.append(record)
        copies.extend(media_copies)
    _require(len({row["case_id"] for row in episodes}) == len(episodes), "duplicate episode IDs")
    descriptor = identity["benchmark"]
    publication = {
        "schema_version": PUBLICATION_SCHEMA,
        "run_id": publication_id,
        "benchmark": benchmark,
        "accepted": accepted,
        "model": {
            "profile": profile_id,
            **identity["policy"],
            "preset_sha256": identity["preset_sha256"],
            "policy_parameters_sha256": identity["policy_parameters_sha256"],
            "method": identity["method"],
            "method_origin": identity["method_origin"],
        },
        "protocol": {
            "version": descriptor.get("protocol_version"),
            "benchmark_version": descriptor.get("version"),
            "benchmark_source_revision": descriptor.get("source_revision"),
            "run": identity["protocol"],
        },
        "schedule": schedule,
        "source": {
            "client_revision": identity["client_git"]["revision"],
            "client_dirty": identity["client_git"]["dirty"],
            "client_diff_sha256": identity["client_git"]["diff_sha256"],
            "raw_evidence": evidence,
            "server_binding": binding,
            "directory": raw_run.name,
            "raw_evidence_location": "local archive; not part of the public result",
        },
        "outcome": {
            "planned": panel["counts"]["planned"],
            "recorded": panel["counts"]["recorded"],
            "completed": panel["counts"]["completed_native"],
            "successes": panel["counts"]["successes"],
            "native_failures": panel["counts"]["native_failures"],
            "policy_failures": panel["counts"]["policy_failures"],
            "infrastructure_errors": panel["counts"]["infrastructure_errors"],
            "missing_closed_results": panel["counts"]["missing_closed_results"],
            "success_rate": panel["full_panel_success_rate"],
            "successful_over_planned": panel["successful_over_planned"],
            "policy_calls": totals["policy_calls"],
            "rejected_actions": totals["rejected_actions"],
        },
        "usage": totals["usage"],
        "usage_incomplete_episodes": totals["usage_incomplete_episodes"],
        "reference": {
            "declaration": panel["reference"],
            "comparison": panel["comparison"],
        },
        "episodes_file": "episodes.json",
        "media_manifest_file": "media.json",
        "caveats": panel["caveats"],
    }
    media = [item for episode in episodes for item in episode["media"]]
    media_manifest = {"schema_version": "starvla-rsi.media-manifest/v1", "run_id": publication_id,
                      "files": media}
    _portable(publication)
    _portable(episodes)
    _portable(media_manifest)

    index_path = results_root / "index.json"
    entry = {"run_id": publication_id, "accepted": accepted, "report": f"reports/{publication_id}/result.json",
             "episodes": len(episodes), "successes": panel["counts"]["successes"],
             "success_rate": panel["full_panel_success_rate"], "protocol": descriptor.get("protocol_version")}
    found = []
    if index_path.exists():
        index = _json(index_path)
        _require(index.get("schema_version") == INDEX_SCHEMA and index.get("benchmark") == benchmark,
                 "existing result index is incompatible")
        found = [row for row in index.get("runs", []) if row.get("run_id") == publication_id]
        runs = [row for row in index.get("runs", []) if row.get("run_id") != publication_id] + [entry]
        latest = publication_id if accepted else index.get("latest_accepted_run")
    else:
        runs = [entry]
        latest = publication_id if accepted else None
    index = {"schema_version": INDEX_SCHEMA, "benchmark": benchmark,
             "latest_accepted_run": latest, "runs": runs}
    _portable(index)

    # Every evidence, identity, panel and destination check runs before any
    # public file is written: a refused publication leaves nothing behind.
    report_dir = results_root / "reports" / publication_id
    media_dir = results_root / "media" / publication_id
    reports = {report_dir / "result.json": publication,
               report_dir / "episodes.json": {"schema_version": EPISODE_SCHEMA,
                                              "run_id": publication_id, "episodes": episodes},
               report_dir / "media.json": media_manifest}
    conflicts = [] if not found or found == [entry] else [f"existing index contains a different run entry: {publication_id}"]
    for path, payload in reports.items():
        if path.exists() or path.is_symlink():
            if not (path.is_file() and not path.is_symlink() and path.read_bytes() == _encode(path, payload)):
                conflicts.append(f"different publication file: {path}")
    for source, relative in copies:
        destination = results_root / relative
        if destination.exists() or destination.is_symlink():
            if not (destination.is_file() and not destination.is_symlink() and _sha(destination) == _sha(source)):
                conflicts.append(f"different media: {destination}")
    replace = bool(conflicts)
    if replace:
        # Only an unaccepted publication of the same source (a growing remote
        # run, or new task descriptions) is replaced, and then in full.
        previous = report_dir / "result.json"
        previous = _json(previous) if previous.is_file() and not previous.is_symlink() else None
        _require(isinstance(previous, dict) and previous.get("accepted") is False
                 and all(row.get("accepted") is False for row in found)
                 and _source_identity(previous) == _source_identity(publication),
                 f"refusing to replace an accepted or differently sourced publication: {conflicts[0]}")
        for directory in (report_dir, media_dir):
            _require(not directory.is_symlink() and (directory.is_dir() or not directory.exists()),
                     f"publication directory is not a plain directory: {directory}")
    else:
        for _, relative in copies:
            temporary = _media_temporary(results_root / relative)
            _require(not (temporary.exists() or temporary.is_symlink()),
                     f"temporary media path already exists: {temporary}")

    if replace:
        for directory in (report_dir, media_dir):
            if directory.exists():
                shutil.rmtree(directory)
    for source, relative in copies:
        _materialize(source, results_root / relative)
    for path, payload in reports.items():
        if not path.exists():
            atomic_write_json(path, payload, overwrite=False)
    atomic_write_json(index_path, index, overwrite=True)
    return {"result": publication, "episodes": episodes, "media": media, "index": index}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-run", required=True, type=Path,
                        help="one closed client run (or its client/server pair) or a remote-run output directory")
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--task-description", action="append", default=[], metavar="TASK=SHORT-DESCRIPTION")
    parser.add_argument("--reference", type=_reference, metavar="SUCCESSES/EPISODES",
                        help="optional operator-declared reference result to compare against")
    args = parser.parse_args(argv)
    output = publish(args.raw_run, args.results_root, _description_map(args.task_description),
                     reference=args.reference)
    print(json.dumps({"run_id": output["result"]["run_id"],
                      "episodes": len(output["episodes"]), "media": len(output["media"]),
                      "result": str(args.results_root / "reports" / output["result"]["run_id"] / "result.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
