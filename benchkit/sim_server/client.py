"""Evaluator-only client for a separately owned, single-attempt SIM server.

This object is never a policy capability. SSH port forwarding supplies remote
connectivity; HTTP is restricted to numeric loopback, with no proxy or retry.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import math
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit
import uuid

from benchkit.contracts import (ActionSpec, BenchmarkDescriptor, EpisodeSpec,
                               ObservationSpec, Usage, ensure_jsonable)
from benchkit.errors import ActionRejected, InfrastructureError, ProtocolError
from benchkit.validation import ValidationIssue, validate_action_vector
from benchkit.sim_server.wire import (PROTOCOL, MAX_MESSAGE_BYTES, dumps, loads,
                                     decode_observation, decode_transition)

MAX_ARTIFACT_BYTES = 16 * 1024 ** 3
MAX_ARTIFACT_FILES = 100_000
ARTIFACT_CHUNK_BYTES = 1024 ** 2
ACTION_REJECTION_PROTOCOL = "starvla-rsi.action-rejection/v1"
SERVER_RETENTION_RECEIPT = "server_media_retention.json"

# Retention classifies closed files, not live observations. These are intentionally
# conservative filename categories, not claims about a file's trust or contents.
# Unknown non-media artifacts are retained: native metrics/provenance filenames
# vary by benchmark and are not safely inferred from a two-name allowlist.
_INTERACTION_ARTIFACTS = frozenset({
    "native_events.jsonl", "private_native_ticks.jsonl", "sim_server_rejections.jsonl",
})
_MODEL_IO_ARTIFACTS = frozenset({"model_transcript.jsonl"})
_TOOL_ARTIFACTS = frozenset({"tools.jsonl"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mkv", ".avi", ".mov"})


def _retain_artifact(path, options):
    """Select client copies; native generation and the server inventory stay intact."""
    from benchkit.driver.recording import RecordingOptions
    options = options or RecordingOptions()
    name = PurePosixPath(path).name
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return options.images and options.copy_server_media
    if suffix in _VIDEO_SUFFIXES:
        return options.videos and options.copy_server_media
    if name in _INTERACTION_ARTIFACTS:
        return options.interactions
    if name in _MODEL_IO_ARTIFACTS:
        return options.model_io
    if name in _TOOL_ARTIFACTS:
        return options.tool_traces
    return True

# Closed vocabulary: a server-provided exception string must never become a
# local traceback or log message, even if it resembles a valid identifier.
_REMOTE_ERROR_CODES = frozenset({
    "artifact_changed", "artifact_finalization_failed", "artifact_limit_exceeded",
    "artifact_symlink", "artifacts_not_finalized", "episode_already_claimed",
    "incomplete_request", "invalid_action", "invalid_artifact_path",
    "invalid_artifact_request", "invalid_envelope", "invalid_fields",
    "invalid_framing", "invalid_length", "invalid_sequence", "invalid_session_state",
    "media_retention_changed", "media_retention_receipt_collision",
    "nonregular_artifact", "server_busy", "unknown_episode", "unknown_operation",
    "unknown_session", "server_identity_mismatch", "native_open_failed",
    "native_or_observation_failed", "native_metrics_failed", "service_request_failed",
})


class SimServerError(InfrastructureError):
    """Validated closed remote failure code, never a native error message."""

    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in _REMOTE_ERROR_CODES else "remote_failure"
        super().__init__("SIM server: " + self.code)


class _RemoteActionRejected(SimServerError):
    def __init__(self, issue, sequence):
        super().__init__("invalid_action")
        self.issue, self.sequence = issue, sequence


def _failure(code: str) -> InfrastructureError:
    return InfrastructureError("SIM server: " + code)


def _fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError("invalid fields")
    return value


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("invalid integer")
    return value


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError("invalid strings")
    if len(value) != len(set(value)):
        raise ValueError("duplicate strings")
    return tuple(value)


def _path(value):
    if (not isinstance(value, str) or not value or len(value) > 4096 or
            "\\" in value or "\x00" in value):
        raise ValueError("invalid artifact path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts) or PurePosixPath(value).is_absolute():
        raise ValueError("invalid artifact path")
    return parts


def _episode(value):
    _fields(value, ("id", "task", "seed", "instruction", "metadata"))
    _integer(value["seed"])
    if not isinstance(value["metadata"], dict):
        raise ValueError("invalid episode metadata")
    return EpisodeSpec(**copy.deepcopy(value))


class SimServerBenchmarkAdapter:
    """A BenchmarkAdapter backed by one server's frozen episode schedule."""

    def __init__(self, endpoint: str, token: str, *, timeout: float = 1200.0):
        try:
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or
                    parsed.username is not None or parsed.password is not None or
                    parsed.path not in ("", "/") or parsed.query or parsed.fragment or
                    parsed.port is None or not 1 <= parsed.port <= 65535 or
                    parsed.netloc != f"127.0.0.1:{parsed.port}"):
                raise ValueError("invalid endpoint")
            if (not isinstance(token, str) or not token or len(token) > 4096 or
                    any(ord(c) < 33 or ord(c) > 126 for c in token)):
                raise ValueError("invalid credential")
            if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                    not math.isfinite(timeout) or timeout <= 0):
                raise ValueError("invalid timeout")
        except Exception:
            raise _failure("invalid_connection_configuration") from None
        self._port, self._token, self._timeout = parsed.port, token, timeout
        self._claimed: set[str] = set()
        data = self._rpc("describe", {})
        try:
            description_fields = {"server_id", "action_rejection", "action_rejection_feedback", "descriptor",
                                  "observation_spec", "action_spec", "budget", "seed", "episodes", "source",
                                  "parameters"}
            if isinstance(data, dict) and "selection" in data:
                description_fields.add("selection")
                selection = _fields(data["selection"], ("episode_ids", "schedule_size"))
                if (_strings(selection["episode_ids"]) != tuple(e["id"] for e in data["episodes"])
                        or _integer(selection["schedule_size"], 1) < len(data["episodes"])):
                    raise ValueError("selection differs from the served schedule")
            _fields(data, description_fields)
            if data["action_rejection"] != ACTION_REJECTION_PROTOCOL:
                raise ValueError("unsupported action rejection contract")
            if type(data["action_rejection_feedback"]) is not bool:
                raise ValueError("invalid action rejection feedback declaration")
            self.action_rejection_feedback = data["action_rejection_feedback"]
            if not isinstance(data["server_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", data["server_id"]):
                raise ValueError("invalid server identity")
            _fields(data["descriptor"], ("name", "version", "protocol_version", "source_revision"))
            self.descriptor = BenchmarkDescriptor(**data["descriptor"])
            obs_fields = {"cameras", "state_names", "modalities", "privileged"}
            if isinstance(data["observation_spec"], dict) and "control_feedback_schema" in data["observation_spec"]:
                obs_fields.add("control_feedback_schema")
                if data["observation_spec"]["control_feedback_schema"] is None:
                    raise ValueError("a declared control feedback schema cannot be null")
            obs = _fields(data["observation_spec"], obs_fields)
            if obs["privileged"] is not False:
                raise ValueError("privileged observations unsupported")
            self.observation_spec = ObservationSpec(**{
                **{k: _strings(obs[k]) for k in ("cameras", "state_names", "modalities")},
                "privileged": False,
                **({"control_feedback_schema": obs["control_feedback_schema"]}
                   if "control_feedback_schema" in obs else {})})
            action = _fields(data["action_spec"], ("mode", "size", "names", "low", "high", "control_hz", "frame", "rotation", "gripper"))
            _integer(action["size"], 1)
            for key in ("frame", "rotation", "gripper"):
                if action[key] is not None and not isinstance(action[key], str):
                    raise ValueError("invalid action semantics")
            for key in ("low", "high"):
                if action[key] is not None and (not isinstance(action[key], list) or any(
                        isinstance(v, bool) or not isinstance(v, (int, float)) for v in action[key])):
                    raise ValueError("invalid action bounds")
            if isinstance(action["control_hz"], bool):
                raise ValueError("invalid control rate")
            self.action_spec = ActionSpec(**{**action, "names": _strings(action["names"]),
                **{k: None if action[k] is None else tuple(action[k]) for k in ("low", "high")}})
            budget_keys = {"max_policy_calls", "environment_step_cap"}
            if isinstance(data["budget"], dict) and "required_replan_interval" in data["budget"]:
                budget_keys.add("required_replan_interval")
                _integer(data["budget"]["required_replan_interval"], 1)
            budget = _fields(data["budget"], budget_keys)
            for key in ("max_policy_calls", "environment_step_cap"):
                if budget[key] is not None:
                    _integer(budget[key], 1)
            for key, value in budget.items():
                setattr(self, key, value)
            _integer(data["seed"])
            if not isinstance(data["episodes"], list) or not data["episodes"]:
                raise ValueError("empty schedule")
            episodes = [_episode(e) for e in data["episodes"]]
            if len({e.id for e in episodes}) != len(episodes):
                raise ValueError("duplicate episodes")
            for key in ("source", "parameters"):
                if not isinstance(data[key], dict):
                    raise ValueError("invalid provenance")
                ensure_jsonable(data[key])
            self._description = copy.deepcopy(data)
        except Exception:
            raise _failure("invalid_description") from None

    @property
    def describe_data(self):
        """Evaluator-only server identity/provenance; never deliver to Policy."""
        return copy.deepcopy(self._description)

    def execution_provenance(self):
        """Cached evaluator provenance, without endpoint or bearer credential."""
        return self.describe_data

    @property
    def parameters(self):
        return copy.deepcopy(self._description["parameters"])

    def _rpc(self, op, params):
        request_id = uuid.uuid4().hex
        connection = None
        try:
            payload = dumps({"protocol": PROTOCOL, "request_id": request_id,
                             "server_id": None if op == "describe" else self._description["server_id"],
                             "op": op, "params": params})
            connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=self._timeout)
            connection.request("POST", "/rpc", body=payload, headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json", "Connection": "close"})
            response = connection.getresponse()
            if response.status != 200 or response.getheader("Transfer-Encoding") is not None:
                raise ValueError("invalid transport response")
            lengths = response.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
                raise ValueError("invalid response length")
            length = int(lengths[0])
            if length > MAX_MESSAGE_BYTES:
                raise ValueError("oversized response")
            body = response.read(length + 1)
            if len(body) != length:
                raise ValueError("incomplete response")
            result = loads(body)
            if not isinstance(result, dict) or result.get("protocol") != PROTOCOL or result.get("request_id") != request_id:
                raise ValueError("uncorrelated response")
            if result.get("ok") is False:
                _fields(result, ("protocol", "request_id", "ok", "error"))
                error = result["error"]
                if isinstance(error, dict) and "rejection" in error:
                    _fields(error, ("code", "rejection", "executed", "next_sequence"))
                    if (op != "step" or error["code"] != "invalid_action" or error["executed"] is not False
                            or self._description["action_rejection"] != ACTION_REJECTION_PROTOCOL):
                        raise ValueError("untrusted action rejection receipt")
                    sequence = _integer(error["next_sequence"], 1)
                    if type(params["sequence"]) is not int or sequence != params["sequence"]:
                        raise ValueError("action rejection sequence mismatch")
                    raise _RemoteActionRejected(ValidationIssue.from_dict(error["rejection"]), sequence)
                _fields(result["error"], ("code",))
                raise SimServerError(result["error"]["code"])
            if result.get("ok") is not True:
                raise ValueError("invalid success flag")
            _fields(result, ("protocol", "request_id", "ok", "result"))
            if not isinstance(result["result"], dict):
                raise ValueError("invalid RPC result")
            return result["result"]
        except SimServerError:
            raise
        except Exception:
            raise _failure("rpc_failed_" + op) from None
        finally:
            if connection is not None:
                connection.close()

    def episodes(self, seed, limit=None):
        if type(seed) is not int or seed != self._description["seed"]:
            raise _failure("schedule_seed_mismatch")
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise _failure("invalid_episode_limit")
        return tuple(_episode(e) for e in self._description["episodes"][:limit])

    def open_episode(self, episode):
        allowed = {e["id"]: e for e in self._description["episodes"]}
        if (not isinstance(episode, EpisodeSpec) or episode.id not in allowed or
                episode.to_dict() != allowed[episode.id] or episode.id in self._claimed):
            raise _failure("episode_not_available")
        self._claimed.add(episode.id)  # A lost reply must not permit another attempt.
        result = self._rpc("open", {"episode_id": episode.id})
        try:
            _fields(result, ("session_id",))
            if not isinstance(result["session_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", result["session_id"]):
                raise ValueError("invalid session")
            return RemoteEpisode(self, result["session_id"])
        except Exception:
            raise _failure("invalid_open_response") from None


class RemoteEpisode:
    """Fail-closed episode stream. Finalization remains possible after a fault."""

    def __init__(self, adapter, session_id):
        self._adapter, self._session_id = adapter, session_id
        self._sequence = 0
        self._reset_attempted = self._faulted = self._terminal = False
        self._finish_attempted = self._closed = False
        self._artifact_dir = None
        self._artifact_mapping = None
        self._recording = None

    def configure_recording(self, options):
        """Set optional closed-artifact client retention once, before binding.

        This is not a server capture negotiation. Reset/step RGB, server-side
        recording, finalization, metrics and one-attempt semantics are unchanged.
        The mandatory evaluator-private receipt preserves the full inventory;
        selective copies do not satisfy an audit requiring all original bytes.
        """
        from benchkit.driver.recording import RecordingOptions
        if (self._recording is not None or self._artifact_dir is not None
                or self._reset_attempted or self._finish_attempted):
            raise _failure("recording_configuration_already_set")
        if not isinstance(options, RecordingOptions):
            raise _failure("invalid_recording_configuration")
        self._recording = options

    def bind_artifact_dir(self, path: Path):
        if self._artifact_dir is not None or self._reset_attempted:
            raise _failure("artifact_binding_already_set")
        try:
            path = Path(path).absolute()
            if not path.is_dir() or path.is_symlink():
                raise ValueError("artifact root must be an existing directory")
            self._artifact_dir = path
        except Exception:
            raise _failure("invalid_artifact_directory") from None

    def reset(self):
        if self._reset_attempted or self._finish_attempted or self._artifact_dir is None:
            raise _failure("reset_not_available")
        self._reset_attempted = True
        try:
            result = self._adapter._rpc("reset", {"session_id": self._session_id, "sequence": 0})
            _fields(result, ("observation",))
            observation = decode_observation(result["observation"], self._adapter.observation_spec)
            if observation.step != 0:
                raise ValueError("reset step mismatch")
            self._sequence = 1
            return observation
        except SimServerError as exc:
            self._faulted = True
            raise SimServerError(exc.code) from None
        except Exception:
            self._faulted = True
            raise _failure("reset_failed") from None

    def step(self, action):
        if not self._sequence or self._faulted or self._terminal or self._finish_attempted:
            raise _failure("step_not_available")
        # A local deterministic rejection has not sent an RPC. Keep the last
        # acknowledged observation/sequence available for a corrected request.
        normalized = validate_action_vector(self._adapter.action_spec, action)
        try:
            result = self._adapter._rpc("step", {"session_id": self._session_id,
                "sequence": self._sequence, "action": list(normalized)})
            _fields(result, ("transition",))
            transition = decode_transition(result["transition"], self._adapter.observation_spec)
            if transition.observation.step != self._sequence:
                raise ValueError("step mismatch")
            self._sequence += 1
            self._terminal = transition.terminated or transition.truncated
            return transition
        except _RemoteActionRejected as exc:
            if exc.sequence != self._sequence:
                self._faulted = True
                raise _failure("invalid_rejection_sequence") from None
            raise ActionRejected(exc.issue, usage=Usage()) from None
        except SimServerError as exc:
            self._faulted = True
            if exc.code == "invalid_action":
                raise ProtocolError("SIM server: invalid_action") from None
            raise SimServerError(exc.code) from None
        except Exception:
            self._faulted = True
            raise _failure("step_failed") from None

    def metrics(self):
        try:
            result = self._adapter._rpc("metrics", {"session_id": self._session_id})
            _fields(result, ("metrics",))
            if not isinstance(result["metrics"], dict):
                raise ValueError("invalid metrics")
            return ensure_jsonable(result["metrics"])
        except Exception:
            raise _failure("metrics_failed") from None

    def artifacts(self):
        if self._artifact_mapping is not None:
            return dict(self._artifact_mapping)
        if self._finish_attempted:
            raise _failure("finalization_previously_failed_no_retry")
        self._finish_attempted = True
        try:
            result = self._adapter._rpc("finish", {"session_id": self._session_id})
            self._closed = True
            _fields(result, ("session_id", "files", "artifacts", "cleanup_error"))
            if result["session_id"] != self._session_id:
                raise ValueError("session mismatch")
            files, mapping = self._inventory(result)
            from benchkit.driver.recording import RecordingOptions
            options = self._recording or RecordingOptions()
            selected = [file for file in files if _retain_artifact(file["path"], options)]
            selected_paths = {file["path"] for file in selected}
            if self._artifact_dir is None:
                raise ValueError("missing artifact directory")
            root = os.open(self._artifact_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                receipt = {"protocol": PROTOCOL, "server": self._adapter.describe_data,
                           "session_id": self._session_id, "finish": result}
                receipt["client_retention"] = {
                        "schema_version": "starvla-rsi.client-artifact-retention/v3",
                        "scope": "server_owned_media_and_selected_client_copies",
                        "recording": options.to_dict(),
                        "native_capture": "unchanged", "server_capture_control": "unsupported",
                        "media_owner": "benchmark_server",
                        "server_retention_receipt": "sim_server_files/" + SERVER_RETENTION_RECEIPT,
                        "server_media_references": [dict(file) for file in files
                            if PurePosixPath(file["path"]).suffix.lower() in _IMAGE_SUFFIXES | _VIDEO_SUFFIXES],
                        "reference_identity": {"server_id": self._adapter.describe_data["server_id"],
                                               "session_id": self._session_id},
                        "media_reference_is_local_copy": False,
                        "selected_paths": [file["path"] for file in selected],
                        "omitted_paths": [file["path"] for file in files
                                          if file["path"] not in selected_paths],
                        "selection_is_download_attestation": False,
                    }
                receipt_fd = os.open("sim_server_receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
                with os.fdopen(receipt_fd, "wb") as stream:
                    stream.write(dumps(receipt))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(root)
                os.mkdir("sim_server_files", mode=0o700, dir_fd=root)
                target = os.open("sim_server_files", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                try:
                    for file in selected:
                        self._download(target, file)
                    os.fsync(target)
                finally:
                    os.close(target)
                os.fsync(root)
            finally:
                os.close(root)
            if result["cleanup_error"] is not None:
                raise ValueError("server cleanup failed")
            self._artifact_mapping = {name: "sim_server_files/" + path for name, path in mapping.items()
                                      if path in selected_paths}
            self._artifact_mapping["sim_server_receipt"] = "sim_server_receipt.json"
            return dict(self._artifact_mapping)
        except Exception:
            raise _failure("artifact_finalization_failed") from None

    def _inventory(self, result):
        files, mapping = result["files"], result["artifacts"]
        if (not isinstance(files, list) or len(files) > MAX_ARTIFACT_FILES or
                not isinstance(mapping, dict) or "sim_server_receipt" in mapping or
                mapping.get("server_media_retention") != SERVER_RETENTION_RECEIPT or
                (result["cleanup_error"] is not None and not isinstance(result["cleanup_error"], str))):
            raise ValueError("invalid inventory")
        seen, total = set(), 0
        for file in files:
            _fields(file, ("path", "size_bytes", "sha256"))
            _path(file["path"])
            total += _integer(file["size_bytes"])
            if total > MAX_ARTIFACT_BYTES or file["path"] in seen:
                raise ValueError("invalid inventory size")
            if not isinstance(file["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", file["sha256"]):
                raise ValueError("invalid digest")
            seen.add(file["path"])
        for path in seen:
            parts = path.split("/")
            if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
                raise ValueError("file directory collision")
        for name, path in mapping.items():
            if not isinstance(name, str) or not name or path not in seen:
                raise ValueError("invalid artifact mapping")
        return files, mapping

    def _download(self, root, file):
        parts = _path(file["path"])
        parent = os.dup(root)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                offset, digest = 0, hashlib.sha256()
                while offset < file["size_bytes"]:
                    result = self._adapter._rpc("read_artifact", {"session_id": self._session_id,
                        "path": file["path"], "offset": offset})
                    _fields(result, ("data",))
                    if not isinstance(result["data"], str) or len(result["data"]) > 4 * ((ARTIFACT_CHUNK_BYTES + 2) // 3):
                        raise ValueError("invalid artifact chunk")
                    chunk = base64.b64decode(result["data"], validate=True)
                    if not chunk or len(chunk) > min(ARTIFACT_CHUNK_BYTES, file["size_bytes"] - offset):
                        raise ValueError("invalid artifact chunk length")
                    stream.write(chunk)
                    digest.update(chunk)
                    offset += len(chunk)
                if digest.hexdigest() != file["sha256"]:
                    raise ValueError("artifact digest mismatch")
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent)
        finally:
            os.close(parent)

    def close(self):
        if self._closed:
            return
        if self._finish_attempted:
            raise _failure("cleanup_outcome_unknown_no_retry")
        self.artifacts()
