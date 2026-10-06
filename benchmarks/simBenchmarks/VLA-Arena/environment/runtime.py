"""Read-only native source and bundled asset verification before SIM creation."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from benchkit.errors import CompatibilityError

REVISION = "babe582ebffc82b979b77964a7e56417d02f63a4"
NATIVE_INVENTORY = "32f0caf4a8efcf7179bdb8075b05bb9fa02d22bac526fb33ceb3ae21c25d65c7"
ROBOSUITE_INVENTORY = "29971f30ce2d9999caa0527bf6fac42cf1e60ef498d8e3bffa2e84f679020222"
VERSIONS = {"robosuite": "1.5.1", "mujoco": "3.3.0", "numpy": "1.26.4",
            "bddl": "1.0.1", "torch": "2.5.1+cpu", "gym": "0.26.2", "future": "1.0.0"}
_PROCESS_NUMBA_CACHE: Path | None = None


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path, paths, *, installed_bytecode: bool = False) -> dict:
    root = root.resolve(strict=True)
    rows = []
    for path in sorted(paths):
        if path.is_symlink():
            raise CompatibilityError("native source/assets must not contain symlinks")
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            # Only wheel-install caches beside a real source file may be
            # excluded. Native checkouts must be clean and run with -B.
            source = path.parent.parent / (path.name.split(".")[0] + ".py")
            if (installed_bytecode and path.parent.name == "__pycache__" and path.is_file()
                    and path.name.endswith(".cpython-311.pyc") and source.is_file()):
                continue
            if installed_bytecode and path.name == "__pycache__" and path.is_dir():
                continue
            raise CompatibilityError("unexpected executable bytecode in native source/package")
        if not path.is_file():
            continue
        path = path.resolve(strict=True)
        if not path.is_relative_to(root):
            raise CompatibilityError("native source inventory escaped its root")
        rows.append({"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size,
                     "sha256": file_sha256(path)})
    rows.sort(key=lambda row: row["path"])
    return {"files": len(rows), "bytes": sum(r["size_bytes"] for r in rows),
            "inventory_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def verify_native_source(root: Path) -> dict:
    root = root.resolve(strict=True)
    try:
        def git(*args):
            return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                           timeout=30, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).strip()
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root or git("rev-parse", "HEAD") != REVISION:
            raise CompatibilityError("VLA-Arena needs its own pinned native Git checkout")
        if git("status", "--porcelain", "--untracked-files=all", "--ignored=matching"):
            raise CompatibilityError("native VLA-Arena checkout has modified, untracked or ignored files")
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompatibilityError("cannot verify native VLA-Arena Git identity") from exc
    paths = list((root / "vla_arena").rglob("*")) + [root / "pyproject.toml"]
    actual = inventory(root, paths)
    pin = json.loads(Path(__file__).with_name("native_source_pin.json").read_text())
    if (pin.get("upstream_revision") != REVISION or pin.get("inventory_sha256") != NATIVE_INVENTORY
            or any(actual[key] != pin.get(key) for key in actual)):
        raise CompatibilityError("native VLA-Arena code/task/asset inventory differs")
    return {**actual, "revision": REVISION, "groups": pin["groups"], "root": str(root)}


def verify_numba_cache(native_root: Path, robosuite_root: Path) -> Path:
    """Require a fresh caller-owned cache, outside both pinned code trees."""
    global _PROCESS_NUMBA_CACHE
    setting = os.environ.get("NUMBA_CACHE_DIR", "")
    path = Path(setting)
    if not setting or not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise CompatibilityError("set NUMBA_CACHE_DIR to a new existing private absolute directory")
    path = path.resolve(strict=True)
    if any(path.is_relative_to(root.resolve()) for root in (native_root, robosuite_root)):
        raise CompatibilityError("Numba cache must be outside pinned native/Robosuite trees")
    if _PROCESS_NUMBA_CACHE is None:
        if any(path.iterdir()):
            raise CompatibilityError("Numba cache must start empty for each fresh server process")
        _PROCESS_NUMBA_CACHE = path
    elif path != _PROCESS_NUMBA_CACHE:
        raise CompatibilityError("cannot switch Numba caches within one server process")
    return path


def prepare_runtime(root: Path) -> dict:
    """Imports selected native modules only after checking code and assets; no SIM."""
    if not sys.dont_write_bytecode:
        raise CompatibilityError("launch the VLA-Arena server with python -B to preserve its clean native tree")
    source = verify_native_source(root)
    if sys.version_info[:2] != (3, 11):
        raise CompatibilityError("the VLA-Arena runtime is pinned to Python 3.11")
    for name, version in VERSIONS.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise CompatibilityError(f"missing VLA-Arena native dependency {name}") from exc
        if actual != version:
            raise CompatibilityError(f"VLA-Arena requires {name}=={version}, found {actual}")
    rs = Path(importlib.metadata.distribution("robosuite").locate_file("robosuite")).resolve(strict=True)
    package = inventory(rs.parent, rs.rglob("*"), installed_bytecode=True)
    if package["inventory_sha256"] != ROBOSUITE_INVENTORY:
        raise CompatibilityError("Robosuite native code/assets differ from the pinned public wheel")
    cache = verify_numba_cache(root, rs)
    config = os.environ.get("LIBERO_CONFIG_PATH")
    if not config or not (Path(config) / "config.yaml").is_file():
        raise CompatibilityError("set LIBERO_CONFIG_PATH to a pre-created isolated native utility config")
    root = root.resolve(strict=True)
    resource = root / "vla_arena/vla_arena"
    expected_config = {"benchmark_root": str(resource), "bddl_files": str(resource / "bddl_files"),
                       "init_states": str(resource / "init_files"), "datasets": str(resource.parent / "datasets")}
    try:
        if json.loads((Path(config) / "config.yaml").read_text()) != expected_config:
            raise ValueError("different resource paths")
    except (OSError, ValueError) as exc:
        raise CompatibilityError("use the unchanged isolated JSON/YAML config produced by environment.configure") from exc
    # The native utils package otherwise writes ~/.libero at import time.
    if "vla_arena" in sys.modules:
        if Path(sys.modules["vla_arena"].__file__).resolve() != root / "vla_arena/__init__.py":
            raise CompatibilityError("another VLA-Arena package is already loaded")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    native = importlib.import_module("vla_arena.vla_arena")
    if Path(native.__file__).resolve() != root / "vla_arena/vla_arena/__init__.py":
        raise CompatibilityError("VLA-Arena import was shadowed")
    for field, relative in (("bddl_files", "bddl_files"), ("init_states", "init_files"), ("assets", "assets")):
        if Path(native.get_vla_arena_path(field)).resolve() != root / "vla_arena/vla_arena" / relative:
            raise CompatibilityError("native VLA-Arena resource path differs")
    robosuite = importlib.import_module("robosuite")
    if Path(robosuite.__file__).resolve() != rs / "__init__.py":
        raise CompatibilityError("Robosuite import was shadowed")
    numba_config = importlib.import_module("numba.core.config")
    if numba_config.CACHE_DIR != str(cache):
        raise CompatibilityError("Numba was imported with a different compiled-cache location")
    pin = json.loads(Path(__file__).with_name("robosuite_pin.json").read_text())
    controller = robosuite.load_composite_controller_config(robot="Panda")
    # The native loader flattens body_parts.arms into body_parts; the pin keeps
    # the original public JSON bytes instead of pretending they are identical.
    expected = {"type": pin["panda_controller"]["type"],
                "body_parts": pin["panda_controller"]["body_parts"]["arms"]}
    if controller != expected:
        raise CompatibilityError("native Panda composite controller configuration differs")
    checked_modules = ("vla_arena.vla_arena.benchmark", "vla_arena.vla_arena.envs",
                       "vla_arena.vla_arena.utils.eval_cost", "vla_arena.vla_arena.utils.eval_init_state")
    for name in checked_modules:
        importlib.import_module(name)  # Registers native classes; does not instantiate a SIM.
    for name, module in tuple(sys.modules.items()):
        if name == "vla_arena" or name.startswith("vla_arena."):
            origin = getattr(module, "__file__", None)
            if origin and not Path(origin).resolve().is_relative_to(root / "vla_arena"):
                raise CompatibilityError("a loaded VLA-Arena module escaped the pinned package")
    return {"native": source, "robosuite": {**package, "root": str(rs),
            "excluded_bytecode": "standard CPython 3.11 installation caches adjacent to source"}, "versions": dict(VERSIONS),
            "controller_config": controller, "imported_native_apis": list(checked_modules),
            "numba_cache": {"root": str(cache), "initially_empty": True, "scope": "process-owned generated cache; not a source pin"},
            "source_memory_attestation": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Read-only native source/runtime check; creates no SIM")
    parser.add_argument("--native-root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_runtime(args.native_root), indent=2, sort_keys=True))
