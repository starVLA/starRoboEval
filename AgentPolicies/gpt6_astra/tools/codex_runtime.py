"""Local Codex CLI readiness checks for the persistent app-server method.

Version, executable and existing login checks only; no inference or SIM access.
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
from benchkit.errors import PolicyPreflightError


TESTED_CLI_VERSION = "0.154.0"  # the version this policy was tested with; other versions also run
_VERSION = re.compile(rb"codex-cli ([0-9A-Za-z.+-]{1,64})")


MAX_PREFLIGHT_BYTES = 128 * 1024  # cap per output stream of each preflight command


PREFLIGHT_TIMEOUT_S = 10.0  # one deadline for all of inspect_runtime


_SAFE_ENVIRONMENT = ("HOME", "CODEX_HOME", "USER", "LOGNAME", "TZ")  # copied as is; they locate the login


# The only codes _Rejected carries; any other becomes "stream_io_failed".
_SAFE_FAILURES = frozenset({
    "runtime_unavailable", "spawn_failed", "timeout", "stream_io_failed",
    "stdout_limit", "stderr_limit", "cleanup_failed",
})


class _Rejected(Exception):  # internal failure with a fixed code, no child output
    def __init__(self, code):
        self.code = code if code in _SAFE_FAILURES else "stream_io_failed"
        super().__init__(self.code)


def codex_environment():  # env for the preflight commands and the app-server
    # Preserve the real login locations; do not relocate HOME/CODEX_HOME or copy
    # their contents. Everything else (including SSH agents, SIM bearer tokens,
    # API keys, proxies, SDK endpoint overrides and parent-thread IDs) is absent.
    result = {key: os.environ[key] for key in _SAFE_ENVIRONMENT if key in os.environ}
    result.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", TERM="dumb", LANG="C", LC_ALL="C")  # fixed PATH, C locale
    # StdioAppServer filters this again with its own allowlist, which drops TERM.
    return result


def _resolve_executable():  # real file behind "codex" on PATH; hashed and launched
    candidate = shutil.which("codex")
    if not candidate:
        raise _Rejected("runtime_unavailable")
    path = Path(candidate).resolve(strict=True)  # follow symlinks to the real file
    details = path.stat()
    if not stat.S_ISREG(details.st_mode) or not os.access(path, os.X_OK):
        raise _Rejected("runtime_unavailable")
    return path


def _binary_digest(path, deadline=None):  # SHA-256, checking the deadline every 1 MiB
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
        os.killpg(process.pid, signal.SIGTERM)  # ask the whole group to exit
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
        os.killpg(process.pid, signal.SIGKILL)  # then force any survivors
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
             stderr_limit, stats):
    """Bound both pipes while writing stdin; never use communicate's unbounded buffers."""
    process = None
    selector = selectors.DefaultSelector()
    output, errors = bytearray(), bytearray()
    offset = 0  # bytes of input_bytes written so far
    deadline = time.monotonic() + timeout_s  # covers spawn, all I/O and the exit
    failure = None
    returncode = None
    try:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=cwd, env=environment, shell=False,
                start_new_session=True, close_fds=True)
        except (OSError, ValueError):
            raise _Rejected("spawn_failed") from None
        stats["launched"] = True
        # Non-blocking pipes on one selector; each is unregistered once finished.
        for stream, role, events in ((process.stdout, "stdout", selectors.EVENT_READ),
                                     (process.stderr, "stderr", selectors.EVENT_READ),
                                     (process.stdin, "stdin", selectors.EVENT_WRITE)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, events, role)
        while selector.get_map():  # until stdout/stderr reach EOF and stdin is closed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Rejected("timeout")
            for key, _ in selector.select(min(remaining, 0.1)):
                stream, role = key.fileobj, key.data
                if role == "stdin":
                    if offset == len(input_bytes):  # all written: close stdin so the child sees EOF
                        selector.unregister(stream)
                        stream.close()
                    else:
                        try:
                            offset += os.write(stream.fileno(), input_bytes[offset:offset + 65536])
                        except BrokenPipeError:  # the child closed stdin early; stop writing
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
                if stats[field] > (stdout_limit if role == "stdout" else stderr_limit):
                    raise _Rejected(role + "_limit")
                (errors if role == "stderr" else output).extend(chunk)
        # Both outputs are closed; the child must also exit before the deadline.
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
    finally:  # always kill and reap the group, also after a normal exit
        selector.close()
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


# Returns (executable, readiness record). persistent_runtime._boot calls it before each launch.
def inspect_runtime(timeout_s=PREFLIGHT_TIMEOUT_S):
    if os.name != "posix":
        raise PolicyPreflightError("unsupported")
    deadline = time.monotonic() + timeout_s
    executable = _resolve_executable()
    digest = _binary_digest(executable, deadline)  # recorded to identify the binary that ran
    environment = codex_environment()
    outputs = []
    # These CLI commands perform no inference. Their bodies stay local and are
    # parsed narrowly; in particular API-key login status is never echoed.
    with tempfile.TemporaryDirectory(prefix="rsi-codex-preflight-") as temporary:
        for arguments in (("--version",), ("login", "status")):
            stats = {}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Rejected("timeout")
            code, out, err = _collect([str(executable), *arguments], cwd=temporary,
                environment=environment, input_bytes=b"", timeout_s=remaining,
                stdout_limit=MAX_PREFLIGHT_BYTES, stderr_limit=MAX_PREFLIGHT_BYTES, stats=stats)
            outputs.append((code, (out + b"\n" + err).strip()))  # both streams
    if outputs[0][0] != 0:  # the CLI must at least run
        raise PolicyPreflightError("dependency_unavailable")
    version = _VERSION.fullmatch(outputs[0][1])  # recorded as reported; None if the format is unfamiliar
    if outputs[1][0] != 0:  # "login status" fails when no login exists
        raise PolicyPreflightError("credentials_missing")
    # Only the login kind is recorded; the status text may contain a masked API key.
    login = outputs[1][1]
    method = ("chatgpt" if login == b"Logged in using ChatGPT"
              else "api_key" if login.startswith(b"Logged in using an API key") else "other")
    return executable, {"cli_version": version and version.group(1).decode(),
        "tested_cli_version": TESTED_CLI_VERSION, "cli_executable_sha256": digest,
        "authentication": "existing_cli_login", "login_method": method, "scope": "local_runtime_only",
        "provider_access_verified": False, "model_access_verified": False,
        "dispatch_configuration_prevalidated": False}


def preflight_runtime():
    """Check that the CLI runs and has a local login, without opening an inference turn."""
    result, failure = None, None
    try:
        _, result = inspect_runtime()
    except PolicyPreflightError as exc:
        failure = PolicyPreflightError(exc.code)  # rebuilt from the code only
    except Exception:  # e.g. _Rejected: no codex on PATH, timeout, I/O
        failure = PolicyPreflightError("dependency_unavailable")
    if failure is not None:
        raise failure from None  # raised outside except, without the original cause
    return result
