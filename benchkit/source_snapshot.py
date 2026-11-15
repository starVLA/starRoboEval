"""Bounded, evaluator-private snapshot of the shared benchmark-service runtime.

The service records SERVICE_SOURCE_FILES in a repository-relative layout; each
benchmark wrapper declares its own supplemental files. Clients record their Git
revision instead. Model code, native simulators, assets, credentials,
dependencies and loaded process memory are not captured here.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Mapping, Sequence

from benchkit.artifacts import atomic_write_json
from benchkit.contracts import JsonValue
from benchkit.errors import InfrastructureError

SCHEMA_VERSION = "starvla-rsi.harness-source/v2"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 2048

# Runtime shared by the benchmark-owned service wrappers. This is deliberately
# independent of participant implementations and arbitrary neighboring files.
# Benchmark-specific files remain the wrapper's separately declared
# SUPPLEMENTAL_FILES inventory.
SERVICE_SOURCE_FILES = (
    "benchkit/__init__.py",
    "benchkit/artifacts.py",
    "benchkit/contracts.py",
    "benchkit/errors.py",
    "benchkit/interfaces.py",
    "benchkit/source_snapshot.py",
    "benchkit/validation.py",
    "benchkit/sim_server/__init__.py",
    "benchkit/sim_server/cli.py",
    "benchkit/sim_server/launch.py",
    "benchkit/sim_server/server.py",
    "benchkit/sim_server/wire.py",
    "benchmarks/__init__.py",
    "benchmarks/simBenchmarks/__init__.py",
)


class SourceSnapshotError(InfrastructureError):
    """Source capture failed before any native episode may start."""


def installed_source_root() -> Path:
    """Return the source location of the actually imported evaluation package."""
    return Path(__file__).absolute().parent


def service_source_files(root: Path, max_files: int) -> list[tuple[Path, tuple[int, ...]]]:
    """Read only the explicit common service runtime, with no-follow traversal."""
    if len(SERVICE_SOURCE_FILES) > max_files:
        raise SourceSnapshotError("service source file count exceeds snapshot limit")
    selected = []
    for relative in sorted(SERVICE_SOURCE_FILES):
        try:
            with os.fdopen(_open_source_file(root, Path(relative)), "rb") as handle:
                details = os.fstat(handle.fileno())
                if not stat.S_ISREG(details.st_mode):
                    raise SourceSnapshotError(f"source must be regular: {relative}")
                selected.append((root / relative, _identity(details)))
        except OSError as exc:
            raise SourceSnapshotError(f"missing or unsafe explicit service source: {relative}") from exc
    return selected


def inventory_digest(files: Sequence[Mapping[str, JsonValue]]) -> str:
    """Recompute SHA-256 of the canonical path-sorted file inventory.

    Encoding: UTF-8 JSON, sorted object keys, separators (',', ':'), ensure_ascii
    False, no trailing newline. Each row contains path, size_bytes and sha256.
    File paths are relative POSIX paths inside the captured package.
    """
    canonical = json.dumps(sorted(files, key=lambda row: row["path"]), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _identity(details: os.stat_result) -> tuple[int, ...]:
    return (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns, details.st_ctime_ns)


def _open_source_file(root: Path, relative: Path) -> int:
    """Open through directory descriptors, never following source symlinks.

    A path-only O_NOFOLLOW on the final file does not protect its parent paths
    if a directory is replaced by a symlink after the inventory scan.
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


def capture_harness_source(run_dir: Path, *, max_file_bytes: int = MAX_FILE_BYTES,
                           max_total_bytes: int = MAX_TOTAL_BYTES,
                           max_files: int = MAX_FILES) -> dict[str, JsonValue]:
    """Copy a fresh source snapshot and atomically publish its verifiable index.

    Symlinks, changing source files, oversized payloads and existing output are
    rejected. A failed capture may leave a partial directory; it is never reused.
    The caller records a terminal initialization error and must not start reset.

    Only SERVICE_SOURCE_FILES are captured; the benchmark wrapper declares its
    own inventory separately.
    """
    root = installed_source_root().parent
    destination = Path(run_dir) / "harness_source"
    for limit in (max_file_bytes, max_total_bytes, max_files):
        if type(limit) is not int or limit <= 0:
            raise ValueError("snapshot limits must be positive integers")
    if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
        raise SourceSnapshotError("safe source capture requires no-follow POSIX file operations")
    if root.is_symlink() or not root.is_dir():
        raise SourceSnapshotError("service source root must be a non-symlink directory")
    forbidden = root / "benchkit"
    if forbidden.resolve() == destination.resolve() or forbidden.resolve() in destination.resolve().parents:
        raise SourceSnapshotError("snapshot output must be outside the service source package")
    destination.mkdir(exist_ok=False)
    files: list[dict[str, JsonValue]] = []
    total_bytes = 0
    try:
        selected = service_source_files(root, max_files)
        if not selected:
            raise SourceSnapshotError("service runtime has no capturable source files")
        for path, initial_identity in selected:
            relative = path.relative_to(root).as_posix()
            descriptor = _open_source_file(root, path.relative_to(root))
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode) or _identity(before) != initial_identity:
                    raise SourceSnapshotError(f"source changed during capture: {relative}")
                if before.st_size > max_file_bytes:
                    raise SourceSnapshotError(f"source file exceeds snapshot byte limit: {relative}")
                payload = handle.read(max_file_bytes + 1)
                if len(payload) > max_file_bytes:
                    raise SourceSnapshotError(f"source file exceeds snapshot byte limit: {relative}")
                if _identity(os.fstat(handle.fileno())) != initial_identity:
                    raise SourceSnapshotError(f"source changed during capture: {relative}")
            total_bytes += len(payload)
            if total_bytes > max_total_bytes:
                raise SourceSnapshotError("service source exceeds total snapshot byte limit")
            target = destination / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(payload)
            files.append({"path": relative, "size_bytes": len(payload),
                          "sha256": hashlib.sha256(payload).hexdigest()})
        if service_source_files(root, max_files) != selected:
            raise SourceSnapshotError("service source tree changed during capture")
    except OSError as exc:
        raise SourceSnapshotError(f"cannot capture service source: {exc}") from exc

    index: dict[str, JsonValue] = {
        "schema_version": SCHEMA_VERSION,
        "package": "benchkit",
        "scope": "explicit shared benchmark-service runtime only; repository-relative layout/v2",
        "source_root": str(root),
        "files_root": "files",
        "files": files,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_digest(files),
        "digest_format": "sha256 of path-sorted file rows as UTF-8 JSON; sorted keys; compact separators; ensure_ascii=false; no newline",
        "exclusions": [
            "symlinks rejected in source scope",
            "files outside SERVICE_SOURCE_FILES; no recursive source scan",
            "benchmark-specific source (separate declared service_source inventory)",
            "participant models, agent drivers, results and credentials",
        ],
        "limitations": "Not an external-policy, prompt, simulator, asset, dependency, or loaded-memory snapshot.",
    }
    index_path = destination / "index.json"
    atomic_write_json(index_path, index, overwrite=False)
    return {"path": "harness_source/index.json", "files_root": "harness_source/files",
            "scope": index["scope"], "source_root": str(root),
            "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "inventory_sha256": index["inventory_sha256"], "file_count": len(files),
            "total_bytes": total_bytes, "limitations": index["limitations"]}
