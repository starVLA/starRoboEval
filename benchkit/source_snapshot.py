"""Bounded, evaluator-private snapshots of shared and benchmark runtime source.

Layout/v2 records repository-relative harness code and explicit benchmark files;
it never recursively captures examples or model directories. Model code/prompts,
native simulators, assets, credentials, dependencies and loaded process memory
remain separate provenance domains. Explicit source_root supports legacy fixtures.
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
LEGACY_SCHEMA_VERSION = "starvla-rsi.harness-source/v1"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 2048
MAX_DEPTH = 32
MAX_TREE_ENTRIES = 16384
_PRIVATE_FILENAMES = {"credentials.json", "credential.json", "secrets.json", "secret.json",
                      "tokens.json", "token.json"}

# Runtime shared by the benchmark-owned service wrappers. This is deliberately
# independent of campaign registration, participant implementations and arbitrary
# neighboring files. Benchmark-specific files remain the wrapper's separately
# declared SUPPLEMENTAL_FILES inventory.
SERVICE_SOURCE_FILES = (
    "benchkit/__init__.py",
    "benchkit/artifacts.py",
    "benchkit/contracts.py",
    "benchkit/errors.py",
    "benchkit/interfaces.py",
    "benchkit/registry.py",
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
        raise SourceSnapshotError("evaluation source file count exceeds snapshot limit")
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


def repository_source_files(root: Path, max_files: int) -> list[tuple[Path, tuple[int, ...]]]:
    """Capture only declared evaluation runtime roots, never examples recursively.

    Participant model implementations are captured separately in model_source;
    results and credentials are never runtime source. Shared diagnostics under
    benchkit/ are included, while generated artifacts, results, rollouts, checks
    and arbitrary benchmark neighbors are not.
    """
    from benchkit.campaigns.benchmark_plans import ADAPTER_MODULES, PLAN_MODULES

    selected = _source_files(root / "benchkit", max_files,
                             excluded_directories=frozenset({"checks", "artifact_checks", "artifacts", "results", "rollouts", "_local"}))
    extras = ["benchmarks/__init__.py", "benchmarks/simBenchmarks/__init__.py",
              # Explicit trusted driver source, not recursively selected model
              # code. Capturing a path here does not transfer its ownership to
              # harness; policy action implementations remain model_source.
              "AgentPolicies/gpt6_astra/tools/runner.py", "AgentPolicies/gpt6_astra/run.py"]
    # Shared SIM transport is captured with harness above, not added twice.
    if PLAN_MODULES.keys() != ADAPTER_MODULES.keys():
        raise SourceSnapshotError("plan and adapter source registrations differ")
    for module in (*PLAN_MODULES.values(), *ADAPTER_MODULES.values()):
        parts = module.split(".")
        if len(parts) < 4 or parts[:2] != ["benchmarks", "simBenchmarks"]:
            raise SourceSnapshotError("invalid benchmark runtime source registration")
        extras.append("/".join(parts) + ".py")
        extras += ["/".join(parts[:depth]) + "/__init__.py"
                   for depth in range(3, len(parts))]
        extras.append("/".join(parts[:3]) + "/server.py")
    for benchmark, catalog in (("SimplerEnv", "task_catalog.json"),
                               ("LIBERO", "libero_catalog.json"), ("SIMPLE", "simple_released_tasks.json")):
        base = "benchmarks/simBenchmarks/" + benchmark + "/bench_server/"
        extras += [base + name for name in ("__init__.py", "adapter.py", "protocol/__init__.py",
                                            "protocol/" + catalog)]
    extras += [
               "benchmarks/simBenchmarks/SimplerEnv/environment/__init__.py",
               "benchmarks/simBenchmarks/SimplerEnv/environment/render_device.py",
               "benchmarks/simBenchmarks/SIMPLE/bench_server/source_inventory.py",
               "benchmarks/simBenchmarks/SIMPLE/bench_server/native_worker_client.py",
               "benchmarks/simBenchmarks/Robocasa_365/bench_server/protocol/robocasa365_target50.json",
               "benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/protocol/robocasa_tabletop_contract.json",
               "benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/protocol/task_catalog.json",
               "benchmarks/simBenchmarks/Robocasa_365/environment/render_lifecycle.py",
               # Standalone native services have no frozen campaign plan yet.
               "benchmarks/simBenchmarks/MetaWorld/__init__.py",
               "benchmarks/simBenchmarks/MetaWorld/bench_server/adapter.py",
               "benchmarks/simBenchmarks/MetaWorld/server.py",
               "benchmarks/simBenchmarks/MetaWorld/bench_server/protocol/task_catalog.json",
               "benchmarks/simBenchmarks/MetaWorld/environment/__init__.py",
               "benchmarks/simBenchmarks/MetaWorld/environment/runtime.py",
               "benchmarks/simBenchmarks/MetaWorld/environment/package_pin.json",
               "benchmarks/simBenchmarks/LIBERO-plus/__init__.py",
               "benchmarks/simBenchmarks/LIBERO-plus/bench_server/adapter.py",
               "benchmarks/simBenchmarks/LIBERO-plus/bench_server/protocol/catalog.py",
               "benchmarks/simBenchmarks/LIBERO-plus/server.py",
               "benchmarks/simBenchmarks/LIBERO-plus/environment/native_source_manifest.json",
               "benchmarks/simBenchmarks/LIBERO-plus/bench_server/protocol/catalogs/libero_spatial.json",
               "benchmarks/simBenchmarks/LIBERO-plus/bench_server/protocol/catalogs/libero_object.json",
               "benchmarks/simBenchmarks/LIBERO-plus/bench_server/protocol/catalogs/libero_goal.json",
               "benchmarks/simBenchmarks/LIBERO-plus/bench_server/protocol/catalogs/libero_10.json",
               "benchmarks/simBenchmarks/Robotwin/__init__.py",
               "benchmarks/simBenchmarks/Robotwin/bench_server/adapter.py",
               "benchmarks/simBenchmarks/Robotwin/server.py",
               "benchmarks/simBenchmarks/Robotwin/environment/__init__.py",
               "benchmarks/simBenchmarks/Robotwin/environment/runtime.py",
               "benchmarks/simBenchmarks/Robotwin/environment/oidn_compat.py",
               "benchmarks/simBenchmarks/Robotwin/environment/deployment.py",
               "benchmarks/simBenchmarks/Robotwin/environment/native_snapshot.json",
               "benchmarks/simBenchmarks/Robotwin/environment/runtime_snapshot.json",
               "benchmarks/simBenchmarks/Robotwin/environment/oidn_2_3_3_snapshot.json",
               "benchmarks/simBenchmarks/DOMINO/__init__.py",
               "benchmarks/simBenchmarks/DOMINO/server.py",
               "benchmarks/simBenchmarks/DOMINO/bench_server/adapter.py",
               "benchmarks/simBenchmarks/DOMINO/environment/__init__.py",
               "benchmarks/simBenchmarks/DOMINO/environment/runtime.py",
               "benchmarks/simBenchmarks/DOMINO/environment/deployment.py",
               "benchmarks/simBenchmarks/DOMINO/environment/native_outcome.py",
               "benchmarks/simBenchmarks/Behavior/__init__.py",
               "benchmarks/simBenchmarks/Behavior/server.py",
               "benchmarks/simBenchmarks/Behavior/bench_server/adapter.py",
               "benchmarks/simBenchmarks/Behavior/bench_server/native_worker_client.py",
               "benchmarks/simBenchmarks/Behavior/environment/__init__.py",
               "benchmarks/simBenchmarks/Behavior/environment/deployment.py",
               "benchmarks/simBenchmarks/Behavior/environment/native_bridge.py",
               "benchmarks/simBenchmarks/Behavior/environment/native_worker.py",
               "benchmarks/simBenchmarks/Behavior/environment/crash_handler.py",
               "benchmarks/simBenchmarks/VLA-Arena/__init__.py",
               "benchmarks/simBenchmarks/VLA-Arena/bench_server/adapter.py",
               "benchmarks/simBenchmarks/VLA-Arena/server.py",
               "benchmarks/simBenchmarks/VLA-Arena/bench_server/protocol/task_catalog.json",
               "benchmarks/simBenchmarks/VLA-Arena/environment/native_source_pin.json",
               "benchmarks/simBenchmarks/VLA-Arena/environment/__init__.py",
               "benchmarks/simBenchmarks/VLA-Arena/environment/runtime.py",
               "benchmarks/simBenchmarks/VLA-Arena/environment/configure.py",
               "benchmarks/simBenchmarks/VLA-Arena/environment/robosuite_pin.json",
               "benchmarks/simBenchmarks/calvin/__init__.py",
               "benchmarks/simBenchmarks/calvin/bench_server/adapter.py",
               "benchmarks/simBenchmarks/calvin/server.py",
               "benchmarks/simBenchmarks/calvin/environment/__init__.py",
               "benchmarks/simBenchmarks/calvin/environment/runtime.py",
               "benchmarks/simBenchmarks/calvin/bench_server/protocol/frozen_sequence.json",
               "benchmarks/simBenchmarks/calvin/bench_server/protocol/eval_sequences.json",
               "benchmarks/simBenchmarks/calvin/environment/runtime_snapshot.json",
               "benchmarks/simBenchmarks/calvin/environment/requirements-rgb-setup.txt"]
    # Standalone services have no campaign plan to contribute package markers.
    for benchmark in ("MetaWorld", "LIBERO-plus", "Robotwin", "DOMINO", "Behavior", "VLA-Arena", "calvin"):
        base = "benchmarks/simBenchmarks/" + benchmark + "/bench_server/"
        extras.append(base + "__init__.py")
        if benchmark != "Robotwin":
            extras.append(base + "protocol/__init__.py")
    for relative in sorted(set(extras)):
        path = root / relative
        try:
            with os.fdopen(_open_source_file(root, Path(relative)), "rb") as handle:
                details = os.fstat(handle.fileno())
                if not stat.S_ISREG(details.st_mode):
                    raise SourceSnapshotError(f"source must be regular: {relative}")
                selected.append((path, _identity(details)))
        except OSError as exc:
            raise SourceSnapshotError(f"missing or unsafe explicit runtime source: {relative}") from exc
    if len(selected) > max_files:
        raise SourceSnapshotError("evaluation source file count exceeds snapshot limit")
    return sorted(selected, key=lambda item: item[0].relative_to(root).as_posix())


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


def _source_files(root: Path, max_files: int, *,
                  excluded_directories: frozenset[str] = frozenset()) -> list[tuple[Path, tuple[int, ...]]]:
    selected: list[tuple[Path, tuple[int, ...]]] = []
    visited = 0
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def visit(relative_directory: Path, descriptor: int, depth: int) -> None:
        nonlocal visited
        if depth > MAX_DEPTH:
            raise SourceSnapshotError("evaluation source nesting exceeds snapshot limit")
        entries = []
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                visited += 1
                if visited > MAX_TREE_ENTRIES:
                    raise SourceSnapshotError("evaluation source tree exceeds entry scan limit")
                entries.append(entry)
        entries.sort(key=lambda entry: entry.name)
        for entry in entries:
            relative = relative_directory / entry.name
            path = root / relative
            if entry.name in excluded_directories:
                continue
            if entry.is_symlink():
                raise SourceSnapshotError(f"source symlinks are not allowed: {relative}")
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            if entry.is_dir(follow_symlinks=False):
                child = os.open(entry.name, directory_flags, dir_fd=descriptor)
                try:
                    visit(relative, child, depth + 1)
                finally:
                    os.close(child)
            elif path.suffix in {".py", ".json"} and entry.name.lower() not in _PRIVATE_FILENAMES:
                if not entry.is_file(follow_symlinks=False):
                    raise SourceSnapshotError(f"source must be a regular file: {relative}")
                selected.append((path, _identity(entry.stat(follow_symlinks=False))))
                if len(selected) > max_files:
                    raise SourceSnapshotError("evaluation source file count exceeds snapshot limit")

    descriptor = os.open(root, directory_flags)
    try:
        visit(Path(), descriptor, 0)
    finally:
        os.close(descriptor)
    return sorted(selected, key=lambda item: item[0].relative_to(root).as_posix())


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


def capture_harness_source(run_dir: Path, *, source_root: Path | None = None,
                           scope: str = "evaluation",
                           max_file_bytes: int = MAX_FILE_BYTES,
                           max_total_bytes: int = MAX_TOTAL_BYTES,
                           max_files: int = MAX_FILES) -> dict[str, JsonValue]:
    """Copy a fresh source snapshot and atomically publish its verifiable index.

    Symlinks, changing source files, oversized payloads and existing output are
    rejected. A failed capture may leave a partial directory; it is never reused.
    The caller records a terminal initialization error and must not start reset.

    The default evaluation scope preserves the complete campaign/driver capture.
    Service scope captures only SERVICE_SOURCE_FILES; its source_root, when
    supplied, is a repository or installed-package root. It does not capture a
    benchmark implicitly: the service wrapper declares that separate inventory.
    Both repository-relative scopes use layout/v2. An explicit source_root with
    the default scope retains the original legacy package-fixture layout/v1.
    """
    if scope not in ("evaluation", "service"):
        raise ValueError("source capture scope must be evaluation or service")
    service_scope = scope == "service"
    repository_layout = source_root is None or service_scope
    root = installed_source_root().parent if source_root is None else Path(source_root).absolute()
    inventory = (service_source_files if service_scope else
                 repository_source_files if repository_layout else _source_files)
    destination = Path(run_dir) / "harness_source"
    for limit in (max_file_bytes, max_total_bytes, max_files):
        if type(limit) is not int or limit <= 0:
            raise ValueError("snapshot limits must be positive integers")
    if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
        raise SourceSnapshotError("safe source capture requires no-follow POSIX file operations")
    if root.is_symlink() or not root.is_dir():
        raise SourceSnapshotError("evaluation source root must be a non-symlink directory")
    forbidden = root / "benchkit" if repository_layout else root
    if forbidden.resolve() == destination.resolve() or forbidden.resolve() in destination.resolve().parents:
        raise SourceSnapshotError("snapshot output must be outside the evaluation source package")
    destination.mkdir(exist_ok=False)
    files: list[dict[str, JsonValue]] = []
    total_bytes = 0
    try:
        selected = inventory(root, max_files)
        if not selected:
            raise SourceSnapshotError("evaluation package has no capturable source files")
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
                raise SourceSnapshotError("evaluation source exceeds total snapshot byte limit")
            target = destination / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(payload)
            files.append({"path": relative, "size_bytes": len(payload),
                          "sha256": hashlib.sha256(payload).hexdigest()})
        if inventory(root, max_files) != selected:
            raise SourceSnapshotError("evaluation source tree changed during capture")
    except OSError as exc:
        raise SourceSnapshotError(f"cannot capture evaluation source: {exc}") from exc

    index: dict[str, JsonValue] = {
        "schema_version": SCHEMA_VERSION if repository_layout else LEGACY_SCHEMA_VERSION,
        "package": "benchkit" if repository_layout else "legacy package fixture",
        "scope": "record tools, explicit benchmark service and trusted agent drivers; repository-relative layout/v2" if repository_layout else "explicit package .py/.json files only",
        "source_root": str(root),
        "files_root": "files",
        "files": files,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_digest(files),
        "digest_format": "sha256 of path-sorted file rows as UTF-8 JSON; sorted keys; compact separators; ensure_ascii=false; no newline",
        "exclusions": ["symlinks rejected in source scope", "__pycache__", "hidden paths",
                       "non-.py/.json files in recursive source scan (explicit runtime supplements may differ)",
                       "credential/secret/token JSON filenames", "tests and arbitrary benchmark neighbors",
                       "model actor code/configuration/results (separate model_source bundle); only two explicit trusted drivers included here"] + (
                           ["artifacts/results/rollouts directories in recursive harness scan"] if repository_layout else []),
        "limitations": "Not an external-policy, prompt, simulator, asset, dependency, or loaded-memory snapshot.",
    }
    if service_scope:
        index["scope"] = "explicit shared benchmark-service runtime only; repository-relative layout/v2"
        index["exclusions"] = [
            "symlinks rejected in source scope",
            "files outside SERVICE_SOURCE_FILES; no recursive source scan",
            "benchmark-specific source (separate declared service_source inventory)",
            "campaign assembly, participant models, trusted agent drivers, results and credentials",
        ]
    index_path = destination / "index.json"
    atomic_write_json(index_path, index, overwrite=False)
    return {"path": "harness_source/index.json", "files_root": "harness_source/files",
            "scope": index["scope"], "source_root": str(root),
            "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "inventory_sha256": index["inventory_sha256"], "file_count": len(files),
            "total_bytes": total_bytes, "limitations": index["limitations"]}
