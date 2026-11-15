"""Evaluator-only renderer identity checks; never initialize a task or choose a fallback GPU."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET


def validate_gpu_uuid(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(
        r"GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value
    ) is None:
        raise ValueError("expected_gpu_uuid must be a complete NVIDIA GPU UUID")
    return value.lower()


def process_devices(xml: str, pid: int) -> list[dict[str, str]]:
    """Read full device identities, not ambiguous PCI bus numbers or CUDA ordinals."""
    devices = []
    for gpu in ET.fromstring(xml).findall("gpu"):
        if any(item.findtext("pid") == str(pid) for item in gpu.findall("processes/process_info")):
            devices.append({"uuid": gpu.findtext("uuid", ""),
                            "pci_bus_id": gpu.findtext("pci/pci_bus_id", ""),
                            "name": gpu.findtext("product_name", "")})
    return devices


def assert_render_device(expected_gpu_uuid: str) -> dict:
    """Fail closed if NVIDIA's process inventory cannot attest this process's device.

    Includes graphics AND compute entries. A PID-namespace mismatch or missing
    process inventory is an unsupported verification environment, not success.
    This is operational evidence, not a sandbox or loaded-memory attestation.
    """
    expected = validate_gpu_uuid(expected_gpu_uuid)
    query = subprocess.run(["nvidia-smi", "-q", "-x"], check=True,
                           capture_output=True, text=True, timeout=15)
    devices = process_devices(query.stdout, os.getpid())
    if len(devices) != 1 or devices[0]["uuid"].lower() != expected:
        raise RuntimeError(f"renderer GPU identity mismatch: expected {expected_gpu_uuid}, observed {devices}; "
                           "no automatic device fallback; check NVIDIA process/PID visibility")
    return {"expected_gpu_uuid": expected_gpu_uuid, "process_id": os.getpid(),
            "observed_devices": devices, "identity_source": "nvidia-smi process inventory"}


def _renderer_probe(device: str, expected: str) -> dict:
    import sapien.core as sapien

    sapien.SapienRenderer.set_log_level("info")
    renderer = sapien.SapienRenderer(offscreen_only=True, device=device)
    result = assert_render_device(expected)
    # Keep renderer alive until the process inventory has been checked.
    del renderer
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check renderer-only GPU identity; no scene/reset/control/model")
    parser.add_argument("--device", required=True, help="exact SAPIEN selector used by server parameters")
    parser.add_argument("--expected-gpu-uuid", required=True)
    parser.add_argument("--output", type=Path, required=True, help="new JSON receipt; existing files are refused")
    args = parser.parse_args(argv)
    validate_gpu_uuid(args.expected_gpu_uuid)
    # Reserve a fresh receipt before allocating resources. The isolated child
    # releases its renderer even if initialization raises or times out.
    with args.output.open("x", encoding="utf-8") as receipt:
        command = [sys.executable, "-B", "-c",
                   "import json,sys; from benchmarks.simBenchmarks.SimplerEnv.environment.render_device "
                   "import _renderer_probe; print('RSI_RENDER_DEVICE='+json.dumps(_renderer_probe(sys.argv[1],sys.argv[2])),flush=True)",
                   args.device, args.expected_gpu_uuid]
        result = {"schema": "starvla-rsi.simpler_env.render-device-preflight/v1", "device": args.device,
                  "expected_gpu_uuid": args.expected_gpu_uuid, "passed": False,
                  "task_resets": 0, "controls": 0, "model_calls": 0,
                  "environment": {key: os.environ.get(key) for key in
                                  ("CUDA_VISIBLE_DEVICES", "VK_ICD_FILENAMES")}}
        try:
            child = subprocess.run(command, capture_output=True, text=True, timeout=60)
            result.update(returncode=child.returncode, stdout=child.stdout, stderr=child.stderr)
            rows = [line.removeprefix("RSI_RENDER_DEVICE=") for line in child.stdout.splitlines()
                    if line.startswith("RSI_RENDER_DEVICE=")]
            if child.returncode == 0 and len(rows) == 1:
                result.update(passed=True, identity=json.loads(rows[0]))
        except subprocess.TimeoutExpired:
            result["error"] = "renderer_preflight_timeout"
        json.dump(result, receipt, indent=2)
        receipt.write("\n")
    print(json.dumps({"passed": result["passed"], "receipt": str(args.output), "task_resets": 0}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
