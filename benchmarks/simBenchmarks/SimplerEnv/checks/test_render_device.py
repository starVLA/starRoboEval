"""Renderer identity regression without a native renderer or GPU."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.SimplerEnv.environment import render_device as module
from benchmarks.simBenchmarks.SimplerEnv.bench_server.adapter import make_simpler_env

UUID = "GPU-e91869ed-7220-098d-9b0b-83b20b495abd"
OTHER = "GPU-c5f065b2-1c41-6fb2-0e84-201c33983a89"


def gpu(uuid=UUID, pid=42, bus="00000000:FD:05.0"):
    return (f"<gpu><uuid>{uuid}</uuid><product_name>NVIDIA fixture</product_name>"
            f"<pci><pci_bus_id>{bus}</pci_bus_id></pci><processes><process_info>"
            f"<pid>{pid}</pid><type>G</type></process_info></processes></gpu>")


class RenderDeviceTests(unittest.TestCase):
    def test_exact_graphics_process_identity(self):
        xml = "<nvidia_smi_log>" + gpu() + gpu(OTHER, 43) + "</nvidia_smi_log>"
        with patch.object(module.os, "getpid", return_value=42), patch.object(
            module.subprocess, "run", return_value=SimpleNamespace(stdout=xml)
        ) as run:
            result = module.assert_render_device(UUID)
        self.assertEqual(result["observed_devices"][0]["pci_bus_id"], "00000000:FD:05.0")
        self.assertEqual(run.call_count, 1)

    def test_unknown_wrong_or_multiple_devices_fail_no_fallback(self):
        for rows in (gpu(pid=43), gpu(OTHER), gpu() + gpu(OTHER)):
            with self.subTest(rows=rows), patch.object(module.os, "getpid", return_value=42), patch.object(
                module.subprocess, "run", return_value=SimpleNamespace(stdout="<nvidia_smi_log>" + rows + "</nvidia_smi_log>")
            ) as run, self.assertRaisesRegex(RuntimeError, "no automatic device fallback"):
                module.assert_render_device(UUID)
            self.assertEqual(run.call_count, 1)

    def test_full_uuid_required(self):
        for value in (0, True, "GPU-123", "cuda:0", "", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.validate_gpu_uuid(value)

    def test_adapter_is_lazy_and_selection_does_not_change_protocol(self):
        with patch.object(module.subprocess, "run", side_effect=AssertionError("no GPU at construction")):
            adapter = make_simpler_env({"device": "cuda:0", "expected_gpu_uuid": UUID})
        self.assertEqual(adapter.expected_gpu_uuid, UUID)
        self.assertEqual(adapter.descriptor, make_simpler_env({}).descriptor)
        with self.assertRaises(ValueError):
            make_simpler_env({"expected_gpu_uuid": "GPU-truncated"})

    def test_preflight_refuses_to_overwrite_receipt_before_child(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text("old failure")
            with patch.object(module.subprocess, "run") as run, self.assertRaises(FileExistsError):
                module.main(["--device", "cuda:0", "--expected-gpu-uuid", UUID, "--output", str(path)])
            run.assert_not_called()
            self.assertEqual(path.read_text(), "old failure")

    def test_runtime_identity_failure_prevents_public_reset(self):
        from unittest.mock import Mock
        from benchmarks.simBenchmarks.SimplerEnv.bench_server import adapter as bridge
        adapter = make_simpler_env({"expected_gpu_uuid": UUID})
        native = SimpleNamespace(reset=Mock(), close=Mock())
        modules = {
            "gymnasium": SimpleNamespace(spec=lambda _: SimpleNamespace(max_episode_steps=60),
                                         make=Mock(return_value=native)),
            "mani_skill2_real2sim": SimpleNamespace(__file__="/native/mani_skill2_real2sim/__init__.py"),
            "simpler_env": SimpleNamespace(__file__="/native/simpler_env/__init__.py",
                                            ENVIRONMENT_MAP={adapter.task: ("fixture-id", {})}),
        }
        session = adapter.open_episode(adapter.episodes(0)[0])
        with patch.dict("sys.modules", modules), patch.object(bridge, "_revision", return_value={}), patch.object(
            module, "assert_render_device", side_effect=RuntimeError("renderer GPU identity mismatch")
        ):
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                session.reset()
        native.reset.assert_not_called()
        session.close()
        native.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
