"""Adversarial adapter boundary checks; no simulator, assets, or renderer needed.

NumPy-backed cases run in the documented SimplerEnv environment. They skip when
only the standard-library core is installed. Source pin checks always run.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.simBenchmarks.SimplerEnv.bench_server import adapter
from benchkit.errors import CompatibilityError, ProtocolError

try:
    import numpy as np
except ImportError:
    np = None


class SourcePinChecks(unittest.TestCase):
    def test_decision_track_preserves_native_horizon_and_predeclares_step_cap(self):
        for task, native in (("widowx_spoon_on_towel", 60), ("google_robot_pick_horizontal_coke_can", 80)):
            with self.subTest(task=task):
                benchmark = adapter.make_simpler_env({
                    "task": task, "budget_mode": "decisions", "max_policy_calls": 40, "replan_interval": 5,
                })
                self.assertEqual(benchmark.native_horizon, native)
                self.assertEqual(benchmark.environment_step_cap, 200)
                self.assertEqual(benchmark.evaluation_horizon, 200)
                self.assertIsNone(benchmark.horizon_multiplier)
                self.assertIn("/decision-40-prefix-5/v1", benchmark.descriptor.protocol_version)
                metadata = benchmark.episodes(0)[0].metadata
                self.assertEqual(metadata["budget_mode"], "decisions")
                self.assertEqual(metadata["max_policy_calls"], 40)
                self.assertEqual(metadata["replan_interval"], 5)
                self.assertEqual(metadata["environment_step_cap"], 200)
        changed = adapter.SimplerEnvBenchmarkAdapter(
            budget_mode="decisions", max_policy_calls=80, replan_interval=5,
        )
        self.assertEqual(changed.environment_step_cap, 400)
        self.assertIn("/decision-80-prefix-5/v1", changed.descriptor.protocol_version)

    def test_invalid_or_ambiguous_decision_budget_is_rejected(self):
        for field in ("max_policy_calls", "replan_interval"):
            for value in (None, True, 0, -1, 5.0, "5"):
                arguments = {"budget_mode": "decisions", "max_policy_calls": 40, "replan_interval": 5}
                arguments[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    adapter.SimplerEnvBenchmarkAdapter(**arguments)
        for arguments in ({"budget_mode": "steps"}, {"max_policy_calls": 40}, {"replan_interval": 5},
                          {"budget_mode": "decisions", "max_policy_calls": 40, "replan_interval": 5,
                           "horizon_multiplier": 2}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                adapter.SimplerEnvBenchmarkAdapter(**arguments)

    def test_decision_track_replaces_native_time_limit_before_reset(self):
        benchmark = adapter.SimplerEnvBenchmarkAdapter(
            budget_mode="decisions", max_policy_calls=40, replan_interval=5,
        )
        session = benchmark.open_episode(benchmark.episodes(0)[0])

        class ConstructionReached(Exception):
            pass

        captured = {}

        def make(env_id, **kwargs):
            captured.update(env_id=env_id, **kwargs)
            # Stop before any simulator construction or optional dependencies.
            raise ConstructionReached

        modules = {
            "gymnasium": SimpleNamespace(spec=lambda env_id: SimpleNamespace(max_episode_steps=60), make=make),
            "mani_skill2_real2sim": SimpleNamespace(__file__="/native/mani_skill2_real2sim/__init__.py"),
            "simpler_env": SimpleNamespace(
                __file__="/native/simpler_env/__init__.py",
                ENVIRONMENT_MAP={benchmark.task: ("fixture-id", {})},
            ),
        }
        with patch.dict("sys.modules", modules), patch.object(adapter, "_revision", return_value={}):
            with self.assertRaises(ConstructionReached):
                session.reset()
        self.assertEqual(captured["max_episode_steps"], 200)
        self.assertEqual(benchmark.native_horizon, 60)

    def test_extended_horizon_has_separate_identity_and_preserves_upstream_value(self):
        original = adapter.SimplerEnvBenchmarkAdapter()
        extended = adapter.SimplerEnvBenchmarkAdapter(horizon_multiplier=2)
        self.assertEqual(original.native_horizon, 60)
        self.assertEqual(extended.native_horizon, 60)
        self.assertEqual(extended.evaluation_horizon, 120)
        self.assertNotEqual(original.descriptor.protocol_version, extended.descriptor.protocol_version)
        self.assertEqual(extended.episodes(0)[0].metadata["horizon_multiplier"], 2)
        for invalid in (True, 0, 3, 2.0, "2"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                adapter.SimplerEnvBenchmarkAdapter(horizon_multiplier=invalid)

    def test_revision_or_tracked_source_drift_is_rejected(self):
        for revision, dirty in (("wrong-revision", ""), (adapter.SIMPLER_REVISION, " M scorer.py")):
            with self.subTest(revision=revision, dirty=dirty):
                responses = [SimpleNamespace(stdout="/unopened-fixture"),
                             SimpleNamespace(stdout=revision), SimpleNamespace(stdout=dirty)]
                with patch.object(adapter.subprocess, "run", side_effect=responses):
                    with self.assertRaises(CompatibilityError):
                        adapter._revision(Path("/unopened-fixture"), adapter.SIMPLER_REVISION)

    def test_parent_git_repository_cannot_attest_a_nested_directory(self):
        with patch.object(adapter.subprocess, "run", return_value=SimpleNamespace(stdout="/parent")) as git:
            with self.assertRaises(CompatibilityError):
                adapter._revision(Path("/parent/native"), adapter.SIMPLER_REVISION)
        self.assertEqual(git.call_args.kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")

    def test_clean_native_root_is_verified_without_optional_git_locks(self):
        replies = [SimpleNamespace(stdout="/native"), SimpleNamespace(stdout=adapter.SIMPLER_REVISION),
                   SimpleNamespace(stdout="")]
        with patch.object(adapter.subprocess, "run", side_effect=replies) as git:
            self.assertFalse(adapter._revision(Path("/native"), adapter.SIMPLER_REVISION)["tracked_dirty"])
        self.assertTrue(all(call.kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0" for call in git.call_args_list))

    def test_unverifiable_checkout_does_not_continue(self):
        with patch.object(adapter.subprocess, "run", side_effect=OSError("git unavailable")):
            with self.assertRaises(CompatibilityError):
                adapter._revision(Path("/unopened-fixture"), adapter.SIMPLER_REVISION)


@unittest.skipIf(np is None, "NumPy available in SimplerEnv runtime; no simulator is required")
class ObservationAllowlistChecks(unittest.TestCase):
    def native_observation(self, camera="3rd_view_camera", joints=8):
        return {
            "image": {
                camera: {
                    "rgb": np.arange(18, dtype=np.uint8).reshape(2, 3, 3),
                    "depth": np.full((2, 3, 1), 314.0),
                    "Segmentation": np.full((2, 3, 4), 42),
                    "camera_to_world": np.eye(4),
                },
                "undeclared_oracle_camera": {"rgb": np.zeros((2, 3, 3), dtype=np.uint8)},
            },
            "agent": {"qpos": np.arange(joints, dtype=float), "qvel": [999.0], "base_pose": [123.0]},
            "extra": {"object_pose": [99.0, 98.0, 97.0], "tcp_pose": [12.0], "success": True},
            "camera_param": {"intrinsic_cv": np.eye(3), "extrinsic_cv": np.eye(4)},
            "reset_info": {"seed": 998, "object_episode": 17},
            "reward": 1000.0,
            "metadata": {"oracle_action": [1.0] * 7},
        }

    def test_rgb_track_drops_all_undeclared_native_information(self):
        raw = self.native_observation()
        observation = adapter.policy_observation(raw, "3rd_view_camera", 3, "Move the spoon.")
        self.assertEqual(set(observation.__dict__),
                         {"step", "instruction", "images", "state", "metadata", "control_feedback"})
        self.assertIsNone(observation.control_feedback)
        self.assertEqual(set(observation.images), {"3rd_view_camera"})
        self.assertIsNone(observation.state)
        self.assertEqual(observation.metadata, {})
        self.assertEqual(observation.instruction, "Move the spoon.")
        self.assertEqual(observation.step, 3)
        self.assertEqual(observation.log_view()["metadata"], {})
        expected = raw["image"]["3rd_view_camera"]["rgb"].copy()
        raw["image"]["3rd_view_camera"]["rgb"][:] = 0
        np.testing.assert_array_equal(observation.images["3rd_view_camera"], expected)

    def test_optional_proprioception_contains_only_copied_joint_encoders(self):
        for camera, joints in (("3rd_view_camera", 8), ("overhead_camera", 11)):
            with self.subTest(camera=camera):
                raw = self.native_observation(camera, joints)
                observation = adapter.policy_observation(raw, camera, 0, "Move.", proprioception=True)
                self.assertEqual(observation.state, tuple(float(value) for value in range(joints)))
                raw["agent"]["qpos"][:] = 888.0
                self.assertEqual(observation.state[0], 0.0)
                self.assertEqual(observation.metadata, {})

    def test_malformed_rgb_and_proprioception_fail_closed(self):
        for image in (np.zeros((2, 3, 4), dtype=np.uint8), np.zeros((2, 3, 3), dtype=np.float32)):
            raw = self.native_observation()
            raw["image"]["3rd_view_camera"]["rgb"] = image
            with self.subTest(shape=image.shape, dtype=image.dtype), self.assertRaises(ProtocolError):
                adapter.policy_observation(raw, "3rd_view_camera", 0, "Move.")
        for qpos in (np.zeros(7), np.array([float("nan")] * 8)):
            raw = self.native_observation()
            raw["agent"]["qpos"] = qpos
            with self.subTest(qpos=qpos), self.assertRaises(ProtocolError):
                adapter.policy_observation(raw, "3rd_view_camera", 0, "Move.", proprioception=True)


@unittest.skipIf(np is None, "NumPy available in SimplerEnv runtime; no simulator is required")
class NativeScoringChecks(unittest.TestCase):
    def test_transient_success_does_not_end_episode_or_replace_last_step_score(self):
        class NativeFixture:
            def __init__(self):
                self.unwrapped = self
                self.calls = 0

            def get_language_instruction(self):
                return "Move the spoon."

            def evaluate(self, **kwargs):
                raise AssertionError("adapter must never call the stateful scorer directly")

            def get_info(self, **kwargs):
                raise AssertionError("adapter must not query a second native score")

            def step(self, action):
                self.calls += 1
                raw = {
                    "image": {"3rd_view_camera": {"rgb": np.zeros((2, 3, 3), dtype=np.uint8)}},
                    "extra": {"object_pose": [9.0], "success": True},
                }
                success = self.calls == 1
                info = {
                    "success": np.bool_(success),
                    "episode_stats": {"consecutive_grasp": np.int64(self.calls)},
                    "object_pose": np.zeros(3),
                }
                return raw, 1.0, success, self.calls == 2, info

        benchmark = adapter.SimplerEnvBenchmarkAdapter()
        session = adapter.SimplerEnvEpisode(benchmark, benchmark.episodes(0)[0])
        native = NativeFixture()
        session.env = native
        first = session.step((0.0,) * 7)
        self.assertFalse(first.terminated)
        self.assertFalse(first.truncated)
        self.assertEqual(first.observation.metadata, {})
        self.assertTrue(session.metrics()["success"])
        second = session.step((0.0,) * 7)
        self.assertFalse(second.terminated)
        self.assertTrue(second.truncated)
        for _ in range(3):
            metrics = session.metrics()
            self.assertIs(metrics["success"], False)
            self.assertIs(metrics["success_ever"], True)
            self.assertEqual(metrics["native_steps"], 2)
        self.assertEqual(native.calls, 2)
        self.assertNotIn("object_pose", second.info)
        self.assertIsNone(metrics["success_at_native_horizon"])
        self.assertIsNone(metrics["success_at_evaluation_horizon"])

        # Capture checkpoints from the one existing step info, without a fresh
        # evaluation call, and do not replace native final-step success.
        benchmark.native_horizon = 3
        benchmark.evaluation_horizon = 4
        native.calls = 0
        session.step((0.0,) * 7)
        self.assertIs(session.metrics()["success_at_native_horizon"], True)
        session.step((0.0,) * 7)
        self.assertIs(session.metrics()["success_at_evaluation_horizon"], False)
        self.assertIs(session.metrics()["success"], False)

    def test_only_native_boolean_success_can_supply_the_score(self):
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                adapter._native_metrics({"success": value})
        with self.assertRaises(ProtocolError):
            adapter._native_metrics({"episode_stats": {"success": True}})


if __name__ == "__main__":
    unittest.main()
