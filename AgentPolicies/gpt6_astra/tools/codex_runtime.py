"""Local Codex CLI readiness checks for the persistent app-server method.

Version, executable and existing login checks only; no inference or SIM access.
The bounded process helpers retain the previous runtime-check behavior.
"""

from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from benchkit.errors import PolicyPreflightError


CLI_VERSION = "0.154.0"


MAX_PREFLIGHT_BYTES = 128 * 1024


PREFLIGHT_TIMEOUT_S = 10.0


_SAFE_ENVIRONMENT = ("HOME", "CODEX_HOME", "USER", "LOGNAME", "TZ")


_SAFE_FAILURES = frozenset({
    "invalid_input", "runtime_unavailable", "spawn_failed", "timeout", "stream_io_failed",
    "stdout_limit", "stderr_limit", "invalid_event", "unexpected_event", "event_order",
    "forbidden_item", "cli_warning", "model_rerouted", "cli_error", "stderr_rejected",
    "invalid_usage", "invalid_output", "incomplete_output", "cli_exit_nonzero", "cleanup_failed",
    "transient_model_error",
})


class _Rejected(Exception):
    def __init__(self, code):
        self.code = code if code in _SAFE_FAILURES else "invalid_event"
        super().__init__(self.code)


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


_STDERR_HINTS = {
    "connection": ("stream disconnected before completion", "connection reset",
                   "connection refused", "connection closed", "error sending request",
                   "network is unreachable", "broken pipe"),
    "timeout": ("connection timed out", "request timed out", "operation timed out"),
    "dns": ("dns error", "failed to lookup address", "name or service not known"),
    "tls": ("certificate verify failed", "invalid peer certificate", "tls handshake"),
    "authentication": ("authentication failed", "token expired", "unauthorized"),
    "quota": ("rate limit exceeded", "quota exceeded", "too many requests"),
    "local_state": ("state db missing rollout path", "database is locked",
                    "failed to open database"),
    "runtime": ("failed to refresh available models", "failed to load model catalog",
                "code mode host", "permission denied", "no space left on device"),
}


def _stderr_diagnostics(payload):
    """Bounded allowlist projection, not raw text or a root-cause assertion."""
    lowered = payload.decode("utf-8", errors="replace").lower()
    hints = [{"kind": kind, "phrase": phrase}
             for kind, phrases in _STDERR_HINTS.items() for phrase in phrases
             if re.search(r"(?<![a-z0-9_])" + re.escape(phrase) + r"(?![a-z0-9_])", lowered)]
    statuses = sorted(set(re.findall(
        r"\bhttp(?:/\d(?:\.\d)?)?(?:\s+status(?:\s+code)?)?\s*[:=]?\s+([45]\d\d)\b",
        lowered)))
    levels = [level for level in ("ERROR", "WARN", "WARNING", "INFO", "DEBUG")
              if re.search(r"(?<![a-zA-Z0-9_])" + level + r"(?![a-zA-Z0-9_])",
                           payload.decode("utf-8", errors="replace"))]
    return {"schema_version": "starvla-rsi.stderr-diagnostic/v1",
            "captured_prefix_sha256": _sha(payload), "captured_prefix_bytes": len(payload),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "recognized_messages": hints, "observed_http_statuses": statuses,
            "observed_levels": levels, "unrecognized_text": "omitted",
            "raw_body_retained": False, "root_cause_verified": False}


def _environment():
    # Preserve the real login locations; do not relocate HOME/CODEX_HOME or copy
    # their contents. Everything else (including SSH agents, SIM bearer tokens,
    # API keys, proxies, SDK endpoint overrides and parent-thread IDs) is absent.
    result = {key: os.environ[key] for key in _SAFE_ENVIRONMENT if key in os.environ}
    result.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", TERM="dumb", LANG="C", LC_ALL="C")
    return result


def _resolve_executable():
    candidate = shutil.which("codex")
    if not candidate:
        raise _Rejected("runtime_unavailable")
    path = Path(candidate).resolve(strict=True)
    details = path.stat()
    if not stat.S_ISREG(details.st_mode) or not os.access(path, os.X_OK):
        raise _Rejected("runtime_unavailable")
    return path


def _binary_digest(path, deadline=None):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            if deadline is not None and time.monotonic() >= deadline:
                raise _Rejected("timeout")
            digest.update(part)
    return digest.hexdigest()


def _cleanup(process):
    """Reap only the newly created process/session, never match other processes."""
    if process is None:
        return
    # start_new_session=True gives this invocation an owned process group. Its
    # local app-server child must not continue inference after our deadline.
    failed = False
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception:
        failed = True
    try:
        process.wait(timeout=0.4)
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        failed = True
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        failed = True
    try:
        process.wait(timeout=0.4)
    except Exception:
        failed = True
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception:
                failed = True
    if failed:
        raise _Rejected("cleanup_failed")


def _collect(argv, *, cwd, environment, input_bytes, timeout_s, stdout_limit,
             stderr_limit, stats, on_line=None, strict_stderr=False):
    """Bound both pipes while writing stdin; never use communicate's unbounded buffers."""
    process = None
    selector = selectors.DefaultSelector()
    output, errors, pending = bytearray(), bytearray(), bytearray()
    offset = 0
    deadline = time.monotonic() + timeout_s
    failure = None
    returncode = None
    stderr_hasher = hashlib.sha256()
    try:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=cwd, env=environment, shell=False,
                start_new_session=True, close_fds=True)
        except (OSError, ValueError):
            raise _Rejected("spawn_failed") from None
        stats["launched"] = True
        for stream, role, events in ((process.stdout, "stdout", selectors.EVENT_READ),
                                     (process.stderr, "stderr", selectors.EVENT_READ),
                                     (process.stdin, "stdin", selectors.EVENT_WRITE)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, events, role)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Rejected("timeout")
            for key, _ in selector.select(min(remaining, 0.1)):
                stream, role = key.fileobj, key.data
                if role == "stdin":
                    if offset == len(input_bytes):
                        selector.unregister(stream)
                        stream.close()
                    else:
                        try:
                            offset += os.write(stream.fileno(), input_bytes[offset:offset + 65536])
                        except BrokenPipeError:
                            selector.unregister(stream)
                            stream.close()
                    continue
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                field = role + "_bytes"
                stats[field] = stats.get(field, 0) + len(chunk)
                if role == "stderr":
                    stderr_hasher.update(chunk)
                    errors.extend(chunk[:max(0, stderr_limit - len(errors))])
                if stats[field] > (stdout_limit if role == "stdout" else stderr_limit):
                    raise _Rejected(role + "_limit")
                if role == "stderr":
                    if strict_stderr:
                        # stderr is a progress/diagnostic channel, not a failed
                        # turn by itself. Identity violations remain fatal even
                        # if a later structured response would look valid.
                        if b"model rerouted:" in errors.lower():
                            raise _Rejected("model_rerouted")
                    continue
                if on_line is None:
                    output.extend(chunk)
                else:
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending = bytearray(rest)
                        if line.strip():
                            on_line(bytes(line))
        if pending.strip():
            raise _Rejected("invalid_event")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _Rejected("timeout")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise _Rejected("timeout") from None
    except _Rejected as exc:
        failure = exc
    except Exception:
        failure = _Rejected("stream_io_failed")
    finally:
        selector.close()
        if strict_stderr and stats.get("stderr_bytes", 0):
            stats["stderr_diagnostic"] = _stderr_diagnostics(bytes(errors))
            stats["stderr_diagnostic"].update(
                observed_bytes=stats["stderr_bytes"], observed_sha256=stderr_hasher.hexdigest(),
                capture_truncated=stats["stderr_bytes"] > len(errors),
                stream_complete=failure is None,
                collection_failure=failure.code if failure else None)
        stats["wrapper_terminated_running_process"] = process is not None and process.poll() is None
        try:
            _cleanup(process)
        except Exception:
            stats["cleanup_failed"] = True
            if failure is None:
                failure = _Rejected("cleanup_failed")
        if process is not None and type(process.returncode) is int:
            stats["returncode"] = process.returncode
    if failure is not None:
        raise failure from None
    return returncode, bytes(output), bytes(errors)


def _inspect_runtime(timeout_s=PREFLIGHT_TIMEOUT_S):
    if os.name != "posix":
        raise PolicyPreflightError("unsupported")
    deadline = time.monotonic() + timeout_s
    executable = _resolve_executable()
    initial_digest = _binary_digest(executable, deadline)
    environment = _environment()
    outputs = []
    # These CLI commands perform no inference. Their bodies stay local and are
    # parsed narrowly; in particular API-key login status is never echoed.
    with tempfile.TemporaryDirectory(prefix="rsi-codex-preflight-") as temporary:
        for arguments in (("--version",), ("exec", "--help"), ("login", "status")):
            stats = {}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Rejected("timeout")
            code, out, err = _collect([str(executable), *arguments], cwd=temporary,
                environment=environment, input_bytes=b"", timeout_s=remaining,
                stdout_limit=MAX_PREFLIGHT_BYTES, stderr_limit=MAX_PREFLIGHT_BYTES, stats=stats)
            outputs.append((code, (out + b"\n" + err).strip()))
            if arguments == ("--version",) and outputs[0] != (0, ("codex-cli " + CLI_VERSION).encode()):
                raise PolicyPreflightError("unsupported")
    required = (b"--ignore-user-config", b"--ignore-rules", b"--strict-config", b"--ephemeral",
                b"--sandbox", b"--json", b"--output-schema", b"--image", b"--model")
    if outputs[1][0] != 0 or not all(option in outputs[1][1] for option in required):
        raise PolicyPreflightError("unsupported")
    if outputs[2] != (0, b"Logged in using ChatGPT"):
        raise PolicyPreflightError("credentials_missing")
    if _binary_digest(executable, deadline) != initial_digest:
        raise PolicyPreflightError("initialization_failed")
    return executable, {"cli_version": CLI_VERSION, "cli_executable_sha256": initial_digest,
        "authentication": "existing_chatgpt_cli_login", "scope": "local_runtime_only",
        "provider_access_verified": False, "model_access_verified": False,
        "dispatch_configuration_prevalidated": False}


def preflight_runtime():
    """Check exact CLI version/help/local login, without opening an inference turn."""
    result, failure = None, None
    try:
        _, result = _inspect_runtime()
    except PolicyPreflightError as exc:
        failure = PolicyPreflightError(exc.code)
    except Exception:
        failure = PolicyPreflightError("dependency_unavailable")
    if failure is not None:
        raise failure from None
    return result
