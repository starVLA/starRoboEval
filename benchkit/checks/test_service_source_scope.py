"""Service capture works without participant/campaign/other-benchmark sources.

All fixtures are disposable; subprocesses forbid native initialization. Copying
the selected installed package files tests path portability, not native readiness.
"""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchkit import source_snapshot
from benchkit.source_snapshot import (
    SERVICE_SOURCE_FILES, SourceSnapshotError, capture_harness_source,
    repository_source_files, MAX_FILES,
)
from benchkit.sim_server.cli import SERVICE_MODULES


ROOT = Path(__file__).resolve().parents[2]


def copy_sources(destination, names):
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)


class ServiceSourceScopeTests(unittest.TestCase):
    def test_synthetic_launcher_declares_its_diagnostic_source_separately(self):
        from benchkit.sim_server import __main__ as synthetic
        expected = {"benchkit/sim_server/__main__.py", "benchkit/diagnostics/__init__.py",
                    "benchkit/diagnostics/smoke.py"}
        self.assertEqual(set(synthetic.SUPPLEMENTAL_FILES), expected)
        self.assertFalse(expected & set(SERVICE_SOURCE_FILES))
        with patch.object(synthetic, "launch", return_value=0) as launch:
            self.assertEqual(synthetic.main(["--help"]), 0)
        self.assertEqual(launch.call_args.kwargs["supplemental_sources"], synthetic.SUPPLEMENTAL_FILES)
        code = r'''
import pathlib, sys
sys.path.insert(0, sys.argv[1])
from benchkit.sim_server.__main__ import make_smoke_benchmark, SUPPLEMENTAL_FILES
from benchkit.sim_server.server import BenchmarkService
service = BenchmarkService(make_smoke_benchmark({}), root=pathlib.Path(sys.argv[2]), seed=1,
                           capture_source=True, supplemental_sources=SUPPLEMENTAL_FILES)
assert service.dispatch('describe', {})['episodes']
assert not service.sessions and not service.claims
assert not any(key.startswith(('AgentPolicies', 'benchmarks.simBenchmarks.', 'benchkit.campaigns')) for key in sys.modules)
service.close()
'''
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "site-packages"
            copy_sources(root, (*SERVICE_SOURCE_FILES, *synthetic.SUPPLEMENTAL_FILES))
            result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code,
                                     str(root), str(base / "output")],
                                    cwd=base, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_service_starts_from_only_its_sources_in_checkout_and_install_layouts(self):
        # -I -S removes cwd/PYTHONPATH/site-package fallbacks. These real wrappers
        # are imported from a deliberately incomplete standalone source tree.
        code = r'''
import importlib, json, pathlib, sys
from unittest.mock import patch
root, output, module_name, configuration = sys.argv[1:]
sys.path.insert(0, root)
class RejectUnrelated:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'AgentPolicies' or fullname.startswith(('AgentPolicies.', 'benchkit.campaigns')):
            raise AssertionError('unrelated import: ' + fullname)
sys.meta_path.insert(0, RejectUnrelated())
module = importlib.import_module(module_name)
adapter_module = importlib.import_module(module_name.rsplit('.', 1)[0] + '.bench_server.adapter')
from benchkit.sim_server.server import BenchmarkService
from benchkit.source_snapshot import SERVICE_SOURCE_FILES
factories = [value for key, value in vars(module).items() if key.startswith('make_') and callable(value)]
assert len(factories) == 1
if module_name.endswith('RoboDojo.server'):
    with patch.object(adapter_module, 'load_runtime', return_value={'python': '/unused/native/python'}):
        adapter = factories[0](json.loads(configuration))
else:
    adapter = factories[0](json.loads(configuration))
with patch.object(type(adapter), 'open_episode', side_effect=AssertionError('native open forbidden')):
    service = BenchmarkService(adapter, root=pathlib.Path(output), seed=20260907,
                               capture_source=True, supplemental_sources=module.SUPPLEMENTAL_FILES)
    description = service.dispatch('describe', {})
    assert description['episodes'] and not service.claims and not service.sessions
    source = json.loads((pathlib.Path(output) / 'harness_source/index.json').read_text())
    assert source['schema_version'] == 'starvla-rsi.harness-source/v2'
    assert {row['path'] for row in source['files']} == set(SERVICE_SOURCE_FILES)
    assert {row['path'] for row in description['source']['supplemental_files']} == set(module.SUPPLEMENTAL_FILES)
    assert not (pathlib.Path(root) / 'AgentPolicies').exists()
    assert not (pathlib.Path(root) / 'benchkit/campaigns').exists()
    service.close()
assert not any(key == 'AgentPolicies' or key.startswith(('AgentPolicies.', 'benchkit.campaigns')) for key in sys.modules)
assert not {'torch','numpy','mujoco','isaacsim','sapien','omnigibson','robosuite','libero'} & set(sys.modules)
'''
        for label, module_name in SERVICE_MODULES.items():
            module = importlib.import_module(module_name)
            directory = module_name.split('.')[2]
            configuration = (ROOT / f"benchmarks/simBenchmarks/{directory}/server.example.json").read_text()
            for layout in ("checkout", "lib/python/site-packages"):
                with self.subTest(benchmark=label, layout=layout), tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary)
                    isolated = base / layout
                    copy_sources(isolated, (*SERVICE_SOURCE_FILES, *module.SUPPLEMENTAL_FILES))
                    self.assertEqual({p.name for p in (isolated / "benchmarks/simBenchmarks").iterdir()
                                      if p.is_dir()}, {directory})
                    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code,
                                             str(isolated), str(base / "output"), module_name, configuration],
                                            cwd=base, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_selected_supplements_cover_explicit_local_runtime_imports(self):
        for module_name in SERVICE_MODULES.values():
            module = importlib.import_module(module_name)
            selected = set(SERVICE_SOURCE_FILES) | set(module.SUPPLEMENTAL_FILES)
            for filename in module.SUPPLEMENTAL_FILES:
                if not filename.endswith(".py"):
                    continue
                for node in ast.walk(ast.parse((ROOT / filename).read_text())):
                    if isinstance(node, ast.ImportFrom):
                        if node.level:
                            package = filename[:-3].split("/")[:-1]
                            target = ".".join(package[:len(package) - node.level + 1])
                            target += "." + node.module if node.module else ""
                        else:
                            target = node.module or ""
                        imports = [target, *(target + "." + alias.name for alias in node.names)]
                    elif isinstance(node, ast.Import):
                        imports = [alias.name for alias in node.names]
                    else:
                        continue
                    for target in imports:
                        if not target.startswith(("benchkit.", "benchmarks.", "AgentPolicies.")):
                            continue
                        relative = target.replace(".", "/")
                        for candidate in (relative + ".py", relative + "/__init__.py"):
                            if (ROOT / candidate).is_file():
                                self.assertIn(candidate, selected, f"{filename} imports uncaptured {candidate}")

    def test_default_full_capture_keeps_campaigns_and_drivers(self):
        expected = {path.relative_to(ROOT).as_posix() for path, _ in repository_source_files(ROOT, MAX_FILES)}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            capture_harness_source(output)
            index = json.loads((output / "harness_source/index.json").read_text())
        self.assertEqual({row["path"] for row in index["files"]}, expected)
        self.assertIn("benchkit/campaigns/workflow.py", expected)
        self.assertIn("AgentPolicies/gpt6_astra/run.py", expected)
        self.assertIn("AgentPolicies/policy_support/runner.py", expected)
        self.assertIn("benchmarks/simBenchmarks/LIBERO/bench_server/adapter.py", expected)
        self.assertIn("benchmarks/simBenchmarks/SimplerEnv/bench_server/adapter.py", expected)
        self.assertEqual(index["schema_version"], "starvla-rsi.harness-source/v2")
        self.assertIn("trusted agent drivers", index["scope"])

    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        root = base / "package-root"
        copy_sources(root, SERVICE_SOURCE_FILES)
        return base, root

    def capture(self, base, root, name="output", **options):
        output = base / name
        output.mkdir()
        result = capture_harness_source(output, source_root=root, scope="service", **options)
        return output, result

    def test_service_scope_ignores_unselected_neighbors_and_keeps_existing_audit(self):
        from benchkit.audits.closed_run import ClosedFiles, audit_source
        base, root = self.fixture()
        (root / "benchkit/credentials.json").write_text('{"not_source": true}')
        (root / "benchkit/unused.py").symlink_to(base / "missing-private-file")
        with patch.object(source_snapshot, "repository_source_files", side_effect=AssertionError("full scan forbidden")):
            output, reference = self.capture(base, root)
        index = json.loads((output / reference["path"]).read_text())
        self.assertEqual({row["path"] for row in index["files"]}, set(SERVICE_SOURCE_FILES))
        self.assertEqual(audit_source(ClosedFiles(output), {"harness_source": reference}), len(SERVICE_SOURCE_FILES))

    def test_service_scope_keeps_file_total_and_count_bounds(self):
        for limits in ({"max_file_bytes": 1}, {"max_total_bytes": 1}, {"max_files": 1}):
            with self.subTest(limits=limits):
                base, root = self.fixture()
                with self.assertRaises(SourceSnapshotError):
                    self.capture(base, root, **limits)
                self.assertFalse((base / "output/harness_source/index.json").exists())

    def test_missing_and_symlinked_selected_sources_fail_before_publish(self):
        for mode in ("missing", "file-link", "parent-link", "root-link"):
            with self.subTest(mode=mode):
                base, root = self.fixture()
                path = root / "benchkit/sim_server/server.py"
                if mode in ("missing", "file-link"):
                    path.unlink()
                    if mode == "file-link":
                        path.symlink_to(ROOT / "benchkit/sim_server/server.py")
                elif mode == "parent-link":
                    parent = path.parent
                    parent.rename(base / "moved")
                    parent.symlink_to(base / "moved", target_is_directory=True)
                else:
                    root.rename(base / "moved")
                    root.symlink_to(base / "moved", target_is_directory=True)
                with self.assertRaises(SourceSnapshotError):
                    self.capture(base, root)
                self.assertFalse((base / "output/harness_source/index.json").exists())

    def test_changed_source_and_raced_parent_remain_rejected(self):
        for mode in ("changed", "parent-link"):
            with self.subTest(mode=mode):
                base, root = self.fixture()
                original = source_snapshot.service_source_files

                def race(root, max_files):
                    selected = original(root, max_files)
                    if mode == "changed":
                        (root / "benchkit/contracts.py").write_text("CHANGED = True\n")
                    else:
                        parent = root / "benchkit/sim_server"
                        parent.rename(base / "moved")
                        parent.symlink_to(base / "moved", target_is_directory=True)
                    return selected

                with patch.object(source_snapshot, "service_source_files", side_effect=race):
                    with self.assertRaises(SourceSnapshotError):
                        self.capture(base, root)
                self.assertFalse((base / "output/harness_source/index.json").exists())

    def test_unknown_scope_fails_before_creating_snapshot(self):
        base, root = self.fixture()
        with self.assertRaisesRegex(ValueError, "scope"):
            capture_harness_source(base, source_root=root, scope="everything")
        self.assertFalse((base / "harness_source").exists())


if __name__ == "__main__":
    unittest.main()
