"""Offline selector checks; native construction and model calls are forbidden."""
from contextlib import redirect_stderr
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

from benchkit.sim_server import cli
from benchkit.sim_server.checks.test_benchmark_conventions import ENTRIES


ROOT = Path(__file__).resolve().parents[3]


class BenchmarkCliTests(unittest.TestCase):
    def test_routes_match_independent_service_fixture_and_catalog(self):
        expected = {identity: f"benchmarks.simBenchmarks.{directory}.server"
                    for directory, _, identity, *_ in ENTRIES}
        self.assertEqual(len(expected), 13)
        self.assertEqual(cli.SERVICE_MODULES, expected)
        self.assertEqual(cli.ALIASES, {"robocasa_365": "robocasa365"})
        catalog = json.loads((ROOT / "benchkit/catalog/benchmarks.json").read_text())
        catalog_ids = {row["id"]: row["directory"] for row in catalog["benchmarks"]}
        for identity, module in expected.items():
            catalog_id = "robocasa_365" if identity == "robocasa365" else identity
            self.assertEqual(catalog_ids[catalog_id], module.rsplit(".", 1)[0].replace(".", "/"))

    def test_every_route_and_alias_forwards_unchanged_argv_and_return_value_once(self):
        for identity in (*cli.SERVICE_MODULES, *cli.ALIASES):
            for selector in (["--benchmark", identity], [f"--benchmark={identity}"]):
                with self.subTest(identity=identity, selector=selector):
                    arguments = ["--parameters", "/a path/config.json", "--seed", "-9",
                                 "--output-dir=/a path/result", "--token-env", "MY_SERVICE_TOKEN",
                                 "--port", "0"]
                    original = ["serve", *arguments[:2], *selector, *arguments[2:]]
                    service = Mock()
                    service.main.return_value = 17
                    with patch.object(cli, "import_module", return_value=service) as load:
                        self.assertEqual(cli.main(original), 17)
                    canonical = cli.ALIASES.get(identity, identity)
                    load.assert_called_once_with(cli.SERVICE_MODULES[canonical])
                    service.main.assert_called_once_with(arguments)
                    self.assertEqual(original, ["serve", *arguments[:2], *selector, *arguments[2:]])

    def test_invalid_routing_is_rejected_before_import(self):
        cases = [[], ["serve"], ["list", "--seed", "1"], ["serve", "--benchmark"],
                 ["serve", "--bench", "libero"], ["serve", "--bench=libero"],
                 ["serve", "--benchmark", "libero", "--bench", "robodojo"],
                 ["serve", "--benchmark", "libero", "--benchmark", "libero"],
                 ["serve", "--benchmark=libero", "--benchmark=robodojo"],
                 ["serve", "--benchmark", "robocasa365", "--benchmark=robocasa_365"]]
        cases += [["serve", "--benchmark", identity, "--help"] for identity in (
            "unknown", "vln_ce", "smoke", "simple", "LIBERO", "../RoboDojo",
            "benchmarks.simBenchmarks.LIBERO.server")]
        for arguments in cases:
            with self.subTest(arguments=arguments), patch.object(cli, "import_module") as load:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    cli.main(arguments)
                self.assertEqual(error.exception.code, 2)
                load.assert_not_called()

    def test_list_and_generic_help_do_not_import_services_in_fresh_process(self):
        for arguments in (["list"], ["--help"], ["list", "--help"], ["serve", "--help"], ["serve", "-h"]):
            with self.subTest(arguments=arguments):
                code = f"""
import sys
from benchkit.sim_server.cli import main
try:
    result = main({arguments!r})
except SystemExit as exc:
    result = exc.code
assert result == 0, result
for name in ('benchmarks', 'AgentPolicies', 'numpy', 'torch', 'isaacsim', 'mujoco',
             'openai', 'anthropic', 'benchkit.campaigns.workflow', 'benchkit.registry',
             'benchkit.sim_server.launch', 'benchkit.sim_server.server'):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name
"""
                result = subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=ROOT,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("listening", result.stdout)
                if arguments == ["list"]:
                    self.assertIn("Development services", result.stdout)
                    self.assertIn("repository-relative", result.stdout)
                    self.assertIn("robocasa365 (alias: robocasa_365)", result.stdout)
                    self.assertNotIn("vln_ce", result.stdout)

    def test_selected_help_imports_only_selected_service_without_native_or_model(self):
        for directory, _, identity, *_ in ENTRIES:
            with self.subTest(benchmark=identity):
                code = f"""
import sys
from benchkit.sim_server.cli import main
try:
    main(['serve', '--benchmark', {identity!r}, '--help'])
except SystemExit as exc:
    assert exc.code == 0, exc.code
else:
    raise AssertionError('selected launcher must handle help')
prefix = 'benchmarks.simBenchmarks.'
assert all(name.startswith(prefix + {directory!r} + '.') or name == prefix + {directory!r}
           for name in sys.modules if name.startswith(prefix)), sorted(sys.modules)
for name in ('AgentPolicies', 'numpy', 'torch', 'isaacsim', 'isaaclab', 'mujoco', 'robosuite',
             'libero', 'simpler_env', 'metaworld', 'sapien', 'omnigibson', 'calvin_env',
             'pybullet', 'openai', 'anthropic', 'benchkit.campaigns.workflow'):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name
"""
                result = subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=ROOT,
                                        capture_output=True, text=True, timeout=30,
                                        env={key: value for key, value in os.environ.items()
                                             if key != "RSI_SIM_SERVER_TOKEN"})
                self.assertEqual(result.returncode, 0, result.stderr)
                for option in ("--parameters", "--seed", "--output-dir", "--token-env"):
                    self.assertIn(option, result.stdout)
                self.assertNotIn("listening", result.stdout)

    def test_dojo_complete_panel_and_token_validation_still_precede_factory_and_storage(self):
        service = importlib.import_module("benchmarks.simBenchmarks.RoboDojo.server")
        for suffix, expected in ((["--episodes", "1"], "complete named panel"),
                                 ([], "URL-safe token"), (["--full"], "unrecognized arguments")):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "server"
                arguments = ["serve", "--benchmark", "robodojo", "--seed", "20260907",
                             "--output-dir", str(output), *suffix]
                with patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": ""}), \
                        patch.object(service, "make_robodojo") as factory, \
                        redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
                    cli.main(arguments)
                self.assertEqual(error.exception.code, 2)
                self.assertIn(expected, stderr.getvalue())
                factory.assert_not_called()
                self.assertFalse(output.exists())

    def test_module_entrypoint_and_packaged_console_definition(self):
        configuration = (ROOT / "pyproject.toml").read_text()
        self.assertIn('rsi-bench = "benchkit.sim_server.cli:main"', configuration)
        result = subprocess.run([sys.executable, "-B", "-m", "benchkit.sim_server.cli", "list"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("simple_humanoid", result.stdout)
        smoke = importlib.import_module("benchkit.sim_server.__main__")
        with patch.object(smoke, "launch", return_value=0) as launch:
            self.assertEqual(smoke.main(["--help"]), 0)
        launch.assert_called_once_with(smoke.make_smoke_benchmark,
                                       supplemental_sources=smoke.SUPPLEMENTAL_FILES, argv=["--help"])


if __name__ == "__main__":
    unittest.main()
