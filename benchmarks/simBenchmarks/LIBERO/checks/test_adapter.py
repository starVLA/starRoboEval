"""Dependency-light LIBERO boundary checks; no native simulator is imported."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from benchmarks.simBenchmarks.LIBERO.bench_server.adapter import (
    FIRST_PASS_SEED,
    INSTRUCTIONS,
    NATIVE_HORIZON,
    TASK_NAMES,
    LiberoBenchmarkAdapter,
    policy_observation,
    task_catalog,
)
from benchkit.contracts import Observation
from benchkit.errors import ProtocolError


class LiberoChecks(unittest.TestCase):
    def test_explicit_task_coverage_has_all_130_suite_task_entries(self) -> None:
        episodes = []
        horizons = {"libero_spatial": 220, "libero_object": 280, "libero_goal": 300,
                    "libero_90": 400, "libero_10": 520}
        for suite, row in task_catalog().items():
            adapter = LiberoBenchmarkAdapter(suite=suite, scope="task_coverage",
                                            budget_mode="decisions", max_policy_calls=200, replan_interval=5)
            selected = adapter.episodes(FIRST_PASS_SEED)
            self.assertEqual(len(selected), row["task_count"])
            self.assertEqual([episode.metadata["task_id"] for episode in selected],
                             list(range(row["task_count"])))
            self.assertEqual(adapter.native_horizon, horizons[suite])
            self.assertEqual(adapter.environment_step_cap, 1000)
            self.assertEqual(adapter.native_engine_horizon, 1010)
            self.assertIn(f"libero-task-coverage/{suite}/rgb/decision-200-prefix-5/v1",
                          adapter.descriptor.protocol_version)
            self.assertTrue(all(episode.metadata["attempt"] == 1 for episode in selected))
            self.assertTrue(all(episode.metadata["initial_state_index"] == 0 for episode in selected))
            episodes.extend(selected)
        self.assertEqual(len(episodes), 130)
        self.assertEqual(len({episode.id for episode in episodes}), 130)
        self.assertEqual(len({episode.task for episode in episodes}), 130)
        self.assertEqual(len({episode.instruction for episode in episodes}), 112)

    def test_coverage_catalog_matches_independent_read_only_inventory(self) -> None:
        inventory = json.loads((Path(__file__).parents[1] / "bench_server/protocol/phase2_task_inventory.json").read_text())
        for row in inventory["suites"]:
            self.assertEqual(task_catalog()[row["suite"]]["tasks"], row["tasks"])

    def test_coverage_is_explicit_and_cannot_change_episode_identity(self) -> None:
        with self.assertRaises(ValueError):
            LiberoBenchmarkAdapter(suite="libero_spatial")
        with self.assertRaises(ValueError):
            LiberoBenchmarkAdapter(suite="libero_plus", scope="task_coverage")
        with self.assertRaises(ValueError):
            LiberoBenchmarkAdapter(scope="all")
        adapter = LiberoBenchmarkAdapter(task_ids=[89], suite="libero_90", scope="task_coverage")
        selected = adapter.episodes(FIRST_PASS_SEED)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].task, "libero_90/task-89")
        with self.assertRaises(ProtocolError):
            adapter.open_episode(replace(selected[0], metadata={**selected[0].metadata, "suite": "libero_10"}))
        for values in ([90], [0, 0], [1, 0], [True], []):
            with self.subTest(values=values), self.assertRaises(ValueError):
                LiberoBenchmarkAdapter(task_ids=values, suite="libero_90", scope="task_coverage")

    def test_decision_track_has_distinct_identity_and_preserves_reference_horizon(self) -> None:
        adapter = LiberoBenchmarkAdapter(budget_mode="decisions", max_policy_calls=40, replan_interval=5)
        self.assertEqual(adapter.native_horizon, 520)
        self.assertEqual(adapter.evaluation_horizon, 200)
        self.assertEqual(adapter.environment_step_cap, 200)
        self.assertIn("/decision-40-prefix-5/v1", adapter.descriptor.protocol_version)
        metadata = adapter.episodes(FIRST_PASS_SEED)[0].metadata
        self.assertEqual(metadata["budget_mode"], "decisions")
        self.assertEqual(metadata["max_policy_calls"], 40)
        self.assertEqual(metadata["replan_interval"], 5)
        self.assertEqual(metadata["environment_step_cap"], 200)
        self.assertEqual(metadata["native_horizon_source"], "retained_starvla_libero10_evaluator_reference")
        extended = LiberoBenchmarkAdapter(budget_mode="decisions", max_policy_calls=240, replan_interval=5)
        self.assertEqual(extended.native_horizon, 520)
        self.assertEqual(extended.environment_step_cap, 1200)
        self.assertEqual(extended.native_engine_horizon, 1210)

    def test_decision_track_does_not_end_at_retained_horizon(self) -> None:
        adapter = LiberoBenchmarkAdapter(budget_mode="decisions", max_policy_calls=120, replan_interval=5)
        session = adapter.open_episode(adapter.episodes(FIRST_PASS_SEED)[0])

        class Native:
            def step(self, action):
                return {}, 0.0, False, {}

        session.env = Native()
        with patch("benchmarks.simBenchmarks.LIBERO.bench_server.adapter.policy_observation",
                   return_value=Observation(step=0, instruction="Move.")):
            session.step_count = NATIVE_HORIZON - 1
            self.assertFalse(session.step((0,) * 7).truncated)
            session.step_count = adapter.environment_step_cap - 1
            self.assertTrue(session.step((0,) * 7).truncated)
        self.assertEqual(session.metrics()["native_horizon"], 520)
        self.assertEqual(session.metrics()["native_steps"], 600)

    def test_invalid_or_ambiguous_decision_limits_are_rejected(self) -> None:
        for field in ("max_policy_calls", "replan_interval"):
            for value in (None, True, 0, -1, 5.0, "5"):
                arguments = {"budget_mode": "decisions", "max_policy_calls": 40, "replan_interval": 5}
                arguments[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    LiberoBenchmarkAdapter(**arguments)
        for arguments in ({"budget_mode": "steps"}, {"max_policy_calls": 40}, {"replan_interval": 5}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                LiberoBenchmarkAdapter(**arguments)

    def test_default_matrix_matches_published_first_two(self) -> None:
        adapter = LiberoBenchmarkAdapter()
        episodes = adapter.episodes(FIRST_PASS_SEED)
        manifest = json.loads((Path(__file__).parent / "fixtures/first_two_manifest.json").read_text())
        self.assertEqual(len(episodes), 2)
        self.assertEqual([episode.metadata["task_id"] for episode in episodes], [0, 1])
        self.assertEqual([row["name"] for row in manifest["tasks"]], list(TASK_NAMES[:2]))
        self.assertEqual([episode.instruction for episode in episodes], list(INSTRUCTIONS[:2]))
        self.assertEqual({episode.metadata["attempt"] for episode in episodes}, {1})
        self.assertEqual({episode.metadata["initial_state_index"] for episode in episodes}, {0})
        self.assertEqual({episode.seed for episode in episodes}, {FIRST_PASS_SEED})
        self.assertEqual(len(set(episode.id for episode in episodes)), 2)

    def test_first_five_expansion_requires_explicit_selection(self) -> None:
        adapter = LiberoBenchmarkAdapter(task_ids=[0, 1, 2, 3, 4])
        manifest = json.loads((Path(__file__).parent / "fixtures/first_five_manifest.json").read_text())
        self.assertEqual(len(adapter.episodes(FIRST_PASS_SEED)), 5)
        self.assertEqual([row["name"] for row in manifest["tasks"]], list(TASK_NAMES))
        self.assertIn("first5", adapter.descriptor.protocol_version)
        self.assertIn("first2", LiberoBenchmarkAdapter().descriptor.protocol_version)

    def test_invalid_selection_seed_and_repetition_are_rejected(self) -> None:
        for selected in ([0, 0], [1, 0], [5], [], [True], "0"):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                LiberoBenchmarkAdapter(task_ids=selected)
        adapter = LiberoBenchmarkAdapter(task_ids=[2])
        with self.assertRaises(ValueError):
            adapter.episodes(0)
        with self.assertRaises(ValueError):
            adapter.episodes(FIRST_PASS_SEED, 2)
        episode = adapter.episodes(FIRST_PASS_SEED)[0]
        with self.assertRaises(ProtocolError):
            adapter.open_episode(replace(episode, metadata={**episode.metadata, "initial_state_index": 1}))

    def test_rgb_and_qpos_are_separate_tracks(self) -> None:
        rgb = LiberoBenchmarkAdapter()
        qpos = LiberoBenchmarkAdapter(proprioception=True)
        self.assertNotEqual(rgb.descriptor.protocol_version, qpos.descriptor.protocol_version)
        self.assertEqual(rgb.observation_spec.state_names, ())
        self.assertEqual(len(qpos.observation_spec.state_names), 9)
        self.assertFalse(rgb.observation_spec.privileged)
        self.assertEqual(rgb.action_spec.validate((0,) * 7), (0.0,) * 7)
        with self.assertRaises(ValueError):
            rgb.action_spec.validate((2,) * 7)

    def test_native_success_is_used_without_exposing_native_info(self) -> None:
        adapter = LiberoBenchmarkAdapter(task_ids=[0])
        session = adapter.open_episode(adapter.episodes(FIRST_PASS_SEED)[0])

        class Native:
            def step(self, action):
                return {"secret_object_pose": [7, 8, 9]}, 1.0, True, {"oracle": "hidden"}

            def check_success(self):
                raise AssertionError("must not call the native predicate a second time")

        session.env = Native()
        with patch(
            "benchmarks.simBenchmarks.LIBERO.bench_server.adapter.policy_observation",
            return_value=Observation(step=1, instruction="Move."),
        ):
            transition = session.step((0,) * 7)
        self.assertTrue(transition.terminated)
        self.assertTrue(session.metrics()["success"])
        self.assertEqual(transition.observation.metadata, {})
        self.assertNotIn("oracle", transition.info)
        self.assertNotIn("secret_object_pose", transition.observation.log_view())
        with self.assertRaises(ProtocolError):
            session.step((0,) * 7)

    def test_native_horizon_truncates_without_success(self) -> None:
        adapter = LiberoBenchmarkAdapter(task_ids=[0])
        session = adapter.open_episode(adapter.episodes(FIRST_PASS_SEED)[0])

        class Native:
            def step(self, action):
                return {}, 0.0, False, {}

        session.env = Native()
        session.step_count = NATIVE_HORIZON - 1
        with patch(
            "benchmarks.simBenchmarks.LIBERO.bench_server.adapter.policy_observation",
            return_value=Observation(step=NATIVE_HORIZON, instruction="Move."),
        ):
            transition = session.step((0,) * 7)
        self.assertTrue(transition.truncated)
        self.assertFalse(transition.terminated)
        self.assertFalse(session.metrics()["success"])

    def test_import_and_matrix_construction_do_not_load_simulators(self) -> None:
        LiberoBenchmarkAdapter().episodes(FIRST_PASS_SEED)
        for package in ("libero", "robosuite", "mujoco", "torch"):
            self.assertNotIn(package, sys.modules)

    def test_numpy_observation_allowlist_and_exact_transform(self) -> None:
        try:
            import numpy as np
        except ImportError:
            self.skipTest("optional array check requires NumPy, no simulator")
        frame = np.zeros((256, 256, 3), dtype=np.uint8)
        frame[0, 0] = [255, 4, 8]
        raw = {
            "agentview_image": frame, "robot0_eye_in_hand_image": frame,
            "robot0_joint_pos": np.zeros(7), "robot0_gripper_qpos": np.zeros(2),
            "object-state": np.ones(33), "robot0_eef_pos": [1, 2, 3],
            "success": True, "reward": 1, "seed": 876,
        }
        observation = policy_observation(raw, 0, "Move.")
        self.assertIsNone(observation.state)
        self.assertEqual(observation.metadata, {})
        self.assertEqual(observation.images["agentview"][-1, -1].tolist(), [255, 4, 8])
        raw["agentview_image"][:] = 0
        self.assertEqual(observation.images["agentview"][-1, -1].tolist(), [255, 4, 8])
        with_state = policy_observation(raw, 0, "Move.", True)
        self.assertEqual(with_state.state, (0.0,) * 9)


if __name__ == "__main__":
    unittest.main()
