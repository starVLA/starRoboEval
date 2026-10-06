"""Offline contract/ordering checks; no native simulator or model dependencies."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import itertools
import math
import struct
import unittest
from unittest.mock import patch, Mock

import numpy as np

from benchmarks.simBenchmarks.DOMINO.bench_server.adapter import (
    DOMINOBenchmarkAdapter, DOMINOEpisode, make_domino, policy_observation,
)
from benchmarks.simBenchmarks.DOMINO.bench_server.protocol import CAMERAS, IMAGE_SHAPE, JOINT_NAMES, NATIVE_HORIZON
from benchmarks.simBenchmarks.DOMINO.environment.native_outcome import NativeOutcome
from benchmarks.simBenchmarks.DOMINO.environment.deployment import (
    digest, inventory, verify_rows, expand_asset_root_template, verify_curobo_asset_paths,
)
from benchmarks.simBenchmarks.DOMINO.environment.runtime import SceneStepCounter, verify_compiled
from benchkit.errors import CompatibilityError
from benchkit.sim_server.server import BenchmarkService


def adapter(**overrides):
    values = dict(source_root="/native/domino", deployment_manifest_sha256="a" * 64,
                  episode_manifest="/private/manifest.pkl", episode_manifest_sha256="b" * 64)
    values.update(overrides)
    return DOMINOBenchmarkAdapter(**values)


class Tracker:
    def __init__(self, env, config):
        self.env, self.steps, self.bounds = env, 0, 0

    def on_episode_start(self):
        self.env.events.append("tracker_start")

    def on_step(self):
        self.steps += 1
        self.env.events.append("metrics_step")

    def record_out_of_bounds(self):
        self.bounds += 1
        self.env.events.append("out_of_bounds_penalty")

    def get_episode_metrics(self, success, fail_reason, seed):
        return SimpleNamespace(success=success, fail_reason=fail_reason, steps_taken=self.steps,
                               max_steps=400, route_completion=100 if success else 0,
                               manipulation_score=100 if success else 0,
                               total_penalty_factor=0.5 if self.bounds else 1, penalty_events=[])


class Env:
    def __init__(self, *, dynamic=True, success=False, fail=False, contact=False,
                 stopped=False, boundary=True, stop_on_contact=True, z=None, horizon=False):
        self.events = []
        self.use_dynamic, self.eval_success, self.eval_fail = dynamic, success, fail
        self.contact, self._dynamic_object_stopped, self.boundary = contact, stopped, boundary
        self.take_action_cnt, self.step_lim = (400 if horizon else 1), 400
        self.position = 0.0
        actor = SimpleNamespace(get_pose=lambda: SimpleNamespace(p=[0, 0, self.position]))
        self.config = {"target_actor": actor, "stop_on_contact": stop_on_contact}
        if z is not None:
            self.config["check_z_threshold"] = 0.1

    def get_dynamic_motion_config(self):
        return self.config if self.use_dynamic else None

    def check_gripper_contact_dynamic_object(self):
        self.events.append("contact")
        return self.contact

    def stop_dynamic_object_motion(self):
        self.events.append("stop_motion")
        self._dynamic_object_stopped = True

    def check_dynamic_object_boundary(self):
        self.events.append("boundary")
        return self.boundary


def native_reference_checks(env, threshold, actor, start_z, stop_on_contact, tracker):
    """Independent transcription of pinned eval_policy.py:352-383.

    No service wrapper calls this oracle. Return models break / next iteration.
    Native take_action's metrics_step has already occurred before this block.
    """
    has_lifted = False
    if threshold is not None and not has_lifted:
        curr_z = actor.get_pose().p[2]
        if curr_z - start_z > threshold:
            has_lifted = True
    if env.eval_success:
        if threshold is not None and not has_lifted:
            return False, "object_not_lifted", True
        return True, None, True
    out_of_bounds = False
    if env.use_dynamic:
        if env.check_gripper_contact_dynamic_object() and stop_on_contact:
            env.stop_dynamic_object_motion()
        if not getattr(env, "_dynamic_object_stopped", False):
            if not env.check_dynamic_object_boundary():
                env.eval_fail = True
                out_of_bounds = True
    if out_of_bounds:
        tracker.record_out_of_bounds()
        return False, "out_of_bounds", True
    if env.eval_fail:
        return False, "eval_fail", True
    return False, None, env.take_action_cnt >= env.step_lim


class NativeParityTests(unittest.TestCase):
    def test_native_asset_root_substitutions_keep_single_assets_suffix(self):
        root = Path("/owned/domino")
        template = "urdf: ${ASSETS_PATH}/assets/robot.urdf\ncollision: $ASSETS_PATH/assets/collision.yml\nagain: ${ASSETS_PATH}/assets/mesh.obj\n"
        expected = "urdf: /owned/domino/assets/robot.urdf\ncollision: /owned/domino/assets/collision.yml\nagain: /owned/domino/assets/mesh.obj\n"
        self.assertEqual(expand_asset_root_template(template, root), expected)
        with self.assertRaises(ValueError):
            expand_asset_root_template("bare ASSETS_PATH is not the native token", root)
        with self.assertRaises(ValueError):
            expand_asset_root_template(template, Path("relative"))

    def test_materialized_curobo_paths_fail_before_native_import(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            urdf, collision = root / "assets/robot.urdf", root / "assets/collision.yml"
            urdf.write_text("<robot/>")
            collision.write_text("collision_spheres: {}")
            config = {"robot_cfg": {"kinematics": {"urdf_path": str(urdf), "collision_spheres": str(collision)}}}
            self.assertEqual(verify_curobo_asset_paths(root, config)["urdf_path"], str(urdf))
            for value in ("${/wrong/assets}/assets/robot.urdf", "assets/robot.urdf", str(root / "missing.urdf")):
                invalid = deepcopy(config)
                invalid["robot_cfg"]["kinematics"]["urdf_path"] = value
                with self.subTest(value=value), self.assertRaises(ValueError):
                    verify_curobo_asset_paths(root, invalid)

    def test_post_action_native_order_matrix(self):
        names = ("dynamic", "success", "fail", "contact", "stopped", "boundary", "stop_on_contact", "horizon")
        for flags in itertools.product((False, True), repeat=len(names)):
            for z in (None, 0.05, 0.2):
                values = dict(zip(names, flags), z=z)
                with self.subTest(**values):
                    env = Env(**values)
                    reference = Env(**values)
                    outcome = NativeOutcome(env, {}, Tracker)
                    reference_tracker = Tracker(reference, {})
                    reference_tracker.on_episode_start()
                    env.position = reference.position = z or 0
                    outcome.tracker.on_step()  # Native take_action already does this.
                    reference_tracker.on_step()
                    config = reference.get_dynamic_motion_config()
                    threshold = config.get("check_z_threshold") if config else None
                    actor = config["target_actor"] if config else None
                    expected = native_reference_checks(reference, threshold, actor, 0,
                                                       values["stop_on_contact"], reference_tracker)
                    outcome.after_action()
                    self.assertEqual((outcome.success, outcome.fail_reason, outcome.finished), expected)
                    self.assertEqual(env.events, reference.events)
                    self.assertEqual(outcome.tracker.steps, 1)  # No wrapper double-count.
                    self.assertEqual(outcome.tracker.bounds, reference_tracker.bounds)

    def test_check_z_actor_does_not_evaluate_missing_target_actor(self):
        env = Env(z=0.2, success=True)
        env.config["check_z_actor"] = env.config.pop("target_actor")
        result = NativeOutcome(env, {}, Tracker)
        env.position = 0.2
        result.after_action()
        self.assertTrue(result.success)

    def test_lift_memory_persists_between_controls(self):
        env = Env(z=0.2)
        outcome = NativeOutcome(env, {}, Tracker)
        env.position = 0.2
        outcome.after_action()
        env.position, env.eval_success = 0, True
        outcome.after_action()
        self.assertTrue(outcome.success)


class CompiledTimestepTests(unittest.TestCase):
    @staticmethod
    def environment(timestep):
        joints = [SimpleNamespace(get_name=Mock(return_value=name)) for name in JOINT_NAMES]
        return SimpleNamespace(
            robot=SimpleNamespace(left_arm_joints=joints[:6], right_arm_joints=joints[6:]),
            scene=SimpleNamespace(get_timestep=Mock(return_value=timestep), set_timestep=Mock(), step=Mock()),
            step_lim=NATIVE_HORIZON, take_action_cnt=0, setup_demo=Mock(), take_action=Mock())

    def test_exact_and_native_float32_timestep_pass_without_native_mutation(self):
        rounded = struct.unpack("!f", struct.pack("!f", 1 / 250))[0]
        self.assertEqual(rounded, 0.004000000189989805)
        # This is the original initialization defect, reproduced without SAPIEN.
        self.assertFalse(math.isclose(rounded, 1 / 250, abs_tol=1e-10))
        for timestep in (1 / 250, rounded, np.float32(1 / 250)):
            with self.subTest(timestep=timestep):
                env = self.environment(timestep)
                self.assertEqual(verify_compiled(env), {
                    "joint_names": list(JOINT_NAMES), "physics_timestep_s": 1 / 250,
                    "action_type": "qpos", "native_horizon": NATIVE_HORIZON,
                    "ticks_per_control": "variable native TOPP interpolation"})
                env.scene.get_timestep.assert_called_once_with()
                for method in (env.scene.set_timestep, env.scene.step, env.setup_demo, env.take_action):
                    method.assert_not_called()
                self.assertEqual((env.step_lim, env.take_action_cnt), (400, 0))

    def test_half_binary32_ulp_boundary_is_not_a_general_frequency_tolerance(self):
        # At 0.004 the binary32 spacing is 2^-31; half is exactly 2^-32.
        lower, upper = 1 / 250 - 2**-32, 1 / 250 + 2**-32
        for timestep in (lower, upper):
            with self.subTest(boundary=timestep):
                verify_compiled(self.environment(timestep))
        for timestep in (math.nextafter(lower, -math.inf), math.nextafter(upper, math.inf)):
            with self.subTest(outside=timestep), self.assertRaises(CompatibilityError):
                verify_compiled(self.environment(timestep))

    def test_adjacent_float32_values_and_invalid_timesteps_still_fail(self):
        bits = struct.unpack("!I", struct.pack("!f", 1 / 250))[0]
        adjacent = tuple(struct.unpack("!f", struct.pack("!I", bits + delta))[0] for delta in (-1, 1))
        for timestep in (*adjacent, 1 / 240, 1 / 251, 0.0, -1 / 250, True, False,
                         float("nan"), float("inf"), -float("inf")):
            with self.subTest(timestep=timestep), self.assertRaises(CompatibilityError):
                verify_compiled(self.environment(timestep))

    def test_other_compiled_contract_guards_are_unchanged(self):
        rounded = struct.unpack("!f", struct.pack("!f", 1 / 250))[0]
        cases = ("joint_order", "horizon", "started_control")
        for case in cases:
            env = self.environment(rounded)
            if case == "joint_order":
                env.robot.left_arm_joints[0].get_name.return_value = "wrong_joint"
            elif case == "horizon":
                env.step_lim += 1
            else:
                env.take_action_cnt = 1
            with self.subTest(case=case), self.assertRaises(CompatibilityError):
                verify_compiled(env)


class ContractTests(unittest.TestCase):
    def test_service_describe_exposes_native_cap_without_reset(self):
        with TemporaryDirectory() as directory:
            value = adapter()
            service = BenchmarkService(value, root=Path(directory) / "service", seed=0)
            self.assertEqual(service.description["budget"]["environment_step_cap"], 400)
            self.assertEqual(service.description["budget"]["required_replan_interval"], 1)
            self.assertFalse(value.claimed)

    def test_construct_and_schedule_do_not_read_native_files(self):
        value = adapter()
        self.assertEqual(value.descriptor.name, "domino")
        self.assertEqual(value.required_replan_interval, 1)
        self.assertEqual(value.episodes(0)[0].metadata["native_horizon"], 400)
        session = value.open_episode(value.episodes(0)[0])
        self.assertFalse(session.reset_attempted)
        with self.assertRaises(Exception):
            value.open_episode(value.episodes(0)[0])

    def test_parameters_reject_unsupported_tracks(self):
        for values in ({"task": "lift_pot"}, {"evaluation_mode": "full"},
                       {"native_seed": True}, {"source_root": "relative"},
                       {"episode_manifest_sha256": "no"}):
            with self.subTest(**values), self.assertRaises(ValueError):
                adapter(**values)
        with self.assertRaises(ValueError):
            make_domino({"expert": True})

    def test_no_added_motion_or_joint_guard(self):
        spec = adapter().action_spec
        self.assertIsNone(spec.low)
        self.assertEqual(spec.validate([12345.] * 14), (12345.,) * 14)
        for values in ([0.] * 13, [False] * 14, [float("nan")] * 14):
            with self.assertRaises((ValueError, TypeError)):
                spec.validate(values)

    def test_public_allowlist_and_copy(self):
        raw = {"observation": {camera: {"rgb": np.zeros(IMAGE_SHAPE, np.uint8), "object_pose": "secret"}
                               for camera in CAMERAS},
               "joint_action": {"vector": np.arange(14, dtype=float)},
               "score": 100, "dynamic_motion_info": "secret"}
        result = policy_observation(raw, 0)
        self.assertEqual(result.state, tuple(float(i) for i in range(14)))
        self.assertEqual(set(result.images), set(CAMERAS))
        self.assertNotIn("secret", str(result.log_view()))
        raw["observation"][CAMERAS[0]]["rgb"][0, 0, 0] = 255
        self.assertEqual(result.images[CAMERAS[0]][0, 0, 0], 0)
        self.assertTrue(all(name.startswith("commanded_target_") for name in adapter().observation_spec.state_names))

    def test_bad_native_state_and_images_fail_closed(self):
        for bad in (None, [0.] * 13, [float("nan")] * 14, [True] * 14):
            raw = {"observation": {c: {"rgb": np.zeros(IMAGE_SHAPE, np.uint8)} for c in CAMERAS},
                   "joint_action": {"vector": bad}}
            with self.assertRaises((ValueError, TypeError, RuntimeError)):
                policy_observation(raw, 0)

    def test_early_diagnostic_not_completed_native_score(self):
        value = adapter()
        session = DOMINOEpisode(value, value.episodes(0)[0])
        self.assertFalse(session.metrics()["native_score_complete"])
        session.native_terminal = True
        self.assertTrue(session.metrics()["native_score_complete"])
        session.control_error = True
        self.assertFalse(session.metrics()["native_score_complete"])

    def test_ack_control_physics_and_native_metrics_counts(self):
        value = adapter()
        session = DOMINOEpisode(value, value.episodes(0)[0])
        env = Env()
        env.take_action_cnt = 0
        env.scene = SimpleNamespace(step=lambda: None)
        session.counter = SceneStepCounter(env.scene)
        env.scene = session.counter
        raw = {"observation": {c: {"rgb": np.zeros(IMAGE_SHAPE, np.uint8)} for c in CAMERAS},
               "joint_action": {"vector": np.zeros(14)}}
        env.get_obs = lambda: raw
        received = []

        def take_action(values, action_type):
            received.append((values, action_type))
            env.take_action_cnt += 1
            for _ in range(3):
                env.scene.step()
            env._metrics_tracker.on_step()

        env.take_action = take_action
        session.env = env
        session.outcome = NativeOutcome(env, {}, Tracker)
        session.reset_completed = True
        session.cache = Path("/owned/cache")
        with patch("benchmarks.simBenchmarks.DOMINO.environment.runtime.native_directory", return_value=nullcontext()):
            result = session.step([12345.] * 14)
        self.assertEqual(received, [((12345.,) * 14, "qpos")])
        self.assertEqual((session.step_count, session.native_steps, session.acknowledged_controls, session.physics_ticks), (1, 1, 1, 3))
        self.assertEqual(session.outcome.tracker.steps, 1)
        self.assertFalse(result.terminated)
        self.assertFalse(session.metrics()["native_score_complete"])
        with self.assertRaises(ValueError):
            session.step([0.] * 13)
        self.assertEqual(len(received), 1)

    def test_native_error_is_not_replayed(self):
        value = adapter()
        session = DOMINOEpisode(value, value.episodes(0)[0])
        env = Env()
        env.take_action_cnt = 0
        session.counter = SceneStepCounter(SimpleNamespace(step=lambda: None))
        session.env, session.reset_completed, session.cache = env, True, Path("/owned/cache")
        def fail(values, action_type):
            env.take_action_cnt += 1
            raise RuntimeError("uncertain native action")
        env.take_action = fail
        with patch("benchmarks.simBenchmarks.DOMINO.environment.runtime.native_directory", return_value=nullcontext()):
            with self.assertRaises(RuntimeError):
                session.step([0.] * 14)
            with self.assertRaises(RuntimeError):
                session.step([0.] * 14)
        self.assertEqual((session.native_steps, session.acknowledged_controls), (1, 0))
        self.assertTrue(session.control_error)
        self.assertFalse(session.metrics()["native_score_complete"])

    def test_bad_derived_config_does_not_import_or_instantiate_native(self):
        value = adapter()
        session = value.open_episode(value.episodes(0)[0])
        prefix = "benchmarks.simBenchmarks.DOMINO.environment.runtime."
        with TemporaryDirectory() as directory:
            session.bind_artifact_dir(Path(directory))
            with patch(prefix + "native_directory", return_value=nullcontext()), \
                    patch(prefix + "readiness", return_value={}), \
                    patch(prefix + "resolved_config", side_effect=ValueError("invalid asset path")), \
                    patch(prefix + "import_native") as imported:
                with self.assertRaisesRegex(ValueError, "invalid asset path"):
                    session.reset()
                imported.assert_not_called()
            self.assertFalse(session.reset_completed)
            self.assertEqual(session.acknowledged_controls, 0)

    def test_partial_reset_failure_cleanup_is_once(self):
        value = adapter()
        session = DOMINOEpisode(value, value.episodes(0)[0])
        env = SimpleNamespace(setup_demo=Mock(side_effect=RuntimeError("partial reset failed")),
                              close_env=Mock(), release_episode_resources=Mock())
        prefix = "benchmarks.simBenchmarks.DOMINO.environment.runtime."
        with TemporaryDirectory() as directory:
            session.bind_artifact_dir(Path(directory))
            with patch(prefix + "native_directory", return_value=nullcontext()), \
                    patch(prefix + "readiness", return_value={}), \
                    patch(prefix + "import_native", return_value=(lambda: env, Tracker, object)), \
                    patch(prefix + "resolved_config", return_value={}), \
                    patch(prefix + "load_entry", return_value={"dynamic_motion_info": {}}):
                with self.assertRaisesRegex(RuntimeError, "partial reset failed"):
                    session.reset()
                session.close()
                with self.assertRaises(RuntimeError):
                    session.reset()
            env.close_env.assert_called_once()
            env.release_episode_resources.assert_called_once()
            self.assertFalse(session.reset_completed)
            self.assertEqual(session.acknowledged_controls, 0)

    def test_full_mocked_reset_two_controls_close(self):
        value = adapter()
        session = value.open_episode(value.episodes(0)[0])
        env = Env()
        env.take_action_cnt = 0
        env.scene = SimpleNamespace(step=lambda: None)
        env.setup_demo = Mock()
        env.set_instruction = Mock()
        env.init_dynamic_motion_for_eval = Mock(return_value=True)
        env.close_env, env.release_episode_resources = Mock(), Mock()
        raw = {"observation": {c: {"rgb": np.zeros(IMAGE_SHAPE, np.uint8)} for c in CAMERAS},
               "joint_action": {"vector": np.zeros(14)}}
        def control(values, action_type):
            env.take_action_cnt += 1
            for _ in range(3):
                env.scene.step()
            env._metrics_tracker.on_step()
        env.take_action = Mock(side_effect=control)
        prefix = "benchmarks.simBenchmarks.DOMINO.environment.runtime."
        with TemporaryDirectory() as directory:
            session.bind_artifact_dir(Path(directory))
            with patch(prefix + "native_directory", return_value=nullcontext()), \
                    patch(prefix + "readiness", return_value={}), \
                    patch(prefix + "import_native", return_value=(lambda: env, Tracker, object)), \
                    patch(prefix + "resolved_config", return_value={}), \
                    patch(prefix + "load_entry", return_value={"dynamic_motion_info": {"private": "motion"}}), \
                    patch(prefix + "verify_compiled", return_value={}), \
                    patch(prefix + "verify_loaded_renderer", return_value=[]), \
                    patch.object(session, "_observe", side_effect=lambda: policy_observation(raw, session.step_count)):
                self.assertEqual(session.reset().step, 0)
                self.assertEqual(session.step([0.] * 14).observation.step, 1)
                self.assertEqual(session.step([0.] * 14).observation.step, 2)
                self.assertEqual(session.outcome.tracker.steps, 2)
                self.assertEqual((session.native_steps, session.acknowledged_controls, session.physics_ticks), (2, 2, 6))
                self.assertFalse(session.metrics()["native_score_complete"])
                session.artifacts()
                session.close()
                session.close()
            env.setup_demo.assert_called_once()
            env.init_dynamic_motion_for_eval.assert_called_once()
            self.assertEqual(env.take_action.call_count, 2)
            env.close_env.assert_called_once()
            env.release_episode_resources.assert_called_once()
            self.assertTrue((Path(directory) / "native_cleanup.json").is_file())

    def test_release_runs_after_close_error_and_is_not_repeated(self):
        value = adapter()
        session = DOMINOEpisode(value, value.episodes(0)[0])
        env = SimpleNamespace(close_env=Mock(side_effect=RuntimeError("close failed")),
                              release_episode_resources=Mock())
        session.env, session.cache = env, Path("/owned/cache")
        with patch("benchmarks.simBenchmarks.DOMINO.environment.runtime.native_directory", return_value=nullcontext()):
            with self.assertRaises(RuntimeError):
                session.close()
            with self.assertRaises(RuntimeError):
                session.close()
        env.close_env.assert_called_once()
        env.release_episode_resources.assert_called_once()

    def test_observation_failure_keeps_native_counts_but_no_ack(self):
        value = adapter()
        session = DOMINOEpisode(value, value.episodes(0)[0])
        env = Env()
        env.take_action_cnt = 0
        session.env, session.cache, session.reset_completed = env, Path("/owned/cache"), True
        session.counter = SceneStepCounter(SimpleNamespace(step=lambda: None))
        session.outcome = NativeOutcome(env, {}, Tracker)
        def take_action(values, action_type):
            env.take_action_cnt += 1
            session.counter.step()
            env._metrics_tracker.on_step()
        env.take_action = take_action
        with patch("benchmarks.simBenchmarks.DOMINO.environment.runtime.native_directory", return_value=nullcontext()), \
                patch.object(session, "_observe", side_effect=RuntimeError("video failed")):
            with self.assertRaisesRegex(RuntimeError, "video failed"):
                session.step([0.] * 14)
        self.assertEqual((session.native_steps, session.step_count, session.acknowledged_controls, session.physics_ticks), (1, 1, 0, 1))
        self.assertTrue(session.control_error)
        self.assertEqual(session.metrics()["metrics_tracker_steps"], 1)

    def test_native_swallowed_tracker_error_is_detected(self):
        value = adapter()
        session = DOMINOEpisode(value, value.episodes(0)[0])
        env = Env()
        env.take_action_cnt = 0
        session.env, session.cache, session.reset_completed = env, Path("/owned/cache"), True
        session.counter = SceneStepCounter(SimpleNamespace(step=lambda: None))
        session.outcome = NativeOutcome(env, {}, Tracker)
        def missing_hook(values, action_type):
            env.take_action_cnt += 1
        env.take_action = missing_hook
        with patch("benchmarks.simBenchmarks.DOMINO.environment.runtime.native_directory", return_value=nullcontext()):
            with self.assertRaisesRegex(RuntimeError, "tracker count"):
                session.step([0.] * 14)
        self.assertEqual((session.native_steps, session.acknowledged_controls), (1, 0))
        self.assertEqual(session.metrics()["metrics_tracker_steps"], 0)

    def test_unknown_bytecode_is_not_ignored_by_inventory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("pass\n")
            rows = inventory(root)
            (root / "source.pyc").write_bytes(b"untracked executable bytes")
            with self.assertRaises(ValueError):
                verify_rows(root, rows)

    def test_symlinks_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("pass\n")
            (root / "alias.py").symlink_to(root / "source.py")
            with self.assertRaises(ValueError):
                inventory(root)


if __name__ == "__main__":
    unittest.main()
