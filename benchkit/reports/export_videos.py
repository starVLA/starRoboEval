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


def component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value).strip(".") or "episode"


def resolve_video(run: Path, episode: dict, source: str) -> Path:
    """Absolute artifacts or bound-worker paths relative to that episode only."""
    path = Path(source)
    if not path.is_absolute():
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
        base = matches[0].resolve(strict=True)
        path = (base / path).resolve(strict=True)
        if not base.is_relative_to(run) or not path.is_relative_to(base):
            raise ValueError("relative worker video escaped its bound artifact directory")
    path = path.resolve(strict=True)
    if not path.is_relative_to(run) or not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("video artifact must be an MP4 file inside the closed run")
    return path


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
    names = [component(item["episode"]["id"]) for item in episodes]
    if len(names) != len(set(names)):
        parser.error("episode archive paths would collide")
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
        target = output if len(episodes) == 1 else output / names[index]
        target.mkdir(exist_ok=True)
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
        report["episodes"].append({
            "episode": episode["episode"], "status": episode["status"],
            "success": episode["success"], "metrics": episode["metrics"],
            "termination_reason": episode["termination_reason"], "error": episode["error"],
            "environment_steps": episode["environment_steps"], "policy_calls": episode["policy_calls"],
            "usage": episode["usage"], "videos": videos,
            "video_status": "available" if videos else "not_produced",
        })
    (output / "index.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
