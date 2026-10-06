"""Pinned, additive deployment for the optional RGB/proprioception EEF track.

Preparation copies only explicitly verified native source and asset bytes into a
new owned directory. It never launches Isaac, accepts a licence, changes an
upstream checkout or rewrites an existing runtime. This is not asset closure or
renderer parity: the four historical material exceptions remain explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

from benchmarks.simBenchmarks.RoboDojo.environment.asset_reference import (
    KNOWN_UNRESOLVED, load_reference, verify_reference_document,
)

SCHEMA = "starvla-rsi.robodojo-reference-eef-runtime/v1"
PIN_FILE = Path(__file__).with_name("reference_eef_snapshot.json")
VERSIONS = {"isaacsim": "5.1.0.0", "isaaclab": "0.54.3", "torch": "2.7.0+cu128",
            "numpy": "1.26.0", "scipy": "1.15.3", "gymnasium": "1.2.1", "av": "18.1.0"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    before = path.stat()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("deployment file changed during hashing")
    return digest.hexdigest()


def canonical_digest(rows) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def pins() -> dict:
    return json.loads(PIN_FILE.read_text())


def safe_relative(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if (not isinstance(name, str) or not name or name == "." or "\\" in name
            or p.is_absolute() or ".." in p.parts or p.as_posix() != name):
        raise ValueError("unsafe deployment relative path")
    return p


def inventory(root: Path, *, exclude=()) -> list[dict]:
    """Exact regular-file tree; excluded top-level trees are separately bound."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("deployment root must be a regular directory")
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] in exclude:
            continue
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"nonregular deployment entry: {relative}")
        if path.is_file():
            rows.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    return rows


def verify_rows(root: Path, rows: list[dict], *, exclude=()) -> None:
    for row in rows:
        safe_relative(row["path"])
    if inventory(root, exclude=exclude) != rows:
        raise ValueError("deployment file inventory or bytes changed")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).strip()


def verify_dependencies(document: dict) -> None:
    expected = pins()
    isaac = Path(document["isaaclab_root"])
    curobo = Path(document["curobo_root"])
    for root, revision in ((isaac, expected["isaaclab_revision"]),
                           (curobo, expected["curobo_revision"])):
        if not root.is_absolute() or root.resolve() != root or root.is_symlink():
            raise ValueError("dependency root must be canonical")
        if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root or git(root, "rev-parse", "HEAD") != revision:
            raise ValueError("native dependency source revision changed")
    if git(isaac, "diff", "--name-only", "HEAD") != "apps/isaaclab.python.kit":
        raise ValueError("IsaacLab patch set changed")
    if sha(isaac / "apps/isaaclab.python.kit") != expected["isaaclab_patch_sha256"]:
        raise ValueError("IsaacLab URDF importer patch bytes changed")
    if git(curobo, "diff", "--name-only", "HEAD"):
        raise ValueError("cuRobo dependency source changed")
    for name in ("python", "recording_support"):
        path = Path(document[name])
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError("runtime dependency path must be canonical")
    if not Path(document["python"]).is_file():
        raise ValueError("native interpreter missing")
    verify_rows(Path(document["recording_support"]), document["recording_support_files"])


def verify_layouts(source: Path) -> list[dict]:
    expected = pins()
    directory = source / "Assets/Eval_Layout/RoboDojo/arx_x5/0"
    paths = [directory / f"classify_objects_{i}.json" for i in range(55)]
    import re
    actual = sorted(p.name for p in directory.iterdir() if re.fullmatch(r"classify_objects_\d+\.json", p.name))
    if actual != sorted(p.name for p in paths):
        raise ValueError("classify layout candidate set changed")
    rows = [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha(p)} for p in paths]
    if canonical_digest(rows) != expected["classify_layout_inventory_sha256"]:
        raise ValueError("classify layout candidate hashes changed")
    for row in expected["layouts"]:
        if rows[row["layout_id"]]["sha256"] != row["sha256"]:
            raise ValueError("selected public panel layout changed")
    return rows


def load_runtime(manifest: Path, expected_sha256: str) -> dict:
    if (manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 8 * 1024 * 1024
            or sha(manifest) != expected_sha256):
        raise ValueError("runtime manifest hash or file changed")
    document = json.loads(manifest.read_text())
    expected = pins()
    if (document.get("schema") != SCHEMA or document.get("native_revision") != expected["native_revision"]
            or document.get("asset_parent_sha256") != expected["asset_parent_sha256"]
            or document.get("additional_asset_inventory_sha256") != expected["additional_asset_inventory_sha256"]
            or document.get("allowed_unresolved") != list(KNOWN_UNRESOLVED)
            or document.get("versions") != VERSIONS or document.get("complete_assets") is not False):
        raise ValueError("runtime manifest protocol changed")
    return document


def verify_runtime(manifest: Path, expected_sha256: str) -> dict:
    document = load_runtime(manifest, expected_sha256)
    root = manifest.parent.resolve()
    source = root / "RoboDojo"
    expected = pins()
    verify_rows(source, document["source_files"], exclude=("Assets",))
    for row in expected["source_files"]:
        if sha(source / row["path"]) != row["sha256"]:
            raise ValueError(f"public native source pin changed: {row['path']}")
    parent = load_reference(root / "asset_parent_manifest.json", expected["asset_parent_sha256"])
    base_rows = parent["files"]
    additions = document["additional_asset_files"]
    if canonical_digest(additions) != expected["additional_asset_inventory_sha256"]:
        raise ValueError("additional reference asset bytes changed")
    expected_rows = sorted(base_rows + additions, key=lambda row: row["path"])
    if len({row["path"] for row in expected_rows}) != len(expected_rows) or document["asset_files"] != expected_rows:
        raise ValueError("asset union differs from the two pinned inventories")
    verify_rows(source / "Assets", expected_rows)
    verify_layouts(source)
    verify_dependencies(document)
    return document


def _write_new(path: Path, document: dict) -> None:
    with path.open("x") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write("\n")


def prepare(*, native_repository: Path, base_assets: Path, additional_assets: Path,
            asset_parent_manifest: Path, runtime_root: Path, python: Path,
            isaaclab_root: Path, curobo_root: Path, recording_support: Path,
            archive: Path, reference_assets: Path | None = None) -> dict:
    """Create-only preparation; all failed/partial outputs are retained."""
    expected = pins()
    runtime_root = runtime_root.absolute()
    archive = archive.absolute()
    if runtime_root.exists() or runtime_root.is_symlink() or archive.exists() or archive.is_symlink():
        raise ValueError("runtime and durable archive must both be new destinations")
    if not runtime_root.parent.is_dir() or not archive.parent.is_dir():
        raise ValueError("create destination parents explicitly before preparation")
    parent = load_reference(asset_parent_manifest, expected["asset_parent_sha256"])
    verify_rows(base_assets.resolve(), parent["files"])
    if reference_assets is not None:
        verify_reference_document(parent, base_assets, reference_assets=reference_assets)
    additions = []
    for relative in expected["additional_asset_leaves"]:
        for row in inventory(additional_assets.resolve() / relative):
            additions.append({**row, "path": relative + "/" + row["path"]})
    additions.sort(key=lambda row: row["path"])
    if canonical_digest(additions) != expected["additional_asset_inventory_sha256"]:
        raise ValueError("additional reference assets differ from the frozen 54-file inventory")
    document = {"schema": SCHEMA, "native_revision": expected["native_revision"],
        "python": str(python.resolve()), "isaaclab_root": str(isaaclab_root.resolve()),
        "curobo_root": str(curobo_root.resolve()), "recording_support": str(recording_support.resolve()),
        "recording_support_files": inventory(recording_support.resolve()),
        "versions": VERSIONS, "asset_parent_sha256": expected["asset_parent_sha256"],
        "additional_asset_inventory_sha256": expected["additional_asset_inventory_sha256"],
        "additional_asset_files": additions, "allowed_unresolved": list(KNOWN_UNRESOLVED),
        "complete_assets": False, "native_execution": False,
        "limitations": ["Historical own asset bytes plus 54 exact selected reference files.",
            "Named inherited missing/remote materials remain qualified, not full asset or renderer parity.",
            "Interpreter/dependencies are external; source and asset archive is not a complete environment."]}
    # Do not copy native environments, acceptance markers, caches or credentials.
    verify_dependencies(document)
    if git(native_repository, "rev-parse", expected["native_revision"]) != expected["native_revision"]:
        raise ValueError("required native source commit unavailable")
    payload = subprocess.check_output(["git", "-C", str(native_repository), "archive", expected["native_revision"]])
    runtime_root.mkdir(mode=0o700)
    source = runtime_root / "RoboDojo"
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(payload)) as bundle:
        for entry in bundle:
            name = entry.name.rstrip("/")
            relative = safe_relative(name)
            target = source / relative
            if entry.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif entry.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(entry) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(entry.mode & 0o755)
            else:
                raise ValueError("native archive contains a link or special file")
    document["source_files"] = inventory(source, exclude=("Assets",))
    assets = source / "Assets"
    assets.mkdir(exist_ok=False)
    for origin, rows in ((base_assets.resolve(), parent["files"]), (additional_assets.resolve(), additions)):
        for row in rows:
            target = assets / safe_relative(row["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            with (origin / row["path"]).open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            if sha(target) != row["sha256"]:
                raise ValueError("asset changed while copying; partial deployment retained")
    document["asset_files"] = sorted(parent["files"] + additions, key=lambda row: row["path"])
    with asset_parent_manifest.open("rb") as src, (runtime_root / "asset_parent_manifest.json").open("xb") as dst:
        shutil.copyfileobj(src, dst)
    manifest = runtime_root / "runtime_manifest.json"
    _write_new(manifest, document)
    manifest_sha = sha(manifest)
    verify_runtime(manifest, manifest_sha)
    with archive.open("xb") as stream, tarfile.open(fileobj=stream, mode="w:gz") as bundle:
        bundle.add(runtime_root, arcname=runtime_root.name, recursive=True)
    result = {"runtime_root": str(runtime_root), "runtime_manifest": str(manifest),
        "runtime_manifest_sha256": manifest_sha, "archive": str(archive), "archive_sha256": sha(archive),
        "native_source_files": len(document["source_files"]), "asset_files": len(document["asset_files"]),
        "reference_assets": str(reference_assets.resolve()) if reference_assets is not None else None,
        "reference_assets_verified": reference_assets is not None,
        "native_execution": False, "original_trees_modified": False}
    _write_new(runtime_root.parent / (runtime_root.name + "-preparation.json"), result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("prepare")
    for name in ("native-repository", "base-assets", "additional-assets", "asset-parent-manifest",
                 "runtime-root", "python", "isaaclab-root", "curobo-root", "recording-support", "archive"):
        build.add_argument("--" + name, required=True, type=Path)
    build.add_argument("--reference-assets", type=Path,
        help="Optional relocated counterpart to verify against the pinned parent reference inventory; "
             "does not rewrite historical manifest provenance or supply runtime assets.")
    check = sub.add_parser("verify")
    check.add_argument("--manifest", required=True, type=Path)
    check.add_argument("--sha256", required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "prepare":
        result = prepare(**args)
    else:
        document = verify_runtime(args["manifest"], args["sha256"])
        result = {"verified": True, "asset_files": len(document["asset_files"]), "native_execution": False}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
