"""Build/serve a read-only local review of explicitly selected closed episodes.

No simulator or model dependencies. Media are referenced, never copied or deleted.
The loopback HTTP server exposes only generated page assets and allowlisted MP4s,
not the repository, raw records, source snapshots, credentials or directory lists.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from benchkit.audits.closed_run import require
from benchkit.reports.interaction_history import _build_history

ASSETS = Path(__file__).with_name("viewer_assets")
STATIC = ("index.html", "app.js", "style.css", "data.js")
SCHEMA = "starvla-rsi.episode-viewer/v1"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def compact_call(call):
    """Keep every decision and its input; explicitly omit intermediate ACKs."""
    row = {key: value for key, value in call.items() if key != "acknowledged_controls"}
    acks = call["acknowledged_controls"]
    row.update(acknowledged_count=len(acks), first_ack=acks[0] if acks else None,
               last_ack=acks[-1] if acks else None,
               omitted_intermediate_ack_count=max(0, len(acks) - 2))
    return row


def javascript_data(value):
    # Safe both as external JS and if inspected in an HTML script context.
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for char, replacement in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                              ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        data = data.replace(char, replacement)
    return "window.EVALUATION_VIEWER=" + data + ";\n"


def build(config_path, output):
    """Operator config is private; project only curated fields into the webpage."""
    config = read_json(config_path)
    specs = config["tasks"]
    require(isinstance(specs, list) and 0 < len(specs) <= 100, "invalid selected task count")
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), "output must be a new directory")
    require(not any(parent.is_symlink() for parent in output.parents), "symlink in output path")
    receipts, tasks, media, identifiers = [], [], {}, set()
    for spec in specs:
        identifier = spec["id"]
        require(isinstance(identifier, str) and re.fullmatch(r"[a-z0-9_-]{1,80}", identifier), "unsafe task ID")
        require(identifier not in identifiers, "duplicate task ID")
        identifiers.add(identifier)
        source = Path(spec["client_dir"])
        require(not source.is_symlink(), "symlink client root")
        source = source.resolve(strict=True)
        require(not output.resolve().is_relative_to(source), "output must be outside source run")
        history, files = _build_history(source)
        require(len(history["episodes"]) == 1, "select one episode per task entry")
        episode = history["episodes"][0]
        require(history["run_id"] == spec["run_id"], "selected run ID mismatch")
        require(episode["task"] == spec["task"], "selected task mismatch")
        # Only this explicitly named final score leaves the private metrics.
        expected_index_hash = files.hashes["episodes.jsonl"]
        indexed = files.jsonl("episodes.jsonl")[0]
        require(files.hashes["episodes.jsonl"] == expected_index_hash,
                "episode index changed after record audit")
        score = indexed["metrics"].get("native_benchmark_score")
        require(score is None or (type(score) in (int, float) and math.isfinite(score)), "invalid final score")
        scale = indexed["metrics"].get("native_benchmark_score_scale")
        scale = scale if isinstance(scale, str) and len(scale) <= 32 else None  # Display hint only.
        videos, cameras = [], set()
        for video in spec.get("videos", []):
            camera = video["camera"]
            require(camera in history["contracts"]["observation"]["cameras"] and camera not in cameras,
                    "video camera not declared or duplicated")
            require(re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", camera), "unsafe camera ID")
            cameras.add(camera)
            require(video["run_id"] == history["run_id"] and video["task"] == episode["task"],
                    "video provenance differs from selected run")
            require(video.get("mapping") == "initial_frame_then_one_per_control", "unsupported frame mapping")
            require(type(video["fps"]) in (int, float) and math.isfinite(video["fps"]) and video["fps"] > 0,
                    "invalid fps")
            require(type(video["frames"]) is int and video["frames"] == episode["counters"]["controls"] + 1,
                    "video frame count does not match complete control sequence")
            require(type(video["bytes"]) is int and video["bytes"] > 0 and
                    re.fullmatch(r"[0-9a-f]{64}", video["sha256"]), "invalid media fingerprint")
            path = Path(video["path"])
            require(path.is_absolute() and path.suffix == ".mp4", "media must be explicit absolute MP4 path")
            url = f"media/{identifier}/video_{camera}.mp4"
            # Private serving manifest contains deployment paths; never expose it over HTTP.
            media[url] = {"path": str(path), "bytes": video["bytes"], "sha256": video["sha256"]}
            videos.append({key: video[key] for key in ("camera", "fps", "frames", "bytes", "sha256", "mapping")})
            videos[-1].update(url=url, verification="declared decode metadata; serving verifies SHA-256")
        tasks.append({"id": identifier, "title": spec["title"], "run_id": history["run_id"],
            "task": episode["task"], "seed": episode["seed"], "method": history["policy"]["name"],
            "method_version": history["policy"]["version"],
            "model": history["policy"]["model"], "benchmark": history["benchmark"]["name"],
            "protocol": history["benchmark"]["protocol_version"], "status": episode["status"],
            "success": episode["success"], "termination_reason": episode["termination_reason"],
            "counters": episode["counters"], "contracts": history["contracts"],
            "score": {"label": "原生 benchmark 分数（事后）", "value": score, "scale": scale,
                      "source": "closed episode metrics.native_benchmark_score; not actor input"},
            "calls": [compact_call(call) for call in episode["calls"]], "videos": videos,
            "limitations": history["limitations"]})
        receipts.append(files)
    data = {"schema": SCHEMA, "title": config.get("title", "具身任务评测回看"),
            "generated_at": datetime.now(timezone.utc).isoformat(), "tasks": tasks}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".episode-viewer-", dir=output.parent) as temporary:
        stage = Path(temporary) / "page"
        stage.mkdir()
        for name in STATIC[:-1]:
            shutil.copyfile(ASSETS / name, stage / name)
        (stage / "data.js").write_text(javascript_data(data), encoding="utf-8")
        (stage / ".media-map.json").write_text(json.dumps(media, indent=2) + "\n", encoding="utf-8")
        for receipt in receipts:
            receipt.verify_unchanged()
        require(not output.exists(), "output appeared during build")
        stage.rename(output)
    return data


def byte_range(header, size):
    if header is None:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()):
        raise ValueError("unsupported byte range")
    left, right = match.groups()
    if not left:
        length = int(right)
        if length <= 0:
            raise ValueError("empty suffix range")
        start, end = max(0, size - length), size - 1
    else:
        start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start > end or start >= size:
        raise ValueError("unsatisfiable range")
    return start, end, True


def handler_for(directory):
    directory = Path(directory).resolve(strict=True)
    allowed = {"/" + name: directory / name for name in STATIC}
    allowed["/"] = allowed["/index.html"]
    # Large exact numeric histories compress well; keep source values unchanged.
    compressed_data = gzip.compress((directory / "data.js").read_bytes(), compresslevel=6)
    mapping = read_json(directory / ".media-map.json")
    for url, meta in mapping.items():
        require(re.fullmatch(r"media/[a-z0-9_-]{1,80}/video_[a-zA-Z0-9_-]{1,80}\.mp4", url), "unsafe media route")
        path = Path(meta["path"]).resolve(strict=True)
        require(path.is_file() and path.stat().st_size == meta["bytes"] and digest(path) == meta["sha256"],
                "media changed or missing; refusing to serve")
        allowed["/" + url] = path

    class ViewerHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.respond(False)

        def do_GET(self):
            self.respond(True)

        def respond(self, body):
            route = urlsplit(self.path).path
            path = allowed.get(route)
            if path is None:
                self.send_error(404)
                return
            if route == "/data.js" and "gzip" in self.headers.get("Accept-Encoding", "") and not self.headers.get("Range"):
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
                self.send_header("Content-Length", str(len(compressed_data)))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if body:
                    try:
                        self.wfile.write(compressed_data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                return
            try:
                size = path.stat().st_size
                start, end, partial = byte_range(self.headers.get("Range"), size)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            except OSError:
                self.send_error(404)
                return
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if body:
                try:
                    with path.open("rb") as stream:
                        stream.seek(start)
                        remaining = end - start + 1
                        while remaining:
                            block = stream.read(min(65536, remaining))
                            if not block:
                                break
                            self.wfile.write(block)
                            remaining -= len(block)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    return ViewerHandler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("build")
    create.add_argument("--config", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--directory", type=Path, required=True)
    serve.add_argument("--port", type=int, default=18766)
    args = parser.parse_args(argv)
    if args.command == "build":
        data = build(args.config, args.output)
        print(json.dumps({"tasks": len(data["tasks"]), "calls": sum(len(t["calls"]) for t in data["tasks"]),
                          "output": str(args.output)}))
    else:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(args.directory))
        print(f"Read-only evaluation viewer: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
