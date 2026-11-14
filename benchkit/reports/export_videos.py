#!/usr/bin/env python3
"""Copy videos from a closed runner result, preserving originals and score context."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

SERVER_VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".avi", ".mov")
MAX_COMPONENT = 64  # keeps every archive path segment well under filesystem name limits


def component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:MAX_COMPONENT].strip(".") or "episode"


def episode_dir_name(created_at: str, episode: dict, case: int) -> str:
    """Date, canonical task ID, short English description and run-local case."""
    date = re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", created_at)
    if date is None:
        raise ValueError("manifest created_at is not an ISO date")
    # Whole words only: a word with any non-ASCII letter is skipped, never truncated.
    words = [word for word in re.findall(r"[^\W_]+", episode["instruction"].lower())
             if re.fullmatch(r"[a-z0-9]+", word) and word not in ("a", "an", "the")][:4]
    description = "-".join(words)[:MAX_COMPONENT].rstrip("-")
    parts = [date.group(), component(episode["task"]), description, f"case{case:03d}"]
    return "-".join(part for part in parts if part)


def artifact_dir(run: Path, episode: dict) -> Path:
    """The bound artifact directory of the one closed result for this episode."""
    matches = []
    for result_path in (run / "episodes").glob("*/result.json"):
        if not result_path.resolve().is_relative_to(run):
            raise ValueError("episode result escaped the closed run")
        recorded = json.loads(result_path.read_text())
        if recorded["episode"]["id"] == episode["episode"]["id"]:
            if recorded != episode:
                raise ValueError("episode index and result disagree")
            matches.append(result_path.parent / "artifacts")
    if len(matches) != 1:
        raise ValueError("relative video requires one matching closed episode result")
    return matches[0].resolve(strict=True)


def resolve_video(run: Path, episode: dict, source: str) -> Path:
    """Absolute artifacts or bound-worker paths relative to that episode only."""
    path = Path(source)
    if not path.is_absolute():
        base = artifact_dir(run, episode)
        path = (base / path).resolve(strict=True)
        if not base.is_relative_to(run) or not path.is_relative_to(base):
            raise ValueError("relative worker video escaped its bound artifact directory")
    path = path.resolve(strict=True)
    if not path.is_relative_to(run) or not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("video artifact must be an MP4 file inside the closed run")
    return path


def server_videos(run: Path, episode: dict) -> list[dict]:
    """Videos the benchmark server kept without a client copy, from the SIM receipt."""
    try:
        receipt = artifact_dir(run, episode) / "sim_server_receipt.json"
    except (OSError, ValueError):
        return []
    if not receipt.is_file():
        return []
    retention = json.loads(receipt.read_text())["client_retention"]
    return [{"path": row["path"], "sha256": row["sha256"], "bytes": row["size_bytes"],
             "server_id": retention["reference_identity"]["server_id"],
             "session_id": retention["reference_identity"]["session_id"]}
            for row in retention["server_media_references"]
            if Path(row["path"]).suffix.lower() in SERVER_VIDEO_SUFFIXES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="new archive directory; never overwritten")
    args = parser.parse_args()
    run = args.run_dir.resolve(strict=True)
    status = json.loads((run / "status.json").read_text())
    if status.get("status") not in ("completed", "completed_with_errors"):
        parser.error("only closed runs may be exported; do not inspect or publish an active attempt")
    manifest = json.loads((run / "manifest.json").read_text())
    episodes = [json.loads(line) for line in (run / "episodes.jsonl").read_text().splitlines() if line]
    if not episodes:
        parser.error("closed run contains no episode records")
    try:
        names = [episode_dir_name(manifest["created_at"], item["episode"], index)
                 for index, item in enumerate(episodes)]
    except (KeyError, TypeError, ValueError) as error:
        parser.error(f"cannot name episode archive directories: {error}")
    # Resolve all sources before creating output. Artifact references must not
    # copy arbitrary files outside this completed run.
    sources = []
    destinations = set()
    for index, episode in enumerate(episodes):
        for key, source in episode.get("artifacts", {}).items():
            worker_video = key.startswith("video_") and key not in ("video_manifest", "video_validation", "video_errors")
            if key == "video" or key.endswith("_video") or worker_video:
                destination_key = (index, component(key))
                if destination_key in destinations:
                    parser.error("video artifact archive paths would collide")
                destinations.add(destination_key)
                try:
                    path = resolve_video(run, episode, source)
                except (OSError, ValueError) as error:
                    parser.error(f"invalid video artifact for {episode['episode']['id']}: {key}: {error}")
                sources.append((index, key, path))
    # Parse server receipts up front so a corrupt one leaves no partial archive.
    on_server = {}
    for index, episode in enumerate(episodes):
        if not any(source_index == index for source_index, _, _ in sources):
            try:
                on_server[index] = server_videos(run, episode)
            except (OSError, ValueError, KeyError, TypeError) as error:
                parser.error(f"invalid SIM receipt for {episode['episode']['id']}: {error!r}")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": "starvla-rsi.video-archive/v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_run": str(run), "run_id": manifest["run_id"],
        "benchmark": manifest["benchmark"], "protocol": manifest["protocol"],
        "policy": manifest["policy"], "episodes": [],
    }
    for index, episode in enumerate(episodes):
        target = output / names[index]
        target.mkdir()
        videos = []
        for source_index, key, source in sources:
            if source_index != index:
                continue
            destination = target / (component(key) + ".mp4")
            shutil.copy2(source, destination)
            source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if hashlib.sha256(destination.read_bytes()).hexdigest() != source_digest:
                raise RuntimeError("copied video digest differs from its source")
            videos.append({"path": str(destination.relative_to(output)), "sha256": source_digest,
                           "source": str(source), "bytes": destination.stat().st_size})
        retained = on_server.get(index, [])
        report["episodes"].append({
            "directory": names[index], "episode": episode["episode"], "status": episode["status"],
            "success": episode["success"], "metrics": episode["metrics"],
            "termination_reason": episode["termination_reason"], "error": episode["error"],
            "environment_steps": episode["environment_steps"], "policy_calls": episode["policy_calls"],
            "usage": episode["usage"], "videos": videos, "server_videos": retained,
            "video_status": "available" if videos else "retained_on_server" if retained else "not_produced",
        })
    (output / "index.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
