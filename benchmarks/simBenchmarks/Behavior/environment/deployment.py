"""File/metadata-only readiness capture; never imports or initializes the SIM.

Asset receipts establish archive/extraction provenance, not full live-asset
attestation. Selected task/robot files are independently rehashed at reset.
"""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from benchmarks.simBenchmarks.Behavior.bench_server.protocol import REVISION, TASK, TASKS, TASK_METADATA_SHA256, task_definition

ARCHIVES = {
    "behavior-1k-assets": "09e9fce600f841dc611aa96c0b1b9f9074f56f0e67898b37b39bd00c38a0095e",
    "omnigibson-robot-assets": "3d813b2181e0581cf2300a40892de70f8475fe59346ceeea4fb9bf7ff21ce126",
    "2026-challenge-task-instances": "d4ac3d72dd585178e85d542f28d1b48233b886c80e196e2f9d3aa5993ba21f81",
}
ASSET_FILES = {
    "2026-challenge-task-instances/metadata/task.jsonl": TASK_METADATA_SHA256,
    "omnigibson-robot-assets/models/r1pro/r1pro.yaml": "63f841cffd5c499102416a797a22fa5b4cbaf146539df7dde8a4a1053e2326f1",
    "omnigibson-robot-assets/models/r1pro/urdf/r1pro.urdf": "b0d76760cbedfbcbe1ddc280380dd5f497bbca380313bc096d7239a2c50dae61",
    "2026-challenge-task-instances/scene_test/public/house_double_floor_lower/json/house_double_floor_lower_task_turning_on_radio_instances/house_double_floor_lower_task_turning_on_radio_0_301_template-tro_state.json": "30a0fe101da1cbf6eb3683d3f9da716399ccd7409974b459dc12a580d2c8ad13",
}
PACKAGES = ("omnigibson", "bddl", "joylo", "torch", "numpy", "isaacsim", "omegaconf", "hydra-core", "imageio", "imageio-ffmpeg")


def selected_asset_files(task=TASK):
    selected = task_definition(task)
    common = {name: sha for name, sha in ASSET_FILES.items() if name != task_definition().instance_path}
    return {**common, selected.instance_path: selected.instance_sha256}


def validate_manifest_task(recorded, task=TASK):
    """Bind the selected case before spawning/importing the native runtime."""
    selected = task_definition(task)
    if selected.name == TASK:
        if recorded.get("schema") != "behavior2026-deployment/v1" or "task" in recorded:
            raise ValueError("radio requires its original deployment v1")
    elif recorded.get("schema") != "behavior2026-deployment/v2" or recorded.get("task") != selected.name:
        raise ValueError("selected task requires its matching deployment v2")
    if recorded.get("selected_asset_files") != selected_asset_files(task):
        raise ValueError("deployment selected task asset identities differ")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("explicit absolute deployment paths required")
    return path


def source_identity(source):
    source = absolute(source)
    def git(*args):
        return subprocess.run(["git", "-c", "safe.directory=" + str(source), "-C", str(source), *args],
                              check=True, capture_output=True, timeout=60).stdout
    if git("rev-parse", "HEAD").decode().strip() != REVISION:
        raise ValueError("BEHAVIOR source revision differs")
    rows = []
    roots = ("OmniGibson/omnigibson", "bddl3/bddl", "joylo/gello")
    for entry in git("ls-tree", "-rz", REVISION, "--", *roots).split(b"\0"):
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        mode, kind, expected = meta.decode().split()
        relative = name.decode()
        path = source / relative
        if kind != "blob" or mode not in ("100644", "100755") or path.is_symlink() or not path.is_file():
            raise ValueError("unsupported or missing native source file")
        data = path.read_bytes()
        if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != expected:
            raise ValueError("modified native source: " + relative)
        rows.append(relative)
    if not rows:
        raise ValueError("empty native source inventory")
    # -B only disables writes: stale or untracked bytecode may still be loaded.
    known = set(rows)
    for root in roots:
        for path in (source / root).rglob("*"):
            if path.is_symlink():
                raise ValueError("native source symlink is not part of this deployment")
            if path.is_file() and path.suffix in (".py", ".pyc", ".pyo", ".so", ".yaml", ".json") and path.relative_to(source).as_posix() not in known:
                raise ValueError("untracked executable/config native source: " + str(path))
    return {"revision": REVISION, "tracked_files_verified": len(rows), "roots": list(roots)}


def runtime_identity(source):
    source = absolute(source)
    origins = {}
    for name, relative in {"omnigibson": "OmniGibson/omnigibson/__init__.py", "bddl": "bddl3/bddl/__init__.py", "gello": "joylo/gello/__init__.py"}.items():
        spec = importlib.util.find_spec(name)  # top-level only: does not execute package
        if spec is None or spec.origin is None or Path(spec.origin).resolve() != (source / relative).resolve():
            raise ValueError("native module origin differs: " + name)
        origins[name] = str(Path(spec.origin).resolve())
    versions = {name: importlib.metadata.version(name) for name in PACKAGES}
    if not versions["isaacsim"].startswith("5.1.") or sys.version_info[:2] != (3, 11):
        raise ValueError("native runtime requires Python3.11 and Isaac Sim5.1")
    if not Path(sys.executable).is_file() or not Path(sys.base_prefix).is_dir():
        raise ValueError("runtime base or interpreter unavailable on current node")
    return {"python": sys.version.split()[0], "executable": str(Path(sys.executable).absolute()),
            "executable_sha256": digest(sys.executable), "base_prefix": sys.base_prefix,
            "versions": versions, "origins": origins}


def asset_identity(data_root, receipts, task=TASK):
    root = absolute(data_root)
    if set(receipts) != set(ARCHIVES):
        raise ValueError("all three archive extraction receipts required")
    result = {}
    for name, expected in ARCHIVES.items():
        path = absolute(receipts[name])
        receipt = json.loads(path.read_text())
        if (receipt.get("archive_sha256") != expected or receipt.get("source_commit") != REVISION
                or Path(receipt.get("target", "")).resolve() != (root / name).resolve()
                or not (root / name).is_dir()):
            raise ValueError("asset extraction receipt differs: " + name)
        result[name] = {"path": str(path), "sha256": digest(path)}
    for name, expected in selected_asset_files(task).items():
        if digest(root / name) != expected:
            raise ValueError("selected native asset differs: " + name)
    return result


def capture(source_root, data_root, receipts, task=TASK):
    selected = task_definition(task)
    source = source_identity(source_root)
    runtime = runtime_identity(source_root)
    assets = asset_identity(data_root, receipts, selected.name)
    record = {"schema": "behavior2026-deployment/v1", "source_root": str(absolute(source_root)),
            "data_root": str(absolute(data_root)), "source": source, "runtime": runtime,
            "asset_receipts": assets, "selected_asset_files": selected_asset_files(selected.name),
            "asset_attestation_scope": "verified archive extraction receipts and selected files; not all live asset bytes"}
    if selected.name != TASK:
        record.update(schema="behavior2026-deployment/v2", task=selected.name)
    return record


def verify(path, expected_sha256, task=TASK):
    path = absolute(path)
    if digest(path) != expected_sha256:
        raise ValueError("deployment manifest hash differs")
    recorded = json.loads(path.read_text())
    validate_manifest_task(recorded, task)
    current = capture(recorded["source_root"], recorded["data_root"],
                      {name: row["path"] for name, row in recorded["asset_receipts"].items()}, task)
    if current != recorded:
        raise ValueError("native deployment changed since capture")
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--receipts", required=True, help="JSON mapping asset directory name to extraction receipt path")
    parser.add_argument("--output", required=True)
    parser.add_argument("--task", choices=tuple(TASKS), default=TASK,
                        help="fixed public-index-0 task; radio keeps deployment v1, selected new tasks use v2")
    args = parser.parse_args()
    record = capture(args.source_root, args.data_root, json.loads(Path(args.receipts).read_text()), args.task)
    with absolute(args.output).open("x") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
    print(digest(args.output))


if __name__ == "__main__":
    main()
