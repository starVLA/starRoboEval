"""Canonical shared transport only; no native calls or external network."""
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


PREFIX = "benchkit.sim_server"
REMOVED = "benchmarks.simBenchmarks.service"
MODULES = ("wire", "client", "server", "launch")
ROOT = Path(__file__).resolve().parents[3]


class ServiceModuleLayoutTests(unittest.TestCase):
    def test_transport_modules_are_implemented_in_the_canonical_package(self):
        directory = Path(__file__).resolve().parents[1]
        for name in MODULES:
            with self.subTest(module=name):
                current = import_module(f"{PREFIX}.{name}")
                self.assertEqual(current.__name__, f"{PREFIX}.{name}")
                self.assertEqual(Path(current.__file__).resolve().parent, directory)
        client = import_module(f"{PREFIX}.client")
        server = import_module(f"{PREFIX}.server")
        self.assertEqual(client.SimServerBenchmarkAdapter.__module__, f"{PREFIX}.client")
        self.assertEqual(server.BenchmarkService.__module__, f"{PREFIX}.server")

    def test_removed_location_has_no_runtime_or_forwarding_modules(self):
        old_directory = ROOT / "benchmarks/simBenchmarks/service"
        self.assertEqual(list(old_directory.rglob("*.py")), [])
        # An empty generated-cache directory may remain a namespace package;
        # none of the old runtime entrypoints may resolve from this checkout.
        for name in (*MODULES, "__main__"):
            with self.subTest(module=name):
                try:
                    old_module = find_spec(f"{REMOVED}.{name}")
                except ModuleNotFoundError:
                    old_module = None
                self.assertIsNone(old_module)

    def test_fresh_imports_need_no_legacy_path_model_or_native_dependency(self):
        code = """
from importlib import import_module
import sys
for name in ('wire', 'client', 'server', 'launch'):
    module = import_module('benchkit.sim_server.' + name)
    assert module.__name__ == 'benchkit.sim_server.' + name
for name in ('benchmarks.simBenchmarks.service', 'numpy', 'torch', 'isaacsim',
             'mujoco', 'robosuite', 'openai', 'anthropic', 'AgentPolicies'):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name
"""
        subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=ROOT,
                       check=True, timeout=15, capture_output=True)

    def test_canonical_monkeypatches_affect_the_actual_implementation(self):
        server = import_module(f"{PREFIX}.server")
        wire = import_module(f"{PREFIX}.wire")
        with patch(f"{PREFIX}.server.CHUNK_BYTES", 7):
            self.assertEqual(server.CHUNK_BYTES, 7)
        with patch(f"{PREFIX}.wire.MAX_MESSAGE_BYTES", 2):
            with self.assertRaises(wire.WireError):
                wire.dumps({"payload": "too long"})

    def test_shared_contract_classes_retain_identity(self):
        from benchkit.contracts import Observation, Transition
        wire = import_module(f"{PREFIX}.wire")
        self.assertIs(wire.Observation, Observation)
        self.assertIs(wire.Transition, Transition)

    def test_cli_selects_only_the_synthetic_entrypoint(self):
        current = import_module(f"{PREFIX}.__main__")
        with patch.object(current, "launch", return_value=0) as launch:
            self.assertEqual(current.main(["--help"]), 0)
        launch.assert_called_once_with(current.make_smoke_benchmark,
                                       supplemental_sources=current.SUPPLEMENTAL_FILES, argv=["--help"])

    def test_cli_help_exits_without_starting_a_service(self):
        result = subprocess.run([sys.executable, "-B", "-m", PREFIX, "--help"], cwd=ROOT,
                                check=True, timeout=15, capture_output=True, text=True)
        self.assertIn("--parameters", result.stdout)
        self.assertIn("--token-env", result.stdout)
        self.assertNotIn("listening", result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
