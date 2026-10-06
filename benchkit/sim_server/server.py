"""Single-thread, fixed-schedule SIM service. Never generates policy actions."""
from __future__ import annotations

import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import traceback
import uuid

from benchkit.artifacts import append_jsonl, atomic_write_json, utc_now
from benchkit.contracts import ensure_jsonable
from benchkit.errors import ActionRejected
from benchkit.validation import ValidationIssue, validate_action_vector
from benchkit.sim_server.wire import (
    MAX_MESSAGE_BYTES, PROTOCOL, dumps, loads, encode_observation, encode_transition,
)

CHUNK_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 ** 3
MAX_ARTIFACT_FILES = 100000
ACTION_REJECTION_PROTOCOL = "starvla-rsi.action-rejection/v1"
MEDIA_RETENTION_SCHEMA = "starvla-rsi.server-media-retention/v1"
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mkv", ".avi", ".mov"})


class ServiceError(RuntimeError):
    """Closed error code; never serialize native exception messages to HTTP."""


class ServiceActionRejected(ServiceError):
    """A proven pre-execution rejection, never an uncertain native failure."""

    def __init__(self, issue, sequence):
        super().__init__("invalid_action")
        self.issue, self.sequence = issue, sequence


def relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or any(p in ("", ".", "..") for p in value.split("/"))
            or PurePosixPath(value).is_absolute()):
        raise ServiceError("invalid_artifact_path")
    return value


def open_regular(root: Path, relative: str):
    """No-follow traversal, including parent components; bounded caller reads."""
    parts = relative_path(relative).split("/")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(os.fstat(child).st_mode):
        os.close(child)
        raise ServiceError("nonregular_artifact")
    return os.fdopen(child, "rb")


def _media_stat(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _verify_media(root, row):
    with open_regular(root, row["path"]) as stream:
        before = os.fstat(stream.fileno())
        if before.st_nlink != 1 or before.st_size != row["size_bytes"]:
            raise ServiceError("media_retention_changed")
        digest, count = hashlib.sha256(), 0
        while payload := stream.read(min(CHUNK_BYTES, before.st_size - count + 1)):
            count += len(payload)
            if count > before.st_size:
                raise ServiceError("media_retention_changed")
            digest.update(payload)
        if (count != before.st_size or digest.hexdigest() != row["sha256"]
                or _media_stat(before) != _media_stat(os.fstat(stream.fileno()))):
            raise ServiceError("media_retention_changed")
        return _media_stat(before)


def _unlink_media(root, relative, expected, removed):
    """Use anchored no-follow directory descriptors; never recursively delete."""
    parts = relative_path(relative).split("/")
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _media_stat(info) != expected:
            raise ServiceError("media_retention_changed")
        os.unlink(parts[-1], dir_fd=parent)
        removed.add(relative)  # Preserve actual deletion even if directory fsync fails.
        os.fsync(parent)
    finally:
        os.close(parent)


def _durable_media_record(root, name, value):
    payload = dumps(value)
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)
    return {"path": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


class BenchmarkService:
    """One native owner, an immutable schedule, at most one active episode.

    The output directory is exclusive: an old attempt directory cannot be
    restarted or silently reused. Restart needs operator reconciliation and a
    separately authorized schedule, not retry-on-failure behavior.
    """

    def __init__(self, adapter, *, root: Path, seed: int, limit: int | None = None,
                 source: dict | None = None, parameters: dict | None = None,
                 excluded_artifact_directories: tuple[str, ...] = (), capture_source: bool = False,
                 supplemental_sources: tuple[str, ...] = (), retain_frame_images: bool = False):
        if type(retain_frame_images) is not bool:
            raise ValueError("retain_frame_images must be a boolean")
        if type(seed) is not int or (limit is not None and (type(limit) is not int or limit <= 0)):
            raise ValueError("seed must be integer; limit must be positive or None")
        required_prefix = getattr(adapter, "required_replan_interval", None)
        if required_prefix is not None and (type(required_prefix) is not int or required_prefix <= 0):
            raise ValueError("required_replan_interval must be a positive integer")
        self.adapter = adapter
        self.retain_frame_images = retain_frame_images
        self.root = Path(root).absolute()
        if self.root.is_symlink():
            raise ValueError("service root must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=False)
        if capture_source:
            from benchkit.source_snapshot import capture_harness_source, installed_source_root
            source = capture_harness_source(self.root, scope="service")
            extras = []
            for relative in supplemental_sources:
                relative = relative_path(relative)
                with open_regular(installed_source_root().parent, relative) as stream:
                    payload = stream.read(2 * 1024 * 1024 + 1)
                if len(payload) > 2 * 1024 * 1024 or len(extras) >= 32:
                    raise ValueError("supplemental service source exceeds capture bound")
                target = self.root / "service_source" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(payload)
                extras.append({"path": relative, "size_bytes": len(payload),
                               "sha256": hashlib.sha256(payload).hexdigest()})
            source = {"benchkit": source, "supplemental_files": extras,
                      "limitations": "Deployment file snapshot, not loaded-memory, dependency or asset attestation"}
        self.excluded = tuple(relative_path(p) for p in excluded_artifact_directories)
        self.episodes = list(adapter.episodes(seed, limit))
        if not self.episodes or len(self.episodes) > 10000:
            raise ValueError("service schedule needs 1..10000 episodes")
        self.schedule = {episode.id: episode for episode in self.episodes}
        if len(self.schedule) != len(self.episodes):
            raise ValueError("duplicate episode IDs")
        self.sessions: dict[str, dict] = {}
        self.claims: set[str] = set()
        self.active: str | None = None
        self.description = ensure_jsonable({
            "server_id": uuid.uuid4().hex,
            "action_rejection": ACTION_REJECTION_PROTOCOL,
            "descriptor": adapter.descriptor.to_dict(),
            "observation_spec": adapter.observation_spec.to_dict(),
            "action_spec": adapter.action_spec.to_dict(),
            "budget": {"budget_mode": getattr(adapter, "budget_mode", "horizon"),
                       "max_policy_calls": getattr(adapter, "max_policy_calls", None),
                       "replan_interval": getattr(adapter, "replan_interval", None),
                       "environment_step_cap": getattr(adapter, "environment_step_cap", None)},
            "seed": seed, "episodes": [episode.to_dict() for episode in self.episodes],
            "source": source or {"scope": "unspecified; not a source attestation"},
            "parameters": parameters or {},
        })
        if required_prefix is not None:
            self.description["budget"]["required_replan_interval"] = required_prefix
        dumps(self.description)
        atomic_write_json(self.root / "service.json", self.description, overwrite=False)

    def _session(self, params: dict, extra: set[str] = frozenset()) -> dict:
        if set(params) != {"session_id", *extra}:
            raise ServiceError("invalid_fields")
        sid = params["session_id"]
        if not isinstance(sid, str) or sid not in self.sessions:
            raise ServiceError("unknown_session")
        return self.sessions[sid]

    def _record(self, record: dict) -> None:
        atomic_write_json(record["root"] / "sim_server_session.json", {
            "protocol": PROTOCOL, "server_id": self.description["server_id"],
            "session_id": record["id"], "episode": record["episode"].to_dict(),
            "state": record["state"], "next_sequence": record["sequence"],
            "acknowledged_controls": record["controls"], "error_code": record["error"],
            "rejected_actions": record["rejections"],
            "cleanup_error": record["cleanup_error"],
            "excluded_artifact_directories": list(self.excluded),
            "media_retention": {"retain_frame_images": self.retain_frame_images,
                                "videos": "retained_on_server", "applies": "after_successful_native_close"},
            "counter_scope": "returned valid transitions; interrupted native calls may have executed",
        })

    def _error(self, record: dict, phase: str) -> None:
        # Evaluator-private local evidence. Only closed codes cross the RPC
        # error envelope. These files are never policy inputs.
        append_jsonl(record["root"] / "sim_server_errors.jsonl", {
            "phase": phase, "traceback": traceback.format_exc(),
        })

    def dispatch(self, op: str, params: dict) -> dict:
        if not isinstance(params, dict):
            raise ServiceError("invalid_fields")
        if op == "describe":
            if params:
                raise ServiceError("invalid_fields")
            return self.description
        if op == "open":
            if set(params) != {"episode_id"} or not isinstance(params["episode_id"], str):
                raise ServiceError("invalid_fields")
            eid = params["episode_id"]
            if eid not in self.schedule:
                raise ServiceError("unknown_episode")
            if eid in self.claims:
                raise ServiceError("episode_already_claimed")
            if self.active is not None:
                raise ServiceError("server_busy")
            sid = uuid.uuid4().hex
            folder = self.root / "episodes" / sid
            folder.mkdir(parents=True, exist_ok=False)
            # Durable claim BEFORE constructing native session. Failed opens are
            # retained attempts and cannot be reset through another connection.
            atomic_write_json(folder / "claim.json", {"episode_id": eid, "session_id": sid}, overwrite=False)
            self.claims.add(eid)
            record = {"id": sid, "episode": self.schedule[eid], "root": folder,
                      "native": None, "state": "opened", "sequence": 0, "controls": 0,
                      "rejections": 0,
                      "error": None, "cleanup_error": None, "final": None, "finish_attempted": False}
            self.sessions[sid] = record
            self.active = sid
            try:
                self._record(record)
                record["native"] = self.adapter.open_episode(record["episode"])
                bind = getattr(record["native"], "bind_artifact_dir", None)
                if callable(bind):
                    bind(folder)
            except Exception:
                record["state"], record["error"] = "faulted", "native_open_failed"
                self._error(record, "open")
                self._record(record)
                # Return a session handle so the evaluator can retain evidence
                # and close; reset will report the fault, never retry open.
            return {"session_id": sid}
        if op in ("reset", "step"):
            record = self._session(params, {"sequence"} | ({"action"} if op == "step" else set()))
            if type(params["sequence"]) is not int or params["sequence"] != record["sequence"]:
                raise ServiceError("invalid_sequence")
            expected = "opened" if op == "reset" else "running"
            if record["state"] != expected:
                raise ServiceError("invalid_session_state")
            action = None
            if op == "step":
                try:
                    if not isinstance(params["action"], list):
                        raise ActionRejected(ValidationIssue("invalid_type", field="action"))
                    action = validate_action_vector(self.adapter.action_spec, params["action"])
                    validate_input = getattr(self.adapter, "validate_action_input", None)
                    if validate_input is not None:
                        if not callable(validate_input):
                            raise TypeError("validate_action_input must be callable")
                        # Pure submitted-value/public-contract check. No native
                        # RPC, render, scorer, sensor read or task feasibility test.
                        validated = validate_input(action)
                        if validated != action:
                            raise ValueError("input validation must not transform an action")
                except ActionRejected as exc:
                    record["rejections"] += 1
                    append_jsonl(record["root"] / "sim_server_rejections.jsonl", {
                        "timestamp": utc_now(), "sequence": record["sequence"],
                        "executed": False, "acknowledged_controls": record["controls"],
                        "issue": exc.issue.to_dict(),
                    })
                    self._record(record)
                    raise ServiceActionRejected(exc.issue, record["sequence"]) from None
                except Exception:
                    record["state"], record["error"] = "faulted", "service_request_failed"
                    self._error(record, "input_validation")
                    self._record(record)
                    raise ServiceError(record["error"]) from None
            record["sequence"] += 1
            record["state"] = "executing"
            self._record(record)
            try:
                if op == "reset":
                    observation = record["native"].reset()
                    result = {"observation": encode_observation(observation, self.adapter.observation_spec)}
                    record["state"] = "running"
                else:
                    transition = record["native"].step(action)
                    result = {"transition": encode_transition(transition, self.adapter.observation_spec)}
                    record["controls"] += 1
                    record["state"] = "terminal" if transition.terminated or transition.truncated else "running"
                self._record(record)
                return result
            except Exception:
                record["state"], record["error"] = "faulted", "native_or_observation_failed"
                self._error(record, op)
                self._record(record)
                raise ServiceError(record["error"]) from None
        if op == "metrics":
            record = self._session(params)
            if record["state"] not in ("running", "terminal"):
                raise ServiceError("invalid_session_state")
            try:
                metrics = ensure_jsonable(record["native"].metrics())
                if not isinstance(metrics, dict) or type(metrics.get("success")) is not bool:
                    raise ValueError()
                return {"metrics": metrics}
            except Exception:
                record["state"], record["error"] = "faulted", "native_metrics_failed"
                self._error(record, "metrics")
                self._record(record)
                raise ServiceError(record["error"]) from None
        if op == "finish":
            return self._finish(self._session(params))
        if op == "read_artifact":
            record = self._session(params, {"path", "offset"})
            if record["final"] is None:
                raise ServiceError("artifacts_not_finalized")
            path = relative_path(params["path"])
            files = {row["path"]: row for row in record["final"]["files"]}
            offset = params["offset"]
            if path not in files or type(offset) is not int or not 0 <= offset <= files[path]["size_bytes"]:
                raise ServiceError("invalid_artifact_request")
            with open_regular(record["root"], path) as stream:
                if os.fstat(stream.fileno()).st_size != files[path]["size_bytes"]:
                    raise ServiceError("artifact_changed")
                stream.seek(offset)
                data = stream.read(min(CHUNK_BYTES, files[path]["size_bytes"] - offset))
            return {"data": base64.b64encode(data).decode("ascii")}
        raise ServiceError("unknown_operation")

    def _finish(self, record: dict) -> dict:
        if record["final"] is not None:
            return record["final"]
        if record["finish_attempted"]:
            raise ServiceError("artifact_finalization_failed")
        record["finish_attempted"] = True
        mapping = {}
        try:
            if record["native"] is not None:
                mapping = ensure_jsonable(record["native"].artifacts())
                if not isinstance(mapping, dict):
                    raise ValueError()
                normalized = {}
                for key, value in mapping.items():
                    if not isinstance(value, str):
                        raise ValueError()
                    path = Path(value)
                    if path.is_absolute():
                        value = path.relative_to(record["root"]).as_posix()
                    normalized[key] = relative_path(value)
                mapping = normalized
        except Exception:
            record["cleanup_error"] = "native_artifacts_failed"
            mapping = {}
            self._error(record, "artifacts")
        finally:
            try:
                if record["native"] is not None:
                    record["native"].close()
            except Exception:
                record["cleanup_error"] = "native_close_failed"
                self._error(record, "close")
            record["state"] = "closed"
            # A failed native close can leave a GPU environment alive. Do not
            # admit another episode; operator intervention is required.
            if record["cleanup_error"] != "native_close_failed":
                self.active = None
            self._record(record)
        for key, value in list(mapping.items()):
            try:
                if any(value == excluded or value.startswith(excluded + "/") for excluded in self.excluded):
                    raise ValueError()
                with open_regular(record["root"], value):
                    pass
            except (OSError, ServiceError, ValueError):
                record["cleanup_error"] = record["cleanup_error"] or "named_artifact_missing"
                del mapping[key]
        self._record(record)
        files = []
        total = 0
        entries = 0
        def scan_error(error):
            raise error
        for directory, directories, filenames in os.walk(record["root"], followlinks=False, onerror=scan_error):
            entries += len(directories) + len(filenames)
            if entries > MAX_ARTIFACT_FILES * 2:
                raise ServiceError("artifact_limit_exceeded")
            directory = Path(directory)
            for name in list(directories):
                path = directory / name
                if path.is_symlink():
                    raise ServiceError("artifact_symlink")
                relative = path.relative_to(record["root"]).as_posix()
                if relative in self.excluded:
                    directories.remove(name)
            for name in sorted(filenames):
                relative = (directory / name).relative_to(record["root"]).as_posix()
                with open_regular(record["root"], relative) as stream:
                    before = os.fstat(stream.fileno())
                    total += before.st_size
                    if total > MAX_ARTIFACT_BYTES or len(files) >= MAX_ARTIFACT_FILES:
                        raise ServiceError("artifact_limit_exceeded")
                    digest = hashlib.sha256()
                    count = 0
                    while data := stream.read(min(CHUNK_BYTES, before.st_size - count + 1)):
                        count += len(data)
                        if count > before.st_size:
                            raise ServiceError("artifact_changed")
                        digest.update(data)
                    after = os.fstat(stream.fileno())
                    if count != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise ServiceError("artifact_changed")
                files.append({"path": relative, "size_bytes": before.st_size, "sha256": digest.hexdigest()})
        # Validate the complete pre-retention inventory before any deletion.
        dumps({"session_id": record["id"], "files": files, "artifacts": mapping,
               "cleanup_error": record["cleanup_error"]})
        files, mapping = self._retain_media(record, files, mapping)
        final = {"session_id": record["id"], "files": sorted(files, key=lambda row: row["path"]),
                 "artifacts": mapping, "cleanup_error": record["cleanup_error"]}
        dumps(final)  # Bound the entire inventory before publishing it.
        record["final"] = final
        atomic_write_json(self.root / f"{record['id']}-artifacts.json", final, overwrite=False)
        return final

    def _retain_media(self, record, files, mapping):
        """Retain canonical videos and optionally frame images after native close.

        All files were inventoried first. Runtime observation files stay intact
        until closure. Metadata, native metrics and videos are never deleted.
        """
        images = [row for row in files if PurePosixPath(row["path"]).suffix.lower() in _IMAGE_SUFFIXES]
        videos = [row for row in files if PurePosixPath(row["path"]).suffix.lower() in _VIDEO_SUFFIXES]
        removed, warning = set(), None
        receipt = {"schema_version": MEDIA_RETENTION_SCHEMA,
                   "retain_frame_images": self.retain_frame_images, "videos": "retained_on_server",
                   "scope": "closed_owned_episode_only; no change to live observations",
                   "omitted_files": [], "warning": None}
        receipt_path = "server_media_retention.json"
        if receipt_path in {row["path"] for row in files} or "server_media_retention" in mapping:
            raise ServiceError("media_retention_receipt_collision")
        if not self.retain_frame_images and images:
            if record["cleanup_error"] is not None:
                warning = "native_finalization_or_close_failed_images_preserved"
            elif not videos or any(row["size_bytes"] <= 0 for row in videos):
                warning = "video_unavailable_images_preserved"
            elif len(videos) < len(self.adapter.observation_spec.cameras):
                # At least one nonempty video per declared sensor is necessary
                # before deleting frames. Generic transport cannot establish
                # camera/frame correspondence or decoding quality from names.
                warning = "video_coverage_incomplete_images_preserved"
            else:
                try:
                    # Revalidate every candidate AND retained video before any
                    # unlink. A changed/symlinked/hardlinked entry keeps images.
                    verified = {row["path"]: _verify_media(record["root"], row) for row in images + videos}
                    _durable_media_record(self.root, record["id"] + "-media-retention-intent.json",
                        {"schema_version": MEDIA_RETENTION_SCHEMA, "session_id": record["id"],
                         "reason": "frame_images_disabled", "candidates": images, "retained_videos": videos})
                    for row in images:
                        _unlink_media(record["root"], row["path"], verified[row["path"]], removed)
                except (OSError, ServiceError):
                    warning = "media_retention_failed_remaining_images_preserved"
        receipt["omitted_files"] = [row for row in images if row["path"] in removed]
        receipt["warning"] = warning
        receipt["video_verification"] = "closed_nonempty_hash_stable_files_and_camera_count; not_decode_or_frame_coverage_attestation"
        receipt["status"] = "warning" if warning else "applied"
        row = _durable_media_record(record["root"], receipt_path, receipt)
        retained = [entry for entry in files if entry["path"] not in removed] + [row]
        # An omitted named frame is intentional, not a missing-native-artifact error.
        retained_mapping = {key: value for key, value in mapping.items() if value not in removed}
        retained_mapping["server_media_retention"] = receipt_path
        return retained, retained_mapping

    def close(self) -> None:
        """Operator shutdown: cleanup only, never reset or retry native controls."""
        if self.active is not None:
            self._finish(self.sessions[self.active])


def make_http_server(service: BenchmarkService, *, token: str, host: str = "127.0.0.1",
                     port: int = 8765, request_timeout: float = 30.0) -> HTTPServer:
    if host != "127.0.0.1":
        raise ValueError("v1 binds only 127.0.0.1; use an authenticated SSH tunnel")
    if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token) is None:
        raise ValueError("service token must have 32..256 URL-safe characters")
    if not math.isfinite(request_timeout) or request_timeout <= 0:
        raise ValueError("request timeout must be positive and finite")

    class Handler(BaseHTTPRequestHandler):
        # Deliberately HTTP/1.0 and one request per connection, no pipelining.
        server_version = "RSISimServer/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(request_timeout)

        def log_message(self, *_):
            pass  # Never log bearer tokens, native fields or raw request bodies.

        def do_POST(self):
            request_id = None
            try:
                if self.path != "/rpc":
                    self.send_error(404)
                    return
                auth = self.headers.get_all("Authorization", [])
                if len(auth) != 1 or not hmac.compare_digest(auth[0], "Bearer " + token):
                    self.send_error(401)
                    return
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
                    raise ServiceError("invalid_framing")
                length = int(lengths[0])
                if not 0 < length <= MAX_MESSAGE_BYTES:
                    raise ServiceError("invalid_length")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ServiceError("incomplete_request")
                message = loads(raw)
                if (set(message) != {"protocol", "request_id", "server_id", "op", "params"}
                        or message["protocol"] != PROTOCOL
                        or not isinstance(message["request_id"], str)
                        or re.fullmatch(r"[a-f0-9]{32}", message["request_id"]) is None
                        or not isinstance(message["op"], str)):
                    raise ServiceError("invalid_envelope")
                request_id = message["request_id"]
                expected_server = None if message["op"] == "describe" else service.description["server_id"]
                if message["server_id"] != expected_server:
                    raise ServiceError("server_identity_mismatch")
                result = service.dispatch(message["op"], message["params"])
                response = {"protocol": PROTOCOL, "request_id": request_id, "ok": True, "result": result}
                payload = dumps(response)
            except Exception as exc:
                code = str(exc) if isinstance(exc, ServiceError) else "service_request_failed"
                error = {"code": code}
                if isinstance(exc, ServiceActionRejected):
                    error.update(rejection=exc.issue.to_dict(), executed=False,
                                 next_sequence=exc.sequence)
                payload = dumps({"protocol": PROTOCOL, "request_id": request_id,
                                 "ok": False, "error": error})
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                # The native call may have executed. Its sequence is consumed;
                # neither lost replies nor disconnects cause control replay.
                pass

    return HTTPServer((host, port), Handler)
