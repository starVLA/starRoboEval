"""Content-pinned clean-task deployment, without native imports or resets.

Only two CuRobo path-config files are derived. Original source and asset roots
are never edited. The package's reference snapshot is not a Git attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

SNAPSHOT_SCHEMA = "starvla-rsi.robotwin-native-snapshot/v1"
DEPLOYMENT_SCHEMA = "starvla-rsi.robotwin-deployment/v1"
SNAPSHOT_FILE = Path(__file__).with_name("native_snapshot.json")
CONFIGS = tuple(f"assets/embodiments/aloha-agilex/curobo_{side}.yml" for side in ("left", "right"))
TEMPLATES = tuple(f"assets/embodiments/aloha-agilex/curobo_{side}_tmp.yml" for side in ("left", "right"))
SOURCE_TREES = ("envs", "task_config", "assets/embodiments/aloha-agilex",
                "assets/objects/050_bell", "assets/objects/060_kitchenpot")
EXTRA_FILES = ("LICENSE", "script/eval_policy.py", "script/requirements.txt",
               "description/task_instruction/lift_pot.json", "description/task_instruction/click_bell.json",
               "assets/objects/objaverse/list.json", "assets/objects/same.json")
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".cache"}
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_FILES = 10000


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def _relative(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or PurePosixPath(value).is_absolute()
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("unsafe deployment path")
    return value


def _regular(root: Path, relative: str) -> Path:
    path = root
    for part in _relative(relative).split("/"):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlink is not a pinned regular file: {relative}")
    if not path.is_file():
        raise ValueError(f"missing deployment file: {relative}")
    return path


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("invalid or oversized manifest")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate manifest key")
            value[key] = item
        return value

    payload = json.loads(path.read_bytes(), object_pairs_hook=unique,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite manifest")))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be an object")
    return payload


def _snapshot_files(root: Path):
    """Inventory clean-track runtime closure; omit unrelated CuRobo docs/Git."""
    selected = set(EXTRA_FILES)
    for relative in SOURCE_TREES:
        base = root / relative
        if not base.is_dir() or base.is_symlink():
            raise ValueError(f"missing regular source/asset directory: {relative}")
        for directory, children, names in os.walk(base, followlinks=False):
            children[:] = [name for name in children if name not in IGNORED_DIRS]
            if Path(directory) == root / "envs/curobo":
                children[:] = [name for name in children if name == "src"]
                names = []
            if Path(directory) == root / "envs/curobo/src":
                children[:] = [name for name in children if name == "curobo"]
                names = []
            for name in children:
                if (Path(directory) / name).is_symlink():
                    raise ValueError("source/asset directory symlink requires explicit materialization")
            for name in names:
                if name.endswith((".pyc", ".pyo")):
                    continue
                path = Path(directory) / name
                if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError("source/asset inventory requires regular files")
                selected.add(path.relative_to(root).as_posix())
    if len(selected) > MAX_FILES:
        raise ValueError("source/asset inventory exceeds file bound")
    return sorted(selected)


def inspect_reference(root: Path) -> dict:
    root = root.resolve(strict=True)
    rows = []
    for relative in _snapshot_files(root):
        path = _regular(root, relative)
        rows.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": digest(path)})
    return {"schema_version": SNAPSHOT_SCHEMA, "native_source_revision": None,
            "scope": "content-pinned local archive; clean Aloha lift_pot/click_bell only; not upstream-full attestation",
            "files": rows, "inventory_sha256": hashlib.sha256(_canonical(rows)).hexdigest()}


def reference_snapshot() -> dict:
    value = _json(SNAPSHOT_FILE)
    if (value.get("schema_version") != SNAPSHOT_SCHEMA or value.get("native_source_revision") is not None
            or not isinstance(value.get("files"), list) or not 1 <= len(value["files"]) <= MAX_FILES):
        raise ValueError("invalid packaged native snapshot")
    previous = ""
    for row in value["files"]:
        if set(row) != {"path", "size_bytes", "sha256"}:
            raise ValueError("invalid snapshot row")
        relative = _relative(row["path"])
        if (relative <= previous or type(row["size_bytes"]) is not int or row["size_bytes"] < 0
                or not isinstance(row["sha256"], str) or len(row["sha256"]) != 64
                or any(character not in "0123456789abcdef" for character in row["sha256"])):
            raise ValueError("invalid snapshot ordering/hash")
        previous = relative
    if hashlib.sha256(_canonical(value["files"])).hexdigest() != value.get("inventory_sha256"):
        raise ValueError("packaged native snapshot digest differs")
    return value


def _derived(root: Path, relative: str, snapshot: dict) -> bytes:
    template = TEMPLATES[CONFIGS.index(relative)]
    source = _regular(root, template)
    expected = next((row for row in snapshot["files"] if row["path"] == template), None)
    if expected is None:
        raise ValueError("pinned CuRobo path template is missing")
    if digest(source) != expected["sha256"]:
        raise ValueError("CuRobo path template changed")
    text = source.read_text()
    if "${ASSETS_PATH}" not in text and "$ASSETS_PATH" not in text:
        raise ValueError("expected native path placeholder is absent")
    return text.replace("${ASSETS_PATH}", str(root)).replace("$ASSETS_PATH", str(root)).encode()


def prepare(reference_root: Path, output: Path) -> dict:
    """Copy matching bytes to a new root; failures keep a partial deployment."""
    source = reference_root.resolve(strict=True)
    target = output.absolute()
    if target != target.resolve() or target.exists() or target.is_symlink() or target == source or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("deployment destination must be new and independent of the reference root")
    snapshot = reference_snapshot()
    target.mkdir(parents=True, exist_ok=False)
    for row in snapshot["files"]:
        original = _regular(source, row["path"])
        destination = target / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        copied = hashlib.sha256()
        with original.open("rb") as reader, destination.open("xb") as writer:
            while block := reader.read(4 * 1024 * 1024):
                copied.update(block)
                writer.write(block)
        if destination.stat().st_size != row["size_bytes"] or copied.hexdigest() != row["sha256"]:
            raise ValueError(f"reference file changed or differs from pinned bytes: {row['path']}")
    derived = []
    for relative, template in zip(CONFIGS, TEMPLATES):
        path = target / relative
        original = path.read_bytes()
        payload = _derived(target, relative, snapshot)
        path.write_bytes(payload)
        derived.append({"path": relative, "template": template,
                        "reference_sha256": hashlib.sha256(original).hexdigest(),
                        "deployed_sha256": hashlib.sha256(payload).hexdigest(),
                        "size_bytes": len(payload), "transform": "native template ASSETS_PATH expansion only"})
    manifest = {"schema_version": DEPLOYMENT_SCHEMA, "root": str(target),
                "reference_snapshot_sha256": digest(SNAPSHOT_FILE),
                "reference_inventory_sha256": snapshot["inventory_sha256"],
                "native_source_revision": None, "derived_files": derived,
                "limitations": "file identity only; no native reset, asset-release completeness or loaded-memory attestation"}
    with (target / "deployment.json").open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return verify(target, digest(target / "deployment.json"))


def verify(root: Path, manifest_sha256: str) -> dict:
    if (not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64
            or any(c not in "0123456789abcdef" for c in manifest_sha256)):
        raise ValueError("deployment manifest SHA-256 must be 64 lowercase hexadecimal characters")
    original_root = root.absolute()
    root = root.resolve(strict=True)
    if root != original_root or root.is_symlink():
        raise ValueError("deployment root must be canonical and not a symlink")
    manifest_path = _regular(root, "deployment.json")
    if digest(manifest_path) != manifest_sha256:
        raise ValueError("deployment manifest digest mismatch")
    manifest = _json(manifest_path)
    snapshot = reference_snapshot()
    if (manifest.get("schema_version") != DEPLOYMENT_SCHEMA or manifest.get("root") != str(root)
            or manifest.get("reference_snapshot_sha256") != digest(SNAPSHOT_FILE)
            or manifest.get("reference_inventory_sha256") != snapshot["inventory_sha256"]
            or manifest.get("native_source_revision") is not None):
        raise ValueError("deployment identity changed")
    rows = {row["path"]: row for row in snapshot["files"]}
    expected_derived = []
    for relative, template in zip(CONFIGS, TEMPLATES):
        payload = _derived(root, relative, snapshot)
        expected_derived.append({"path": relative, "template": template,
                                 "reference_sha256": rows[relative]["sha256"],
                                 "deployed_sha256": hashlib.sha256(payload).hexdigest(),
                                 "size_bytes": len(payload), "transform": "native template ASSETS_PATH expansion only"})
    if manifest.get("derived_files") != expected_derived:
        raise ValueError("unexpected deployment transformation")
    expected = {relative: dict(row) for relative, row in rows.items()}
    for row in expected_derived:
        expected[row["path"]] = {"path": row["path"], "size_bytes": row["size_bytes"],
                                  "sha256": row["deployed_sha256"]}
    actual = set()
    for directory, children, names in os.walk(root, followlinks=False):
        for child in children:
            if (Path(directory) / child).is_symlink():
                raise ValueError("unverified deployment directory symlink")
        for name in names:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if relative != "deployment.json":
                actual.add(relative)
    if actual != set(expected):
        raise ValueError("deployment file set changed; caches, overrides and extra files are not allowed")
    for relative, row in expected.items():
        path = _regular(root, relative)
        if path.stat().st_size != row["size_bytes"] or digest(path) != row["sha256"]:
            raise ValueError(f"deployment content changed: {relative}")
    return {"deployment_root": str(root), "deployment_manifest_sha256": manifest_sha256,
            "reference_snapshot_sha256": digest(SNAPSHOT_FILE),
            "reference_inventory_sha256": snapshot["inventory_sha256"],
            "native_source_revision": None, "file_count": len(expected),
            "total_bytes": sum(row["size_bytes"] for row in expected.values()),
            "derived_files": expected_derived, "status": "content_verified_not_native_validated"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="materialize a new matching clean-task deployment")
    prepare_parser.add_argument("--reference-root", type=Path, required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    check_parser = subparsers.add_parser("check", help="hash files only; no SIM imports/reset")
    check_parser.add_argument("--root", type=Path, required=True)
    check_parser.add_argument("--manifest-sha256", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "prepare":
        result = prepare(arguments.reference_root, arguments.output_dir)
    else:
        result = verify(arguments.root, arguments.manifest_sha256)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
