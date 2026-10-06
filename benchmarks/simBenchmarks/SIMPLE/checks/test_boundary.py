"""SIMPLE interface checks without Isaac, MuJoCo, torch, or historical VLA models."""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import (
    ACTION_NAMES, ACTION_SPEC, HORIZONS, SEED, TASKS, SimpleHumanoidBenchmarkAdapter,
    amo_payload, decode_action, public_observation, validate_tick_result,
)
from benchkit.errors import ProtocolError


class SimpleBoundaryTests(unittest.TestCase):
    def test_import_has_no_native_or_model_dependencies(self):
        code = "import sys; import benchmarks.simBenchmarks.SIMPLE.bench_server.adapter; "
        code += "assert not any(n in sys.modules for n in ('torch','simple','mujoco','isaacsim','decoupled_wbc'))"
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_named_36_mapping_preserves_legacy_left_hand_order(self):
        command = decode_action(list(range(36)))
        joints = command["joint_positions"]
        self.assertEqual(len(set(ACTION_NAMES)), 36)
        self.assertEqual(joints["left_hand_middle_0_joint"], 3)
        self.assertEqual(joints["left_hand_index_0_joint"], 5)
        self.assertEqual(joints["right_hand_index_0_joint"], 10)
        self.assertEqual(joints["left_shoulder_pitch_joint"], 14)
        self.assertEqual(joints["right_wrist_yaw_joint"], 27)
        self.assertEqual(joints["waist_yaw_joint"], 30)
        self.assertEqual(command["navigate_cmd"], (32, 33, 34, 35))
        self.assertEqual(command["base_height"], 31)

    def test_amo_waist_is_separate_from_fixed_native_torso(self):
        payload = amo_payload(list(range(36)), (0.11, -0.15, 0.03))
        self.assertEqual(payload["action_command"], [32, 35, 33, 30.25, 0.11, -0.15, 0.03, 34])
        self.assertEqual(payload["waist_qpos"]["waist_roll_joint"], 28)
        self.assertFalse(any(name.startswith("waist_") for name in payload["target_qpos"]))
        self.assertEqual(len(payload["target_qpos"]), 28)

    def test_actions_reject_wrong_length_nonfinite_bool_and_strings(self):
        for vector in ([0] * 7, [0] * 35, [0] * 37,
            [float("nan")] + [0] * 35, [float("inf")] + [0] * 35,
            [True] + [0] * 35, ["0"] + [0] * 35):
            with self.subTest(vector=vector), self.assertRaises((ValueError, TypeError)):
                ACTION_SPEC.validate(vector)

    def test_rgb_only_allowlist_and_copy(self):
        import numpy as np
        frame = np.ones((360, 640, 3), dtype=np.uint8)
        raw = {"head_stereo_left": frame, "head_stereo_right": frame,
            "joint_qpos": [7] * 43, "proprio": {"object_pose": [9]},
            "success": True, "reward": 1, "environment_config": "secret", "distance": 0}
        obs = public_observation(raw, 0, "native instruction")
        self.assertEqual(tuple(obs.images), ("head_stereo_left",))
        self.assertIsNone(obs.state)
        self.assertEqual(obs.metadata, {})
        frame[:] = 42
        self.assertEqual(int(obs.images["head_stereo_left"][0, 0, 0]), 1)
        for malformed in (np.zeros((360, 640, 4), dtype=np.uint8),
            np.zeros((224, 224, 3), dtype=np.uint8), np.zeros((360, 640, 3), dtype=float)):
            with self.assertRaises(ProtocolError):
                public_observation({"head_stereo_left": malformed}, 0, "instruction")

    def test_first_two_are_predetermined_not_success_selected(self):
        episodes = tuple(SimpleHumanoidBenchmarkAdapter(task_names=(task,)).episodes(SEED)[0] for task in TASKS)
        adapter = SimpleHumanoidBenchmarkAdapter()
        self.assertEqual(tuple(item.task for item in episodes), TASKS)
        self.assertEqual([item.metadata["reference_native_horizon"] for item in episodes], [400, 1000])
        self.assertTrue(all(item.metadata["dr_level"] == 0 and item.metadata["episode_index"] == 0 for item in episodes))
        with self.assertRaises(ProtocolError):
            adapter.episodes(SEED + 1)
        with self.assertRaises(ProtocolError):
            adapter.open_episode(replace(episodes[0], metadata={**episodes[0].metadata, "episode_index": 1}))
        with self.assertRaises(ValueError):
            SimpleHumanoidBenchmarkAdapter(task_names=(TASKS[0], TASKS[0]))
        with self.assertRaises(ValueError):
            SimpleHumanoidBenchmarkAdapter(task_names=TASKS)

    def test_backend_specific_names_and_distinct_sensor_budget_tracks(self):
        mp = SimpleHumanoidBenchmarkAdapter()
        sonic = SimpleHumanoidBenchmarkAdapter(task_names=(TASKS[1],))
        self.assertEqual(mp.action_spec.names[34], "turning_flag")
        self.assertEqual(sonic.action_spec.names[34], "turning_gate")
        self.assertEqual(mp.observation_spec.state_names, ACTION_NAMES[:31])
        self.assertEqual(mp.environment_step_cap, 1000)
        self.assertEqual(mp.native_horizon, 400)
        self.assertEqual(mp.budget_mode, "decisions")
        self.assertEqual((mp.max_policy_calls, mp.replan_interval), (200, 5))
        rgb = SimpleHumanoidBenchmarkAdapter(proprioception=False)
        old = SimpleHumanoidBenchmarkAdapter(proprioception=False, budget_mode="horizon")
        self.assertFalse(rgb.observation_spec.state_names)
        self.assertEqual(old.environment_step_cap, 400)
        self.assertEqual(len({a.descriptor.protocol_version for a in (mp, sonic, rgb, old)}), 4)

    def test_qpos31_track_only_exposes_measured_named_robot_joints(self):
        import numpy as np
        raw = {"head_stereo_left": np.zeros((360, 640, 3), dtype=np.uint8),
            "joint_positions": {name: index * .01 for index, name in enumerate(ACTION_NAMES[:31])},
            "base_world_pose": [42] * 7, "object_qpos": [99], "amo_obs_command": [7] * 9}
        obs = public_observation(raw, 1, "native instruction", True)
        self.assertEqual(obs.state, tuple(index * .01 for index in range(31)))
        self.assertEqual(obs.metadata, {})
        self.assertIsNone(public_observation(raw, 1, "native instruction", False).state)
        raw["joint_positions"]["object_joint"] = 0
        with self.assertRaises(ProtocolError):
            public_observation(raw, 1, "native instruction", True)
        del raw["joint_positions"]["object_joint"]
        raw["joint_positions"][ACTION_NAMES[0]] = float("nan")
        with self.assertRaises(ProtocolError):
            public_observation(raw, 1, "native instruction", True)

    def test_decision_time_limit_does_not_end_at_reference_400(self):
        import gymnasium as gym
        class FakeNative(gym.Env):
            metadata = {"max_episode_steps": 400}
            def reset(self, **kwargs):
                return {}, {}
            def step(self, action):
                return {}, 0., False, False, {}
        raw = FakeNative()
        env = gym.wrappers.TimeLimit(raw, max_episode_steps=SimpleHumanoidBenchmarkAdapter().environment_step_cap)
        env.reset()
        for _ in range(400):
            result = env.step(None)
        self.assertFalse(result[3])
        for _ in range(600):
            result = env.step(None)
        self.assertTrue(result[3])
        self.assertEqual(raw.metadata["max_episode_steps"], 400)

    def test_diagnostic_hold_not_available_to_normal_session(self):
        adapter = SimpleHumanoidBenchmarkAdapter()
        session = adapter.open_episode(adapter.episodes(SEED)[0])
        with self.assertRaises(ProtocolError):
            session.diagnostic_hold()
        session.close()

    def test_rpc_rejects_truthiness_nonfinite_and_counter_errors(self):
        valid = {"success": False, "terminated": False, "truncated": False, "reward": 0., "native_steps": 1}
        self.assertEqual(validate_tick_result(valid, 1), (False, False, False, 0.))
        for field in ("success", "terminated", "truncated"):
            for value in ("false", "true", None, 0, 1, []):
                with self.subTest(field=field, value=value), self.assertRaises(ProtocolError):
                    validate_tick_result({**valid, field: value}, 1)
        for value in ("0", None, True, float("nan"), float("inf")):
            with self.assertRaises(ProtocolError):
                validate_tick_result({**valid, "reward": value}, 1)
        for value in (True, 0, 2, "1", 1.0):
            with self.assertRaises(ProtocolError):
                validate_tick_result({**valid, "native_steps": value}, 1)

    def test_private_success_info_never_enters_observation(self):
        from benchkit.contracts import Observation
        for diagnostic in (False, True):
            adapter = SimpleHumanoidBenchmarkAdapter(diagnostic=diagnostic)
            session = adapter.open_episode(adapter.episodes(SEED)[0])
            session._rpc = Mock(return_value={"success": True, "terminated": True,
                "truncated": False, "reward": .9, "native_steps": 1})
            session._observation = Mock(return_value=Observation(1, "task"))
            transition = session.diagnostic_hold() if diagnostic else session.step([0.] * 36)
            self.assertEqual(transition.info, {"native_success": True, "native_steps": 1})
            self.assertEqual(transition.observation.metadata, {})
            self.assertIsNone(transition.observation.state)

    def test_worker_step_calls_native_step_exactly_once_and_never_scores(self):
        worker_file = Path(__file__).parents[1] / "environment/native_worker.py"
        spec = importlib.util.spec_from_file_location("simple_private_worker_test", worker_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.NativeRuntime()
            runtime.artifact_dir = Path(directory)
            runtime.raw = SimpleNamespace(_success=True)
            runtime.env = SimpleNamespace(step=Mock(return_value=({}, .7, True, False, {"oracle": True})))
            runtime._native_action = Mock(return_value="encoded-native-action")
            runtime.capture = Mock(return_value={"frame": "rgb/private.png", "instruction": "task"})
            result = runtime.step([0] * 36)
            runtime.env.step.assert_called_once_with("encoded-native-action")
            self.assertEqual(runtime.steps, 1)
            self.assertTrue(result["success"])
            self.assertNotIn("oracle", result)
            with self.assertRaises(ValueError):
                runtime.step([0] * 36)
        tree = ast.parse(worker_file.read_text())
        calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertNotIn("compute_reward", calls)
        self.assertNotIn("check_success", calls)
        self.assertNotIn("load_dataset", calls)

    def test_v2_passes_unclipped_finite_targets_to_native_amo(self):
        worker_file = Path(__file__).parents[1] / "environment/native_worker.py"
        spec = importlib.util.spec_from_file_location("simple_native_target_test", worker_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        action_module = ModuleType("simple.core.action")
        action_module.ActionCmd = lambda kind, **parameters: SimpleNamespace(type=kind, parameters=parameters)
        runtime = module.NativeRuntime()
        runtime.agent = None
        runtime.amo_torso_ypr = (0., -.15, 0.)
        # No joint-limit capability is needed to convert a public command.
        runtime.robot = SimpleNamespace()
        vector = [0.] * 36
        vector[3] = 1.5208409952754696e-06  # public measured value from the closed failed probe
        vector[14] = 4.0  # finite target outside the MJCF's physical joint range
        vector[31] = .75
        with patch.dict(sys.modules, {"simple.core.action": action_module}):
            converted = runtime._native_action(vector)
            self.assertEqual(converted.type, "eval_move_actuators")
            self.assertEqual(converted.parameters["target_qpos"][ACTION_NAMES[3]], vector[3])
            self.assertEqual(converted.parameters["target_qpos"][ACTION_NAMES[14]], 4.)
            self.assertEqual(converted.parameters["action_command"], [0., 0., 0., 0., 0., -.15, 0., 0.])
            for invalid in ([0.] * 35, [float("nan")] + vector[1:], [True] + vector[1:]):
                with self.assertRaises((ValueError, TypeError)):
                    runtime._native_action(invalid)
        self.assertEqual(vector[3], 1.5208409952754696e-06)

    def test_v2_declares_no_added_command_bounds_and_keeps_native_shape(self):
        for task in TASKS:
            adapter = SimpleHumanoidBenchmarkAdapter(task_names=(task,))
            self.assertTrue(adapter.descriptor.protocol_version.endswith("/v2"))
            self.assertIsNone(adapter.action_spec.low)
            self.assertIsNone(adapter.action_spec.high)
            values = [0.] * 36
            values[3] = 1.5208409952754696e-06
            values[31] = .75
            self.assertEqual(adapter.action_spec.validate(values), tuple(values))
            self.assertEqual(adapter.action_spec.control_hz, 50.)

    def test_service_malformed_rejection_preserves_sequence_then_accepts_raw_encoder(self):
        import numpy as np
        from benchkit.contracts import Observation, Transition
        from benchkit.sim_server.server import BenchmarkService, ServiceActionRejected
        adapter = SimpleHumanoidBenchmarkAdapter()
        image = np.zeros((360, 640, 3), dtype=np.uint8)
        def observation(step):
            return Observation(step, "fixture", images={"head_stereo_left": image}, state=(0.,) * 31)
        native = SimpleNamespace(reset=Mock(return_value=observation(0)),
            step=Mock(return_value=Transition(observation(1), 0., False, False)),
            metrics=lambda: {}, artifacts=lambda: {}, close=Mock())
        with tempfile.TemporaryDirectory() as directory, patch.object(adapter, "open_episode", return_value=native):
            service = BenchmarkService(adapter, root=Path(directory) / "service", seed=SEED)
            try:
                sid = service.dispatch("open", {"episode_id": adapter.episodes()[0].id})["session_id"]
                service.dispatch("reset", {"session_id": sid, "sequence": 0})
                with self.assertRaises(ServiceActionRejected):
                    service.dispatch("step", {"session_id": sid, "sequence": 1, "action": [0.] * 35})
                native.step.assert_not_called()
                self.assertEqual(service.sessions[sid]["sequence"], 1)
                self.assertEqual(service.sessions[sid]["state"], "running")
                action = [0.] * 36
                action[3], action[31] = 1.5208409952754696e-06, .75
                service.dispatch("step", {"session_id": sid, "sequence": 1, "action": action})
                native.step.assert_called_once_with(tuple(action))
                self.assertEqual(service.sessions[sid]["controls"], 1)
                self.assertEqual(service.sessions[sid]["sequence"], 2)
            finally:
                service.close()

    def test_initial_success_unstable_reset_and_source_drift_fail_closed(self):
        worker_file = Path(__file__).parents[1] / "environment/native_worker.py"
        spec = importlib.util.spec_from_file_location("simple_private_guard_test", worker_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.check_initial_state(False)
        module.check_initial_state(False, True)
        for success, stable in ((True, None), (True, True), (False, False), ("false", True), (None, True)):
            with self.assertRaises(ValueError):
                module.check_initial_state(success, stable)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native_source.py"
            path.write_text("first")
            expected = module.fingerprint(path)["sha256"]
            module.require_hash(path, expected)
            path.write_text("drifted")
            with self.assertRaises(ValueError):
                module.require_hash(path, expected)


    def test_operator_parameters_and_episode_limits_are_strict(self):
        from benchkit.registry import create_benchmark
        for args in ({"gpu_id": True}, {"gpu_id": -1}, {"gpu_id": "4"},
                     {"worker_timeout": float("nan")}, {"worker_timeout": 0},
                     {"worker_timeout": True}, {"diagnostic": "false"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                create_benchmark("simple_humanoid", args)
        adapter = create_benchmark("simple_humanoid")
        for limit in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                adapter.episodes(limit=limit)
        self.assertEqual(len(adapter.episodes(limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
