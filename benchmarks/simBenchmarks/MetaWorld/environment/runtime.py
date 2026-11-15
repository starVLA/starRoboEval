"""Read-only native package verification; importing this module creates no SIM."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path, PurePosixPath

from benchkit.errors import CompatibilityError

PACKAGE_INVENTORY_SHA256 = "768366070ab463f23539105601f530461ffb0523946f889749295a0a2c367454"
VERSIONS = {"metaworld": "3.1.1", "mujoco": "3.3.0", "gymnasium": "1.3.0",
            "numpy": "1.24.4", "packaging": "26.2"}


def package_pin() -> dict:
    pin = json.loads(Path(__file__).with_name("package_pin.json").read_text(encoding="utf-8"))
    rows = pin.get("files", [])
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (pin.get("schema_version") != "starvla-rsi.metaworld.package-pin/v1"
            or pin.get("distribution") != "metaworld" or pin.get("version") != "3.1.1"
            or digest != PACKAGE_INVENTORY_SHA256
            or pin.get("file_inventory_sha256") != digest):
        raise CompatibilityError("MetaWorld package pin differs from the reviewed source inventory")
    return pin


def verify_package_tree(package_root: Path, pin: dict) -> None:
    """Check all native code/assets, including unexpected files; bytecode is excluded."""
    root = package_root.resolve(strict=True)
    expected = set()
    for row in pin["files"]:
        relative = PurePosixPath(row["path"])
        if (relative.is_absolute() or ".." in relative.parts or "." in relative.parts
                or not relative.parts or relative.parts[0] != "metaworld"):
            raise CompatibilityError("unsafe path in MetaWorld package pin")
        relative = Path(*relative.parts[1:])
        if relative.as_posix() in expected:
            raise CompatibilityError("duplicate path in MetaWorld package pin")
        expected.add(relative.as_posix())
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise CompatibilityError(f"missing or unsafe native file: {relative}")
        if path.stat().st_size != row["size_bytes"]:
            raise CompatibilityError(f"native file size differs: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise CompatibilityError(f"native file hash differs: {relative}")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if (p.is_file() or p.is_symlink()) and "__pycache__" not in p.parts
              and p.suffix != ".pyc"}
    if actual != expected:
        raise CompatibilityError("native MetaWorld file inventory differs from the pinned wheel")


def verify_runtime() -> dict:
    """Verify installed files and imports without constructing/resetting an environment."""
    pin = package_pin()
    for name, version in VERSIONS.items():
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise CompatibilityError(f"install the MetaWorld server requirements: missing {name}") from exc
        if installed != version:
            raise CompatibilityError(f"MetaWorld track requires {name}=={version}, found {installed}")
    distribution = importlib.metadata.distribution("metaworld")
    root = Path(distribution.locate_file("metaworld")).resolve(strict=True)
    spec = importlib.util.find_spec("metaworld")
    if spec is None or not spec.origin or Path(spec.origin).resolve() != root / "__init__.py":
        raise CompatibilityError("MetaWorld import is shadowed outside the pinned distribution")
    verify_package_tree(root, pin)
    return {"versions": dict(VERSIONS), "native_distribution_root": str(root),
            "package_file_count": len(pin["files"]),
            "package_inventory_sha256": PACKAGE_INVENTORY_SHA256,
            "pin_source": "installed wheel RECORD SHA-256 verified against actual code and asset bytes",
            "git_revision": None}


if __name__ == "__main__":
    print(json.dumps(verify_runtime(), indent=2, sort_keys=True))
