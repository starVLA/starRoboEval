"""One Claude Messages conversation per episode: requests, tool results, recovery and usage."""
from __future__ import annotations

import base64
import hashlib
import math
import os
import stat
import tempfile
import time
from pathlib import Path

from AgentPolicies.claude_opus.tools.json_io import compact_json, write_json
from AgentPolicies.claude_opus.tools.public_observation import compatibility_errors
from benchkit.contracts import ActionRejectionFeedback, EpisodeUsage, ExecutionFeedback, Usage
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError, PolicyPreflightError
from benchkit.driver.recording import RecordingOptions
from benchkit.validation import ValidationIssue

TRANSPORT = "anthropic-messages/v1"  # named in each receipt and in the policy descriptor
CONTEXT_MANAGEMENT_BETA = "context-management-2025-06-27"  # enables server-side tool-result clearing
# A 429 or 529 answer is retried after a backoff, up to ten failed requests in
# a row, i.e. at most nine retries.
OVERLOAD_MAX_ATTEMPTS = 10
OVERLOAD_BACKOFF_S = 30
# Model-facing text sent when a response ends without a robot action and is continued.
CONTINUE_INSTRUCTION = ("Continue the SAME unfinished episode at the last acknowledged observation. "
                        "No reset, new episode or replay of executed actions.\n")
# Preflight counts tokens for this one message; nothing is generated.
PREFLIGHT_PROBE = "Preflight token count only; no episode is running."
# Usage counters as each Messages response reports them; input_tokens excludes cache reads and writes.
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def reject_action(code, field="response", *, actual=None, limit=None):
    """Reject a robot_act reply; the runner feeds the issue back and the model may correct it."""
    if actual is not None:  # keep only a finite number as the recorded actual value
        try:
            if not math.isfinite(actual):
                actual = None
        except (OverflowError, TypeError, ValueError):
            actual = None
    raise ActionRejected(ValidationIssue(code, field, actual=actual, limit=limit))


def _field(block, name):
    """One field of a content block, whether an SDK object or a plain dict."""
    return block.get(name) if isinstance(block, dict) else getattr(block, name, None)


def _plain(value):
    """A JSON copy of an SDK object for records; None stays None."""
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return value.model_dump(mode="json", exclude_none=True)


def _digest(text):
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}


def _block_record(block):
    """A content block for records: thinking, its signature and image bytes become digests."""
    data = dict(_plain(block))
    kind = data.get("type")
    if kind == "thinking":  # never recorded as text; the signature is opaque
        data["thinking"] = _digest(data.get("thinking") or "")
        data["signature"] = _digest(data.get("signature") or "")
    elif kind == "redacted_thinking":
        data["data"] = _digest(data.get("data") or "")
    elif kind == "image":
        data["source"] = {"type": "base64_digest", **_digest(data.get("source", {}).get("data", ""))}
    elif kind == "tool_result" and isinstance(data.get("content"), list):
        data["content"] = [_block_record(item) for item in data["content"]]
    return data


def _refusal_category(message):
    """Only the category of a refusal; its explanation and credit token are not recorded."""
    category = _field(getattr(message, "stop_details", None) or {}, "category")
    return category if isinstance(category, str) and len(category) <= 64 else None


def _image_block(data):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.b64encode(data).decode()}}


def _status_code(error):
    status = getattr(error, "status_code", None)
    return status if type(status) is int else None


def _error_kind(error):
    """The body's error type, e.g. overloaded_error; a mid-stream error arrives with HTTP status 200."""
    body = getattr(error, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        kind = body["error"].get("type")
        if isinstance(kind, str) and len(kind) <= 64:
            return kind
    return None


def _classify_error(error):
    """'overload' or 'network' for a failure a same-conversation retry may recover; None otherwise."""
    import anthropic
    import httpx
    if isinstance(error, (anthropic.APIConnectionError, httpx.TransportError)):  # includes timeouts
        return "network"
    if isinstance(error, anthropic.APIStatusError):
        status, kind = _status_code(error), _error_kind(error)
        if status in (429, 529) or kind in ("rate_limit_error", "overloaded_error"):
            return "overload"
        if status == 408 or (status is not None and status >= 500) or kind == "api_error":
            return "network"
    # Authentication, permission, invalid request and unparseable stream output are not retried.
    return None


def _failure_code(error):
    code = getattr(error, "code", None)  # set by _RecoveryError
    if isinstance(code, str) and len(code) <= 64:
        return code
    status = _status_code(error)
    if status is not None:
        return f"api_status_{status}"
    if _classify_error(error) == "network":
        return "api_connection_failed"
    return "messages_session_failed"


class _RecoveryError(PolicyError):
    def __init__(self, code, *, category="infrastructure"):
        super().__init__(code)
        self.code = code  # becomes the call's failure_code in act()
        self.category = category  # "policy" only for the model's own refusal


class MessagesRuntime:
    """One Messages conversation per episode; each act() returns the model's next robot_act decision."""

    recording_configurable = True  # tells the runner this policy filters its own artifacts by category
    compatibility_errors = staticmethod(compatibility_errors)  # the runner checks the benchmark specs with it

    def __init__(self, client=None):
        self._client = client  # injected for offline checks; else built on first use
        self.context = self.audit = self.temporary = None  # per episode; end_episode clears them
        self.recording = RecordingOptions()  # default retention until the runner calls configure_recording
        self.interaction_recorder = None  # the runner's recorder; while None, _record does nothing

    @property
    def client(self):
        if self._client is None:
            import anthropic
            # An explicit key turns off the SDK's other credential sources; the key is never recorded.
            # Retries are ours (bounded by the configuration), so the SDK makes exactly one attempt.
            self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=0)
        return self._client

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
        # Check dependencies and the key's presence, then count tokens for the
        # full request shape. The server validates tools, betas and settings;
        # no response is generated.
        try:
            import anthropic  # noqa: F401
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            raise PolicyPreflightError("dependency_unavailable") from None
        if self._client is None and not os.environ.get("ANTHROPIC_API_KEY"):
            raise PolicyPreflightError("credentials_missing")
        probe = self._preflight_policy()  # a fresh copy (messages_native.py); this instance stays untouched
        settings = probe._request_settings()
        settings.pop("max_tokens")  # not a token-counting parameter
        try:
            probe.client.beta.messages.count_tokens(**settings, messages=[{"role": "user", "content": PREFLIGHT_PROBE}],
                                                    timeout=self.config["timeout_s"])
        except Exception:  # a rejected key is not reported apart: preflight does not attest access
            raise PolicyPreflightError("initialization_failed") from None

    def start_episode(self, context):
        if self.context is not None or self.audit is None:  # no open episode, and bind_artifact_dir ran
            raise PolicyError("Direct requires a fresh model artifact binding for each episode")
        errors = self._context_errors(context)
        if errors:
            raise PolicyError("; ".join(errors))
        self.context = context
        self.temporary = tempfile.TemporaryDirectory(prefix="rsi-direct-messages-")  # removed in end_episode
        self.public = Path(self.temporary.name).resolve() / "observations"  # host-written packets/images
        self.public.mkdir(mode=0o700)
        # The episode's conversation, append-only: earlier messages are never edited, so
        # preserved thinking and the prompt cache stay valid. Context editing happens server-side.
        self.messages = []
        self.settings = None  # model, system, tools and options; fixed at the first request
        self.pending_tool_use = None  # id of the robot_act call awaiting our tool_result
        # packet: last packet sent; feedback: last ACK's public counters, None until the next ACK;
        # rejection: issue sent with the next packet; pending_action: validated reply awaiting its ACK.
        self.packet = self.feedback = self.rejection = self.pending_action = None
        # robot_act calls received; ACKed controls; ACKed decisions; rejections fed back.
        self.action_submissions = self.executed_controls = self.executed_decisions = self.rejected_calls = 0
        # Recovery counters. *_continuations are episode totals; *_consecutive count the current
        # streak and are reset by a valid reply in act(). Completed-turn continuations are capped per episode.
        self.completed_turn_continuations = self.network_continuations = self.network_consecutive = 0
        self.overload_continuations = self.overload_consecutive = 0
        self.seen_calls = set()  # tool_use ids already accepted; a repeat is an error
        self.api_requests = 0  # Messages requests sent in this episode, failed ones included
        self.tokens = dict.fromkeys(TOKEN_FIELDS, 0)  # summed over every completed response
        # False once a request failed after its stream started: its tokens may be billed but are unknown.
        self.tokens_complete = True
        self.context_edits = {"responses": 0, "cleared_tool_uses": 0, "cleared_input_tokens": 0}
        self.last_response_id = self.reported_model = self.last_stop_reason = self.refusal_category = None
        self._reset_call_accounting()
        self.control_limit = context.max_steps  # gives remaining_controls in each packet
        self.public_files = {}  # relative path -> size/sha256 of each file the host wrote to public
        self.workspace = None  # set by messages_native.start_episode, sent in every packet

    def _reset_call_accounting(self):
        """Requests and tokens of the policy call in progress."""
        self.call_requests = 0
        self.call_tokens = dict.fromkeys(TOKEN_FIELDS, 0)
        self.call_tokens_known = True

    # The request

    def _request_settings(self):
        """Everything but the messages; identical for every request of the episode."""
        config = self.config  # self.config and self.prompt come from the messages_native.py subclass
        return {"model": config["model"], "max_tokens": config["max_tokens"],
            # One explicit breakpoint caches tools + system; the top-level field caches the growing tail.
            "system": [{"type": "text", "text": self.prompt, "cache_control": {"type": "ephemeral"}}],
            "tools": [self._tool_spec()],
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},  # at most one call per response
            "thinking": {"type": config["thinking"]},  # adaptive: always on, never a budget
            "output_config": {"effort": config["effort"]},
            "cache_control": {"type": "ephemeral"},
            "context_management": {"edits": [{"type": config["context_editing"],
                "trigger": {"type": "input_tokens", "value": config["context_trigger_input_tokens"]},
                "keep": {"type": "tool_uses", "value": config["context_keep_tool_uses"]},
                "clear_at_least": {"type": "input_tokens", "value": config["context_clear_at_least_input_tokens"]},
                "clear_tool_inputs": config["context_clear_tool_inputs"]}]},
            "betas": [CONTEXT_MANAGEMENT_BETA]}

    def _open_conversation(self):
        self.settings = self._request_settings()
        # session.json: the request settings exactly as sent; the client and its headers are never written.
        self._write_audit("session.json", {"schema_version": "starvla-rsi.claude-opus-session/v1",
            "transport": TRANSPORT, "settings": self.settings}, category="tool_traces")
        self._record("model_io", {"event": "session_instructions", "text": self.prompt,
                                  "tools": self.settings["tools"]})

    def _append_user(self, content, event, **details):
        self.messages.append({"role": "user", "content": content})
        self._record("model_io", {"event": event, **details, "content": [_block_record(block) for block in content]})

    def _send(self, params):
        """One streamed request; returns the final message."""
        started = False
        try:
            with self.client.beta.messages.stream(**params, timeout=self.config["timeout_s"]) as stream:
                for _event in stream:
                    started = True  # the request reached the model; its input may be billed
                return stream.get_final_message()
        except Exception:
            if started:  # tokens of a broken stream are not reported
                self.tokens_complete = self.call_tokens_known = False
            raise

    def _request(self):
        """Send the conversation; retry recoverable failures with the same messages."""
        params = {**self.settings, "messages": list(self.messages)}
        while True:
            self.call_requests += 1
            self.api_requests += 1
            try:
                message = self._send(params)
            except Exception as exc:
                kind = _classify_error(exc)
                # Record the classification and counters, not the provider's error text.
                self._record("tool_traces", {"event": "api_error", "classification": kind or "other",
                    "error_type": type(exc).__name__, "status_code": _status_code(exc),
                    "error_kind": _error_kind(exc), "api_request": self.api_requests,
                    "network_continuations": self.network_continuations,
                    "overload_continuations": self.overload_continuations})
                if kind == "overload":
                    self._spend_overload_continuation()
                elif kind == "network":
                    self._spend_network_continuation()
                else:
                    raise
                continue
            self._apply_usage(message)
            return message

    def _apply_usage(self, message):
        """Add one response's tokens and context edits; record the response."""
        usage = message.usage
        values = {key: getattr(usage, key, None) for key in TOKEN_FIELDS}
        for key in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            values[key] = 0 if values[key] is None else values[key]  # absent: no caching on this response
        if not all(type(value) is int and 0 <= value <= 2**63 - 1 for value in values.values()):
            raise PolicyError("invalid Messages usage counters")
        for key, value in values.items():
            self.tokens[key] += value
            self.call_tokens[key] += value
        edits = [_plain(edit) for edit in (_field(message.context_management, "applied_edits") or [])]
        if edits:
            self.context_edits["responses"] += 1
            for edit in edits:
                for key in ("cleared_tool_uses", "cleared_input_tokens"):
                    if type(edit.get(key)) is int:
                        self.context_edits[key] += edit[key]
        self.last_response_id, self.reported_model = message.id, message.model
        self.last_stop_reason = message.stop_reason if isinstance(message.stop_reason, str) else None
        self.refusal_category = _refusal_category(message)
        self._record("model_io", {"event": "api_response", "api_request": self.api_requests,
            "id": message.id, "model": message.model, "stop_reason": message.stop_reason,
            "refusal_category": self.refusal_category, "usage": values,
            "context_management": {"applied_edits": edits},
            "content": [_block_record(block) for block in message.content]})
        # Fallbacks are not enabled: a response from another model fails the call.
        if not isinstance(message.model, str) or not (message.model == self.config["model"]
                                                      or message.model.startswith(self.config["model"] + "-")):
            raise _RecoveryError("model_mismatch")

    def _usage(self, started):
        """This call's usage: its requests and tokens, and the elapsed time."""
        latency = time.monotonic() - started
        if not self.call_tokens_known:  # a broken stream: billed tokens are unknown, not zero
            return Usage(calls=self.call_requests, input_tokens=None, output_tokens=None,
                         cached_input_tokens=None, estimated_cost_usd=None, latency_s=latency)
        tokens = self.call_tokens
        return Usage(calls=self.call_requests, input_tokens=tokens["input_tokens"] + tokens["cache_read_input_tokens"]
                     + tokens["cache_creation_input_tokens"], output_tokens=tokens["output_tokens"],
                     cached_input_tokens=tokens["cache_read_input_tokens"], estimated_cost_usd=None, latency_s=latency)

    def _receipt(self):
        """Counters attached to each decision, submission file, call failure and closed.json."""
        return {"schema_version": "starvla-rsi.claude-opus-receipt/v1", "transport": TRANSPORT,
            "requested_model": self.config["model"], "reported_model": self.reported_model,
            "last_response_id": self.last_response_id, "last_stop_reason": self.last_stop_reason,
            "refusal_category": self.refusal_category,
            "action_submissions": self.action_submissions, "api_requests": self.api_requests,
            "call_requests": self.call_requests, "call_tokens": dict(self.call_tokens),
            "call_tokens_known": self.call_tokens_known, "episode_tokens": dict(self.tokens),
            "network_continuations": self.network_continuations,
            "overload_continuations": self.overload_continuations,
            "overload_consecutive": self.overload_consecutive, "overload_max_attempts": OVERLOAD_MAX_ATTEMPTS,
            "completed_turn_continuations": self.completed_turn_continuations,
            "context_edits": dict(self.context_edits)}

    # Waiting for the robot_act call

    def _next_action(self):
        """Request until the model calls robot_act; return the call's tool name and input."""
        while True:
            message = self._request()
            content = list(message.content)
            # The full assistant content, thinking blocks included, goes back unchanged. An empty
            # reply is not kept (the API rejects empty messages); the continuation then follows the
            # previous user turn, and the API merges consecutive user turns.
            if content:
                self.messages.append({"role": "assistant", "content": content})
            calls = [block for block in content if _field(block, "type") == "tool_use"]
            stop = message.stop_reason
            # stop_reason decides first: a refused or cut-off response's tool input is never used.
            if stop == "refusal":
                raise _RecoveryError("model_refusal", category="policy")
            if stop == "tool_use" and len(calls) == 1:
                return self._accept_tool_call(calls[0])
            if stop in ("end_turn", "stop_sequence", "max_tokens"):
                self._continue_turn(calls, stop)  # ended without a usable robot_act call
                continue
            raise _RecoveryError("unexpected_stop_reason")

    def _accept_tool_call(self, block):
        call_id = _field(block, "id")
        if not isinstance(call_id, str) or call_id in self.seen_calls:
            raise PolicyError("stale or duplicated action tool call")
        self.seen_calls.add(call_id)
        self.pending_tool_use = call_id  # answered by _reply in the next act()
        return {"tool": _field(block, "name"), "arguments": _field(block, "input")}  # act() checks both

    def _continue_turn(self, calls, stop):
        """Ask again with the last packet, within the per-episode allowance. Images are not
        attached again; the model already received them."""
        if self.completed_turn_continuations >= self.config["completed_turn_continuations"]:
            raise _RecoveryError("ended_without_action")
        self.completed_turn_continuations += 1
        text = {"type": "text", "text": CONTINUE_INSTRUCTION + compact_json(self.packet)}
        if calls:  # max_tokens cut a robot_act call: answer it as not executed, never run it
            content = [{"type": "tool_result", "tool_use_id": _field(block, "id"), "is_error": True,
                        "content": [text]} for block in calls]
        else:
            content = [text]
        self._append_user(content, "continuation", stop_reason=stop,
                          completed_turn_continuations=self.completed_turn_continuations)

    # Recovery

    def _spend_overload_continuation(self):
        """Allow one more request after a 429/529, after a backoff."""
        if self.overload_consecutive >= OVERLOAD_MAX_ATTEMPTS - 1:
            raise _RecoveryError("server_overloaded_attempts_exhausted")
        self.overload_continuations += 1
        self.overload_consecutive += 1
        time.sleep(OVERLOAD_BACKOFF_S)  # blocks inside the current policy call

    def _spend_network_continuation(self):
        # The configured allowance caps the current streak; network_continuations is the episode total.
        if self.network_consecutive >= self.config["network_continuations"]:
            raise _RecoveryError("network_continuations_exhausted")
        self.network_continuations += 1
        self.network_consecutive += 1
        time.sleep(self.config["network_backoff_s"])

    # Public observation files

    def _remember_public(self, path, payload):
        # messages_native.py calls this for each file it writes to public; _export_public checks against it.
        self.public_files[path.relative_to(self.public).as_posix()] = {
            "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    def _export_public(self):
        from benchkit.artifacts import open_no_follow
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
            descriptor = open_no_follow(self.public, Path(relative))  # follows no symlink on the path
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
        content = [{"type": "text", "text": compact_json(packet)}] + [_image_block(data) for data in images]
        result = {"type": "tool_result", "tool_use_id": self.pending_tool_use, "content": content}
        if self.rejection is not None:  # the previous reply was rejected and executed nothing new
            result["is_error"] = True
        self.pending_tool_use = None
        self._append_user([result], "robot_tool_result", packet=packet, image_attachments=len(images))

    # Reading step 6 of 6: one policy call through the Messages conversation. The
    # hooks it calls (_observation, _validate_action, _decision) are in messages_native.py.
    def act(self, observation):
        started = time.monotonic()
        self._reset_call_accounting()
        usage = None
        if self.context is None or (self.action_submissions and self.feedback is None):  # previous call not ACKed
            raise PolicyError("Direct call without episode or execution acknowledgment")
        try:
            packet, images = self._observation(observation)  # built in messages_native.py
            if not self.messages:  # first call: the instruction, the first packet and its images
                self._open_conversation()
                text = self._initial_instruction() + compact_json(packet)
                self._append_user([{"type": "text", "text": text}] + [_image_block(data) for data in images],
                                  "initial_observation", packet=packet, image_attachments=len(images))
            elif self.pending_tool_use is not None:  # later calls answer the open robot_act call
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
            params = self._next_action()  # request until the model calls robot_act
            self._record("model_io", {"event": "robot_action_submission", "tool": params.get("tool"),
                                      "arguments": params.get("arguments")})
            self.action_submissions += 1
            arguments = params.get("arguments")
            encoded = compact_json(arguments).encode()
            receipt = self._receipt()
            receipt["arguments_sha256"] = hashlib.sha256(encoded).hexdigest()
            receipt["arguments_bytes"] = len(encoded)
            usage = self._usage(started)  # this call's requests and tokens
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
            # Report only a short failure code and the exception type. Everything but
            # the model's own refusal is an infrastructure error, never a policy failure.
            raise PolicyCallError("Claude Messages session failed",
                usage=usage if usage is not None else self._usage(started),
                metadata={"failure_code": _failure_code(exc), "error_type": type(exc).__name__,
                          "provider_receipt": self._receipt()},
                category=getattr(exc, "category", "infrastructure")) from None

    def _feedback(self, feedback):
        # The ACK must match this call's counters and cannot execute more controls than were submitted.
        if (self.pending_tool_use is None or self.feedback is not None
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
        """Tokens summed over every completed response, read once after end_episode.

        Each response reports its own usage, so per-call usage is exact and
        this total equals the per-call sum. It is incomplete only when a
        stream broke after it started: those tokens may be billed but are unknown.
        """
        tokens = self.tokens
        total = Usage(calls=self.api_requests, input_tokens=tokens["input_tokens"] + tokens["cache_read_input_tokens"]
                      + tokens["cache_creation_input_tokens"], output_tokens=tokens["output_tokens"],
                      cached_input_tokens=tokens["cache_read_input_tokens"], estimated_cost_usd=None, latency_s=None)
        return EpisodeUsage(total=total, complete=self.tokens_complete)

    def end_episode(self):
        # The final robot_act call stays unanswered; no request is sent at close.
        try:
            if self.audit is not None and self.context is not None:
                # closed.json: how the episode closed, with the final receipt.
                self._write_audit("closed.json", {"schema_version": "starvla-rsi.claude-opus-close/v1",
                    "final_ack_delivery": "withheld_on_close", "pending_tool": self.pending_tool_use is not None,
                    "reported_tokens_complete": self.tokens_complete,
                    "executed_controls": self.executed_controls, "executed_decisions": self.executed_decisions,
                    "receipt": self._receipt()})
                # The client-side history; signatures and image bytes are kept only as digests.
                self._write_audit("conversation.json", {"schema_version": "starvla-rsi.claude-opus-conversation/v1",
                    "messages": [{"role": message["role"], "content": [_block_record(block)
                                  for block in message["content"]]} for message in self.messages]},
                    category="model_io")
                try:
                    self._export_public()  # only the observations the host wrote
                except (OSError, ValueError, TypeError, RecursionError, OverflowError, PolicyError):
                    self._record_warning()
        finally:
            if self.temporary is not None:
                self.temporary.cleanup()  # deletes the episode's observation files
            # Cleared, so the next episode needs a new bind_artifact_dir and start_episode.
            self.context = self.audit = self.temporary = None
            self.messages = []

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

    # Hooks implemented by ClaudeOpusPolicy in messages_native.py.

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
