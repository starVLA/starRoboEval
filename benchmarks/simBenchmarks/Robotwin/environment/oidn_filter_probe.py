"""Pinned OIDN 2.3.3 synthetic CUDA RT filter readiness; never a simulator.

This optional benchmark setup tool creates no SAPIEN scene, task or policy. It
exercises a selected CUDA device, an explicit stream and shared device buffers.
A passing synthetic filter is not proof of native RGB correctness.
"""
import argparse
import array
import ctypes as c
import hashlib
import json
import math
import os
from pathlib import Path
import random

from benchmarks.simBenchmarks.Robotwin.environment import oidn_compat
from benchmarks.simBenchmarks.Robotwin.environment.renderer_readiness import verify_libraries, library_names


def run(library_directory, report):
    core = c.CDLL(str(library_directory / "libOpenImageDenoise_core.so.2.3.3"), c.RTLD_LOCAL)
    api = c.CDLL(str(library_directory / "libOpenImageDenoise.so.2.3.3"), c.RTLD_LOCAL)
    cuda = c.CDLL("libcuda.so.1", c.RTLD_LOCAL)
    cuda_signatures = {
        "cuInit": ([c.c_uint], c.c_int),
        "cuDeviceGet": ([c.POINTER(c.c_int), c.c_int], c.c_int),
        "cuDeviceGetName": ([c.c_void_p, c.c_int, c.c_int], c.c_int),
        "cuDeviceComputeCapability": ([c.POINTER(c.c_int), c.POINTER(c.c_int), c.c_int], c.c_int),
        "cuDevicePrimaryCtxRetain": ([c.POINTER(c.c_void_p), c.c_int], c.c_int),
        "cuDevicePrimaryCtxRelease": ([c.c_int], c.c_int),
        "cuCtxPushCurrent_v2": ([c.c_void_p], c.c_int),
        "cuCtxPopCurrent_v2": ([c.POINTER(c.c_void_p)], c.c_int),
        "cuStreamCreate": ([c.POINTER(c.c_void_p), c.c_uint], c.c_int),
        "cuStreamDestroy_v2": ([c.c_void_p], c.c_int),
        "cuStreamSynchronize": ([c.c_void_p], c.c_int),
        "cuMemAlloc_v2": ([c.POINTER(c.c_uint64), c.c_size_t], c.c_int),
        "cuMemFree_v2": ([c.c_uint64], c.c_int),
        "cuMemcpyHtoD_v2": ([c.c_uint64, c.c_void_p, c.c_size_t], c.c_int),
        "cuMemcpyDtoH_v2": ([c.c_void_p, c.c_uint64, c.c_size_t], c.c_int),
    }
    oidn_signatures = {
        "oidnGetNumPhysicalDevices": ([], c.c_int),
        "oidnNewCUDADevice": ([c.POINTER(c.c_int), c.POINTER(c.c_void_p), c.c_int], c.c_void_p),
        "oidnGetDeviceError": ([c.c_void_p, c.POINTER(c.c_char_p)], c.c_int),
        "oidnGetDeviceInt": ([c.c_void_p, c.c_char_p], c.c_int),
        "oidnCommitDevice": ([c.c_void_p], None),
        "oidnReleaseDevice": ([c.c_void_p], None),
        "oidnNewFilter": ([c.c_void_p, c.c_char_p], c.c_void_p),
        "oidnNewSharedBuffer": ([c.c_void_p, c.c_void_p, c.c_size_t], c.c_void_p),
        "oidnSetFilterImage": ([c.c_void_p, c.c_char_p, c.c_void_p, c.c_int] + [c.c_size_t] * 5, None),
        "oidnSetFilterBool": ([c.c_void_p, c.c_char_p, c.c_bool], None),
        "oidnCommitFilter": ([c.c_void_p], None),
        "oidnExecuteFilter": ([c.c_void_p], None),
        "oidnReleaseFilter": ([c.c_void_p], None),
        "oidnReleaseBuffer": ([c.c_void_p], None),
    }
    for library, signatures in ((cuda, cuda_signatures), (api, oidn_signatures)):
        for name, (args, result) in signatures.items():
            getattr(library, name).argtypes = args
            getattr(library, name).restype = result

    def cu(name, *args):
        result = getattr(cuda, name)(*args)
        if result:
            raise RuntimeError(f"{name} failed CUDA error {result}")

    def check(stage):
        message = c.c_char_p()
        code = api.oidnGetDeviceError(device, c.byref(message))
        if code:
            raise RuntimeError(f"OIDN {stage}: {code} {message.value!r}")

    device = filter_ = None
    native_device, context, stream = c.c_int(), c.c_void_p(), c.c_void_p()
    pointers, buffers, host_arrays = [], [], []
    retained = pushed = False
    try:
        cu("cuInit", 0)
        cu("cuDeviceGet", c.byref(native_device), 0)
        name, major, minor = c.create_string_buffer(256), c.c_int(), c.c_int()
        cu("cuDeviceGetName", name, 256, native_device)
        cu("cuDeviceComputeCapability", c.byref(major), c.byref(minor), native_device)
        report["selected_cuda_device"] = {"visible_ordinal": 0, "name": name.value.decode(), "compute_capability": [major.value, minor.value]}
        cu("cuDevicePrimaryCtxRetain", c.byref(context), native_device)
        retained = True
        cu("cuCtxPushCurrent_v2", context)
        pushed = True
        cu("cuStreamCreate", c.byref(stream), 0)
        report["physical_devices_enumerated"] = api.oidnGetNumPhysicalDevices()
        device = api.oidnNewCUDADevice(c.byref(native_device), c.byref(stream), 1)
        check("creation")
        if not device:
            raise RuntimeError("OIDN CUDA creation returned a null device")
        api.oidnCommitDevice(device)
        check("commit device")
        report["oidn_version"] = api.oidnGetDeviceInt(device, b"version")
        check("version query")
        filter_ = api.oidnNewFilter(device, b"RT")
        check("create RT filter")
        width = height = 64
        count, size = width * height * 3, width * height * 3 * 4
        rng = random.Random(20260916)
        color = array.array("f", (0.4 + 0.1 * (i % 3) + rng.uniform(-0.2, 0.2) for i in range(count)))
        albedo = array.array("f", (0.4 + 0.1 * (i % 3) for i in range(count)))
        normal = array.array("f", (float(i % 3 == 2) for i in range(count)))
        output = array.array("f", [float("nan")] * count)
        for field, values in ((b"color", color), (b"albedo", albedo), (b"normal", normal), (b"output", output)):
            host = (c.c_float * count).from_buffer(values)
            host_arrays.append(host)
            pointer = c.c_uint64()
            cu("cuMemAlloc_v2", c.byref(pointer), size)
            pointers.append(pointer)
            cu("cuMemcpyHtoD_v2", pointer, host, size)
            buffer = api.oidnNewSharedBuffer(device, c.c_void_p(pointer.value), size)
            check("new shared CUDA buffer")
            buffers.append(buffer)
            api.oidnSetFilterImage(filter_, field, buffer, 3, width, height, 0, 12, width * 12)
            check("set shared image")
        api.oidnSetFilterBool(filter_, b"hdr", True)
        api.oidnCommitFilter(filter_)
        check("commit filter")
        api.oidnExecuteFilter(filter_)
        check("execute filter")
        cu("cuStreamSynchronize", stream)
        cu("cuMemcpyDtoH_v2", host_arrays[-1], pointers[-1], size)
        finite = all(math.isfinite(value) for value in output)
        report["filter"] = {
            "kind": "RT", "shape": [height, width, 3], "format": "float32", "hdr": True,
            "color_albedo_normal": True, "quality": "unchanged OIDN default", "shared_device_buffers": True,
            "nondefault_cuda_stream": True, "output_all_finite": finite,
            "input_sha256": hashlib.sha256(color.tobytes()).hexdigest(),
            "output_sha256": hashlib.sha256(output.tobytes()).hexdigest(),
            "mean_absolute_change": sum(abs(a - b) for a, b in zip(color, output)) / count if finite else None,
        }
        report["passed"] = finite and report["filter"]["mean_absolute_change"] > 1e-6
        report["loaded_oidn_maps"] = sorted({line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines() if "OpenImageDenoise" in line})
    finally:
        if filter_:
            api.oidnReleaseFilter(filter_)
        for buffer in buffers:
            api.oidnReleaseBuffer(buffer)
        if device:
            api.oidnReleaseDevice(device)
        for pointer in pointers:
            cu("cuMemFree_v2", pointer)
        if stream:
            cu("cuStreamDestroy_v2", stream)
        if pushed:
            previous = c.c_void_p()
            cu("cuCtxPopCurrent_v2", c.byref(previous))
        if retained:
            cu("cuDevicePrimaryCtxRelease", native_device)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--library-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = {"kind": "robotwin-oidn-2.3.3-synthetic-cuda-filter-probe", "passed": False,
              "native_scenes": 0, "native_resets": 0, "native_controls": 0, "model_calls": 0,
              "capability_evaluation": False, "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
              "library_directory": str(args.library_directory.absolute()),
              "compatibility_snapshot_sha256": oidn_compat.SNAPSHOT_SHA256,
              "limitation": "Synthetic stream/shared-buffer CUDA RT filter only; not native renderer, task, physics or scoring validation",
              "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        try:
            oidn_compat.reject_preloaded_runtime()
            report["libraries"] = verify_libraries(args.library_directory, oidn_compat.TRACK)
            run(args.library_directory.absolute(), report)
            expected = {str(args.library_directory.absolute() / name) for name in library_names(oidn_compat.TRACK)}
            if set(report["loaded_oidn_maps"]) != expected:
                raise RuntimeError("unexpected mapped OIDN library path")
        except Exception as exc:
            report["passed"] = False
            report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, allow_nan=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
