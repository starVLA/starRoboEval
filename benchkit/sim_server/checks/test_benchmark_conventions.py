"""One service acceptance fixture across all implemented integrations.

Mocks only the HTTP listener and Dojo's deployment-manifest read. No simulator,
model call, native reset or physical control is permitted by these checks.
"""
from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
ENTRIES = (
    ("RoboDojo", "make_robodojo", "robodojo", "task_catalog.json", 5, 16),
    ("SimplerEnv", "make_simpler_env", "simpler_env", "task_catalog.json", 1, 7),
    ("LIBERO", "make_libero", "libero", "libero_catalog.json", 1, 7),
    ("SIMPLE", "make_simple_humanoid", "simple_humanoid", "simple_released_tasks.json", 1, 36),
    ("Robocasa_365", "make_robocasa365", "robocasa365", "robocasa365_target50.json", 1, 12),
    ("Robocasa_tabletop", "make_tabletop", "robocasa_tabletop", "robocasa_tabletop_contract.json", 1, 29),
    ("MetaWorld", "make_metaworld", "metaworld", "task_catalog.json", 1, 4),
    ("LIBERO-plus", "make_libero_plus", "libero_plus", "catalogs/libero_spatial.json", 1, 7),
    ("Robotwin", "make_robotwin", "robotwin", None, 1, 14),
    ("DOMINO", "make_domino", "domino", None, 1, 14),
    ("Behavior", "make_behavior", "behavior", None, 1, 23),
    ("VLA-Arena", "make_vla_arena", "vla_arena", "task_catalog.json", 1, 7),
    ("calvin", "make_calvin", "calvin", "frozen_sequence.json", 1, 7),
)


class BenchmarkConventionTests(unittest.TestCase):
    def test_standard_regression_runner_includes_service_gate(self):
        from benchkit.checks.run_regressions import GROUPS
        self.assertEqual(GROUPS["benchmark_service"], "benchkit/sim_server/checks")
        for directory, *_ in ENTRIES:
            self.assertEqual(GROUPS[directory], f"benchmarks/simBenchmarks/{directory}/checks")

    def test_every_entrypoint_has_benchmark_owned_main_and_explicit_sources(self):
        for directory, factory, _, catalog, _, _ in ENTRIES:
            with self.subTest(benchmark=directory):
                module = importlib.import_module(f"benchmarks.simBenchmarks.{directory}.server")
                self.assertEqual(module.main.__module__, module.__name__)
                base = f"benchmarks/simBenchmarks/{directory}/"
                expected = {base + name for name in ("server.py", "bench_server/__init__.py",
                                                    "bench_server/adapter.py")}
                if catalog is not None:
                    expected |= {base + "bench_server/protocol/" + catalog,
                                 base + "bench_server/protocol/__init__.py"}
                self.assertTrue(expected <= set(module.SUPPLEMENTAL_FILES))
                self.assertEqual(len(module.SUPPLEMENTAL_FILES), len(set(module.SUPPLEMENTAL_FILES)))
                for path in module.SUPPLEMENTAL_FILES:
                    self.assertTrue(path.startswith(base), path)
                    self.assertTrue((ROOT / path).is_file(), path)
                with patch.object(module, "launch", return_value=0) as launch:
                    self.assertEqual(module.main(["--help"]), 0)
                self.assertIs(launch.call_args.args[0], getattr(module, factory))
                self.assertEqual(launch.call_args.kwargs["argv"], ["--help"])
                self.assertEqual(launch.call_args.kwargs["supplemental_sources"], module.SUPPLEMENTAL_FILES)

    def test_same_startup_lifecycle_captures_native_contract_without_reset(self):
        from benchkit.sim_server.cli import main
        for directory, factory_name, identity, _, count, dimension in ENTRIES:
            with self.subTest(benchmark=directory), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                module = importlib.import_module(f"benchmarks.simBenchmarks.{directory}.server")
                adapter_module = importlib.import_module(f"benchmarks.simBenchmarks.{directory}.bench_server.adapter")
                if directory == "RoboDojo":
                    stack.enter_context(patch.object(adapter_module, "load_runtime", return_value={"python": "/native/bin/python"}))
                config = ROOT / f"benchmarks/simBenchmarks/{directory}/server.example.json"
                adapter = getattr(module, factory_name)(json.loads(config.read_text()))
                self.assertEqual(adapter.descriptor.name, identity)
                self.assertEqual(adapter.action_spec.size, dimension)
                stack.enter_context(patch.object(type(adapter), "open_episode", side_effect=AssertionError("native open forbidden")))
                stack.enter_context(patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": "s" * 48}))
                http = Mock(server_port=8766)
                descriptions = []

                def connect(service, **kwargs):
                    self.assertEqual(service.claims, set())
                    self.assertEqual(service.sessions, {})
                    expected_exclusions = ("cache",) if directory in {
                        "SIMPLE", "RoboDojo", "Robotwin", "DOMINO", "Behavior"} else ()
                    self.assertEqual(service.excluded, expected_exclusions)
                    descriptions.append(service.dispatch("describe", {}))
                    return http

                stack.enter_context(patch("benchkit.sim_server.launch.make_http_server", side_effect=connect))
                output = Path(temporary) / "server"
                args = ["--parameters", str(config), "--seed", "20260907",
                        "--output-dir", str(output), "--port", "8766"]
                if directory != "RoboDojo":
                    args += ["--episodes", "1"]
                with redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(main(["serve", "--benchmark", identity, *args]), 0)
                self.assertEqual(json.loads(stdout.getvalue())["native_resets"], 0)
                self.assertEqual(len(descriptions[0]["episodes"]), count)
                self.assertEqual(descriptions[0]["descriptor"]["name"], identity)
                fixed_caps = {"MetaWorld": 400, "Robotwin": 400, "DOMINO": 400,
                              "Behavior": 3224, "VLA-Arena": 300, "calvin": 1800}
                if directory in fixed_caps:
                    self.assertEqual(descriptions[0]["budget"]["environment_step_cap"], fixed_caps[directory])
                records = descriptions[0]["source"]["supplemental_files"]
                self.assertEqual({row["path"] for row in records}, set(module.SUPPLEMENTAL_FILES))
                for row in records:
                    self.assertEqual(hashlib.sha256((output / "service_source" / row["path"]).read_bytes()).hexdigest(), row["sha256"])
                source = json.loads((output / "harness_source/index.json").read_text())
                selector = "benchkit/sim_server/cli.py"
                captured = next(row for row in source["files"] if row["path"] == selector)
                payload = (ROOT / selector).read_bytes()
                self.assertEqual(captured["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual((output / "harness_source/files" / selector).read_bytes(), payload)
                http.serve_forever.assert_called_once_with(poll_interval=0.25)
                http.server_close.assert_called_once()

    def test_service_imports_do_not_depend_on_models_campaign_or_native_runtime(self):
        for directory, *_ in ENTRIES:
            with self.subTest(benchmark=directory):
                code = f"""
import importlib, sys
importlib.import_module('benchmarks.simBenchmarks.{directory}.server')
for name in ('AgentPolicies', 'torch', 'numpy', 'mujoco', 'robosuite', 'libero', 'simpler_env',
             'mani_skill2_real2sim', 'isaacsim', 'metaworld', 'sapien', 'calvin_env',
             'pybullet', 'vla_arena', 'omnigibson', 'gello', 'benchkit.campaigns.workflow',
             'benchmarks.simBenchmarks.{directory}.evaluation',
             'benchmarks.simBenchmarks.{directory}.bench_server.protocol.plan'):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name
"""
                result = subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=ROOT,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
