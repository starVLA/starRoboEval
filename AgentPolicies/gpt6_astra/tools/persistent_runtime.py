"""One persistent Codex conversation per episode: launch, turns, tool replies, recovery and usage."""
from __future__ import annotations

import base64
import hashlib
import math
import os
from pathlib import Path
import stat
import tempfile
import time

from benchkit.contracts import ActionRejectionFeedback, EpisodeUsage, ExecutionFeedback, Usage
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError, PolicyPreflightError
from benchkit.recording import RecordingOptions
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.tools.codex_app_server import TransportTimeout
from AgentPolicies.gpt6_astra.tools.codex_config import (
    PERMISSIONS, inherited_mcp_names, launch_command, launch_settings, verify_configuration,
)
from AgentPolicies.gpt6_astra.tools.json_io import compact_json, write_json
from AgentPolicies.gpt6_astra.tools.public_observation import compatibility_errors

TRANSPORT = "codex-app-server/v1"  # named in each receipt and in the policy descriptor
# Process startup can outlast an ordinary RPC.
INITIALIZE_TIMEOUT_S = 120
# A turn that Codex closes with serverOverloaded is continued after a backoff,
# up to ten failed turns in a row, i.e. at most nine continuations.
OVERLOAD_MAX_ATTEMPTS = 10
OVERLOAD_BACKOFF_S = 30
# Waiting for an action keeps reading the same turn for up to ten windows of
# timeout_s, without another model request.
ACTION_WAIT_MAX_WINDOWS = 10
# Closing interrupts a turn left waiting on the unanswered robot tool so the
# server reports the last response's tokens. Together with session close it
# fits in a remote run's 30 s interrupt grace.
FINAL_TOKEN_FLUSH_TIMEOUT_S = 10
# Model-facing text sent when a turn ends without a robot action and is continued.
CONTINUE_INSTRUCTION = ("Continue the SAME unfinished episode at the last acknowledged observation. "
                        "No reset, new episode or replay of executed actions.\n")
# Usage field name -> app-server tokenUsage field name.
TOKEN_FIELDS = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
                "cached_input_tokens": "cachedInputTokens"}


def reject_action(code, field="response", *, actual=None, limit=None):
    """Reject a robot_act reply; the runner feeds the issue back and the model may correct it."""
    if actual is not None:  # keep only a finite number as the recorded actual value
        try:
            if not math.isfinite(actual):
                actual = None
        except (OverflowError, TypeError, ValueError):
            actual = None
    raise ActionRejected(ValidationIssue(code, field, actual=actual, limit=limit))


def _is_network_error(error):
    """True for a connection/stream failure, which a same-thread continuation may recover."""
    # Structured form: one connection-failure kind, with at most an HTTP status that is not 4xx (408 allowed).
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
    # Otherwise match the error text; quota, auth, safety and 401/403/429 never count as network.
    text = compact_json(error).lower()
    if any(word in text for word in ("quota", "usage limit", "usagelimitexceeded", "usage_limit_exceeded",
                                     "unauthorized", "authentication", "invalid api key", "invalidapikey",
                                     "permission denied", "permissiondenied", "safety", '"httpstatuscode":401',
                                     '"httpstatuscode":403', '"httpstatuscode":429')):
        return False
    return any(word in text for word in ("stream disconnected", "responsestreamdisconnected", "error decoding response body",
                                         "network error", "connection reset", "connection closed", "connection timed out",
                                         "tls close_notify"))


def _is_overload_error(error):
    # In app-server 0.154.0, the tested version, CodexErrorInfo is a camelCase unit enum here.
    # Only this code counts as an overload; error text does not.
    return isinstance(error, dict) and error.get("codexErrorInfo") == "serverOverloaded"


class _OverloadRecoveryError(PolicyError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code  # becomes the call's failure_code in act()


class _TurnWait:
    """What the wait for the next robot_act call has seen in the current turn."""

    def __init__(self, window_s):
        self.window_s = window_s
        self.restart()

    def restart(self):
        self.deadline = time.monotonic() + self.window_s  # end of the current wait window
        # Error notifications seen in this turn; terminal_network_error is one Codex will not retry.
        self.network_error = self.terminal_network_error = self.overload_error = None


class PersistentRuntime:
    """One Codex thread per episode; each act() returns the model's next robot_act decision."""

    recording_configurable = True  # tells the runner this policy filters its own artifacts by category
    compatibility_errors = staticmethod(compatibility_errors)  # the runner checks the benchmark specs with it

    def __init__(self):
        self.context = self.audit = self.temporary = self.transport = None  # per episode; end_episode clears them
        self.recording = RecordingOptions()  # default retention until the runner calls configure_recording
        self.interaction_recorder = None  # the runner's recorder; while None, _record does nothing

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
            # Numbered as the call in progress, i.e. the runner's current policy_call.
            self.interaction_recorder.record(category, payload, policy_call=self.action_submissions + 1)

    def _record_warning(self):
        if self.interaction_recorder is not None:
            self.interaction_recorder.warn("direct_optional_artifact_failed")

    def _write_audit(self, name, value, *, category="interactions"):
        if getattr(self.recording, category):  # skipped when this recording category is off
            try:
                write_json(self.audit / name, value)
            except (OSError, ValueError, TypeError, RecursionError, OverflowError):
                self._record_warning()  # an optional file failed: a warning, not an episode error

    def bind_artifact_dir(self, path):
        if self.context is not None:
            raise PolicyError("cannot change Direct artifact destination during an episode")
        self.audit = Path(path).resolve()  # audit files and exports go here
        self.audit.mkdir(mode=0o700, exist_ok=False)  # must be a new directory for each episode

    def preflight_runtime(self):
        # Check the CLI and login, then verify the configuration on an
        # ephemeral thread. No turn is started.
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
            probe = self._preflight_policy()  # a fresh copy (codex_native.py); this instance stays untouched
            # Set by hand: the probe has no episode, so start_episode never runs for it.
            probe.audit, probe.actor, probe.public = base / "audit", base / "actor", base / "public"
            for path in (probe.audit, probe.actor, probe.public):
                path.mkdir(mode=0o700)
            try:
                probe._boot(ephemeral=True)  # launch, check the configuration, start a thread; no turn
            except Exception:
                raise PolicyPreflightError("initialization_failed") from None
            finally:
                if probe.transport is not None:
                    probe.transport.close()  # stop the probe's app-server before its directory is removed

    def start_episode(self, context):
        if self.context is not None or self.audit is None:  # no open episode, and bind_artifact_dir ran
            raise PolicyError("Direct requires a fresh model artifact binding for each episode")
        errors = self._context_errors(context)
        if errors:
            raise PolicyError("; ".join(errors))
        self.context = context
        self.temporary = tempfile.TemporaryDirectory(prefix="rsi-direct-actor-")  # removed in end_episode
        self.public = Path(self.temporary.name).resolve() / "observations"  # host-written packets/images; Codex reads
        self.actor = Path(self.temporary.name).resolve() / "work"  # Codex cwd; the model's only writable root
        self.public.mkdir(mode=0o700)
        self.actor.mkdir(mode=0o700)
        # Set by _boot/_turn; pending_rpc is the request id of the robot_act call awaiting our reply.
        self.thread_id = self.turn_id = self.pending_rpc = None
        self.turn_active = False  # True from turn/start until that turn's turn/completed
        self.tokens_complete = True  # returned by episode_usage; end_episode sets it
        # packet: last packet sent; feedback: last ACK's public counters, None until the next ACK;
        # rejection: issue sent with the next packet; pending_action: validated reply awaiting its ACK.
        self.packet = self.feedback = self.rejection = self.pending_action = None
        # robot_act calls received; ACKed controls; ACKed decisions; rejections fed back.
        self.action_submissions = self.executed_controls = self.executed_decisions = self.rejected_calls = 0
        # Recovery counters. *_continuations are episode totals; *_consecutive count the current
        # streak and are reset by a valid reply in act(). Completed-turn continuations are capped per episode.
        self.completed_turn_continuations = self.network_continuations = self.network_consecutive = 0
        self.overload_continuations = self.overload_consecutive = 0
        # Idle wait windows: episode total, and within the current policy call.
        self.action_wait_timeouts = self.current_action_wait_timeouts = 0
        self.last_overload_error_code = None  # receipt field; set once an overload is seen
        self.seen_calls = set()  # robot_act callIds already accepted; a repeat is an error
        self.tokens = None  # latest thread-cumulative counters; None until the first nonzero report
        self.token_watermark = {key: 0 for key in TOKEN_FIELDS}  # tokens already given to earlier calls
        self.usage_updates = 0  # token reports applied
        self.zero_usage_notices = 0  # all-zero reports skipped before the first real one
        self.control_limit = context.max_steps  # gives remaining_controls in each packet
        self.public_files = {}  # relative path -> size/sha256 of each file the host wrote to public
        self.workspace = None  # set by codex_native.start_episode, sent in every packet

    def _boot(self, *, ephemeral=False):
        from AgentPolicies.gpt6_astra.tools.codex_app_server import StdioAppServer
        from AgentPolicies.gpt6_astra.tools.codex_runtime import codex_environment, inspect_runtime
        executable, readiness = inspect_runtime()  # the codex binary on PATH, and CLI/login facts for session.json
        # self.config and self.prompt come from the codex_native.py subclass.
        model, provider, effort = self.config["model"], self.config["provider"], self.config["reasoning_effort"]
        # Codex's own database and logs stay in the temporary runtime directory.
        (self.actor.parent / "runtime").mkdir(mode=0o700, exist_ok=True)
        # Transport diagnostics go to the audit directory unless recording
        # drops unknown artifacts.
        transport_dir = (self.audit / "transport" if self.recording.retain_unknown_artifacts
                         else self.actor.parent / "runtime" / "transport")
        # Start the app-server child; launch_command passes every launch setting as a -c override.
        self.transport = StdioAppServer(launch_command(executable, self.actor, self.public, model, provider, effort),
            transport_dir, cwd=self.actor, env=codex_environment())

        def read_configuration():
            # Handshake, then return the effective config; it also includes the user's own Codex config.
            self.transport.request("initialize", {"clientInfo": {"name": "rsi-direct", "version": "1"},
                                                  "capabilities": {"experimentalApi": True}}, INITIALIZE_TIMEOUT_S)
            self.transport.notify("initialized", {})
            response = self.transport.request("config/read", {"cwd": str(self.actor), "includeLayers": False}, 30)
            if not isinstance(response, dict) or not isinstance(response.get("config"), dict):
                raise PolicyError("invalid effective Codex configuration")
            return response["config"]

        effective = read_configuration()
        inherited_names, enabled_names = inherited_mcp_names(effective)  # MCP servers from the user's config
        if enabled_names:
            # Empty table overrides merge with user configuration. Discover names
            # before any thread/turn, reap this bootstrap child, then explicitly
            # disable every inherited server for exactly one replacement child.
            del effective
            self.transport.close()  # Failure must prevent the replacement.
            self._write_audit("configuration_bootstrap.json", {
                "schema_version": "starvla-rsi.codex-configuration-bootstrap/v1",
                "inherited_mcp_count": len(inherited_names), "enabled_mcp_count": len(enabled_names),
                "bootstrap_closed": True, "thread_started": False,
                "transport_diagnostics": self.transport.diagnostics()}, category="tool_traces")
            isolated_dir = transport_dir.with_name("transport-isolated")
            isolated_dir.mkdir(mode=0o700, exist_ok=False)
            self.transport = StdioAppServer(launch_command(executable, self.actor, self.public, model, provider, effort,
                disabled_mcp_names=inherited_names), isolated_dir, cwd=self.actor, env=codex_environment())
            effective = read_configuration()
            final_names, _ = inherited_mcp_names(effective)
            if not set(final_names) <= set(inherited_names):  # no new server appeared in the replacement
                raise PolicyError("inherited MCP configuration changed during child isolation")
        # Compare the effective config with launch_settings; returns a receipt for session.json.
        isolation = verify_configuration(effective, self.actor, self.public, model, provider, effort)
        del effective  # not kept: it may contain private credentials
        if enabled_names:
            isolation.update(configuration_bootstrap_restarts=1, disabled_inherited_mcp_count=len(inherited_names))
        # The episode's thread: the prompt as developer instructions and robot_act as its only dynamic tool.
        answer = self.transport.request("thread/start", {
            "cwd": str(self.actor), "model": self.config["model"], "modelProvider": self.config["provider"],
            "config": {"model_reasoning_effort": effort},
            "developerInstructions": self.prompt, "dynamicTools": [self._tool_spec()], "ephemeral": ephemeral,
            "allowProviderModelFallback": False, "approvalPolicy": "never", "permissions": PERMISSIONS,
            "runtimeWorkspaceRoots": [str(self.actor)]}, 30)
        active = answer.get("activePermissionProfile")
        # The exact API shape is verified by the pinned CLI's generated schema.
        active_id = active.get("id") if isinstance(active, dict) else active
        # The server reports the settings it applied; any difference fails the boot.
        if (answer.get("model") != self.config["model"] or answer.get("modelProvider") != provider
                or answer.get("reasoningEffort") != effort or active_id != PERMISSIONS
                or answer.get("approvalPolicy") != "never" or answer.get("cwd") != str(self.actor)):
            raise PolicyError("app-server did not accept the declared Direct identity/permissions")
        self.thread_id = answer["thread"]["id"]  # every later turn and event is tied to this thread
        self._write_audit("session.json", {"schema_version": "starvla-rsi.codex-direct-session/v1",
            "thread_id": self.thread_id, "requested_model": self.config["model"],
            "reported_model": answer["model"], "reported_effort": answer["reasoningEffort"],
            "permission_profile": active_id,
            "runtime": readiness, "configuration_receipt": isolation,
            "launch_settings": launch_settings(self.actor, self.public, model, provider, effort)}, category="tool_traces")
        if not ephemeral:  # the preflight probe has no episode to record
            self._record("model_io", {"event": "session_instructions", "text": self.prompt,
                                      "tools": [self._tool_spec()]})

    def _turn(self, text, images=()):
        items = [{"type": "text", "text": text}]
        items += [{"type": "image", "url": "data:image/png;base64," + base64.b64encode(data).decode()}
                  for data in images]
        # Active from the request on: a failed or ambiguous start may still
        # have reached the model, so its usage cannot be called complete.
        self.turn_active = True
        result = self.transport.request("turn/start", {"threadId": self.thread_id,
            "model": self.config["model"], "effort": self.config["reasoning_effort"], "input": items,
            "approvalPolicy": "never", "permissions": PERMISSIONS, "cwd": str(self.actor),
            "runtimeWorkspaceRoots": [str(self.actor)]}, 30)
        self.turn_id = result["turn"]["id"]  # tool calls, items and completions are matched against it
        self._record("model_io", {"event": "turn_input", "text": text,
                                  "image_attachments": len(images), "delivery": "request_acknowledged"})

    def _remember_public(self, path, payload):
        # codex_native.py calls this for each file it writes to public; _export_public checks against it.
        self.public_files[path.relative_to(self.public).as_posix()] = {
            "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    def _export_public(self):
        from benchkit.source_snapshot import _open_source_file
        # Images if images are recorded; packet JSON if interactions and model_io are.
        selected = {path: record for path, record in self.public_files.items()
                    if ((path.endswith(".png") and self.recording.images)
                        or (path.endswith(".json") and self.recording.interactions
                            and self.recording.model_io))}
        if not selected:
            return
        # The directory must hold exactly the recorded files: no symlinks, special files or extras.
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
        destination.mkdir()  # fails if an export already exists
        for relative, expected in selected.items():
            descriptor = _open_source_file(self.public, Path(relative))  # follows no symlink on the path
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != expected["size_bytes"]:
                    raise PolicyError("public observation export size changed")
                payload = stream.read(expected["size_bytes"] + 1)  # one extra byte reveals growth
            # The copy must be the bytes the host wrote.
            if len(payload) != expected["size_bytes"] or hashlib.sha256(payload).hexdigest() != expected["sha256"]:
                raise PolicyError("public observation export bytes changed")
            target = destination / relative
            target.parent.mkdir(exist_ok=True)
            with target.open("xb") as stream:  # create-only
                stream.write(payload)
        write_json(self.audit / "public_manifest.json", selected)  # size and sha256 of each exported file

    def _reply(self, packet, images):
        # The tool result: the packet as JSON text, then the image attachments.
        content = [{"type": "inputText", "text": compact_json(packet)}]
        content += [{"type": "inputImage", "imageUrl": "data:image/png;base64," + base64.b64encode(data).decode()}
                    for data in images]
        pending = self.pending_rpc
        self.pending_rpc = None  # Ambiguous delivery is terminal, never resend.
        # Answer the open robot_act call; success is False when the reply reports a rejection.
        self.transport.reply(pending, {"success": self.rejection is None, "contentItems": content})
        self._record("model_io", {"event": "robot_tool_result", "packet": packet,
                                  "image_attachments": len(images), "delivery": "reply_written_not_attested"})

    def _usage(self, started):
        """This call's usage: tokens reported since the previous call, and the elapsed time."""
        if self.tokens is None:
            return Usage.unavailable(latency_s=time.monotonic() - started)  # no counter yet: tokens unknown
        delta = {key: self.tokens[key] - self.token_watermark[key] for key in TOKEN_FIELDS}
        self.token_watermark = self.tokens.copy()  # the next call counts from here
        return Usage(calls=None, **delta, estimated_cost_usd=None, latency_s=time.monotonic() - started)

    def _token_update(self, params):
        """Apply one thread/tokenUsage/updated notice."""
        raw = params.get("tokenUsage", {}).get("total", {})  # cumulative for the whole thread
        if (not all(type(raw.get(key)) is int and 0 <= raw[key] <= 2**63 - 1 for key in TOKEN_FIELDS.values())
                or raw["cachedInputTokens"] > raw["inputTokens"]):
            raise PolicyError("invalid app-server token counters")
        values = {key: raw[name] for key, name in TOKEN_FIELDS.items()}
        if self.tokens is None and not any(values.values()):
            self.zero_usage_notices += 1
            return  # All-zero notices before the first real report are placeholders, not usage.
        if self.tokens is not None and any(values[key] < self.tokens[key] for key in TOKEN_FIELDS):
            raise PolicyError("app-server cumulative token counters decreased")
        self.tokens = values  # _usage takes per-call deltas of these
        self.usage_updates += 1

    def _receipt(self):
        """Counters attached to each decision, submission file, call failure and closed.json."""
        return {"schema_version": "starvla-rsi.codex-direct-receipt/v1", "transport": TRANSPORT,
            "thread_id_sha256": hashlib.sha256((self.thread_id or "").encode()).hexdigest(),
            "action_submissions": self.action_submissions, "network_continuations": self.network_continuations,
            "overload_continuations": self.overload_continuations,
            "overload_consecutive": self.overload_consecutive,
            "overload_max_attempts": OVERLOAD_MAX_ATTEMPTS,
            "last_overload_error_code": self.last_overload_error_code,
            "action_wait_timeouts": self.action_wait_timeouts,
            "current_action_wait_timeouts": self.current_action_wait_timeouts,
            "action_wait_max_windows": ACTION_WAIT_MAX_WINDOWS,
            "action_wait_window_s": self.config["timeout_s"],
            "completed_turn_continuations": self.completed_turn_continuations,
            "app_server_reported_cumulative_tokens": self.tokens, "usage_updates": self.usage_updates,
            "zero_or_unavailable_notices": self.zero_usage_notices,
            "transport_diagnostics": self.transport.diagnostics() if self.transport else None}

    def _next_action(self):
        """Wait for the model's next robot_act call in the current turn and return its params."""
        self.current_action_wait_timeouts = 0
        wait = _TurnWait(self.config["timeout_s"])  # one window of timeout_s; restarted on each continuation
        while True:
            event = self._next_event(wait)
            if event is not None:
                call = self._handle_event(event, wait)
                if call is not None:
                    return call

    # Waiting for events

    def _next_event(self, wait):
        """The next app-server event, or None after the wait moved to a new window or turn."""
        remaining = wait.deadline - time.monotonic()
        if remaining <= 0:
            if wait.overload_error:  # the overloaded turn's failed completion never came
                raise _OverloadRecoveryError("server_overloaded_unconfirmed_closure")
            if wait.terminal_network_error is None:
                # Events kept arriving past the window. Without a final
                # network error the turn is still live: open the next window.
                wait.deadline = self._next_wait_window()
                return None
            raise TimeoutError("Direct agent idle timeout")  # events kept coming after a final network error
        try:
            return self.transport.next_message(remaining)  # blocks until the window ends
        except TimeoutError as exc:
            self._after_wait_timeout(exc, wait)
            return None

    def _next_wait_window(self):
        """Count one idle window and return the next deadline; fail after ACTION_WAIT_MAX_WINDOWS in one call."""
        self.action_wait_timeouts += 1
        self.current_action_wait_timeouts += 1
        self._record("tool_traces", {"event": "action_wait_timeout",
            "action_wait_timeouts": self.action_wait_timeouts,
            "current_action_wait_timeouts": self.current_action_wait_timeouts,
            "max_windows": ACTION_WAIT_MAX_WINDOWS,
            "window_s": self.config["timeout_s"], "additional_model_request": False})
        if self.current_action_wait_timeouts >= ACTION_WAIT_MAX_WINDOWS:
            raise TransportTimeout("event_timeout")  # its code becomes the call's failure_code in act()
        return time.monotonic() + self.config["timeout_s"]

    def _after_wait_timeout(self, exc, wait):
        # Request/write timeouts may mean ambiguous delivery. Never
        # convert them into an event wait or a recovery request.
        if isinstance(exc, TransportTimeout) and exc.code != "event_timeout":
            raise exc
        if wait.overload_error:
            # Overload recovery needs this turn's failed completion; an
            # idle thread summary is not enough.
            raise _OverloadRecoveryError("server_overloaded_unconfirmed_closure") from None
        if not wait.terminal_network_error:  # the turn may still be running: keep waiting
            if isinstance(exc, TransportTimeout) and exc.code == "event_timeout":
                wait.deadline = self._next_wait_window()
                return
            raise exc
        self._recover_after_network_failure(exc, wait)  # final network error, then silence

    def _recover_after_network_failure(self, exc, wait):
        # A final network error was seen but the turn's completion did not
        # arrive. Confirm from the thread summary that the thread is idle and
        # nothing is pending. The turn history is not requested: a long visual
        # thread can exceed the transport's single-message limit.
        response = self.transport.request("thread/read", {
            "threadId": self.thread_id, "includeTurns": False}, 30)
        thread = response.get("thread", {})
        # Recover only when the thread is idle after a network error, with no tool call, action or ACK pending.
        if (thread.get("id") != self.thread_id or thread.get("status", {}).get("type") != "idle"
                or not _is_network_error(wait.terminal_network_error) or self.pending_rpc is not None
                or self.pending_action is not None or self.feedback is not None):
            raise exc
        # A notification may have arrived while thread/read was in
        # flight.  Any such event makes this summary-based closure
        # ambiguous: fail closed instead of crossing one event while
        # another remains queued or issuing an extra model request.
        try:
            self.transport.next_message(.05)  # a short look for any queued event
        except TimeoutError:
            self._spend_network_continuation()
            self._continue_turn(wait)  # nothing queued: continue in a new turn
            return
        raise PolicyError("app-server event raced with thread summary recovery")

    # Handling events

    def _handle_event(self, event, wait):
        """Apply one app-server event; return the params of a new robot_act call, else None."""
        method, params = event.get("method"), event.get("params", {})
        if params.get("threadId") not in (None, self.thread_id):
            raise PolicyError("app-server event belongs to another thread")
        if method == "thread/tokenUsage/updated":
            self._token_update(params)  # cumulative token counters
        elif method == "model/rerouted":
            raise PolicyError("model rerouting is forbidden for this declared method")
        elif method == "item/tool/call":
            return self._accept_tool_call(event, params)  # robot_act, the thread's only dynamic tool
        elif method in ("item/started", "item/completed"):
            self._handle_item(method, params)
        elif method == "turn/completed":
            self._handle_turn_completed(params, wait)
        elif method == "error":
            self._handle_error_notification(params, wait)
        elif method == "turn/failed":
            raise PolicyError("unsupported app-server turn failure notification")
        elif "id" in event and "method" in event:  # any other server request, e.g. an approval prompt
            raise PolicyError("unexpected capability or approval request")
        return None  # other notifications (deltas, status, warnings) need no action

    def _accept_tool_call(self, event, params):
        if (params.get("threadId") != self.thread_id or params.get("turnId") != self.turn_id
                or not isinstance(params.get("callId"), str) or params["callId"] in self.seen_calls
                or "id" not in event):
            raise PolicyError("stale or duplicated action tool call")
        self.seen_calls.add(params["callId"])
        self.pending_rpc = event["id"]  # answered by _reply in the next act()
        return params  # act() checks the tool name and arguments

    def _handle_item(self, method, params):
        if params.get("turnId") != self.turn_id:  # an earlier turn's item
            return
        kind = params.get("item", {}).get("type")
        if kind in ("webSearch", "mcpToolCall", "collabAgentToolCall"):  # tools the launch settings turn off
            raise PolicyError("out-of-scope native tool event")
        # Tool and token events do not extend the action-wait window.
        if method == "item/completed":
            self._record_visible_item(params.get("item", {}))

    def _handle_turn_completed(self, params, wait):
        """The turn ended without a robot_act call: continue it if recovery allows, else fail."""
        turn = params.get("turn", {})
        if turn.get("id") != self.turn_id:  # an earlier turn
            return
        self.turn_active = False
        error = turn.get("error") or wait.overload_error or wait.network_error  # else an error notified earlier
        if turn.get("status") == "failed" and _is_overload_error(error):
            self._spend_overload_continuation(params)
        elif turn.get("status") == "failed" and _is_network_error(error):
            self._spend_network_continuation()
        elif (turn.get("status") == "completed"  # finished normally without calling robot_act
              and self.completed_turn_continuations < self.config["completed_turn_continuations"]):
            self.completed_turn_continuations += 1
        else:  # any other failure, an interruption, or the per-episode allowance used up
            raise PolicyError("Direct agent ended without an action or native closure")
        self._continue_turn(wait)

    def _handle_error_notification(self, params, wait):
        if (params.get("threadId") != self.thread_id or params.get("turnId") != self.turn_id
                or type(params.get("willRetry")) is not bool):
            raise PolicyError("invalid app-server error notification")
        error = params.get("error", params)
        is_overload, is_network = _is_overload_error(error), _is_network_error(error)
        # Record the classification and counters, not the provider's error text.
        self._record("tool_traces", {"event": "app_server_error_notification",
            "classification": "overload" if is_overload else "network" if is_network else "other",
            "will_retry": params["willRetry"],
            "action_wait_timeouts": self.action_wait_timeouts,
            "current_action_wait_timeouts": self.current_action_wait_timeouts,
            "action_submissions": self.action_submissions, "executed_controls": self.executed_controls,
            "network_continuations": self.network_continuations,
            "overload_continuations": self.overload_continuations})
        if is_overload:
            self.last_overload_error_code = "server_overloaded"
            wait.overload_error = error
            wait.network_error = wait.terminal_network_error = None  # the newest error decides
            # Continue only after this turn's failed completion arrives.
        elif is_network:
            wait.overload_error = None
            wait.network_error = error  # classifies a later failed completion that carries no error
            if params["willRetry"] is False:  # Codex gave up on this request
                wait.terminal_network_error = error
                wait.deadline = min(wait.deadline, time.monotonic() + 30)  # wait <= 30 s for the failed completion
        else:
            wait.overload_error = None
            if params["willRetry"] is not True:  # other errors are tolerated only while Codex retries them
                raise PolicyError("app-server turn failed; no task/action retry")

    # Continuing the same turn

    def _spend_overload_continuation(self, params):
        """Allow one more turn after a serverOverloaded failure, after a backoff."""
        self.last_overload_error_code = "server_overloaded"
        # Continue only when no tool call, unacknowledged action or ACK is pending.
        if (params.get("threadId") != self.thread_id or self.pending_rpc is not None
                or self.pending_action is not None or self.feedback is not None):
            raise _OverloadRecoveryError("server_overloaded_ambiguous_action_state")
        if self.overload_consecutive >= OVERLOAD_MAX_ATTEMPTS - 1:
            raise _OverloadRecoveryError("server_overloaded_attempts_exhausted")
        self.overload_continuations += 1
        self.overload_consecutive += 1
        time.sleep(OVERLOAD_BACKOFF_S)  # blocks inside the current policy call

    def _spend_network_continuation(self):
        # The configured allowance caps the current streak; network_continuations is the episode total.
        if self.network_consecutive >= self.config["network_continuations"]:
            raise PolicyError("same-thread network continuation allowance exhausted")
        self.network_continuations += 1
        self.network_consecutive += 1
        time.sleep(self.config["network_backoff_s"])

    def _continue_turn(self, wait):
        """Start a new turn in the same thread with the last packet. Images are not attached
        again; the packet still lists their file paths."""
        self._turn(CONTINUE_INSTRUCTION + compact_json(self.packet))
        wait.restart()  # fresh window and error state for the new turn

    def _record_visible_item(self, item):
        """Record visible messages and the listed tool fields; reasoning and other items are skipped."""
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

    # Reading step 6 of 6: one policy call through the Codex conversation. The
    # hooks it calls (_observation, _validate_action, _decision) are in codex_native.py.
    def act(self, observation):
        started = time.monotonic()
        self.current_action_wait_timeouts = 0
        usage = None
        if self.context is None or (self.action_submissions and self.feedback is None):  # previous call not ACKed
            raise PolicyError("Direct call without episode or execution acknowledgment")
        try:
            packet, images = self._observation(observation)  # built in codex_native.py
            if self.transport is None:  # first call: start Codex and the episode's conversation
                self._boot()
                self._turn(self._initial_instruction() + compact_json(packet), images)
            elif self.pending_rpc is not None:  # later calls answer the open robot_act tool call
                reply = packet
                if self.rejection is not None:  # tell the model why its last reply was rejected
                    reply = {**packet, "error_type": "recoverable_tool_input", "validation_issue": self.rejection,
                             "no_execution": self.feedback["executed_steps"] == 0,
                             "executed_prefix_controls": self.feedback["executed_steps"],
                             "rejected_controls_executed": 0, "rejected_calls": self.rejected_calls,
                             "correction": "Correct this input; do not reset or replay acknowledged controls."}
                self._reply(reply, images)
            else:
                raise PolicyError("missing pending action tool acknowledgment")
            self.rejection = None
            self.feedback = None  # consumed; the next call needs a new ACK
            params = self._next_action()  # wait for the model's next robot_act call
            self._record("model_io", {"event": "robot_action_submission", "tool": params.get("tool"),
                                      "arguments": params.get("arguments")})
            self.action_submissions += 1
            arguments = params.get("arguments")
            encoded = compact_json(arguments).encode()
            receipt = self._receipt()
            receipt["arguments_sha256"] = hashlib.sha256(encoded).hexdigest()
            receipt["arguments_bytes"] = len(encoded)
            usage = self._usage(started)  # tokens since the previous call
            try:
                if len(encoded) > self.config["max_response_bytes"]:
                    reject_action("invalid_length", limit=self.config["max_response_bytes"])
                if params.get("tool") != self._tool_name():
                    reject_action("invalid_action")
                value, vector = self._validate_action(arguments, packet)
            except ActionRejected as exc:
                self._write_audit(f"submission-{self.action_submissions:06d}.json", {"receipt": receipt,
                    "rejected": exc.issue.to_dict()}, category="model_io")
                raise ActionRejected(exc.issue, usage=usage, metadata={"provider_receipt": receipt}) from None
            self.pending_action = value  # the coming ACK is checked against it
            self.network_consecutive = 0  # a valid reply ends any recovery streak
            self.overload_consecutive = 0
            self._write_audit(f"submission-{self.action_submissions:06d}.json", {"receipt": receipt,
                "response": value}, category="model_io")
            return self._decision(value, vector, usage, receipt)
        except ActionRejected:
            raise  # the runner feeds it back to the model or ends the episode
        except Exception as exc:
            # Report only a short failure code and the exception type, as an
            # infrastructure error, never as a policy failure.
            code = getattr(exc, "code", "direct_session_failed")
            if not isinstance(code, str) or len(code) > 64:
                code = "direct_session_failed"
            raise PolicyCallError("Codex Direct session failed", usage=usage if usage is not None else self._usage(started),
                metadata={"failure_code": code, "error_type": type(exc).__name__, "provider_receipt": self._receipt()},
                category="infrastructure") from None

    def _feedback(self, feedback):
        # The ACK must match this call's counters and cannot execute more controls than were submitted.
        if (self.pending_rpc is None or self.feedback is not None
                or feedback.policy_calls != self.action_submissions
                or feedback.environment_steps != self.executed_controls + feedback.executed_steps
                or feedback.action_decisions != self.executed_decisions + int(feedback.executed_steps > 0)
                or (feedback.executed_steps and (self.pending_action is None
                    or feedback.executed_steps > self.pending_action["steps"]))):
            raise PolicyError("invalid Direct execution/rejection acknowledgment")
        public_feedback = {key: getattr(feedback, key) for key in
                           ("policy_calls", "action_decisions", "environment_steps", "executed_steps")}
        self.executed_controls, self.executed_decisions = feedback.environment_steps, feedback.action_decisions  # ACKed
        self.feedback = public_feedback  # sent as previous_execution in the next packet
        self._write_audit(f"ack-{self.action_submissions:06d}.json", feedback.to_dict())
        self.pending_action = None  # settled by this ACK

    def observe_execution(self, feedback):
        if not isinstance(feedback, ExecutionFeedback):
            raise PolicyError("expected execution feedback")
        self._feedback(feedback)
        self.rejection = None

    def observe_rejection(self, feedback):
        if not isinstance(feedback, ActionRejectionFeedback) or feedback.rejected_actions != self.rejected_calls + 1:
            raise PolicyError("expected rejection feedback")
        self._feedback(feedback)
        self.rejection = feedback.issue.to_dict()  # sent with the next packet
        self.rejected_calls += 1

    def episode_usage(self):
        """Thread-cumulative app-server tokens, read once after end_episode.

        Per-call usage is a delta of this counter, and each call's tokens are
        reported only after the next tool reply, so the per-call sum misses
        the last response (and every response when no counter arrived before
        the first robot call). end_episode interrupts the open turn so that
        response is reported; the total is incomplete if that did not close it.
        """
        total = (Usage.unavailable() if self.tokens is None else
                 Usage(calls=None, **self.tokens, estimated_cost_usd=None, latency_s=None))
        return EpisodeUsage(total=total, complete=self.tokens_complete)

    def _flush_final_tokens(self):
        """Interrupt the turn waiting on the robot tool and apply its token report
        and completion. Any failure leaves the counters as seen."""
        deadline = time.monotonic() + FINAL_TOKEN_FLUSH_TIMEOUT_S
        try:
            self.transport.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id},
                                   FINAL_TOKEN_FLUSH_TIMEOUT_S)
            while True:
                event = self.transport.next_message(max(deadline - time.monotonic(), 0))
                params = event.get("params")
                if not isinstance(params, dict) or params.get("threadId") != self.thread_id:
                    continue  # skip events without params or from another thread
                if event.get("method") == "thread/tokenUsage/updated":
                    self._token_update(params)  # may carry the final response's tokens
                elif event.get("method") == "turn/completed" and params.get("turn", {}).get("id") == self.turn_id:
                    self.turn_active = False
                    return "completed"
        except Exception:  # accounting only; never changes the episode outcome
            return "failed"

    def end_episode(self):
        # The final tool call stays unanswered: its turn is interrupted only to
        # collect its tokens, then the app-server is closed.
        flush = "not_applicable"  # no turn waiting on an open robot_act call
        try:
            try:
                # Only a turn still waiting on the final robot_act call has a response left to report.
                if self.transport is not None and self.pending_rpc is not None and self.turn_active:
                    flush = "failed"  # until the turn's completion is applied
                    flush = self._flush_final_tokens()
            finally:
                # A turn still open at close may hold an unreported response.
                self.tokens_complete = not self.turn_active
                if self.transport is not None:
                    self.transport.close()  # stops the app-server process group
        finally:
            try:
                if self.audit is not None and self.context is not None:
                    # closed.json: how the episode closed, with the final receipt.
                    self._write_audit("closed.json", {"schema_version": "starvla-rsi.codex-direct-close/v1",
                        "final_ack_delivery": "withheld_on_close", "pending_tool": self.pending_rpc is not None,
                        "final_token_flush": flush, "reported_tokens_complete": self.tokens_complete,
                        "executed_controls": self.executed_controls, "executed_decisions": self.executed_decisions,
                        "receipt": self._receipt()})
                    # Export only the observations the host wrote; actor scratch
                    # files may hold symlinks or arbitrary output.
                    try:
                        self._export_public()
                    except (OSError, ValueError, TypeError, RecursionError, OverflowError, PolicyError):
                        self._record_warning()
            finally:
                if self.temporary is not None:
                    self.temporary.cleanup()  # deletes the workspace, observations and Codex runtime files
                # Cleared, so the next episode needs a new bind_artifact_dir and start_episode.
                self.context = self.audit = self.temporary = self.transport = None

    def _context_errors(self, context):
        """Reasons this runtime cannot run the episode's context; empty when it can."""
        errors = self.compatibility_errors(context.observation_spec, context.action_spec)
        if (context.invalid_action_handling != "feedback"
                or type(context.max_steps) is not int or context.max_steps <= 0
                or type(context.max_policy_calls) is not int or context.max_policy_calls <= 0
                or (context.replan_interval is not None and (type(context.replan_interval) is not int
                    or context.replan_interval <= 0))):
            errors.append("persistent method requires feedback, positive horizon/call cap and, if declared, "
                          "a positive execution prefix")
        return errors

    # Hooks implemented by CodexNativePolicy in codex_native.py.

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
