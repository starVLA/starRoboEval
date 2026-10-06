"""Check pinned OIDN CUDA device initialization, without importing a simulator.

This optional setup tool is not part of the episode's runtime source closure.
A successful device check does not establish native rendering correctness.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path

from benchmarks.simBenchmarks.Robotwin.environment.deployment import digest
from benchmarks.simBenchmarks.Robotwin.environment.runtime import (
    RUNTIME_SNAPSHOT, RUNTIME_SNAPSHOT_SHA256, BUNDLED_RENDERER, COMPAT_RENDERER, RENDERER_RUNTIMES)

LIBRARIES = (
    "libOpenImageDenoise_core.so.2.0.1",
    "libOpenImageDenoise.so.2.0.1",
    "libOpenImageDenoise_device_cuda.so.2.0.1",
)
API_REFERENCE = "https://github.com/RenderKit/oidn/blob/v2.0.1/include/OpenImageDenoise/oidn.h"


def library_names(renderer_runtime: str) -> tuple[str, ...]:
    if renderer_runtime == BUNDLED_RENDERER:
        return LIBRARIES
    if renderer_runtime == COMPAT_RENDERER:
        return tuple(name.replace("2.0.1", "2.3.3") for name in LIBRARIES)
    raise ValueError("unknown RoboTwin renderer runtime")


def verify_libraries(directory: Path, renderer_runtime: str = BUNDLED_RENDERER) -> dict:
    """Reject a different OIDN build before loading any native library."""
    if digest(RUNTIME_SNAPSHOT) != RUNTIME_SNAPSHOT_SHA256:
        raise ValueError("packaged RoboTwin runtime snapshot changed")
    snapshot = json.loads(RUNTIME_SNAPSHOT.read_text())
    expected = {Path(row["path"]).name: row for row in snapshot["packages"]["sapien"]["files"]
                if row["path"].startswith("sapien/oidn_library/")}
    if renderer_runtime == COMPAT_RENDERER:
        from benchmarks.simBenchmarks.Robotwin.environment import oidn_compat
        expected = {Path(row["path"]).name: row for row in oidn_compat.snapshot()["release_files"]
                    if row["path"].endswith(".so.2.3.3")}
    hashes = {}
    for name in library_names(renderer_runtime):
        path, row = directory / name, expected[name]
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or symlinked pinned OIDN library: {name}")
        if path.stat().st_size != row["size_bytes"]:
            raise ValueError(f"OIDN library size differs from runtime_snapshot.json: {name}")
        actual_digest = digest(path)
        if actual_digest != row["sha256"]:
            raise ValueError(f"OIDN library differs from runtime_snapshot.json: {name}")
        hashes[name] = actual_digest
    return hashes


def check_cuda_device(api) -> dict:
    """Use OIDN 2.0.1 C API, not a SAPIEN scene or denoising operation."""
    signatures = {
        "oidnGetNumPhysicalDevices": ([], ctypes.c_int),
        "oidnNewDevice": ([ctypes.c_int], ctypes.c_void_p),
        "oidnGetDeviceError": ([ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)], ctypes.c_int),
        "oidnCommitDevice": ([ctypes.c_void_p], None),
        "oidnReleaseDevice": ([ctypes.c_void_p], None),
    }
    for name, (arguments, result) in signatures.items():
        getattr(api, name).argtypes = arguments
        getattr(api, name).restype = result
    physical = api.oidnGetNumPhysicalDevices()
    handle = api.oidnNewDevice(3)  # OIDN_DEVICE_TYPE_CUDA, not automatic CPU fallback.
    message = ctypes.c_char_p()
    try:
        if handle:
            api.oidnCommitDevice(handle)
        code = api.oidnGetDeviceError(handle, ctypes.byref(message))
        return {"physical_devices": physical, "device_created": bool(handle),
                "error_code": code,
                "error_message": message.value.decode(errors="replace") if message.value else None,
                "passed": bool(handle) and code == 0}
    finally:
        if handle:
            api.oidnReleaseDevice(handle)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-directory", type=Path, required=True)
    parser.add_argument("--renderer-runtime", choices=RENDERER_RUNTIMES, default=BUNDLED_RENDERER)
    parser.add_argument("--output", type=Path, required=True, help="unused evaluator-private report path")
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before device work; never replace an existing diagnostic receipt.
    with args.output.open("x", encoding="utf-8") as stream:
        report = {"kind": "robotwin-oidn-2.0.1-cuda-device-readiness", "passed": False,
                  "native_scenes": 0, "native_resets": 0, "native_controls": 0, "model_calls": 0,
                  "library_directory": str(args.library_directory.absolute()),
                  "runtime_snapshot_sha256_expected": RUNTIME_SNAPSHOT_SHA256,
                  "device_selection_environment": {key: os.environ.get(key) for key in
                      ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "OIDN_DEVICE_CUDA", "OIDN_VERBOSE")},
                  "api_reference": API_REFERENCE,
                  "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "limitation": "Default CUDA device initialization only; not every enumerated GPU, denoising, rendering or task verification"}
        try:
            report["renderer_runtime"] = args.renderer_runtime
            if args.renderer_runtime == COMPAT_RENDERER:
                from benchmarks.simBenchmarks.Robotwin.environment import oidn_compat
                oidn_compat.reject_preloaded_runtime()
                report["kind"] = "robotwin-oidn-2.3.3-cuda-device-readiness"
                report["compatibility_snapshot_sha256"] = oidn_compat.SNAPSHOT_SHA256
                report["api_reference"] = API_REFERENCE.replace("v2.0.1", "v2.3.3")
            report["libraries"] = verify_libraries(args.library_directory, args.renderer_runtime)
            # Match pinned SAPIEN's core/main preloading; retain both handles.
            loaded = [ctypes.CDLL(str((args.library_directory / name).absolute()), ctypes.RTLD_LOCAL)
                      for name in library_names(args.renderer_runtime)[:2]]
            report.update(check_cuda_device(loaded[-1]))
        except Exception as exc:
            report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, allow_nan=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
