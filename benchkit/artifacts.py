"""Atomic writers, no-follow reads and runtime provenance for evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import selectors
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping

from benchkit.contracts import JsonValue, ensure_jsonable


def utc_now() -> str:
    """Return a UTC timestamp in a stable machine-readable format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def atomic_write_json(path: Path, payload: Mapping[str, JsonValue], *, overwrite: bool = True) -> None:
    """Write one JSON object without exposing a partially written final file."""
    normalized = ensure_jsonable(payload, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(normalized, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # Atomic publication without replacing an existing file or symlink.
            os.link(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    """Persist a directory entry change where the platform supports it."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def append_jsonl(path: Path, payload: Mapping[str, JsonValue]) -> None:
    """Append and flush one event to a JSON Lines stream."""
    normalized = ensure_jsonable(payload, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(normalized, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def open_no_follow(root: Path, relative: Path) -> int:
    """Open a file below root through directory descriptors, never following symlinks.

    A path-only O_NOFOLLOW on the final file does not protect its parent paths
    if a directory is replaced by a symlink between a scan and the read.
    """
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root, directory_flags)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=descriptor)
    finally:
        os.close(descriptor)


def _git_diff_digest(repository: Path, scope: str, *, max_bytes: int = 32 * 1024 * 1024,
                     timeout_s: float = 15.0) -> dict[str, JsonValue]:
    """Hash a bounded scoped diff stream without retaining patch text."""
    command = ["git", "-C", str(repository), "diff", "--no-ext-diff", "--no-textconv",
               "HEAD", "--binary", "--", scope]
    digest = hashlib.sha256()
    byte_count = 0
    deadline = time.monotonic() + timeout_s
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("Git diff exceeded its time limit")
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    if byte_count > max_bytes:
                        raise ValueError("Git diff exceeded its byte limit")
                    digest.update(chunk)
            return_code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            if return_code:
                raise subprocess.CalledProcessError(return_code, command)
        except BaseException:
            process.kill()
            process.wait()
            raise
    return {"status": "recorded", "scope": scope, "sha256": digest.hexdigest(),
            "size_bytes": byte_count, "includes_untracked_files": False,
            "format": "git diff --no-ext-diff --no-textconv HEAD --binary -- <scope>"}


def git_provenance(repository: Path | None) -> dict[str, JsonValue]:
    """Collect a revision, dirty flag and whole-checkout diff digest without mutating Git state."""
    location = Path(repository) if repository is not None else Path(__file__).parent
    unavailable: dict[str, JsonValue] = {
        "status": "unavailable", "scope": ".",
        "sha256": None, "includes_untracked_files": False,
    }
    try:
        root = Path(subprocess.run(
            ["git", "-C", str(location), "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, text=True, timeout=10,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        ).stdout.strip()).resolve()
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "dirty": None,
                "diff": {**unavailable, "reason": "git_checkout_unavailable"}}
    # Tracked changes anywhere in the checkout: harness, drivers, policies and prompts.
    try:
        diff = _git_diff_digest(root, ".")
    except (OSError, subprocess.SubprocessError, TimeoutError, ValueError) as exc:
        diff = {**unavailable, "reason": type(exc).__name__}
    return {"revision": revision, "dirty": dirty, "diff": diff}


def runtime_provenance(repository: Path | None = None) -> dict[str, JsonValue]:
    """Collect the minimum environment identity needed to interpret a run."""
    return ensure_jsonable(
        {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "git": git_provenance(repository),
        }
    )
