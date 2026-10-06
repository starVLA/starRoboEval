"""Index explicit closed anonymous legacy runs and selected original videos.

This is an offline adoption tool, not an evaluator or a complete artifact audit.
It never imports adapters, follows mailbox references, rescans campaign trees,
copies source/assets, or changes original results. It preserves unknown identity.
Named-profile reporting and user-attributed model labels need separate entrypoints;
null provider/model fields do not override an explicit model-profile declaration.
Infrastructure diagnostics retain their purpose and use archived media paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "starvla-rsi.result-index/v1"
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
SUCCESS_FIELDS = {
    "simpler_env": "success", "libero": "native_success",
    "robocasa365": "native_success", "robocasa_365": "native_success",
    "simple_humanoid": "native_success", "robocasa_tabletop": "native_success",
    "robodojo": "native_success",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _object(pairs: list) -> dict:
    value: dict = {}
    for key, item in pairs:
        require(key not in value, f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON value: {value}")


def _float(value: str) -> float:
    number = float(value)
    require(math.isfinite(number), "nonfinite JSON number")
    return number


def decode(payload: bytes) -> Any:
    return json.loads(payload, object_pairs_hook=_object,
                      parse_constant=_reject_constant, parse_float=_float)


def component(value: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), "empty path component")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "episode"


class ClosedFiles:
    """Bounded reads of explicitly selected regular files inside one closed run."""

    def __init__(self, root: Path):
        require(not root.is_symlink(), "source run must not be a symlink")
        self.root = root.resolve(strict=True)
        require(self.root.is_dir(), "source run must be a directory")
        self.hashes: dict[str, str] = {}

    def path(self, relative: str) -> Path:
        part = Path(relative)
        require(bool(part.parts) and not part.is_absolute() and ".." not in part.parts,
                "unsafe source-relative path")
        path = self.root
        for name in part.parts:
            path = path / name
            require(not path.is_symlink(), f"symlink in source path: {relative}")
        require(path.is_file() and path.resolve().is_relative_to(self.root),
                f"missing or outside source file: {relative}")
        return path

    def read(self, relative: str, *, limit: int = MAX_JSON_BYTES,
             destination: Path | None = None) -> bytes | None:
        path = self.path(relative)
        digest = hashlib.sha256()
        chunks = []
        total = 0
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_size <= limit,
                    "source is not a bounded regular file")
            target = destination.open("xb") if destination is not None else None
            try:
                while chunk := source.read(1024 * 1024):
                    total += len(chunk)
                    require(total <= limit, "source exceeds read limit")
                    digest.update(chunk)
                    if target is not None:
                        target.write(chunk)
                    elif limit == MAX_JSON_BYTES:
                        chunks.append(chunk)
            finally:
                if target is not None:
                    target.close()
            after = os.fstat(source.fileno())
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                    "source changed during read")
        actual = digest.hexdigest()
        require(relative not in self.hashes or self.hashes[relative] == actual,
                f"source changed since inspection: {relative}")
        self.hashes[relative] = actual
        return b"".join(chunks) if destination is None and limit == MAX_JSON_BYTES else None

    def json(self, relative: str) -> Any:
        return decode(self.read(relative))

    def jsonl(self, relative: str) -> list:
        return [decode(line) for line in self.read(relative).splitlines() if line]

    def verify_unchanged(self) -> None:
        for relative in list(self.hashes):
            self.read(relative, limit=MAX_VIDEO_BYTES if relative.lower().endswith(".mp4") else MAX_JSON_BYTES)


def _counter(value: Any, label: str) -> int:
    require(type(value) is int and value >= 0, f"invalid {label} counter")
    return value


def _same_json(left: Any, right: Any) -> bool:
    """Compare JSON records without Python's bool/int/float equality aliases."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _anonymous_policy(manifest: dict) -> dict:
    policy = manifest["policy"]
    require(isinstance(policy, dict), "invalid policy descriptor")
    require(policy.get("model") is None and policy.get("provider") is None,
            "anonymous namespace cannot adopt a named model/provider run")
    parameters = policy.get("parameters", {})
    require(isinstance(parameters, dict), "invalid policy parameters")
    profiles = [container["model_profile"] for container in (manifest, parameters) if "model_profile" in container]
    for profile in profiles:
        require(isinstance(profile, dict) and profile.get("id") == "anonymous_code_agent",
                "anonymous namespace requires an anonymous_code_agent model profile; "
                "explicit other or invalid profiles cannot be relabelled")
    require(not profiles or all(_same_json(profile, profiles[0]) for profile in profiles),
            "manifest and policy model profiles disagree")
    return policy


def _progress(events: list, result: dict, benchmark: str) -> dict:
    field = SUCCESS_FIELDS.get(benchmark)
    steps = [event for event in events if event.get("event") == "environment_step"]
    calls = [event.get("policy_call") for event in steps]
    valid_calls = all(type(call) is int and 1 <= call <= result["policy_calls"] for call in calls)
    coverage = bool(field) and len(steps) == result["environment_steps"] and valid_calls and all(
        type(event.get("environment_step")) is int and event["environment_step"] == index
        and type(event.get("info", {}).get(field)) is bool
        for index, event in enumerate(steps, 1)) and calls == sorted(calls)
    first = next((event for event in steps if event.get("info", {}).get(field) is True), None) if field else None
    return {
        "native_success_field": field, "complete_step_coverage": coverage,
        "first_native_success_step": first["environment_step"] if first and coverage else None,
        "policy_call_at_first_native_success": first.get("policy_call") if first and coverage else None,
        "first_native_success_timestamp": first.get("timestamp") if first and coverage else None,
    }


def inspect_run(source: dict) -> tuple[dict, ClosedFiles, list]:
    require(isinstance(source, dict) and set(source) <= {"run_dir", "videos"}, "invalid run selection")
    require(isinstance(source.get("run_dir"), str) and Path(source["run_dir"]).is_absolute(),
            "source run_dir must be explicit and absolute")
    files = ClosedFiles(Path(source["run_dir"]))
    lifecycle = files.json("status.json")
    require(lifecycle.get("status") in ("completed", "completed_with_errors"), "only closed runs may be indexed")
    manifest = files.json("manifest.json")
    policy = _anonymous_policy(manifest)
    parameters = policy.get("parameters", {})
    diagnostic = (policy.get("name") == "constant-action-diagnostic"
                  or manifest.get("purpose") == "infrastructure_validation_only"
                  or parameters.get("purpose") == "infrastructure_validation_only")
    benchmark = manifest["benchmark"]["name"]
    indexed = files.jsonl("episodes.jsonl")
    episodes_written = _counter(lifecycle.get("episodes_written"), "episodes_written")
    require(indexed and len(indexed) == episodes_written, "closed episode count mismatch")
    episode_root = files.root / "episodes"
    require(episode_root.is_dir() and not episode_root.is_symlink(), "invalid episode directory")
    result_paths = sorted(episode_root.glob("*/result.json"))
    require(len(result_paths) == len(indexed), "episode file/index count mismatch")
    by_id = {result["episode"]["id"]: result for result in indexed}
    require(len(by_id) == len(indexed), "duplicate episode identity")
    rows = []
    result_directories = {}
    for path in result_paths:
        relative = path.relative_to(files.root).as_posix()
        result = files.json(relative)
        episode_id = result["episode"]["id"]
        require(_same_json(result, by_id.get(episode_id)) and episode_id not in result_directories,
                "canonical result and episode index disagree")
        result_directories[episode_id] = path.parent
        for name in ("environment_steps", "policy_calls"):
            _counter(result[name], name)
        if "action_decisions" in result:
            count = _counter(result["action_decisions"], "executed action decisions")
            require(count <= min(result["policy_calls"], result["environment_steps"]),
                    "executed action decisions exceed calls or controls")
        require(result["status"] in ("completed", "error"), "unknown episode lifecycle")
        if result["status"] == "completed":
            require(type(result["success"]) is bool and result["error"] is None,
                    "completed result success/error mismatch")
        else:
            require(result["success"] is None and isinstance(result["error"], dict),
                    "error result must retain null success")
        events = files.jsonl(path.with_name("events.jsonl").relative_to(files.root).as_posix())
        require(events and events[0].get("event") == "episode_start"
                and events[-1].get("event") == "episode_end" and _same_json(events[-1].get("result"), result),
                "episode event closure/result mismatch")
        row = {key: result.get(key) for key in (
            "episode", "status", "success", "error", "termination_reason", "environment_steps",
            "policy_calls", "usage", "metrics", "duration_s")}
        row.update(source_result=str(path), progress=_progress(events, result, benchmark))
        if "action_decisions" in result:
            row["action_decisions"] = result["action_decisions"]
        rows.append(row)
    summary = files.json("summary.json")
    completed = sum(row["status"] == "completed" for row in rows)
    expected = {"attempted": len(rows), "completed": completed, "errors": len(rows) - completed,
                "successes": sum(row["success"] is True for row in rows),
                "policy_calls": sum(row["policy_calls"] for row in rows)}
    require(all(type(summary.get(key)) is int and summary[key] == value for key, value in expected.items()),
            "closed summary and canonical results disagree")
    require((lifecycle["status"] == "completed") == (expected["errors"] == 0), "run lifecycle and errors disagree")
    run_key = component(manifest["run_id"]) + "-" + hashlib.sha256(str(files.root).encode()).hexdigest()[:12]
    selections = source.get("videos", [])
    require(isinstance(selections, list), "videos must be an explicit list")
    media = []
    for selection in selections:
        require(isinstance(selection, dict) and set(selection) == {"episode_id", "artifact", "camera", "description"},
                "video selection needs episode_id, artifact, camera and description")
        episode_id = selection["episode_id"]
        require(episode_id in by_id, "selected video episode is absent")
        result = by_id[episode_id]
        reference = result.get("artifacts", {}).get(selection["artifact"])
        require(isinstance(reference, str), "selected artifact is absent")
        path = Path(reference)
        if not path.is_absolute():
            path = result_directories[episode_id] / "artifacts" / path
        require(path.is_relative_to(files.root) and path.suffix.lower() == ".mp4",
                "video must be an MP4 inside selected run")
        relative = path.relative_to(files.root).as_posix()
        files.read(relative, limit=MAX_VIDEO_BYTES)
        task = component(result["episode"]["task"])
        description = selection["description"]
        require(isinstance(description, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+", description),
                "video description must be a short English hyphenated phrase")
        camera = component(selection["camera"])
        date = str(manifest["created_at"])[:10]
        require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)), "invalid source creation date")
        case = component(files.root.parent.name)
        episode_key = hashlib.sha256(episode_id.encode()).hexdigest()[:8]
        directory = f"{date}-{task}-{description}-{run_key}-{case}-{episode_key}"
        require(len(directory.encode()) <= 240, "video directory name is too long; use a shorter description")
        # A fixed-action infrastructure diagnostic may execute many controls.
        archive_reasons = []
        if diagnostic:
            archive_reasons.append("infrastructure_validation_only")
        if result["environment_steps"] == 0:
            archive_reasons.append("zero_controls")
        if result["policy_calls"] == 0:
            archive_reasons.append("no_policy_calls")
        if result["status"] == "error":
            archive_reasons.append("episode_error")
        archive = "archive/" if archive_reasons else ""
        destination = f"media/{archive}{component(benchmark)}/{directory}/{camera}-{path.name}"
        media.append({"source": str(path), "source_relative": relative, "path": destination,
                      "sha256": files.hashes[relative], "size_bytes": path.stat().st_size,
                      "camera": selection["camera"], "episode_id": episode_id,
                      "diagnostic": diagnostic, "archive_reasons": archive_reasons})
    row = {
        "source_run": str(files.root), "run_id": manifest["run_id"], "benchmark": manifest["benchmark"],
        "policy": policy, "protocol": manifest["protocol"], "action_spec": manifest.get("action_spec"),
        "observation_spec": manifest.get("observation_spec"), "runtime": manifest.get("runtime"),
        "harness_source": manifest.get("harness_source"), "status": lifecycle["status"],
        "summary": summary, "episodes": rows, "videos": media, "source_files_sha256": files.hashes,
        "diagnostic": diagnostic,
    }
    if "purpose" in manifest:
        row["purpose"] = manifest["purpose"]
    elif "purpose" in parameters:
        row["purpose"] = parameters["purpose"]
    elif diagnostic:
        row["purpose"] = "infrastructure_validation_only"
    for key in ("model_source", "model_profile"):
        if key in manifest:
            row[key] = manifest[key]
    if "model_profile" not in row and "model_profile" in policy.get("parameters", {}):
        row["model_profile"] = policy["parameters"]["model_profile"]
    files.verify_unchanged()
    return row, files, media


def adopt(sources: list, output: Path) -> dict:
    """Create a new index, plus only explicitly selected exact-byte video copies."""
    require(isinstance(sources, list) and bool(sources), "sources must be a nonempty explicit list")
    require(not output.exists() and not output.is_symlink(), "output must be a new directory")
    output = output.resolve()
    inspected = [inspect_run(source) for source in sources]
    roots = [files.root for _, files, _ in inspected]
    require(len(roots) == len(set(roots)), "duplicate source run")
    require(all(not output.is_relative_to(root) and not root.is_relative_to(output) for root in roots),
            "output must not overlap any source run")
    destinations = [video["path"] for _, _, videos in inspected for video in videos]
    require(len(destinations) == len(set(destinations)), "selected video output paths collide")
    for _, files, _ in inspected:
        files.verify_unchanged()
    report = {
        "schema_version": SCHEMA_VERSION, "namespace": "anonymous_code_agent", "model": None, "provider": None,
        "created_at": datetime.now(timezone.utc).isoformat(), "runs": [row for row, _, _ in inspected],
        "limitations": ["Index of the explicit closed source list, not full benchmark coverage or a merged model score.",
                        "Original manifests, results, source packages and paths remain unchanged.",
                        "Hashes cover the listed records and selected videos, not all source/assets/wire artifacts.",
                        "Native first success is read from existing step logs; incomplete evidence remains null.",
                        "Diagnostic runs retain native outcomes as infrastructure evidence, not model capability scores.",
                        "Model/provider identity, accounting and isolation are not retroactively verified."],
    }
    output.mkdir(parents=True, exist_ok=False)
    for _, files, videos in inspected:
        for video in videos:
            destination = output / video["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            files.read(video["source_relative"], limit=MAX_VIDEO_BYTES, destination=destination)
            copied = hashlib.sha256()
            with destination.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    copied.update(chunk)
            require(copied.hexdigest() == video["sha256"], "copied video digest mismatch")
        files.verify_unchanged()
    # Publish last. A failed partial adoption has no index.json and is never reused.
    with (output / "index.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True, help="JSON array of explicit absolute run_dir selections")
    parser.add_argument("--output-dir", type=Path, required=True, help="new model results index directory")
    args = parser.parse_args()
    require(args.sources.stat().st_size <= MAX_JSON_BYTES, "source selection exceeds size limit")
    report = adopt(decode(args.sources.read_bytes()), args.output_dir)
    print(json.dumps({"index": str(args.output_dir / "index.json"), "runs": len(report["runs"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
