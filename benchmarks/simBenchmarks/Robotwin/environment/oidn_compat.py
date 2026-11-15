"""Explicit, content-pinned SAPIEN overlay for the OIDN 2.3.3 CUDA track.

This copies only selected files to a NEW owned directory. The original Python
environment, native task code, shaders, physics and scorer are never patched.
Other dependencies remain read-only references to the selected base environment.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile

from benchkit.errors import CompatibilityError
from benchmarks.simBenchmarks.Robotwin.environment.deployment import digest

TRACK = "oidn_2_3_3_cuda_v1"
SNAPSHOT = Path(__file__).with_name("oidn_2_3_3_snapshot.json")
SNAPSHOT_SHA256 = "eeba6582e55741106684a4481951a8354148a43e17b22a1d35595a0428a14c13"
LOADER_NOTICE = b"# RSI compatibility overlay: OIDN loader paths only, 2.0.1 to 2.3.3.\n"
RECORD = "sapien-3.0.0b1.dist-info/RECORD"
RECEIPT = "rsi-oidn-compatibility.json"


def snapshot() -> dict:
    if digest(SNAPSHOT) != SNAPSHOT_SHA256:
        raise CompatibilityError("packaged OIDN compatibility snapshot changed")
    return json.loads(SNAPSHOT.read_text())


def package_rows(base_rows) -> list[dict]:
    """Preserve all original SAPIEN bytes except its loader and OIDN directory."""
    pin = snapshot()
    kept = [dict(row) for row in base_rows
            if row["path"] != "sapien/_oidn_tricks.py"
            and not row["path"].startswith("sapien/oidn_library/")]
    replacements = [pin["derived_loader"], *pin["release_files"]]
    return sorted(kept + [{key: row[key] for key in ("path", "size_bytes", "sha256")}
                         for row in replacements], key=lambda row: row["path"])


def all_rows(base_rows) -> list[dict]:
    return sorted(package_rows(base_rows) + snapshot()["unchanged_sapien_distribution_files"],
                  key=lambda row: row["path"])


def record_bytes(rows) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    for row in sorted(rows, key=lambda row: row["path"]):
        encoded = base64.urlsafe_b64encode(bytes.fromhex(row["sha256"])).decode().rstrip("=")
        writer.writerow([row["path"], "sha256=" + encoded, row["size_bytes"]])
    writer.writerow([RECORD, "", ""])
    return stream.getvalue().encode()


def _regular(path: Path, row: dict) -> None:
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != row["size_bytes"]
            or digest(path) != row["sha256"]):
        raise CompatibilityError(f"OIDN compatibility file mismatch: {row['path']}")
    if path.resolve() != path.absolute():
        raise CompatibilityError(f"symlinked OIDN compatibility path: {row['path']}")


def _base_rows() -> list[dict]:
    from benchmarks.simBenchmarks.Robotwin.environment import runtime
    pin = snapshot()
    if (pin["base_runtime_snapshot_sha256"] != runtime.RUNTIME_SNAPSHOT_SHA256
            or digest(runtime.RUNTIME_SNAPSHOT) != runtime.RUNTIME_SNAPSHOT_SHA256):
        raise CompatibilityError("original RoboTwin runtime snapshot changed")
    return json.loads(runtime.RUNTIME_SNAPSHOT.read_text())["packages"]["sapien"]["files"]


def _loaded_native_paths() -> set[str]:
    if sys.platform != "linux":
        raise CompatibilityError("OIDN CUDA compatibility track requires Linux")
    maps = Path("/proc/self/maps").read_text()
    return {line.split()[-1] for line in maps.splitlines()
            if any(token in line for token in ("OpenImageDenoise", "libsapien.so", "libsvulkan2.so", "libsimsense-"))}


def reject_preloaded_runtime() -> None:
    if any(name == "sapien" or name.startswith("sapien.") for name in sys.modules):
        raise CompatibilityError("start the OIDN compatibility service in a fresh process; SAPIEN is already imported")
    if _loaded_native_paths():
        raise CompatibilityError("start a fresh process; SAPIEN/OIDN native libraries are already loaded")


def verify_overlay(distribution, base_rows) -> dict:
    root = Path(distribution.locate_file("")).absolute()
    rows = all_rows(base_rows)
    expected = {row["path"] for row in rows}
    # The dedicated overlay is not a general-purpose site-packages directory.
    # No extra native libraries, Python overrides, bytecode or .pth files enter it.
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise CompatibilityError("OIDN overlay must not contain symlinks")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected | {RECORD, RECEIPT}:
        raise CompatibilityError("OIDN overlay file set differs from its reviewed closure")
    if {str(path) for path in distribution.files or ()} != expected | {RECORD}:
        raise CompatibilityError("OIDN overlay distribution RECORD inventory differs")
    if (root / RECORD).read_bytes() != record_bytes(rows):
        raise CompatibilityError("OIDN overlay distribution RECORD content differs")
    for row in rows:
        _regular(root / row["path"], row)
    spec = importlib.util.find_spec("sapien")
    if spec is None or spec.origin != str(root / "sapien/__init__.py"):
        raise CompatibilityError("SAPIEN import would not use the verified compatibility overlay")
    receipt = json.loads((root / RECEIPT).read_text())
    if (receipt.get("renderer_runtime") != TRACK
            or receipt.get("compatibility_snapshot_sha256") != SNAPSHOT_SHA256
            or receipt.get("release_sha256") != snapshot()["release_sha256"]):
        raise CompatibilityError("OIDN overlay preparation receipt differs")
    reject_preloaded_runtime()
    return {"renderer_runtime": TRACK, "oidn_version": "2.3.3", "overlay_root": str(root),
            "compatibility_snapshot_sha256": SNAPSHOT_SHA256,
            "selected_distribution_files": len(rows), "record_sha256": digest(root / RECORD),
            "scope": "owned SAPIEN/OIDN overlay; other dependencies shared read-only; no driver/JIT/loaded-memory attestation"}


def verify_loaded(root: Path, *, require_cuda_plugin: bool) -> dict:
    """Check the paths actually mapped after import/setup, without stepping SIM."""
    pin = snapshot()
    allowed = {str((root / row["path"]).absolute()) for row in
               pin["release_files"] + pin["unchanged_sapien_distribution_files"]
               if ".so" in row["path"]}
    required = {str(root / "sapien/oidn_library" / name) for name in
                ("libOpenImageDenoise.so.2.3.3", "libOpenImageDenoise_core.so.2.3.3")}
    required.update(str(root / row["path"]) for row in pin["unchanged_sapien_distribution_files"]
                    if row["path"].startswith("sapien.libs/"))
    if require_cuda_plugin:
        required.add(str(root / "sapien/oidn_library/libOpenImageDenoise_device_cuda.so.2.3.3"))
    actual = _loaded_native_paths()
    if not required.issubset(actual) or not actual.issubset(allowed):
        raise CompatibilityError("loaded SAPIEN/OIDN library paths do not match the selected compatibility track")
    loaded = sys.modules.get("sapien")
    if loaded is None or getattr(loaded, "__file__", None) != str(root / "sapien/__init__.py"):
        raise CompatibilityError("loaded SAPIEN module does not match the compatibility overlay")
    return {"loaded_native_library_paths": sorted(actual),
            "cuda_plugin_loaded": str(root / "sapien/oidn_library/libOpenImageDenoise_device_cuda.so.2.3.3") in actual,
            "limitation": "path verification is not loaded-memory or successful-denoising attestation"}


def prepare(archive: Path, output: Path) -> dict:
    """Copy a verified base distribution plus exact official CUDA release files."""
    from benchmarks.simBenchmarks.Robotwin.environment import runtime
    pin = snapshot()
    if (not output.is_absolute() or ".." in output.parts or output.exists()
            or output.is_symlink() or output.resolve() != output):
        raise ValueError("OIDN overlay output must be a new canonical absolute directory")
    if (archive.is_symlink() or not archive.is_file()
            or archive.stat().st_size != pin["release_size_bytes"] or digest(archive) != pin["release_sha256"]):
        raise CompatibilityError("OIDN archive does not match the pinned official release")
    runtime.verify_runtime()  # Read-only original track; no native imports.
    base_rows = _base_rows()
    distribution = importlib.metadata.distribution("sapien")
    for row in pin["unchanged_sapien_distribution_files"]:
        _regular(Path(distribution.locate_file(row["path"])), row)
    original_loader = Path(distribution.locate_file("sapien/_oidn_tricks.py")).read_bytes()
    if original_loader.count(b"2.0.1") != 2:
        raise CompatibilityError("unexpected original SAPIEN OIDN loader")
    loader = LOADER_NOTICE + original_loader.replace(b"2.0.1", b"2.3.3")
    if hashlib.sha256(loader).hexdigest() != pin["derived_loader"]["sha256"]:
        raise CompatibilityError("derived SAPIEN OIDN loader differs")
    rows = all_rows(base_rows)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len({item.name for item in members}) != len(members):
            raise CompatibilityError("OIDN archive contains duplicate paths")
        payloads = {}
        for row in pin["release_files"]:
            member = bundle.getmember(pin["archive_prefix"] + row["archive_path"])
            if not member.isfile() or member.size != row["size_bytes"]:
                raise CompatibilityError("OIDN release member type/size differs")
            with bundle.extractfile(member) as stream:
                data = stream.read(row["size_bytes"] + 1)
            if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise CompatibilityError("OIDN release member content differs")
            payloads[row["path"]] = data
    # No extractall: only fixed, content-verified regular files are materialized.
    output.mkdir(parents=True, exist_ok=False)
    payloads["sapien/_oidn_tricks.py"] = loader
    for row in rows:
        destination = output / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if row["path"] in payloads:
            with destination.open("xb") as stream:
                stream.write(payloads[row["path"]])
        else:
            shutil.copyfile(distribution.locate_file(row["path"]), destination)
        _regular(destination, row)
    with (output / RECORD).open("xb") as stream:
        stream.write(record_bytes(rows))
    receipt = {"renderer_runtime": TRACK, "compatibility_snapshot_sha256": SNAPSHOT_SHA256,
               "base_runtime_snapshot_sha256": runtime.RUNTIME_SNAPSHOT_SHA256,
               "base_distribution_root": str(Path(distribution.locate_file("")).absolute()),
               "overlay_root": str(output), "release_sha256": pin["release_sha256"],
               "selected_distribution_files": len(rows), "record_sha256": digest(output / RECORD),
               "native_scenes": 0, "native_resets": 0, "native_controls": 0, "model_calls": 0}
    with (output / RECEIPT).open("x") as stream:
        stream.write(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.archive, args.output_dir), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
