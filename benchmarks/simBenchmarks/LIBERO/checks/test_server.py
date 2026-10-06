"""Native-free LIBERO server construction; not renderer or capability tests."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from benchmarks.simBenchmarks.LIBERO import server
from benchmarks.simBenchmarks.LIBERO.bench_server.adapter import FIRST_PASS_SEED, LiberoBenchmarkAdapter
from benchkit.source_snapshot import SERVICE_SOURCE_FILES

DIRECTORY = Path(__file__).resolve().parents[1]


def example():
    return json.loads((DIRECTORY / "server.example.json").read_text())


class LiberoServerChecks(unittest.TestCase):
    def test_canonical_entrypoint_has_no_compatibility_files(self):
        from benchmarks.simBenchmarks.LIBERO.bench_server import adapter as canonical

        self.assertFalse((DIRECTORY / "adapter.py").exists())
        self.assertFalse((DIRECTORY / "evaluation/plan.py").exists())
        self.assertTrue((DIRECTORY / "bench_server/protocol/plan.py").is_file())
        self.assertIs(server.make_libero, canonical.make_libero)

    def test_nested_catalog_preserves_all_pinned_task_data(self):
        from importlib import resources
        catalog = resources.files("benchmarks.simBenchmarks.LIBERO.bench_server.protocol").joinpath(
            "libero_catalog.json")
        self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(),
                         "0081b6347bdd438a3659de222f38fec019cda593dde81b030014fe8a63cf8814")

    def test_example_selects_one_fixed_rgb_task_and_explicit_decision_track(self):
        adapter = server.make_libero(example())
        episode, = adapter.episodes(FIRST_PASS_SEED)
        self.assertEqual(adapter.descriptor.name, "libero")
        self.assertEqual(adapter.descriptor.source_revision, "8f1084e3132a39270c3a13ebe37270a43ece2a01")
        self.assertEqual(episode.task, "libero_10/task-0")
        self.assertEqual(episode.metadata["initial_state_index"], 0)
        self.assertEqual(episode.metadata["attempt"], 1)
        self.assertEqual(adapter.observation_spec.cameras, ("agentview", "robot0_eye_in_hand"))
        self.assertEqual(adapter.observation_spec.state_names, ())
        self.assertEqual(adapter.action_spec.size, 7)
        self.assertEqual((adapter.budget_mode, adapter.max_policy_calls, adapter.replan_interval),
                         ("decisions", 200, 5))
        self.assertEqual(adapter.environment_step_cap, 1000)
        self.assertEqual(adapter.native_horizon, 520)
        self.assertEqual(adapter.native_engine_horizon, 1010)

    def test_example_cannot_select_unknown_tasks_or_ambiguous_limits(self):
        for update in ({"task_ids": [0, 0]}, {"task_ids": [10]}, {"suite": "libero_plus"},
                       {"budget_mode": "horizon"}, {"max_policy_calls": True},
                       {"replan_interval": 0}, {"policy": "hidden-policy"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                server.make_libero({**example(), **update})
        adapter = server.make_libero(example())
        with self.assertRaises(ValueError):
            adapter.episodes(FIRST_PASS_SEED, 2)
        with self.assertRaises(ValueError):
            adapter.episodes(0)

    def test_entrypoint_uses_only_its_benchmark_factory(self):
        with patch.object(server, "launch", return_value=0) as launch:
            self.assertEqual(server.main(["--help"]), 0)
        launch.assert_called_once_with(server.make_libero,
                                      supplemental_sources=server.SUPPLEMENTAL_FILES,
                                      argv=["--help"])

    def test_launcher_describes_and_captures_sources_without_opening_native(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "server"
            http = Mock(server_port=8766)
            seen = []

            def connect(service, **kwargs):
                seen.append(service.dispatch("describe", {}))
                self.assertEqual(service.claims, set())
                self.assertEqual(service.sessions, {})
                self.assertEqual(service.excluded, ())
                return http

            with (patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": "s" * 48}),
                  patch("benchkit.sim_server.launch.make_http_server", side_effect=connect),
                  patch.object(LiberoBenchmarkAdapter, "open_episode", side_effect=AssertionError("native open")),
                  redirect_stdout(io.StringIO()) as stdout):
                result = server.main(["--parameters", str(DIRECTORY / "server.example.json"),
                                      "--seed", str(FIRST_PASS_SEED), "--episodes", "1",
                                      "--output-dir", str(output), "--port", "8766"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue())["native_resets"], 0)
            http.serve_forever.assert_called_once_with(poll_interval=0.25)
            http.server_close.assert_called_once()
            self.assertEqual(seen[0]["descriptor"]["name"], "libero")
            self.assertEqual(seen[0]["budget"]["environment_step_cap"], 1000)
            supplemental = seen[0]["source"]["supplemental_files"]
            self.assertEqual({row["path"] for row in supplemental}, set(server.SUPPLEMENTAL_FILES))
            index = json.loads((output / "harness_source/index.json").read_text())
            shared = {row["path"]: row for row in index["files"]}
            selected = {row["path"]: row for row in supplemental}
            self.assertEqual(set(shared), set(SERVICE_SOURCE_FILES))
            self.assertFalse(set(shared) & set(selected))
            self.assertNotIn("benchmarks/simBenchmarks/LIBERO/adapter.py", shared.keys() | selected.keys())
            # Plan assembly belongs to the separately retained campaign capture,
            # not the service runtime selected by this benchmark's wrapper.
            self.assertNotIn("benchmarks/simBenchmarks/LIBERO/bench_server/protocol/plan.py",
                             shared.keys() | selected.keys())
            for captured_root, inventory in (("harness_source/files", shared), ("service_source", selected)):
                for relative, row in inventory.items():
                    original = (DIRECTORY.parents[2] / relative).read_bytes()
                    captured = (output / captured_root / relative).read_bytes()
                    self.assertEqual(captured, original)
                    self.assertEqual(row["size_bytes"], len(captured))
                    self.assertEqual(row["sha256"], hashlib.sha256(captured).hexdigest())

    def test_example_factory_does_not_import_simulators_or_models(self):
        code = """
import json, sys
from benchmarks.simBenchmarks.LIBERO.server import make_libero
with open('benchmarks/simBenchmarks/LIBERO/server.example.json') as stream:
    adapter = make_libero(json.load(stream))
assert len(adapter.episodes(20260907)) == 1
for name in ('numpy', 'libero', 'robosuite', 'mujoco', 'torch', 'AgentPolicies'):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name
"""
        completed = subprocess.run([sys.executable, "-B", "-S", "-c", code],
                                   cwd=DIRECTORY.parents[2], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
