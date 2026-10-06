"""File-only preparation of a new owned DOMINO deployment; never starts a SIM.

Inputs are operator-supplied, existing source/assets. Runtime capture records
the selected compatibility environment, not native Torch2.4.1 parity. No pip,
installer, global configuration, expert or model invocation is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

from benchmarks.simBenchmarks.DOMINO.bench_server.protocol import (
    NATIVE_REVISION, CUROBO_REVISION, RUNTIME_VERSIONS,
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inventory(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"deployment source must not contain symlinks: {path}")
        if path.is_file():
            rows.append({"path": path.relative_to(root).as_posix(),
                         "size_bytes": path.stat().st_size, "sha256": digest(path)})
    return rows


def verify_rows(root: Path, rows: list[dict], *, exact: bool = True) -> None:
    names = []
    for row in rows:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("unsafe inventory path")
        path = root / relative
        if (any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent)
                or not path.resolve().is_relative_to(root.resolve())
                or not path.is_file() or path.stat().st_size != row["size_bytes"]
                or digest(path) != row["sha256"]):
            raise ValueError(f"content identity differs: {relative}")
        names.append(relative.as_posix())
    if len(names) != len(set(names)):
        raise ValueError("duplicate inventory path")
    if exact:
        actual = [row["path"] for row in inventory(root)]
        if sorted(names) != sorted(actual):
            raise ValueError("unrecorded or missing deployment files")


def verify_git_files(source: Path, git_reference: Path, revision: str, prefixes: tuple[str, ...]) -> dict:
    """Compare bytes to public Git blob identities, including archived sources."""
    result = subprocess.run(["git", "-c", "safe.directory=" + str(git_reference),
                             "-C", str(git_reference), "ls-tree", "-rz", revision,
                             "--", *prefixes], check=True, capture_output=True)
    paths = []
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        metadata, filename = item.split(b"\t", 1)
        mode, kind, expected = metadata.decode().split()
        name = filename.decode()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError("unsupported upstream source entry")
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing upstream file: {name}")
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected:
            raise ValueError(f"upstream source differs: {name}")
        paths.append(name)
    if not paths:
        raise ValueError("empty upstream source identity")
    return {"revision": revision, "git_blob_files_verified": len(paths), "verified_paths": paths}


def capture_runtime() -> dict:
    versions = {}
    packages = {}
    for name, expected in RUNTIME_VERSIONS.items():
        distribution = importlib.metadata.distribution(name)
        if distribution.version != expected:
            raise ValueError(f"{name} differs from declared SM120 compatibility runtime")
        versions[name] = distribution.version
        if name in ("sapien", "mplib", "toppra"):
            root = Path(distribution.locate_file(name)).resolve()
            packages[name] = {"root": str(root), "files": inventory(root)}
    return {"python": sys.version.split()[0], "versions": versions, "packages": packages,
            "scope": "listed versions and SAPIEN/MPLib/TOPPRA files, not all dependencies or loaded-memory attestation"}


def expand_asset_root_template(template: str, deployment_root: Path) -> str:
    """Match native script/update_embodiment_config_path.py, not shell expansion.

    Despite its name, ASSETS_PATH is the repository root; the pinned templates
    themselves append /assets. Replace the whole placeholder, braces included.
    """
    if not deployment_root.is_absolute():
        raise ValueError("asset template requires an absolute deployment root")
    if "${ASSETS_PATH}" not in template and "$ASSETS_PATH" not in template:
        raise ValueError("native CuRobo asset-root placeholder missing")
    return template.replace("${ASSETS_PATH}", str(deployment_root)).replace(
        "$ASSETS_PATH", str(deployment_root))


def verify_curobo_asset_paths(root: Path, config: dict) -> dict:
    """Reject malformed/out-of-tree/missing materialized native config inputs."""
    kinematics = config["robot_cfg"]["kinematics"]
    verified = {}
    for key in ("urdf_path", "collision_spheres"):
        value = kinematics[key]
        if not isinstance(value, str) or "$" in value:
            raise ValueError(f"unexpanded CuRobo asset path: {key}")
        path = Path(value)
        if (not path.is_absolute() or ".." in path.parts or not path.is_file()
                or not path.resolve().is_relative_to((root / "assets").resolve())):
            raise ValueError(f"missing or out-of-deployment CuRobo asset: {key}")
        verified[key] = str(path)
    return verified


def prepare(source: Path, source_git: Path, assets: Path, curobo: Path,
            curobo_git: Path, destination: Path) -> dict:
    for path in (source, source_git, assets, curobo, curobo_git, destination):
        if not path.is_absolute():
            raise ValueError("all deployment inputs must be absolute paths")
    if destination.exists():
        raise ValueError("destination must be new; deployments are never merged or overwritten")
    source_identity = verify_git_files(source, source_git, NATIVE_REVISION,
                                      ("envs", "script", "task_config", "description", "LICENSE"))
    curobo_identity = verify_git_files(curobo, curobo_git, CUROBO_REVISION,
                                      ("src", "setup.py", "pyproject.toml", "setup.cfg", "LICENSE"))
    runtime = capture_runtime()
    destination.mkdir(parents=True, exist_ok=False)
    # Copy only verified Git entries, never arbitrary untracked source or .so.
    for name in source_identity["verified_paths"]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    for name in ("embodiments/aloha-agilex", "objects/050_bell", "objects/objaverse"):
        inventory(assets / name)  # Reject links before copytree could follow one.
        shutil.copytree(assets / name, destination / "assets" / name)
    if (assets / "objects/same.json").is_file():
        shutil.copy2(assets / "objects/same.json", destination / "assets/objects/same.json")
    for name in curobo_identity["verified_paths"]:
        target = destination / "envs/curobo" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(curobo / name, target)
    derived = []
    import yaml
    for side in ("left", "right"):
        name = f"assets/embodiments/aloha-agilex/curobo_{side}.yml"
        template = destination / f"assets/embodiments/aloha-agilex/curobo_{side}_tmp.yml"
        original = template.read_text()
        path = destination / name
        path.write_text(expand_asset_root_template(original, destination))
        asset_paths = verify_curobo_asset_paths(destination, yaml.safe_load(path.read_text()))
        derived.append({"path": name, "template_sha256": digest(template), "sha256": digest(path),
                        "transform": "native ${ASSETS_PATH}/$ASSETS_PATH expansion to deployment repository root only",
                        "verified_asset_paths": asset_paths})
    manifest = {"schema": "domino.owned-deployment/v1", "native_source": source_identity,
                "curobo_source": curobo_identity, "runtime": runtime, "derived_files": derived,
                "files": inventory(destination), "asset_scope": "aloha-agilex plus click_bell0/1; no full-suite asset claim"}
    (destination / "deployment.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"root": str(destination), "deployment_manifest_sha256": digest(destination / "deployment.json"),
            "source": {k: v for k, v in source_identity.items() if k != "verified_paths"},
            "curobo": {k: v for k, v in curobo_identity.items() if k != "verified_paths"}, "native_resets": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "source-git", "assets", "curobo", "curobo-git", "destination"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(**vars(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
