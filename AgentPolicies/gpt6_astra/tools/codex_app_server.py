"""Bounded, model-owned transport for one persistent local Codex app-server.

Wire reference: https://learn.chatgpt.com/docs/app-server (JSONL over stdio;
JSON-RPC envelopes omit ``jsonrpc``). This module does not initialize a thread,
make an inference request, handle a tool, retry an RPC, or connect to a SIM.
The trusted caller owns launch configuration, the actor's permissions, and all
thread/turn/tool semantics. Existing CLI login is used; auth files are not read.

``workspace`` is a host-only diagnostics directory, not an actor workspace.
RPC logs contain envelope metadata and hashes ONLY, never payloads, reasoning,
auth or encrypted content. Stderr is independently drained, pattern-redacted,
and retained with a byte cap in a create-only 0600 file. Nonempty stderr alone
is not a transport failure. Pattern redaction is not a complete secret detector;
diagnostics still must not be mounted into the actor's readable filesystem.
This is a trusted-local transport, not an OS isolation or provider attestation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time


TRANSPORT = "codex-app-server-stdio/v1"  # transport ID, also recorded in the policy's receipts
_ENVIRONMENT = ("HOME", "CODEX_HOME", "USER", "LOGNAME", "PATH", "TMPDIR", "TZ",
                "LANG", "LC_ALL")  # the only variables the child receives; see child_environment
# Method names the RPC log may write in clear; any other name (e.g. config/read) is logged as a hash.
_METHODS = frozenset({"initialize", "initialized", "thread/start", "thread/read",
    "thread/resume", "thread/started", "thread/status/changed", "thread/tokenUsage/updated",
    "turn/start", "turn/started", "turn/completed", "turn/interrupt", "turn/failed",
    "item/started", "item/completed", "item/tool/call", "item/agentMessage/delta",
    "item/reasoning/summaryTextDelta", "item/reasoning/textDelta",
    "item/reasoning/summaryPartAdded", "item/commandExecution/outputDelta",
    "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
    "error", "warning", "model/rerouted", "serverRequest/resolved"})
# Every public failure code. TransportError turns any other code into "stream_io_failed".
_CODES = frozenset({"invalid_input", "unsupported_platform", "workspace_unavailable",
    "spawn_failed", "pipes_unavailable", "stream_io_failed", "diagnostic_io_failed",
    "invalid_json", "invalid_envelope", "message_limit", "queue_limit",
    "unexpected_response", "duplicate_server_request", "unknown_server_request",
    "request_limit", "request_timeout", "event_timeout", "write_timeout",
    "rpc_error", "stdout_eof", "closed", "cleanup_failed", "process_ownership_unverified"})
# Stderr redaction: group 1 (the label) is kept, group 2 (the secret) becomes [REDACTED].
_TOKEN_PATTERNS = (
    re.compile(r"(?i)(\b(?:authorization|proxy-authorization)\s*[:=]\s*)([^\r\n]+)"),  # HTTP auth headers
    # key=value pairs whose key names a token, secret, password, API key or credential
    re.compile(r"(?i)(\b(?:[a-z0-9_]*(?:token|secret|password|api[_-]?key)[a-z0-9_]*|credential)\s*[\"']?\s*[:=]\s*[\"']?)([^\s,;\"'}]+)"),
    re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/-]+=*)"),  # bearer tokens
    re.compile(r"()(\bsk-[A-Za-z0-9_-]{8,})"),  # sk- API keys
    re.compile(r"()(\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"),  # JWTs
    re.compile(r"(?i)(https?://)([^\s/@:]+:[^\s/@]+@)"),  # user:password@ in URLs
)


class TransportError(RuntimeError):
    """Fixed public error; arbitrary child text is never an exception message."""

    def __init__(self, code, *, diagnostics=None, rpc_code=None):
        self.code = code if code in _CODES else "stream_io_failed"  # unknown codes become a generic one
        self.diagnostics = diagnostics or {}
        # The server's JSON-RPC error code, kept only if it is a 32-bit int.
        self.rpc_code = rpc_code if type(rpc_code) is int and -(2**31) <= rpc_code < 2**31 else None
        super().__init__("Codex app-server transport: " + self.code)


class TransportTimeout(TransportError, TimeoutError):  # callers also catch it as a plain TimeoutError
    pass


class RpcError(TransportError):  # the server answered a request with an error object
    pass


@dataclass(frozen=True)
class TransportLimits:
    max_message_bytes: int = 32 * 1024 * 1024  # one JSONL line, in either direction
    max_queued_bytes: int = 64 * 1024 * 1024  # received messages and responses not yet taken by a caller
    max_queued_messages: int = 1024  # unread notifications and server requests
    max_pending_requests: int = 16  # per side: our in-flight requests; server requests awaiting reply
    max_rpc_log_bytes: int = 16 * 1024 * 1024  # rpc_metadata.jsonl stops growing past this
    max_stderr_bytes: int = 1024 * 1024  # size cap of stderr.redacted.log
    max_stderr_line_bytes: int = 64 * 1024  # longer stderr lines are dropped whole
    write_timeout_s: float = 30.0  # deadline for notify()/reply(); request() uses its own timeout
    cleanup_grace_s: float = 0.8  # wait used for the waitpid lock, after SIGTERM, reaping and joins

    def __post_init__(self):
        for name in ("max_message_bytes", "max_queued_bytes", "max_queued_messages",
                     "max_pending_requests", "max_rpc_log_bytes", "max_stderr_bytes",
                     "max_stderr_line_bytes"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 1024 * 1024 * 1024:  # each limit: an int from 1 to 2**30
                raise TransportError("invalid_input")
        _duration(self.write_timeout_s)
        _duration(self.cleanup_grace_s)


def _duration(value):
    if type(value) not in (int, float):
        raise TransportError("invalid_input")
    try:
        valid = math.isfinite(value) and 0 < value <= 86400  # seconds: positive, finite, at most one day
    except OverflowError:
        valid = False
    if not valid:
        raise TransportError("invalid_input")
    return float(value)


def child_environment(source=None):
    """Select CLI/login path and locale variables, never evaluator/API credentials.

    Explicit environments receive the same allowlist. Values are not logged;
    no authentication file, token, keyring or arbitrary environment key is read.
    """
    source = os.environ if source is None else source  # default: this process's environment
    if not hasattr(source, "get"):
        raise TransportError("invalid_input")
    result = {}
    for name in _ENVIRONMENT:
        value = source.get(name)
        if value is not None:
            if not isinstance(value, str) or "\x00" in value or len(value) > 32768:
                raise TransportError("invalid_input")
            result[name] = value
    return result


def _json_value(value, depth=0):  # raise unless plain JSON: str keys, finite floats, depth <= 100
    if depth > 100:
        raise ValueError("JSON nesting")
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise ValueError("JSON value")


def _pairs(items):  # json.loads hook: reject objects with duplicate keys
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _identifier(value):  # RPC id -> (type, value) key, so 1 and "1" stay distinct
    if type(value) is int and -(2**63) <= value < 2**63:
        return (int, value)
    if type(value) is str and 0 < len(value) <= 256:
        return (str, value)
    raise TransportError("invalid_envelope")


def _envelope(message):  # check the shape; return "request", "notification" or "response"
    if type(message) is not dict or ("jsonrpc" in message and message["jsonrpc"] != "2.0"):
        raise TransportError("invalid_envelope")
    keys = set(message) - {"jsonrpc"}
    if "method" in keys:  # a request (with id) or a notification (without)
        if (not keys <= {"method", "params", "id", "emittedAtMs"} or type(message["method"]) is not str
                or not 0 < len(message["method"]) <= 256 or type(message.get("params", {})) is not dict):
            raise TransportError("invalid_envelope")
        # Codex 0.154.0 server events may include this generated-schema timestamp.
        # It does not grant arbitrary extra envelope fields or response metadata.
        if "emittedAtMs" in keys and (type(message["emittedAtMs"]) is not int
                or not 0 <= message["emittedAtMs"] < 2**63):
            raise TransportError("invalid_envelope")
        if "id" in keys:
            _identifier(message["id"])
        return "request" if "id" in keys else "notification"
    if keys not in ({"id", "result"}, {"id", "error"}):  # a response has exactly one of result/error
        raise TransportError("invalid_envelope")
    _identifier(message["id"])
    if "error" in keys:
        error = message["error"]
        if (type(error) is not dict or type(error.get("code")) is not int
                or type(error.get("message")) is not str):
            raise TransportError("invalid_envelope")
    return "response"


class StdioAppServer:
    """One owned process group; bidirectional RPC without implicit model calls.

    ``cwd`` must be an explicitly prepared actor directory. Its readable roots
    must not include ``workspace``; this layout check is not an OS sandbox.
    ``request`` timeouts poison the connection (outcome uncertain, never replay).
    ``next_message`` idle timeouts do not poison it, permitting an explicit
    read-only thread-status query by the caller. No recovery is initiated here.
    """

    def __init__(self, argv, workspace, *, env=None, cwd=None,
                 popen=subprocess.Popen, limits=None):
        self.limits = limits or TransportLimits()
        if not isinstance(self.limits, TransportLimits):
            raise TransportError("invalid_input")
        if os.name != "posix":
            raise TransportError("unsupported_platform")
        if (not isinstance(argv, (list, tuple)) or not argv
                or any(not isinstance(v, str) or not v or "\x00" in v for v in argv) or cwd is None):
            raise TransportError("invalid_input")
        environment = child_environment(env)  # allowlisted copy of env (or os.environ)
        self.workspace = Path(workspace).absolute()  # diagnostics dir: RPC metadata log and redacted stderr
        actor = Path(cwd).resolve()  # the child's working directory
        # Diagnostics must not be a symlink or lie inside the actor directory.
        if (self.workspace.is_symlink() or not actor.is_dir()
                or self.workspace.resolve().is_relative_to(actor)):
            raise TransportError("workspace_unavailable")
        self._state = threading.Condition(threading.RLock())  # guards the state below; waiters sleep on it
        self._write_lock = threading.Lock()  # one writer on the child's stdin at a time
        self._close_lock = threading.Lock()  # one close() at a time
        self._log_lock = threading.Lock()  # one writer on the two log files at a time
        self._incoming = deque()  # notifications and server requests for next_message()
        self._responses = {}  # id key -> None while waiting, then (message, size)
        self._server_requests = {}  # id key -> "waiting", then "replying" until reply() is written
        self._queued_bytes = 0  # bytes held in _incoming and _responses
        self._next_id = 1  # ids of our requests count up from 1
        self._failure = None  # first fatal code; once set, every call raises it
        self._last_error = None  # last code raised to a caller (diagnostics only)
        self._closing = self._closed = False
        self._reader_stop = threading.Event()  # tells the reader threads to exit (set late in close)
        self._threads = []
        self.process = None
        self._spawn_pid = None  # child pid, which is also its group and session id
        self._spawn_identity_verified = False  # close() may signal the group only if True
        self._logs = {}
        # SHA-256 of every byte per stream, for diagnostics.
        self._hashes = {name: hashlib.sha256() for name in ("stdin", "stdout", "stderr")}
        self._counts = dict(requests_started=0, requests_completed=0, rpc_errors=0,
            notifications_written=0, replies_written=0, messages_received=0,
            stdin_bytes=0, stdout_bytes=0, stderr_bytes=0, rpc_log_bytes=0,
            stderr_retained_bytes=0, stderr_redactions=0, stderr_omitted_lines=0)
        self._stderr_truncated = self._rpc_log_truncated = self._stdout_eof = False
        self._cleanup = dict(attempted=False, ownership_proven=False,  # close() outcome, reported in diagnostics
            group_cleanup_verified=None, sent_term=False, sent_kill=False,
            process_reaped=False, readers_stopped=False, succeeded=None, signal_errors=[], errors=[])
        try:
            self.workspace.mkdir(mode=0o700, exist_ok=True)
            # Create the logs relative to a no-follow dir fd: new files only (O_EXCL), mode 0600.
            directory = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for name in ("rpc_metadata.jsonl", "stderr.redacted.log"):
                    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=directory)
                    self._logs[name] = os.fdopen(descriptor, "wb", buffering=0)
            finally:
                os.close(directory)
        except OSError:
            for stream in self._logs.values():
                stream.close()
            raise TransportError("workspace_unavailable") from None
        try:
            # New session, so the child leads its own process group and close() can signal all of it.
            self.process = popen(list(argv), cwd=str(actor), env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=False, bufsize=0, start_new_session=True)
            self._spawn_pid = self.process.pid
            # Hold Popen's private waitpid lock: the child cannot be reaped (pid reused) during the check.
            wait_lock = getattr(self.process, "_waitpid_lock", None)
            if wait_lock is None or not wait_lock.acquire(timeout=self.limits.cleanup_grace_s):
                raise TransportError("process_ownership_unverified")
            try:
                # Still running, and its pid is its own group id and session id.
                self._spawn_identity_verified = (self.process.returncode is None
                    and os.getpgid(self._spawn_pid) == self._spawn_pid
                    and os.getsid(self._spawn_pid) == self._spawn_pid)
            except OSError:
                self._spawn_identity_verified = False
            finally:
                wait_lock.release()
            if not self._spawn_identity_verified:
                raise TransportError("process_ownership_unverified")
            if any(stream is None for stream in (self.process.stdin, self.process.stdout, self.process.stderr)):
                raise TransportError("pipes_unavailable")
            os.set_blocking(self.process.stdin.fileno(), False)  # lets _send() stop at its deadline
            # Reader threads drain stdout (messages) and stderr (redacted log) while the child runs.
            for name, target in (("stdout", self._read_stdout), ("stderr", self._read_stderr)):
                thread = threading.Thread(target=target, name="rsi-codex-" + name, daemon=True)
                self._threads.append(thread)
                thread.start()
        except BaseException as error:  # record the code and clean up before raising
            self._fail(error.code if isinstance(error, TransportError) else "spawn_failed")
            try:
                self.close()
            except TransportError:
                pass
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise TransportError(self._failure, diagnostics=self.diagnostics()) from None

    def diagnostics(self):
        """JSON-only, payload-free snapshot; unknown provider accounting stays unknown."""
        with self._state:
            return dict(schema_version="starvla-rsi.codex-app-server-diagnostics/v1",
                transport=TRANSPORT, process_started=self.process is not None,
                closed=self._closed, stdout_eof=self._stdout_eof,
                failure_code=self._failure, last_error_code=self._last_error,
                counts=dict(self._counts),
                stream_sha256={key: value.hexdigest() for key, value in self._hashes.items()},
                stderr_truncated=self._stderr_truncated, rpc_log_truncated=self._rpc_log_truncated,
                rpc_payloads_retained=False, stderr_redaction="pattern_based_not_complete_secret_detection",
                wrapper_restarts=0, provider_requests=None, backend_identity_verified=False,
                cleanup={**self._cleanup, "errors": list(self._cleanup["errors"]),
                         "signal_errors": list(self._cleanup["signal_errors"])})

    receipt = diagnostics

    def _error(self, code, *, rpc_code=None):  # build (not raise) the exception matching the code
        with self._state:
            self._last_error = code
        cls = TransportTimeout if code.endswith("_timeout") else RpcError if code == "rpc_error" else TransportError
        return cls(code, diagnostics=self.diagnostics(), rpc_code=rpc_code)

    def _fail(self, code):  # poison the connection: first code wins, waiters wake
        with self._state:
            if self._failure is None:
                self._failure = code
            self._state.notify_all()

    def _alive(self):  # raise if closing/closed or already failed
        if self._closed or self._closing:
            raise self._error("closed")
        if self._failure is not None:
            raise self._error(self._failure)

    def _observe_bytes(self, role, data):
        with self._state:
            self._counts[role + "_bytes"] += len(data)
            self._hashes[role].update(data)

    def _log_rpc(self, direction, data, message, kind):  # metadata and hash only, never the payload
        item = dict(direction=direction, kind=kind, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        if message is not None:
            method = message.get("method")
            if method in _METHODS:
                item["method"] = method
            elif isinstance(method, str):
                item["method_sha256"] = hashlib.sha256(method.encode()).hexdigest()
            if "id" in message:
                identifier = message["id"]
                if type(identifier) is int:
                    item["id"] = identifier
                else:
                    item["id_sha256"] = hashlib.sha256(str(identifier).encode()).hexdigest()
            if kind == "response":
                item["has_error"] = "error" in message
        payload = (json.dumps(item, separators=(",", ":")) + "\n").encode()
        with self._log_lock, self._state:
            if self._counts["rpc_log_bytes"] + len(payload) > self.limits.max_rpc_log_bytes:
                self._rpc_log_truncated = True  # this and later lines are dropped
                return
            self._logs["rpc_metadata.jsonl"].write(payload)
            self._counts["rpc_log_bytes"] += len(payload)

    def _chunks(self, stream):  # raw reads until EOF or _reader_stop
        with selectors.DefaultSelector() as selector:
            selector.register(stream, selectors.EVENT_READ)
            while not self._reader_stop.is_set():
                if not selector.select(0.1):  # wake every 0.1 s to check _reader_stop
                    continue
                data = os.read(stream.fileno(), 65536)
                if not data:
                    return
                yield data

    def _read_stdout(self):  # reader thread: split stdout into JSONL messages
        pending = bytearray()
        try:
            for chunk in self._chunks(self.process.stdout):
                self._observe_bytes("stdout", chunk)
                pending.extend(chunk)
                while b"\n" in pending:  # one message per newline-terminated line
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    if len(line) + 1 > self.limits.max_message_bytes:
                        raise TransportError("message_limit")
                    self._receive(bytes(line) + b"\n")
                if len(pending) >= self.limits.max_message_bytes:  # unfinished line already too long
                    raise TransportError("message_limit")
            if pending and not self._closing:  # EOF in the middle of a line
                self._log_rpc("stdout", bytes(pending), None, "incomplete_json")
                raise TransportError("invalid_json")
            with self._state:
                self._stdout_eof = not self._reader_stop.is_set()  # real EOF, not a requested stop
            if not self._closing:
                self._fail("stdout_eof")  # the child closed stdout (e.g. it exited)
        except TransportError as error:  # framing/protocol errors poison the connection
            self._fail(error.code)
        except (OSError, ValueError):
            if not self._closing:
                self._fail("stream_io_failed")

    def _receive(self, line):  # parse, check and route one line (reader thread)
        message = None
        try:
            message = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs)
            _json_value(message)
        except (UnicodeError, ValueError, RecursionError):
            self._log_rpc("stdout", line, None, "invalid_json")
            raise TransportError("invalid_json") from None
        kind = _envelope(message)
        self._log_rpc("stdout", line, message, kind)
        with self._state:
            self._counts["messages_received"] += 1
            if self._queued_bytes + len(line) > self.limits.max_queued_bytes:
                raise TransportError("queue_limit")
            if kind == "response":  # hand it to the request() waiting on this id
                key = _identifier(message["id"])
                if key not in self._responses or self._responses[key] is not None:  # an id we still wait for
                    raise TransportError("unexpected_response")
                self._responses[key] = (message, len(line))
            else:  # notifications and server requests go to next_message()
                if len(self._incoming) >= self.limits.max_queued_messages:
                    raise TransportError("queue_limit")
                if kind == "request":  # the server now waits for our reply() to this id
                    key = _identifier(message["id"])
                    if key in self._server_requests:
                        raise TransportError("duplicate_server_request")
                    if len(self._server_requests) >= self.limits.max_pending_requests:
                        raise TransportError("request_limit")
                    self._server_requests[key] = "waiting"
                self._incoming.append((message, len(line)))
            self._queued_bytes += len(line)
            self._state.notify_all()  # wake request()/next_message() waiters

    def _stderr_line(self, raw):  # redact one line and append it to the capped log
        text = raw.decode("utf-8", errors="replace")
        count = 0
        for pattern in _TOKEN_PATTERNS:
            text, changed = pattern.subn(lambda match: match.group(1) + "[REDACTED]", text)
            count += changed
        payload = text.encode("utf-8")
        with self._log_lock, self._state:
            remaining = self.limits.max_stderr_bytes - self._counts["stderr_retained_bytes"]
            kept = payload[:remaining]  # past the byte cap the rest is dropped
            self._logs["stderr.redacted.log"].write(kept)
            self._counts["stderr_retained_bytes"] += len(kept)
            self._counts["stderr_redactions"] += count
            self._stderr_truncated |= len(kept) != len(payload)

    def _read_stderr(self):  # reader thread: drain stderr so the child never blocks on it
        pending, omitting = bytearray(), False
        try:
            for chunk in self._chunks(self.process.stderr):
                self._observe_bytes("stderr", chunk)
                if omitting:  # skip the rest of an over-long line, up to its newline
                    _, separator, chunk = chunk.partition(b"\n")
                    if not separator:
                        continue
                    omitting = False
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    if len(line) <= self.limits.max_stderr_line_bytes:
                        self._stderr_line(bytes(line) + b"\n")
                    else:  # over-long complete line: dropped and counted
                        with self._state:
                            self._stderr_truncated = True
                            self._counts["stderr_omitted_lines"] += 1
                if len(pending) > self.limits.max_stderr_line_bytes:  # over-long partial line
                    pending.clear()
                    omitting = True
                    with self._state:
                        self._stderr_truncated = True
                        self._counts["stderr_omitted_lines"] += 1
            if pending and not omitting:  # last line without a newline
                self._stderr_line(bytes(pending))
        except (OSError, ValueError):
            if not self._closing:
                self._fail("diagnostic_io_failed")  # stderr read or log write failed

    def _send(self, message, deadline):  # check, frame and write one message by deadline
        try:
            _json_value(message)
            kind = _envelope(message)
            payload = (json.dumps(message, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()
        except (ValueError, TypeError, RecursionError):
            raise self._error("invalid_input") from None
        if len(payload) > self.limits.max_message_bytes:
            raise self._error("message_limit")
        # Waiting for another writer counts against this message's deadline.
        if not self._write_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            self._fail("write_timeout")
            raise self._error("write_timeout")
        try:
            with self._state:
                self._alive()  # recheck after waiting for the lock
            sent = 0
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdin, selectors.EVENT_WRITE)
                    while sent < len(payload):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            self._fail("write_timeout")  # a line may be half written: stream unusable
                            raise self._error("write_timeout")
                        try:
                            count = os.write(self.process.stdin.fileno(), payload[sent:])
                        except BlockingIOError:  # pipe full again; wait until writable
                            continue
                        if count <= 0:
                            raise OSError("pipe write")
                        self._observe_bytes("stdin", payload[sent:sent + count])
                        sent += count
                self._log_rpc("stdin", payload, message, kind)  # logged once the whole line is written
            except TransportError:
                raise
            except (OSError, ValueError):
                self._fail("stream_io_failed")
                raise self._error("stream_io_failed") from None
        finally:
            self._write_lock.release()

    def request(self, method, params, timeout):  # send, then block for the result; timeout covers both
        deadline = time.monotonic() + _duration(timeout)
        with self._state:
            self._alive()
            if len(self._responses) >= self.limits.max_pending_requests:  # our in-flight requests
                raise self._error("request_limit")
            identifier = self._next_id
            self._next_id += 1
            key = _identifier(identifier)
            self._responses[key] = None  # reserve the slot before sending, so the reply finds it
            self._counts["requests_started"] += 1
        try:
            self._send(dict(id=identifier, method=method, params=params), deadline)
            with self._state:
                while self._responses[key] is None:
                    self._alive()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._fail("request_timeout")  # outcome unknown: poison, never resend
                        raise self._error("request_timeout")
                    self._state.wait(remaining)  # woken by _receive() or _fail()
                response, size = self._responses.pop(key)
                self._queued_bytes -= size
                self._counts["requests_completed"] += 1
                if "error" in response:
                    self._counts["rpc_errors"] += 1
                    raise self._error("rpc_error", rpc_code=response["error"]["code"])
                return response["result"]
        finally:  # free the slot on any exit; a late reply is then unexpected
            with self._state:
                row = self._responses.pop(key, None)
                if row is not None:
                    self._queued_bytes -= row[1]

    def notify(self, method, params):  # one-way message, no response
        self._send(dict(method=method, params=params), time.monotonic() + self.limits.write_timeout_s)
        with self._state:
            self._counts["notifications_written"] += 1

    def reply(self, identifier, result):  # answer a server request (e.g. item/tool/call)
        key = _identifier(identifier)
        with self._state:
            self._alive()
            if self._server_requests.get(key) != "waiting":  # queued and not yet answered
                raise self._error("unknown_server_request")
            self._server_requests[key] = "replying"  # blocks a second reply during this write
        self._send(dict(id=identifier, result=result), time.monotonic() + self.limits.write_timeout_s)
        with self._state:
            del self._server_requests[key]  # freed only after the write succeeds
            self._counts["replies_written"] += 1

    def next_message(self, timeout):  # next notification or server request
        deadline = time.monotonic() + _duration(timeout)
        with self._state:
            self._alive()
            while not self._incoming:
                self._alive()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise self._error("event_timeout")  # no _fail: the caller may wait again or query
                self._state.wait(remaining)
            self._alive()
            message, size = self._incoming.popleft()
            self._queued_bytes -= size
            return message

    def close(self):
        """Signal only while an owned, unreaped child reserves this group's PID.

        CPython's waitpid lock prevents concurrent Popen poll/wait from reaping
        the leader while signals are sent. No poll/wait occurs during the grace
        period, and no destructive group signal occurs after releasing the lock.
        An already-reaped leader does not establish ownership of a reused PGID.
        Callers must not reap this owned child through an external waitpid/SIGCHLD
        handler; this POSIX/Popen lifecycle contract is not an OS process sandbox.
        """
        with self._close_lock:
            if self._closed:  # repeat call: re-raise a failed cleanup, else no-op
                if self._cleanup["succeeded"] is False:
                    raise self._error("cleanup_failed")
                return
            with self._state:
                self._closing = True  # new calls raise "closed"; readers ignore EOF/I/O errors
                self._cleanup["attempted"] = True
                self._state.notify_all()  # wake blocked callers so they raise
            errors = []
            process = self.process
            if process is not None:
                wait_lock = getattr(process, "_waitpid_lock", None)
                # Hold Popen's waitpid lock while signalling, so the leader cannot be reaped and its pid reused.
                held = wait_lock is not None and wait_lock.acquire(timeout=self.limits.cleanup_grace_s)
                group_absent = False
                signal_errors = []
                leader_visible = term_live_error = False
                try:
                    # Ours only if verified at spawn, same pid, and not yet reaped.
                    owned = (held and self._spawn_identity_verified
                             and process.pid == self._spawn_pid and process.returncode is None)
                    self._cleanup["ownership_proven"] = bool(owned)
                    if owned:
                        # The unreaped child (even a zombie) reserves the PID.
                        # Revalidate a live leader's group; an exited child can
                        # have no getpgid entry on macOS while remaining unreaped.
                        try:
                            owned = (os.getpgid(self._spawn_pid) == self._spawn_pid
                                     and os.getsid(self._spawn_pid) == self._spawn_pid)
                            leader_visible = bool(owned)
                        except ProcessLookupError:
                            pass
                        except OSError:
                            owned = False
                        self._cleanup["ownership_proven"] = bool(owned)
                    if owned:
                        # SIGTERM, wait up to cleanup_grace_s for readers to reach EOF, then SIGKILL the group.
                        for sig, field in ((signal.SIGTERM, "sent_term"), (signal.SIGKILL, "sent_kill")):
                            try:
                                os.killpg(self._spawn_pid, sig)
                                self._cleanup[field] = True
                            except ProcessLookupError:
                                group_absent = True  # group already gone, nothing left to kill
                                break
                            except OSError:
                                signal_errors.append("group_" + ("term" if sig == signal.SIGTERM else "kill") + "_failed")
                                # SIGTERM failed on a live leader: an error even if the group is gone later.
                                term_live_error |= sig == signal.SIGTERM and leader_visible
                            if sig == signal.SIGTERM:
                                deadline = time.monotonic() + self.limits.cleanup_grace_s
                                for thread in self._threads:
                                    thread.join(timeout=max(0, deadline - time.monotonic()))
                finally:
                    if held:
                        wait_lock.release()
                # Signals are now permanently finished. Only wait/read-only
                # existence checks may follow; a recycled PID is never killed.
                try:
                    process.wait(timeout=self.limits.cleanup_grace_s)  # reap the leader
                    self._cleanup["process_reaped"] = True
                except (subprocess.TimeoutExpired, OSError):
                    errors.append("process_reap_failed")
                try:
                    os.killpg(self._spawn_pid, 0)  # signal 0: existence check only
                except ProcessLookupError:
                    group_absent = True
                except OSError:
                    pass
                if not self._spawn_identity_verified:
                    errors.append("group_ownership_unverified")
                elif not owned and not group_absent:  # group may still exist and is not provably ours
                    errors.append("group_ownership_unverified")
                elif signal_errors and (not group_absent or term_live_error):  # they count unless the group is gone
                    errors.extend(signal_errors)
                self._cleanup["signal_errors"] = sorted(set(signal_errors))
                # Verified: the group is gone, or it was ours and got SIGKILL.
                self._cleanup["group_cleanup_verified"] = bool(self._spawn_identity_verified and
                    (group_absent or (owned and self._cleanup["sent_kill"])))
                # Readers normally end at pipe EOF; otherwise stop them with _reader_stop.
                for thread in self._threads:
                    thread.join(timeout=self.limits.cleanup_grace_s)
                self._reader_stop.set()
                for thread in self._threads:
                    thread.join(timeout=0.3)
                self._cleanup["readers_stopped"] = not any(thread.is_alive() for thread in self._threads)
                if not self._cleanup["readers_stopped"]:
                    errors.append("reader_join_timeout")
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            errors.append("pipe_close_failed")
            else:
                self._cleanup["readers_stopped"] = True
            with self._log_lock:
                for stream in self._logs.values():
                    try:
                        stream.close()
                    except OSError:
                        errors.append("diagnostic_close_failed")
            with self._state:
                self._closed = True
                self._cleanup.update(errors=sorted(set(errors)), succeeded=not errors)
                self._state.notify_all()
            if errors:
                raise self._error("cleanup_failed")
