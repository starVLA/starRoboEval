"""Shared public-only persistent Codex runtime; no robot or benchmark strategy."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

from benchkit.contracts import ActionRejectionFeedback, ExecutionFeedback, Usage
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError, PolicyPreflightError
from benchkit.recording import RecordingOptions
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.tools.public_observation import compatibility_errors

ROOT = Path(__file__).absolute().parents[1]
TRANSPORT = "codex-app-server/v1"
# Process startup can outlast an ordinary RPC. This is one bounded handshake,
# not a retry or extension of model-turn idle timeouts.
INITIALIZE_TIMEOUT_S = 120
# Codex native model-service recovery, not benchmark/task retries.
# Ten failed turns total means at most nine additional turn/start requests.
OVERLOAD_MAX_ATTEMPTS = 10
OVERLOAD_BACKOFF_S = 30
# A local action-wait timeout is not a failed provider turn. Keep consuming the
# same stream, with ten total finite windows and no additional model request.
ACTION_WAIT_MAX_WINDOWS = 10
# Configuration discovery is local and bounded; never a model/action retry.
MAX_INHERITED_MCP_SERVERS = 128
MAX_MCP_NAME_BYTES = 1024
PERMISSIONS = "rsi_direct_actor"
TOKEN_FIELDS = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
                "cached_input_tokens": "cachedInputTokens"}


def _json(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def _write(path, value):
    payload = _json(value).encode()
    with Path(path).open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(payload)
    return payload


def _toml(value, *, ensure_ascii=True):
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(k, ensure_ascii=ensure_ascii) + "="
                              + _toml(v, ensure_ascii=ensure_ascii) for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=ensure_ascii)


def launch_settings(actor, public, audit, effort):
    """No inherited shell secrets, network tools, repository or SIM filesystem.

    This is an explicitly requested sandbox profile, not an attestation of the
    host kernel or managed Codex configuration. Unsupported profiles fail closed.
    The app-server itself retains the existing login; shell tools do not.
    """
    files = {":minimal": "read", str(Path(sys.prefix).resolve()): "read",
             str(Path(sys.base_prefix).resolve()): "read",
             str(actor): "write", str(public): "read"}
    runtime = Path(actor).parent / "runtime"
    settings = {
        "model": "gpt-6-astra", "model_provider": "openai", "model_reasoning_effort": effort,
        "forced_login_method": "chatgpt", "approval_policy": "never",
        "default_permissions": PERMISSIONS, "permissions." + PERMISSIONS + ".filesystem": files,
        "permissions." + PERMISSIONS + ".network.enabled": False,
        "shell_environment_policy.inherit": "none",
        "shell_environment_policy.experimental_use_profile": False, "allow_login_shell": False,
        "shell_environment_policy.set": {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin:/usr/sbin:/sbin",
                                          "LANG": "C", "LC_ALL": "C"},
        "web_search": "disabled", "mcp_servers": {}, "project_doc_max_bytes": 0, "notify": [],
        "agents.enabled": False, "history.persistence": "none",
        "sqlite_home": str(runtime / "db"), "log_dir": str(runtime / "logs"),
        "features.shell_tool": True, "features.view_image": True, "features.code_mode_host": True,
        "features.skip_host_skill_discovery": True,
    }
    for feature in ("apps", "plugins", "browser_use", "computer_use", "multi_agent", "multi_agent_v2",
                    "hooks", "goals", "memories", "skill_search", "skill_mcp_dependency_install",
                    "request_permissions_tool", "image_generation", "tool_suggest", "remote_control",
                    "remote_plugin", "auth_elicitation", "mcp_2026_07_28"):
        settings["features." + feature] = False
    return settings


def verify_configuration(config, actor, public, audit, effort):
    """Fail before a turn if inherited user/project config expands capabilities.

    --strict-config validates config syntax; it does not ignore user config.
    Do not record the raw effective config: it may contain private credentials.
    """
    wanted = launch_settings(actor, public, audit, effort)
    for key, expected in wanted.items():
        if key.startswith("permissions.") or key == "mcp_servers":
            continue
        actual = config
        for component in key.split("."):
            actual = actual.get(component) if isinstance(actual, dict) else None
        if actual != expected or (type(expected) is bool and type(actual) is not bool):
            raise PolicyError("effective Codex configuration differs from declared Direct settings")
    profile = (config.get("permissions") or {}).get(PERMISSIONS)
    if not isinstance(profile, dict) or profile.get("extends") is not None or profile.get("workspace_roots") is not None:
        raise PolicyError("Direct permission profile may not inherit additional roots")
    filesystem = {key: value for key, value in (profile.get("filesystem") or {}).items() if value is not None}
    network = {key: value for key, value in (profile.get("network") or {}).items() if value is not None}
    if filesystem != wanted["permissions." + PERMISSIONS + ".filesystem"] or network != {"enabled": False}:
        raise PolicyError("Direct permission profile contains additional filesystem/network authority")
    _, enabled = _inherited_mcp_names(config)
    if enabled:
        raise PolicyError("inherited MCP servers must be explicitly disabled before Direct execution")
    shell = config.get("shell_environment_policy") or {}
    if shell.get("set") != wanted["shell_environment_policy.set"]:
        raise PolicyError("inherited shell environment is not allowed")
    if any(config.get(key) for key in ("model_instructions_file", "experimental_compact_prompt_file",
                                       "instructions", "compact_prompt")):
        raise PolicyError("inherited model/compact instructions are not allowed")
    return {"effective_configuration_checked": True, "enabled_mcp_servers": 0,
            "permission_roots_match": True, "shell_environment_match": True,
            "kernel_isolation_attested": False}


def _inherited_mcp_names(config):
    """Extract bounded names/flags only; never log endpoints, commands or secrets."""
    if not isinstance(config, dict):
        raise PolicyError("invalid effective Codex configuration")
    servers = config.get("mcp_servers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict) or len(servers) > MAX_INHERITED_MCP_SERVERS:
        raise PolicyError("invalid inherited MCP configuration")
    names, enabled = [], []
    for name, server in servers.items():
        try:
            valid_name = (type(name) is str and bool(name)
                          and len(name.encode("utf-8")) <= MAX_MCP_NAME_BYTES
                          and not any(ord(character) < 32 or ord(character) == 127 for character in name))
        except UnicodeError:
            valid_name = False
        if (not valid_name or not isinstance(server, dict)
                or ("enabled" in server and type(server["enabled"]) is not bool)):
            raise PolicyError("invalid inherited MCP configuration")
        names.append(name)
        if server.get("enabled") is not False:
            enabled.append(name)
    return tuple(sorted(names)), tuple(sorted(enabled))


def _launch(executable, actor, public, audit, effort, *, disabled_mcp_names=()):
    argv = [str(executable), "app-server", "--stdio", "--strict-config"]
    for key, value in launch_settings(actor, public, audit, effort).items():
        argv += ["-c", key + "=" + _toml(value)]
    # The pinned CLI's dotted override-key parser is not a TOML key parser.
    # Put names inside one TOML inline-table VALUE, with a plain top-level key.
    # Non-ASCII scalars stay literal: JSON surrogate pairs are not valid TOML.
    names, _ = _inherited_mcp_names({"mcp_servers": {name: {"enabled": False} for name in disabled_mcp_names}})
    if names:
        argv += ["-c", "mcp_servers=" + _toml({name: {"enabled": False} for name in names}, ensure_ascii=False)]
    return argv


def _bad(code, field="response", *, actual=None, limit=None):
    if actual is not None:
        try:
            if not math.isfinite(actual):
                actual = None
        except (OverflowError, TypeError, ValueError):
            actual = None
    raise ActionRejected(ValidationIssue(code, field, actual=actual, limit=limit))


def _network_error(error):
    if isinstance(error, dict) and error.get("codexErrorInfo") is not None:
        info = error["codexErrorInfo"]
        allowed = {"httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected"}
        if not isinstance(info, dict) or len(info) != 1 or next(iter(info)) not in allowed:
            return False
        details = next(iter(info.values()))
        if not isinstance(details, dict) or not set(details) <= {"httpStatusCode"}:
            return False
        status = details.get("httpStatusCode")
        if status is not None and (type(status) is not int or not 0 <= status <= 65535
                                   or 400 <= status < 500 and status != 408):
            return False
        return True
    text = _json(error).lower()
    if any(word in text for word in ("quota", "usage limit", "usagelimitexceeded", "usage_limit_exceeded",
                                     "unauthorized", "authentication", "invalid api key", "invalidapikey",
                                     "permission denied", "permissiondenied", "safety", '"httpstatuscode":401',
                                     '"httpstatuscode":403', '"httpstatuscode":429')):
        return False
    return any(word in text for word in ("stream disconnected", "responsestreamdisconnected", "error decoding response body",
                                         "network error", "connection reset", "connection closed", "connection timed out",
                                         "tls close_notify"))


def _overload_error(error):
    # Pinned app-server 0.154.0 CodexErrorInfo is a camelCase unit enum here.
    # Do not infer capacity from arbitrary provider prose or other error codes.
    return isinstance(error, dict) and error.get("codexErrorInfo") == "serverOverloaded"


class _OverloadRecoveryError(PolicyError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PersistentRuntime:
    """One live thread per episode, yielding only method-owned robot decisions."""

    recording_configurable = True
    compatibility_errors = staticmethod(compatibility_errors)

    def __init__(self):
        self.context = self.audit = self.temporary = self.transport = None
        self.recording = RecordingOptions()
        self.interaction_recorder = None

    def configure_recording(self, options):
        if self.context is not None or not isinstance(options, RecordingOptions):
            raise ValueError("configure recording before starting a Direct episode")
        self.recording = options

    def bind_interaction_recorder(self, recorder):
        if self.context is not None:
            raise ValueError("bind interaction recorder before starting an episode")
        self.interaction_recorder = recorder

    def _record(self, category, payload):
        if self.interaction_recorder is not None:
            self.interaction_recorder.record(category, payload, policy_call=self.issued + 1)

    def _record_warning(self):
        if self.interaction_recorder is not None:
            self.interaction_recorder.warn("direct_optional_artifact_failed")

    def _write_audit(self, name, value, *, category="interactions"):
        if getattr(self.recording, category):
            try:
                _write(self.audit / name, value)
            except (OSError, ValueError, TypeError, RecursionError, OverflowError):
                self._record_warning()

    def bind_artifact_dir(self, path):
        if self.context is not None:
            raise PolicyError("cannot change Direct artifact destination during an episode")
        self.audit = Path(path).resolve()
        self.audit.mkdir(mode=0o700, exist_ok=False)

    def preflight_runtime(self):
        # Local login plus an ephemeral configuration-only thread. No turn,
        # inference, robot action or permanent case claim is made here.
        from AgentPolicies.gpt6_astra.tools.codex_runtime import preflight_runtime
        preflight_runtime()
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
            from AgentPolicies.gpt6_astra.tools.codex_app_server import StdioAppServer  # noqa: F401
        except ImportError:
            raise PolicyPreflightError("dependency_unavailable") from None
        with tempfile.TemporaryDirectory(prefix="rsi-direct-preflight-") as temporary:
            base = Path(temporary).resolve()
            probe = self._preflight_policy()
            probe.audit, probe.actor, probe.public = base / "audit", base / "actor", base / "public"
            for path in (probe.audit, probe.actor, probe.public):
                path.mkdir(mode=0o700)
            try:
                probe._boot(ephemeral=True)
            except Exception:
                raise PolicyPreflightError("initialization_failed") from None
            finally:
                if probe.transport is not None:
                    probe.transport.close()

    def start_episode(self, context):
        if self.context is not None or self.audit is None:
            raise PolicyError("Direct requires a fresh model artifact binding for each episode")
        errors = self._context_errors(context)
        if errors:
            raise PolicyError("; ".join(errors))
        self.context = context
        self.temporary = tempfile.TemporaryDirectory(prefix="rsi-direct-actor-")
        self.public = Path(self.temporary.name).resolve() / "observations"
        self.actor = Path(self.temporary.name).resolve() / "work"
        self.public.mkdir(mode=0o700)
        self.actor.mkdir(mode=0o700)
        self.thread_id = self.turn_id = self.pending_rpc = None
        self.packet = self.feedback = self.rejection = self.pending_action = None
        self.issued = self.controls = self.decisions = self.rejected = 0
        self.continuations = self.network_continuations = self.network_consecutive = 0
        self.overload_continuations = self.overload_consecutive = 0
        self.action_wait_timeouts = self.current_action_wait_timeouts = 0
        self.last_overload_error_code = None
        self.seen_calls = set()
        self.tokens = None
        self.token_watermark = {key: 0 for key in TOKEN_FIELDS}
        self.usage_updates = 0
        self.zero_usage_notices = 0
        self.control_limit = context.max_steps
        self.public_files = {}
        self.workspace = None

    def _boot(self, *, ephemeral=False):
        from AgentPolicies.gpt6_astra.tools.codex_app_server import StdioAppServer
        from AgentPolicies.gpt6_astra.tools.codex_runtime import _environment, _inspect_runtime
        executable, readiness = _inspect_runtime()
        effort = self.config["reasoning_effort"]
        # Native Codex internals are private temporary state, not report assets.
        (self.actor.parent / "runtime").mkdir(mode=0o700, exist_ok=True)
        # RPC/error diagnostics are not image exports. Default video-only media
        # must not erase them; explicit non-media reduction still uses scratch.
        transport_dir = (self.audit / "transport" if self.recording.retain_unknown_artifacts
                         else self.actor.parent / "runtime" / "transport")
        self.transport = StdioAppServer(_launch(executable, self.actor, self.public, self.audit, effort),
            transport_dir, cwd=self.actor, env=_environment())

        def read_configuration():
            self.transport.request("initialize", {"clientInfo": {"name": "rsi-direct", "version": "1"},
                                                  "capabilities": {"experimentalApi": True}}, INITIALIZE_TIMEOUT_S)
            self.transport.notify("initialized", {})
            response = self.transport.request("config/read", {"cwd": str(self.actor), "includeLayers": False}, 30)
            if not isinstance(response, dict) or not isinstance(response.get("config"), dict):
                raise PolicyError("invalid effective Codex configuration")
            return response["config"]

        effective = read_configuration()
        inherited_names, enabled_names = _inherited_mcp_names(effective)
        if enabled_names:
            # Empty table overrides merge with user configuration. Discover names
            # before any thread/turn, reap this bootstrap child, then explicitly
            # disable every inherited server for exactly one replacement child.
            # No global config writes, actor input, inference or control replay.
            del effective
            self.transport.close()  # Failure must prevent the replacement.
            self._write_audit("configuration_bootstrap.json", {
                "schema_version": "starvla-rsi.codex-configuration-bootstrap/v1",
                "inherited_mcp_count": len(inherited_names), "enabled_mcp_count": len(enabled_names),
                "bootstrap_closed": True, "thread_started": False,
                "transport_diagnostics": self.transport.diagnostics()}, category="tool_traces")
            isolated_dir = transport_dir.with_name("transport-isolated")
            isolated_dir.mkdir(mode=0o700, exist_ok=False)
            self.transport = StdioAppServer(_launch(executable, self.actor, self.public, self.audit, effort,
                disabled_mcp_names=inherited_names), isolated_dir, cwd=self.actor, env=_environment())
            effective = read_configuration()
            final_names, _ = _inherited_mcp_names(effective)
            if not set(final_names) <= set(inherited_names):
                raise PolicyError("inherited MCP configuration changed during child isolation")
        isolation = verify_configuration(effective, self.actor, self.public, self.audit, effort)
        del effective
        if enabled_names:
            isolation.update(configuration_bootstrap_restarts=1, disabled_inherited_mcp_count=len(inherited_names))
        answer = self.transport.request("thread/start", {
            "cwd": str(self.actor), "model": self.config["model"], "modelProvider": self.config["provider"],
            "config": {"model_reasoning_effort": effort},
            "developerInstructions": self.prompt, "dynamicTools": [self._tool_spec()], "ephemeral": ephemeral,
            "allowProviderModelFallback": False, "approvalPolicy": "never", "permissions": PERMISSIONS,
            "runtimeWorkspaceRoots": [str(self.actor)]}, 30)
        active = answer.get("activePermissionProfile")
        # The exact API shape is verified by the pinned CLI's generated schema.
        active_id = active.get("id") if isinstance(active, dict) else active
        if (answer.get("model") != self.config["model"] or answer.get("modelProvider") != "openai"
                or answer.get("reasoningEffort") != effort or active_id != PERMISSIONS
                or answer.get("approvalPolicy") != "never" or answer.get("cwd") != str(self.actor)):
            raise PolicyError("app-server did not accept the declared Direct identity/permissions")
        self.thread_id = answer["thread"]["id"]
        self._write_audit("session.json", {"schema_version": "starvla-rsi.codex-direct-session/v1",
            "thread_id": self.thread_id, "requested_model": self.config["model"],
            "reported_model": answer["model"], "reported_effort": answer["reasoningEffort"],
            "permission_profile": active_id, "provider_identity_verified": False,
            "runtime": readiness, "configuration_receipt": isolation,
            "launch_settings": launch_settings(self.actor, self.public, self.audit, effort)}, category="tool_traces")
        if not ephemeral:
            self._record("model_io", {"event": "session_instructions", "text": self.prompt,
                                      "tools": [self._tool_spec()]})

    def _turn(self, text, images=()):
        items = [{"type": "text", "text": text}]
        items += [{"type": "image", "url": "data:image/png;base64," + base64.b64encode(data).decode()}
                  for data in images]
        result = self.transport.request("turn/start", {"threadId": self.thread_id,
            "model": self.config["model"], "effort": self.config["reasoning_effort"], "input": items,
            "approvalPolicy": "never", "permissions": PERMISSIONS, "cwd": str(self.actor),
            "runtimeWorkspaceRoots": [str(self.actor)]}, 30)
        self.turn_id = result["turn"]["id"]
        self._record("model_io", {"event": "turn_input", "text": text,
                                  "image_attachments": len(images), "delivery": "request_acknowledged"})

    def _remember_public(self, path, payload):
        self.public_files[path.relative_to(self.public).as_posix()] = {
            "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    def _export_public(self):
        from benchkit.source_snapshot import _open_source_file
        selected = {path: record for path, record in self.public_files.items()
                    if ((path.endswith(".png") and self.recording.images)
                        or (path.endswith(".json") and self.recording.interactions
                            and self.recording.model_io))}
        if not selected:
            return
        actual = set()
        for root, directories, names in os.walk(self.public, followlinks=False):
            for name in directories + names:
                path = Path(root) / name
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise PolicyError("unsafe public observation export entry")
                if name in names:
                    actual.add(path.relative_to(self.public).as_posix())
        if actual != set(self.public_files):
            raise PolicyError("public observation export inventory changed")
        destination = self.audit / "public_observations"
        destination.mkdir()
        for relative, expected in selected.items():
            descriptor = _open_source_file(self.public, Path(relative))
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != expected["size_bytes"]:
                    raise PolicyError("public observation export size changed")
                payload = stream.read(expected["size_bytes"] + 1)
            if len(payload) != expected["size_bytes"] or hashlib.sha256(payload).hexdigest() != expected["sha256"]:
                raise PolicyError("public observation export bytes changed")
            target = destination / relative
            target.parent.mkdir(exist_ok=True)
            with target.open("xb") as stream:
                stream.write(payload)
        _write(self.audit / "public_manifest.json", selected)

    def _reply(self, packet, images):
        content = [{"type": "inputText", "text": _json(packet)}]
        content += [{"type": "inputImage", "imageUrl": "data:image/png;base64," + base64.b64encode(data).decode()}
                    for data in images]
        pending = self.pending_rpc
        self.pending_rpc = None  # Ambiguous delivery is terminal, never resend.
        self.transport.reply(pending, {"success": self.rejection is None, "contentItems": content})
        self._record("model_io", {"event": "robot_tool_result", "packet": packet,
                                  "image_attachments": len(images), "delivery": "reply_written_not_attested"})

    def _usage(self, started):
        if self.tokens is None:
            return Usage.unavailable(latency_s=time.monotonic() - started)
        delta = {key: self.tokens[key] - self.token_watermark[key] for key in TOKEN_FIELDS}
        self.token_watermark = self.tokens.copy()
        return Usage(calls=None, **delta, estimated_cost_usd=None, latency_s=time.monotonic() - started)

    def _token_update(self, params):
        raw = params.get("tokenUsage", {}).get("total", {})
        if (not all(type(raw.get(key)) is int and 0 <= raw[key] <= 2**63 - 1 for key in TOKEN_FIELDS.values())
                or raw["cachedInputTokens"] > raw["inputTokens"]):
            raise PolicyError("invalid app-server token counters")
        values = {key: raw[name] for key, name in TOKEN_FIELDS.items()}
        if self.tokens is None and not any(values.values()):
            self.zero_usage_notices += 1
            return  # A default all-zero notice does not establish free inference.
        if self.tokens is not None and any(values[key] < self.tokens[key] for key in TOKEN_FIELDS):
            raise PolicyError("app-server cumulative token counters decreased")
        self.tokens = values
        self.usage_updates += 1

    def _receipt(self):
        return {"schema_version": "starvla-rsi.codex-direct-receipt/v1", "transport": TRANSPORT,
            "thread_id_sha256": hashlib.sha256((self.thread_id or "").encode()).hexdigest(),
            "action_submissions": self.issued, "network_continuations": self.network_continuations,
            "overload_continuations": self.overload_continuations,
            "overload_consecutive": self.overload_consecutive,
            "overload_max_attempts": OVERLOAD_MAX_ATTEMPTS,
            "last_overload_error_code": self.last_overload_error_code,
            "action_wait_timeouts": self.action_wait_timeouts,
            "current_action_wait_timeouts": self.current_action_wait_timeouts,
            "action_wait_max_windows": ACTION_WAIT_MAX_WINDOWS,
            "action_wait_window_s": self.config["timeout_s"],
            "completed_turn_continuations": self.continuations,
            "app_server_reported_cumulative_tokens": self.tokens, "usage_updates": self.usage_updates,
            "zero_or_unavailable_notices": self.zero_usage_notices,
            "provider_identity_verified": False, "provider_calls": None,
            "accounting": "observed cumulative deltas; final queued notifications may be absent; provider calls/retries unknown",
            "transport_diagnostics": self.transport.diagnostics() if self.transport else None}

    def _next_action(self):
        from AgentPolicies.gpt6_astra.tools.codex_app_server import TransportTimeout

        self.current_action_wait_timeouts = 0

        def next_wait_window():
            self.action_wait_timeouts += 1
            self.current_action_wait_timeouts += 1
            self._record("tool_traces", {"event": "action_wait_timeout",
                "action_wait_timeouts": self.action_wait_timeouts,
                "current_action_wait_timeouts": self.current_action_wait_timeouts,
                "max_windows": ACTION_WAIT_MAX_WINDOWS,
                "window_s": self.config["timeout_s"], "additional_model_request": False})
            if self.current_action_wait_timeouts >= ACTION_WAIT_MAX_WINDOWS:
                raise TransportTimeout("event_timeout")
            return time.monotonic() + self.config["timeout_s"]

        deadline = time.monotonic() + self.config["timeout_s"]
        network_error = None
        terminal_network_error = None
        overload_error = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if overload_error:
                    raise _OverloadRecoveryError("server_overloaded_unconfirmed_closure")
                if terminal_network_error is None:
                    # A matching willRetry=true network notification leaves
                    # this turn live. Consume the same bounded wait allowance;
                    # it neither proves closure nor authorizes another request.
                    deadline = next_wait_window()
                    continue
                raise TimeoutError("Direct agent idle timeout")
            try:
                event = self.transport.next_message(remaining)
            except TimeoutError as exc:
                # Request/write timeouts may mean ambiguous delivery. Never
                # convert them into an event wait or a recovery request.
                if isinstance(exc, TransportTimeout) and exc.code != "event_timeout":
                    raise
                if overload_error:
                    # Unlike legacy network recovery, an idle summary is not
                    # sufficient: wait for this exact turn's failed completion.
                    raise _OverloadRecoveryError("server_overloaded_unconfirmed_closure") from None
                if not terminal_network_error:
                    if isinstance(exc, TransportTimeout) and exc.code == "event_timeout":
                        deadline = next_wait_window()
                        continue
                    raise
                # A persistent visual thread can be much larger than the
                # transport's single-message limit.  Recovery needs only the
                # runtime state: the network error was already observed for
                # this turn, and no robot action is executed until a tool call
                # is returned to the runner.  Never request/replay history.
                response = self.transport.request("thread/read", {
                    "threadId": self.thread_id, "includeTurns": False}, 30)
                thread = response.get("thread", {})
                if (thread.get("id") != self.thread_id or thread.get("status", {}).get("type") != "idle"
                        or not _network_error(terminal_network_error) or self.pending_rpc is not None
                        or self.pending_action is not None or self.feedback is not None):
                    raise
                # A notification may have arrived while thread/read was in
                # flight.  Any such event makes this summary-based closure
                # ambiguous: fail closed instead of crossing one event while
                # another remains queued or issuing an extra model request.
                try:
                    self.transport.next_message(.05)
                except TimeoutError:
                    if self.network_consecutive >= self.config["network_continuations"]:
                        raise PolicyError("same-thread network continuation allowance exhausted")
                    self.network_continuations += 1
                    self.network_consecutive += 1
                    time.sleep(self.config["network_backoff_s"])
                    self._turn("Continue the SAME unfinished episode at the last acknowledged observation. "
                               "No reset, new episode or replay of executed actions.\n" + _json(self.packet))
                    network_error = terminal_network_error = None
                    deadline = time.monotonic() + self.config["timeout_s"]
                    continue
                raise PolicyError("app-server event raced with thread summary recovery")
            method, params = event.get("method"), event.get("params", {})
            if params.get("threadId") not in (None, self.thread_id):
                raise PolicyError("app-server event belongs to another thread")
            if method == "thread/tokenUsage/updated":
                self._token_update(params)
            elif method == "model/rerouted":
                raise PolicyError("model rerouting is forbidden for this declared method")
            elif method == "item/tool/call":
                if (params.get("threadId") != self.thread_id or params.get("turnId") != self.turn_id
                        or not isinstance(params.get("callId"), str) or params["callId"] in self.seen_calls
                        or "id" not in event):
                    raise PolicyError("stale or duplicated action tool call")
                self.seen_calls.add(params["callId"])
                self.pending_rpc = event["id"]
                return params
            elif method in ("item/started", "item/completed"):
                if params.get("turnId") != self.turn_id:
                    continue
                kind = params.get("item", {}).get("type")
                if kind in ("webSearch", "mcpToolCall", "collabAgentToolCall"):
                    raise PolicyError("out-of-scope native tool event")
                # Visible tool/token activity is not the next robot action;
                # it cannot reset this window or replenish its allowance.
                if method == "item/completed":
                    self._record_visible_item(params.get("item", {}))
            elif method == "turn/completed":
                turn = params.get("turn", {})
                if turn.get("id") != self.turn_id:
                    continue
                error = turn.get("error") or overload_error or network_error
                if turn.get("status") == "failed" and _overload_error(error):
                    self.last_overload_error_code = "server_overloaded"
                    if (params.get("threadId") != self.thread_id or self.pending_rpc is not None
                            or self.pending_action is not None or self.feedback is not None):
                        raise _OverloadRecoveryError("server_overloaded_ambiguous_action_state")
                    if self.overload_consecutive >= OVERLOAD_MAX_ATTEMPTS - 1:
                        raise _OverloadRecoveryError("server_overloaded_attempts_exhausted")
                    self.overload_continuations += 1
                    self.overload_consecutive += 1
                    time.sleep(OVERLOAD_BACKOFF_S)
                elif turn.get("status") == "failed" and _network_error(error):
                    if self.network_consecutive >= self.config["network_continuations"]:
                        raise PolicyError("same-thread network continuation allowance exhausted")
                    self.network_continuations += 1
                    self.network_consecutive += 1
                    time.sleep(self.config["network_backoff_s"])
                elif turn.get("status") == "completed" and self.continuations < self.config["completed_turn_continuations"]:
                    self.continuations += 1
                else:
                    raise PolicyError("Direct agent ended without an action or native closure")
                self._turn("Continue the SAME unfinished episode at the last acknowledged observation. "
                           "No reset, new episode or replay of executed actions.\n" + _json(self.packet))
                network_error = terminal_network_error = None
                overload_error = None
                deadline = time.monotonic() + self.config["timeout_s"]
            elif method == "error":
                if (params.get("threadId") != self.thread_id or params.get("turnId") != self.turn_id
                        or type(params.get("willRetry")) is not bool):
                    raise PolicyError("invalid app-server error notification")
                error = params.get("error", params)
                is_overload, is_network = _overload_error(error), _network_error(error)
                # Only validated, allowlisted diagnostics: no provider prose,
                # raw payload, thread/turn identifiers or additional details.
                self._record("tool_traces", {"event": "app_server_error_notification",
                    "classification": "overload" if is_overload else "network" if is_network else "other",
                    "will_retry": params["willRetry"],
                    "action_wait_timeouts": self.action_wait_timeouts,
                    "current_action_wait_timeouts": self.current_action_wait_timeouts,
                    "action_submissions": self.issued, "executed_controls": self.controls,
                    "network_continuations": self.network_continuations,
                    "overload_continuations": self.overload_continuations})
                if is_overload:
                    self.last_overload_error_code = "server_overloaded"
                    overload_error = error
                    network_error = terminal_network_error = None
                    # willRetry is not proof of closure. No turn/start here.
                elif is_network:
                    overload_error = None
                    network_error = error
                    if params["willRetry"] is False:
                        terminal_network_error = error
                        deadline = min(deadline, time.monotonic() + 30)
                else:
                    overload_error = None
                    if params["willRetry"] is not True:
                        raise PolicyError("app-server turn failed; no task/action retry")
            elif method == "turn/failed":
                raise PolicyError("unsupported app-server turn failure notification")
            elif "id" in event and "method" in event:
                raise PolicyError("unexpected capability or approval request")

    def _record_visible_item(self, item):
        """Only visible messages/tool fields, never reasoning or raw envelopes."""
        kind = item.get("type")
        fields = {
            "agentMessage": ("text",),
            "commandExecution": ("command", "aggregatedOutput", "exitCode", "status", "durationMs"),
            "imageView": ("path",),
            # File contents and arbitrary nested tool metadata are not copied.
            "fileChange": ("status",),
        }.get(kind)
        if fields is None:
            return
        payload = {"event": "visible_item", "type": kind}
        payload.update({key: item[key] for key in fields if key in item
                        and (item[key] is None or type(item[key]) in (str, int, float, bool))})
        self._record("model_io" if kind == "agentMessage" else "tool_traces", payload)

    def act(self, observation):
        started = time.monotonic()
        self.current_action_wait_timeouts = 0
        usage = None
        if self.context is None or (self.issued and self.feedback is None):
            raise PolicyError("Direct call without episode or execution acknowledgment")
        try:
            packet, images = self._observation(observation)
            if self.transport is None:
                self._boot()
                self._turn(self._initial_instruction() + _json(packet), images)
            elif self.pending_rpc is not None:
                reply = packet
                if self.rejection is not None:
                    reply = {**packet, "error_type": "recoverable_tool_input", "validation_issue": self.rejection,
                             "no_execution": self.feedback["executed_steps"] == 0,
                             "executed_prefix_controls": self.feedback["executed_steps"],
                             "rejected_controls_executed": 0, "rejected_calls": self.rejected,
                             "correction": "Correct this input; do not reset or replay acknowledged controls."}
                self._reply(reply, images)
            else:
                raise PolicyError("missing pending action tool acknowledgment")
            self.rejection = None
            self.feedback = None
            params = self._next_action()
            self._record("model_io", {"event": "robot_action_submission", "tool": params.get("tool"),
                                      "arguments": params.get("arguments")})
            self.issued += 1
            arguments = params.get("arguments")
            encoded = _json(arguments).encode()
            receipt = self._receipt()
            receipt["arguments_sha256"] = hashlib.sha256(encoded).hexdigest()
            receipt["arguments_bytes"] = len(encoded)
            usage = self._usage(started)
            try:
                if len(encoded) > self.config["max_response_bytes"]:
                    _bad("invalid_length", limit=self.config["max_response_bytes"])
                if params.get("tool") != self._tool_name():
                    _bad("invalid_action")
                value, vector = self._validate_action(arguments, packet)
            except ActionRejected as exc:
                self._write_audit(f"submission-{self.issued:06d}.json", {"receipt": receipt,
                    "rejected": exc.issue.to_dict()}, category="model_io")
                raise ActionRejected(exc.issue, usage=usage, metadata={"provider_receipt": receipt}) from None
            self.pending_action = value
            self.network_consecutive = 0
            self.overload_consecutive = 0
            self._write_audit(f"submission-{self.issued:06d}.json", {"receipt": receipt,
                "response": value}, category="model_io")
            return self._decision(value, vector, usage, receipt)
        except ActionRejected:
            raise
        except Exception as exc:
            # Never publish provider text, local config, raw exceptions or paths.
            code = getattr(exc, "code", "direct_session_failed")
            if not isinstance(code, str) or len(code) > 64:
                code = "direct_session_failed"
            raise PolicyCallError("Codex Direct session failed", usage=usage if usage is not None else self._usage(started),
                metadata={"failure_code": code, "error_type": type(exc).__name__, "provider_receipt": self._receipt()},
                category="infrastructure") from None

    def _feedback(self, feedback):
        if (self.pending_rpc is None or self.feedback is not None or feedback.policy_calls != self.issued
                or feedback.environment_steps != self.controls + feedback.executed_steps
                or feedback.action_decisions != self.decisions + int(feedback.executed_steps > 0)
                or (feedback.executed_steps and (self.pending_action is None
                    or feedback.executed_steps > self.pending_action["steps"]))):
            raise PolicyError("invalid Direct execution/rejection acknowledgment")
        public_feedback = {key: getattr(feedback, key) for key in
                           ("policy_calls", "action_decisions", "environment_steps", "executed_steps")}
        self.controls, self.decisions = feedback.environment_steps, feedback.action_decisions
        self.feedback = public_feedback
        self._write_audit(f"ack-{self.issued:06d}.json", feedback.to_dict())
        self.pending_action = None

    def observe_execution(self, feedback):
        if not isinstance(feedback, ExecutionFeedback):
            raise PolicyError("expected execution feedback")
        self._feedback(feedback)
        self.rejection = None

    def observe_rejection(self, feedback):
        if not isinstance(feedback, ActionRejectionFeedback) or feedback.rejected_actions != self.rejected + 1:
            raise PolicyError("expected rejection feedback")
        self._feedback(feedback)
        self.rejection = feedback.issue.to_dict()
        self.rejected += 1

    def end_episode(self):
        # No post-horizon turn, provider call, action or unmetered final report.
        # The final tool remains unanswered and the owned process is cancelled.
        try:
            if self.transport is not None:
                self.transport.close()
        finally:
            try:
                if self.audit is not None and self.context is not None:
                    self._write_audit("closed.json", {"schema_version": "starvla-rsi.codex-direct-close/v1",
                        "final_ack_delivery": "withheld_on_close", "pending_tool": self.pending_rpc is not None,
                        "executed_controls": self.controls, "executed_decisions": self.decisions,
                        "no_post_episode_continuation": True, "receipt": self._receipt()})
                    # Only host-written public observations are exported. Actor
                    # scratch files can contain symlinks/arbitrary output and are
                    # deliberately not recursively copied into trusted artifacts.
                    try:
                        self._export_public()
                    except (OSError, ValueError, TypeError, RecursionError, OverflowError, PolicyError):
                        self._record_warning()
            finally:
                if self.temporary is not None:
                    self.temporary.cleanup()
                self.context = self.audit = self.temporary = self.transport = None

    def _context_errors(self, context):
        errors = self.compatibility_errors(context.observation_spec, context.action_spec)
        if (context.invalid_action_handling != "feedback" or context.budget_mode != "horizon"
                or type(context.max_steps) is not int or context.max_steps <= 0
                or type(context.max_policy_calls) is not int or context.max_policy_calls <= 0
                or (context.replan_interval is not None and (type(context.replan_interval) is not int
                    or context.replan_interval <= 0))):
            errors.append("persistent method requires feedback, positive horizon/call cap and, if declared, "
                          "a positive execution prefix")
        return errors

    def _tool_name(self):
        raise NotImplementedError

    def _tool_spec(self):
        raise NotImplementedError

    def _initial_instruction(self):
        raise NotImplementedError

    def _preflight_policy(self):
        raise NotImplementedError

    def _observation(self, observation):
        raise NotImplementedError

    def _validate_action(self, arguments, packet):
        raise NotImplementedError

    def _decision(self, value, vectors, usage, receipt):
        raise NotImplementedError
