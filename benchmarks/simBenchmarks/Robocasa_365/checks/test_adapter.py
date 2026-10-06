"""Dependency-light native adapter boundary, budget and provenance regression checks."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import (
    ACTION_SPEC, NATIVE_HORIZONS, PILOT_SEED, PILOT_TASKS, RoboCasa365BenchmarkAdapter,
    asset_dependency_manifest, verify_git_root,
)
from benchkit.contracts import Observation
from benchkit.errors import CompatibilityError, ProtocolError
from AgentPolicies.policy_support.runner import RunRequest


class AdapterChecks(unittest.TestCase):
    def test_manifest_is_fixed_and_budget_tracks_are_distinct(self):
        native = RoboCasa365BenchmarkAdapter()
        decision = RoboCasa365BenchmarkAdapter(budget_mode="decisions", max_policy_calls=200, replan_interval=5)
        episodes = native.episodes(PILOT_SEED)
        self.assertEqual([ep.task for ep in episodes], list(PILOT_TASKS))
        self.assertEqual([ep.metadata["native_horizon"] for ep in episodes], [750, 450])
        self.assertEqual(decision.environment_step_cap, 1000)
        self.assertNotEqual(native.descriptor.protocol_version, decision.descriptor.protocol_version)
        RunRequest(Path("unused"), budget_mode="decisions", max_steps=1000, max_policy_calls=200, replan_interval=5)
        self.assertEqual(len(native.episodes(PILOT_SEED, 1)), 1)
        for candidate in (replace(episodes[0], seed=1), replace(episodes[0], metadata={})):
            with self.assertRaises(ProtocolError):
                native.open_episode(candidate)
        for seed in (0, True):
            with self.assertRaises(ValueError):
                native.episodes(seed)

    def test_illegal_selection_and_limits_are_rejected(self):
        for selected in ([], [1, 0], [0, 0], [2], [True]):
            with self.assertRaises(ValueError):
                RoboCasa365BenchmarkAdapter(task_ids=selected)
        for calls, prefix in ((0, 5), (201, 5), (200, 6), (True, 5), (200, 1.0)):
            with self.assertRaises(ValueError):
                RoboCasa365BenchmarkAdapter(budget_mode="decisions", max_policy_calls=calls, replan_interval=prefix)
        for index in (6, 11):
            action = [0.] * 12
            action[index] = 0.49
            with self.assertRaises(ValueError):
                ACTION_SPEC.validate(action)

    def test_reset_success_is_rejected_without_starting_policy_steps(self):
        adapter = RoboCasa365BenchmarkAdapter()
        session = adapter.open_episode(adapter.episodes(PILOT_SEED)[0])
        with patch.object(session, "_observe", return_value=Observation(0, "Open.")):
            with self.assertRaises(ProtocolError):
                session._finish_reset({}, True)
        self.assertIsNone(session.started_at)
        self.assertEqual(session.step_count, 0)

    def test_native_success_and_ever_are_not_substituted(self):
        adapter = RoboCasa365BenchmarkAdapter()
        session = adapter.open_episode(adapter.episodes(PILOT_SEED)[0])
        session.success = False
        session.success_ever = True
        self.assertFalse(session.metrics()["success"])
        self.assertFalse(session.metrics()["native_success_final"])
        self.assertTrue(session.metrics()["success_ever"])

    def test_decisions_do_not_truncate_at_native_reference_horizon(self):
        adapter = RoboCasa365BenchmarkAdapter(budget_mode="decisions", max_policy_calls=200, replan_interval=5)
        session = adapter.open_episode(adapter.episodes(PILOT_SEED)[1])
        session.env = SimpleNamespace(step=lambda action: ({"private": "not public"}, 0., False, False, {"success": False}))
        session.started_at = 1.
        with patch("benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter.action_dictionary", return_value={}), \
             patch.object(session, "_observe", return_value=Observation(450, "Navigate.")):
            session.step_count = NATIVE_HORIZONS["NavigateKitchen"] - 1
            transition = session.step((0.,) * 12)
            self.assertFalse(transition.truncated)
            self.assertNotIn("private", transition.observation.metadata)
            session.step_count = 999
            self.assertTrue(session.step((0.,) * 12).truncated)
            with self.assertRaises(ProtocolError):
                session.step((0.,) * 12)

    def test_native_success_ends_episode_without_second_scorer_call(self):
        adapter = RoboCasa365BenchmarkAdapter()
        session = adapter.open_episode(adapter.episodes(PILOT_SEED)[0])
        session.env = SimpleNamespace(step=lambda action: ({}, 1., False, False, {"success": True}))
        session.started_at = 1.
        with patch("benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter.action_dictionary", return_value={}), \
             patch.object(session, "_observe", return_value=Observation(1, "Open.")):
            self.assertTrue(session.step((0.,) * 12).terminated)
        self.assertTrue(session.metrics()["native_success_final"])
        self.assertEqual(session.metrics()["first_success_step"], 1)

    def test_asset_closure_and_missing_references_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "texture.png").write_bytes(b"asset content")
            (root / "included.xml").write_text('<mujoco><asset><texture file="texture.png"/></asset></mujoco>')
            xml = f'<mujoco><include file="{root / "included.xml"}"/></mujoco>'
            manifest = asset_dependency_manifest(xml, [root])
            self.assertTrue(manifest["complete"])
            self.assertEqual(manifest["file_count"], 2)
            self.assertFalse(manifest["all_benchmark_assets_verified"])
            (root / "texture.png").unlink()
            missing = asset_dependency_manifest(xml, [root])
            self.assertFalse(missing["complete"])
            self.assertTrue(missing["errors"])
            relative = asset_dependency_manifest('<mujoco><asset><mesh file="unknown.stl"/></asset></mujoco>', [root])
            self.assertFalse(relative["complete"])

    def test_parent_git_repository_cannot_attest_nested_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "native"
            root.mkdir()
            outputs = [str(root.parent), "revision", ""]
            with patch("benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter.subprocess.run",
                       side_effect=[SimpleNamespace(stdout=value) for value in outputs]) as run:
                with self.assertRaises(CompatibilityError):
                    verify_git_root(root, "revision")
                self.assertTrue(all(call.kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0" for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
