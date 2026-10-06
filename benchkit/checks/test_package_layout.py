"""Responsibility packages are actual implementations, not compatibility shells."""
import hashlib
from importlib import import_module, resources
from importlib.util import find_spec
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from benchkit.source_snapshot import capture_harness_source


ROOT = Path(__file__).resolve().parents[2]
REMOVED = ("campaign", "benchmark_plans", "campaign_coverage", "result_index", "smoke", "runner")


class PackageLayoutChecks(unittest.TestCase):
    def test_top_level_names_are_real_packages_without_old_aliases(self):
        for name in ("benchkit", "benchmarks"):
            module = import_module(name)
            self.assertEqual(Path(module.__file__).resolve(), ROOT / name / "__init__.py")
        for old_name in ("harness", "examples"):
            self.assertFalse((ROOT / old_name / "__init__.py").exists())
        code = """
import importlib.util
for name in ('harness', 'examples'):
    spec = importlib.util.find_spec(name)
    # An ignored historical artifact directory may form an empty namespace,
    # but it must not expose an initializer or live compatibility entrypoint.
    assert spec is None or spec.origin is None, name
    if spec is not None:
        try:
            entrypoint = importlib.util.find_spec(name + ('.contracts' if name == 'harness' else '.simBenchmarks.RoboDojo.server'))
        except ModuleNotFoundError:
            entrypoint = None
        assert entrypoint is None, name
"""
        subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=ROOT,
                       check=True, timeout=30, capture_output=True)

    def test_old_flat_entrypoints_are_absent_without_forwarders(self):
        for name in REMOVED:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "benchkit" / (name + ".py")).exists())
                self.assertIsNone(find_spec("benchkit." + name))
        self.assertFalse((ROOT / "benchkit/catalog.py").exists())
        self.assertFalse((ROOT / "benchkit/benchmark_catalog.json").exists())
        code = """
import importlib
for name in ('campaign', 'benchmark_plans', 'campaign_coverage', 'result_index', 'smoke', 'runner'):
    try:
        importlib.import_module('benchkit.' + name)
    except ModuleNotFoundError as error:
        assert error.name == 'benchkit.' + name
    else:
        raise AssertionError('removed import still resolves: ' + name)
"""
        subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=ROOT,
                       check=True, timeout=30, capture_output=True)

    def test_harness_root_has_no_runner_exports(self):
        import benchkit
        for name in ("EvaluationRunner", "RunRequest"):
            self.assertNotIn(name, benchkit.__all__)
            self.assertFalse(hasattr(benchkit, name))
        from AgentPolicies.policy_support.runner import EvaluationRunner
        self.assertEqual(EvaluationRunner.__module__, "AgentPolicies.policy_support.runner")

    def test_packages_own_actual_implementations(self):
        checks = (("benchkit.campaigns.workflow", "prepare", "benchkit/campaigns/workflow.py"),
                  ("benchkit.campaigns.benchmark_plans", "get_plan", "benchkit/campaigns/benchmark_plans.py"),
                  ("benchkit.reports.campaign_coverage", "audit_tools", "benchkit/reports/campaign_coverage.py"),
                  ("benchkit.reports.result_index", "ClosedFiles", "benchkit/reports/result_index.py"),
                  ("benchkit.diagnostics.smoke", "ReachBenchmark", "benchkit/diagnostics/smoke.py"),
                  ("benchkit.catalog", "load_catalog", "benchkit/catalog/__init__.py"))
        for module_name, symbol, relative in checks:
            with self.subTest(module=module_name):
                module = import_module(module_name)
                self.assertEqual(module.__name__, module_name)
                self.assertEqual(getattr(module, symbol).__module__, module_name)
                self.assertEqual(Path(module.__file__).resolve(), ROOT / relative)

    def test_catalog_resource_is_packaged_beside_its_loader(self):
        from benchkit.catalog import load_catalog, validate_repository_catalog
        payload = json.loads(resources.files("benchkit.catalog").joinpath("benchmarks.json").read_text())
        self.assertEqual([row["id"] for row in payload["benchmarks"]], [row.id for row in load_catalog()])
        self.assertEqual(validate_repository_catalog(ROOT), [])

    def test_private_local_directory_is_not_live_source(self):
        from benchkit.checks.check_boundaries import _sources
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "_local").mkdir()
            (root / "_local/private_experiment.py").write_text("import private_simulator\n")
            (root / "public.py").write_text("pass\n")
            self.assertEqual(list(_sources(root)), [root / "public.py"])

    def test_coverage_auditor_default_root_survives_deeper_package(self):
        from benchkit.reports.campaign_coverage import AUDIT_FILES, audit_tools
        modules = audit_tools()
        self.assertEqual([Path(module.__file__).resolve() for module in modules],
                         [ROOT / relative for relative in AUDIT_FILES])

    def test_imports_and_help_do_not_initialize_a_native_or_policy_backend(self):
        code = """
import importlib
import sys
for name in ('benchkit.campaigns.workflow', 'benchkit.reports.campaign_coverage',
             'benchkit.reports.result_index', 'benchkit.catalog'):
    importlib.import_module(name)
for prefix in ('numpy','torch','mujoco','isaacsim','robosuite','openai','anthropic','AgentPolicies'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
"""
        subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=ROOT,
                       check=True, timeout=30, capture_output=True)
        for module, phrase in (("benchkit.campaigns", "prepare"),
                               ("benchkit.reports.result_index", "--help")):
            result = subprocess.run([sys.executable, "-B", "-m", module, "--help"], cwd=ROOT,
                                    check=True, timeout=30, capture_output=True, text=True)
            self.assertIn(phrase, result.stdout)
            self.assertEqual(result.stderr, "")

    def test_source_snapshot_contains_new_packages_and_catalog_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            capture_harness_source(output)
            index = json.loads((output / "harness_source/index.json").read_text())
            rows = {row["path"]: row for row in index["files"]}
            expected = ("benchkit/campaigns/__init__.py", "benchkit/campaigns/__main__.py",
                        "benchkit/campaigns/workflow.py", "benchkit/campaigns/benchmark_plans.py",
                        "benchkit/catalog/__init__.py", "benchkit/catalog/benchmarks.json",
                        "benchkit/reports/campaign_coverage.py", "benchkit/reports/result_index.py",
                        "benchkit/diagnostics/smoke.py", "AgentPolicies/policy_support/runner.py")
            for relative in expected:
                with self.subTest(relative=relative):
                    self.assertIn(relative, rows)
                    captured = (output / "harness_source/files" / relative).read_bytes()
                    self.assertEqual(hashlib.sha256(captured).hexdigest(), rows[relative]["sha256"])
                    self.assertEqual(captured, (ROOT / relative).read_bytes())
            for name in REMOVED:
                self.assertNotIn("benchkit/" + name + ".py", rows)


if __name__ == "__main__":
    unittest.main()
