"""No simulator is imported or reset; fake native objects test the boundary."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from benchkit.contracts import Observation
from benchkit.errors import CompatibilityError, ProtocolError
from benchmarks.simBenchmarks.Robotwin import server
from benchmarks.simBenchmarks.Robotwin.bench_server import adapter
from benchmarks.simBenchmarks.Robotwin.environment import deployment, runtime

DIRECTORY = Path(__file__).resolve().parents[1]
EXPECTED_STATE_NAMES = (
    *(f"measured_fl_joint{i}_rad" for i in range(1, 7)), "commanded_left_gripper_01",
    *(f"measured_fr_joint{i}_rad" for i in range(1, 7)), "commanded_right_gripper_01",
)
MEASURED_STATE = (0.1, -0.2, 0.3, -0.4, 0.5, -0.6, 0.25,
                  -0.7, 0.8, -0.9, 1.0, -1.1, 1.2, 0.75)


def example():
    return json.loads((DIRECTORY / "server.example.json").read_text())


def fake_sensor_robot():
    """Commands deliberately differ from sensed arms; grippers remain commands."""
    return SimpleNamespace(
        get_left_arm_real_jointState=Mock(return_value=list(MEASURED_STATE[:7])),
        get_right_arm_real_jointState=Mock(return_value=list(MEASURED_STATE[7:])),
        get_left_arm_jointState=Mock(side_effect=AssertionError("drive targets are not measured arms")),
        get_right_arm_jointState=Mock(side_effect=AssertionError("drive targets are not measured arms")),
        left_mplib_planner=Mock(), right_mplib_planner=Mock(),
    )


class FakeScene:
    def __init__(self):
        self.calls = 0
        self.token = object()

    def step(self):
        self.calls += 1
        return self.token


class FakeEnv:
    def __init__(self):
        self.scene = FakeScene()
        self.take_action_cnt = 0
        self.eval_success = False
        self.close_env = Mock()
        self.setup_demo = Mock()
        self.robot = fake_sensor_robot()
        self.check_success = Mock(side_effect=AssertionError("adapter must not query native scorer"))
        self.play_once = Mock(side_effect=AssertionError("expert cannot run"))
        self.actions = []

    def take_action(self, vector, action_type):
        self.actions.append((vector, action_type))
        self.take_action_cnt += 1
        for _ in range(self.take_action_cnt + 1):
            self.scene.step()


class RobotwinServerChecks(unittest.TestCase):
    def test_literal_readme_evaluator_command_parses_without_execution(self):
        from benchkit.cli import build_parser
        readme = (DIRECTORY / "README.md").read_text()
        commands = re.findall(r"```sh\n(.*?)\n```", readme, flags=re.DOTALL)
        example_command, = [command for command in commands if command.startswith("python -B -m benchkit run")]
        tokens = shlex.split(example_command.replace("\\\n", " "))
        arguments = build_parser().parse_args(tokens[4:])
        self.assertEqual(arguments.benchmark, "robotwin")
        self.assertEqual(arguments.sim_server, "http://127.0.0.1:8771")
        self.assertEqual(arguments.model_profile, "anonymous_code_agent")
        self.assertEqual(arguments.policy_args, {"directory": "/absolute/opaque-mailbox"})
        self.assertEqual((arguments.max_policy_calls, arguments.replan_interval, arguments.max_steps), (200, 5, 1000))
        self.assertEqual(arguments.budget_mode, "horizon")

    def test_factory_and_horizon_are_explicit_and_lazy(self):
        benchmark = server.make_robotwin(example())
        episode, = benchmark.episodes(20260907, 1)
        self.assertEqual(benchmark.descriptor.name, "robotwin")
        self.assertEqual(benchmark.descriptor.source_revision,
                         "content-inventory-sha256:" + runtime.NATIVE_INVENTORY_SHA256)
        self.assertEqual((episode.task, episode.metadata["native_seed"]), ("lift_pot", 100000))
        self.assertIsNone(episode.metadata["native_source_revision"])
        self.assertEqual(episode.metadata["native_horizon"], 400)
        self.assertEqual(benchmark.budget_mode, "horizon")
        self.assertIsNone(benchmark.action_spec.control_hz)
        self.assertEqual(benchmark.action_spec.size, 14)
        self.assertEqual(benchmark.action_spec.names[6], "left_gripper")
        self.assertEqual(benchmark.observation_spec.cameras, adapter.CAMERAS)
        self.assertEqual(benchmark.observation_spec.state_names, EXPECTED_STATE_NAMES)
        self.assertEqual(benchmark.observation_spec.modalities,
                         ("language", "rgb", "joint_position", "gripper_command"))
        self.assertFalse(benchmark.observation_spec.privileged)
        self.assertEqual(benchmark.descriptor.protocol_version,
                         "robotwin-local-content/clean-fixed-seed/qpos14-rgb320-state14/fast-v3")
        compat = server.make_robotwin({**example(), "renderer_runtime": runtime.COMPAT_RENDERER})
        self.assertEqual(compat.descriptor.protocol_version,
                         "robotwin-local-content/clean-fixed-seed/qpos14-rgb320-state14-oidn233/fast-v4")
        self.assertEqual(compat.observation_spec, benchmark.observation_spec)
        self.assertEqual(compat.action_spec, benchmark.action_spec)

    def test_factory_rejects_unreviewed_tracks_and_ambiguous_inputs(self):
        for update in ({"task": "all"}, {"task": ["lift_pot"]}, {"evaluation_mode": "full"},
                       {"task": "not-a-task"}, {"native_seed": True}, {"native_seed": -1},
                       {"source_root": "relative"}, {"source_root": "/tmp/../native"},
                       {"deployment_manifest_sha256": "a"}, {"budget_mode": "decisions"},
                       {"max_policy_calls": 200}, {"expert_check": True}, {"action_type": "ee"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                server.make_robotwin({**example(), **update})
        benchmark = server.make_robotwin(example())
        for seed, limit in ((True, 1), (-1, 1), (20260907, 2), (20260907, True)):
            with self.assertRaises(ValueError):
                benchmark.episodes(seed, limit)
        with self.assertRaises(ValueError):
            server.make_robotwin({})

    def test_action_validation_preserves_native_order_and_bounds(self):
        spec = server.make_robotwin(example()).action_spec
        vector = [0.0] * 14
        vector[6] = vector[13] = 1.0
        self.assertEqual(spec.validate(vector), tuple(vector))
        for bad in (True, float("nan"), 10.1):
            invalid = vector.copy()
            invalid[0] = bad
            with self.assertRaises((TypeError, ValueError)):
                spec.validate(invalid)
        vector[13] = -0.01
        with self.assertRaises(ValueError):
            spec.validate(vector)

    def test_one_service_claim_is_consumed_before_reset(self):
        benchmark = server.make_robotwin(example())
        episode, = benchmark.episodes(20260907)
        session = benchmark.open_episode(episode)
        with self.assertRaises(ProtocolError):
            benchmark.open_episode(episode)
        with self.assertRaises(ProtocolError):
            session.reset()  # No artifact root means no native imports or construction.
        self.assertTrue(session.reset_attempted)
        self.assertFalse(session.metrics()["native_reset_returned"])
        with self.assertRaises(ProtocolError):
            session.reset()

    def test_artifact_binding_rejects_closed_or_finalized_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            for terminal_method in ("close", "artifacts"):
                with self.subTest(method=terminal_method):
                    benchmark = server.make_robotwin(example())
                    episode, = benchmark.episodes(20260907)
                    session = benchmark.open_episode(episode)
                    getattr(session, terminal_method)()
                    target = Path(temporary) / terminal_method
                    with self.assertRaises(ProtocolError):
                        session.bind_artifact_dir(target)
                    self.assertFalse(target.exists())

    def test_factory_never_imports_native_or_model_packages(self):
        code = """
import json,sys
from benchmarks.simBenchmarks.Robotwin.server import make_robotwin
with open('benchmarks/simBenchmarks/Robotwin/server.example.json') as stream:
    benchmark=make_robotwin(json.load(stream))
assert len(benchmark.episodes(20260907)) == 1
for name in ('numpy','torch','sapien','mplib','curobo','envs','AgentPolicies'):
    assert not any(key==name or key.startswith(name+'.') for key in sys.modules), name
"""
        result = subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=DIRECTORY.parents[2],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_entrypoint_delegates_and_excludes_only_derived_cache(self):
        with patch.object(server, "launch", return_value=0) as launch:
            self.assertEqual(server.main(["--help"]), 0)
            launch.assert_called_once_with(server.make_robotwin, excluded_artifact_directories=("cache",),
                                           supplemental_sources=server.SUPPLEMENTAL_FILES, argv=["--help"])

    def test_launcher_is_listening_without_native_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "service"
            http = Mock(server_port=8771)
            descriptions = []

            def connect(service, **kwargs):
                self.assertFalse(service.sessions)
                self.assertFalse(service.claims)
                descriptions.append(service.dispatch("describe", {}))
                return http

            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": "x" * 48}))
                stack.enter_context(patch("benchkit.sim_server.launch.make_http_server", side_effect=connect))
                stack.enter_context(patch.object(adapter.RoboTwinBenchmarkAdapter, "open_episode", side_effect=AssertionError("native open")))
                stdout = stack.enter_context(redirect_stdout(io.StringIO()))
                result = server.main(["--parameters", str(DIRECTORY / "server.example.json"),
                                      "--seed", "20260907", "--episodes", "1", "--port", "8771",
                                      "--output-dir", str(output)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue())["native_resets"], 0)
            self.assertEqual(descriptions[0]["budget"]["budget_mode"], "horizon")
            self.assertEqual(descriptions[0]["episodes"][0]["metadata"]["native_horizon"], 400)
            self.assertEqual(descriptions[0]["observation_spec"]["state_names"], list(EXPECTED_STATE_NAMES))
            http.serve_forever.assert_called_once_with(poll_interval=0.25)
            http.server_close.assert_called_once()


class PassiveNativeInstrumentationChecks(unittest.TestCase):
    def test_scene_counter_does_not_advance_on_construction_or_reads(self):
        native = FakeScene()
        counter = runtime.SceneStepCounter(native)
        self.assertEqual((native.calls, counter.steps), (0, 0))
        self.assertIs(counter.token, native.token)
        self.assertEqual(native.calls, 0)
        self.assertIs(counter.step(), native.token)
        self.assertEqual((native.calls, counter.steps), (1, 1))
        error = RuntimeError("physics failure")
        native.step = Mock(side_effect=error)
        with self.assertRaises(RuntimeError) as caught:
            counter.step()
        self.assertIs(caught.exception, error)
        self.assertEqual(counter.steps, 1)
        native.step.assert_called_once_with()

    def test_topp_returns_exact_native_object_and_rethrows_exact_exception(self):
        result = (object(), SimpleNamespace(shape=(17, 6)), object(), object(), object())
        planner = SimpleNamespace(TOPP=Mock(return_value=result))
        events = []
        recorder = runtime.TOPPRecorder(planner, "left", events)
        path = object()
        self.assertIs(recorder.TOPP(path, 1 / 250, verbose=True), result)
        planner.TOPP.assert_called_once_with(path, 1 / 250, verbose=True)
        self.assertEqual(events, [{"side": "left", "status": "native_path", "samples": 17, "native_fallback_ticks": 0}])
        error = RuntimeError("native TOPP failed")
        planner.TOPP = Mock(side_effect=error)
        with self.assertRaises(RuntimeError) as caught:
            recorder.TOPP(path)
        self.assertIs(caught.exception, error)
        self.assertEqual(events[-1]["status"], "native_exception")
        planner.TOPP.assert_called_once_with(path)
        empty = (object(), SimpleNamespace(shape=(0, 6)), object(), object(), object())
        planner.TOPP = Mock(return_value=empty)
        self.assertIs(recorder.TOPP(path), empty)
        self.assertEqual(events[-1]["native_fallback_ticks"], 50)

    def test_jit_cache_context_is_owned_and_restores_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, cache = root / "native", root / "private-cache"
            source.mkdir()
            cache.mkdir()
            cwd = Path.cwd()
            with patch.dict(os.environ, {"TORCH_EXTENSIONS_DIR": "/previous/cache"}):
                with runtime.native_directory(source, cache):
                    self.assertEqual(Path.cwd(), source)
                    self.assertEqual(os.environ["TORCH_EXTENSIONS_DIR"], str(cache))
                self.assertEqual(Path.cwd(), cwd)
                self.assertEqual(os.environ["TORCH_EXTENSIONS_DIR"], "/previous/cache")
            with self.assertRaises(CompatibilityError):
                with runtime.native_directory(source, source / "cache"):
                    self.fail("cache inside source accepted")


class EpisodeLifecycleChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "native"
        self.source.mkdir()
        self.benchmark = server.make_robotwin({**example(), "source_root": str(self.source)})
        self.episode, = self.benchmark.episodes(20260907)
        self.session = self.benchmark.open_episode(self.episode)
        self.session.bind_artifact_dir(self.root / "artifacts")
        self.native = FakeEnv()
        self.patches = ExitStack()
        self.patches.enter_context(patch.object(runtime, "readiness", return_value={}))
        self.patches.enter_context(patch.object(runtime, "create_native", return_value=self.native))
        self.patches.enter_context(patch.object(runtime, "resolved_native_config", return_value={}))
        self.patches.enter_context(patch.object(runtime, "verify_compiled_control", return_value={}))
        self.observe = self.patches.enter_context(patch.object(self.session, "_observe", side_effect=lambda:
            Observation(step=self.session.step_count, instruction=self.episode.instruction)))

    def tearDown(self):
        self.patches.close()
        self.temporary.cleanup()

    def test_control_counter_is_not_a_physics_or_decision_counter(self):
        self.session.reset()
        self.native.setup_demo.assert_called_once_with(now_ep_num=0, seed=100000, is_test=True)
        vector = (0.0,) * 6 + (1.0,) + (0.0,) * 6 + (1.0,)
        self.session.step(vector)
        self.session.step(vector)
        metrics = self.session.metrics()
        self.assertEqual(metrics["native_steps"], 2)
        self.assertEqual(metrics["acknowledged_controls"], 2)
        self.assertEqual(metrics["policy_physics_ticks"], 5)
        self.assertIsNone(metrics["initialization_physics_ticks"])
        self.assertEqual(self.native.actions, [(vector, "qpos"), (vector, "qpos")])
        self.native.check_success.assert_not_called()
        self.native.play_once.assert_not_called()
        self.session.close()
        self.native.close_env.assert_called_once_with()
        self.session.close()
        self.assertEqual(self.native.close_env.call_count, 1)

    def test_partial_reset_is_retained_and_never_retried(self):
        error = RuntimeError("native unstable scene")
        self.native.setup_demo.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            self.session.reset()
        self.assertIs(caught.exception, error)
        metrics = self.session.metrics()
        self.assertTrue(metrics["reset_attempted"])
        self.assertFalse(metrics["native_reset_returned"])
        self.assertFalse(metrics["reset_completed"])
        self.assertEqual(metrics["native_steps"], 0)
        self.assertIsNone(metrics["initialization_physics_ticks"])
        self.native.close_env.assert_called_once_with()
        with self.assertRaises(ProtocolError):
            self.session.reset()

    def test_close_failure_is_sticky_including_after_partial_reset(self):
        self.native.setup_demo.side_effect = RuntimeError("partial reset")
        self.native.close_env.side_effect = OSError("native close failed")
        with self.assertRaises(RuntimeError):
            self.session.reset()
        with self.assertRaises(ProtocolError):
            self.session.close()
        self.native.close_env.assert_called_once_with()
        cleanup = json.loads((self.root / "artifacts/native_cleanup.json").read_text())
        self.assertFalse(cleanup["native_close_returned"])
        self.assertIn("OSError", cleanup["error_types"])

    def test_render_error_records_executed_but_unacknowledged_control(self):
        self.session.reset()
        self.observe.side_effect = RuntimeError("render failed")
        with self.assertRaises(RuntimeError):
            self.session.step((0.0,) * 14)
        self.assertEqual(self.session.metrics()["native_steps"], 1)
        self.assertEqual(self.session.metrics()["completed_native_controls"], 1)
        self.assertEqual(self.session.metrics()["acknowledged_controls"], 0)
        self.assertEqual(self.session.metrics()["policy_physics_ticks"], 2)
        with self.assertRaises(ProtocolError):
            self.session.step((0.0,) * 14)
        self.session.close()

    def test_native_cached_success_stops_without_an_extra_scorer_query(self):
        self.session.reset()
        original_control = self.native.take_action

        def succeed(vector, action_type):
            original_control(vector, action_type)
            self.native.eval_success = True

        self.native.take_action = succeed
        result = self.session.step((0.0,) * 14)
        self.assertTrue(result.terminated)
        self.assertEqual(result.reward, 1.0)
        self.assertFalse(result.truncated)
        self.native.check_success.assert_not_called()
        with self.assertRaises(ProtocolError):
            self.session.step((0.0,) * 14)
        self.session.close()

    def test_native_400_target_horizon_is_not_extended_by_runner_examples(self):
        self.session.reset()
        self.session.step_count = self.session.native_steps = self.native.take_action_cnt = 399
        result = self.session.step((0.0,) * 14)
        self.assertFalse(result.terminated)
        self.assertTrue(result.truncated)
        self.assertEqual(self.session.metrics()["native_steps"], 400)
        with self.assertRaises(ProtocolError):
            self.session.step((0.0,) * 14)
        self.session.close()

    def test_compiled_contract_failure_retains_successful_setup_but_no_reset_observation(self):
        with patch.object(runtime, "verify_compiled_control", side_effect=CompatibilityError("joint bounds changed")):
            with self.assertRaises(CompatibilityError):
                self.session.reset()
        self.assertTrue(self.session.metrics()["native_reset_returned"])
        self.assertFalse(self.session.metrics()["reset_completed"])
        self.assertEqual(self.session.metrics()["acknowledged_controls"], 0)
        self.native.close_env.assert_called_once_with()


class DeploymentChecks(unittest.TestCase):
    def test_packaged_snapshot_is_content_not_inherited_git(self):
        snapshot = deployment.reference_snapshot()
        self.assertIsNone(snapshot["native_source_revision"])
        self.assertEqual(snapshot["inventory_sha256"], runtime.NATIVE_INVENTORY_SHA256)
        self.assertEqual(len(snapshot["files"]), 2088)
        self.assertEqual(sum(row["size_bytes"] for row in snapshot["files"]), 1011813984)
        self.assertEqual(deployment.digest(runtime.RUNTIME_SNAPSHOT), runtime.RUNTIME_SNAPSHOT_SHA256)
        required = set(deployment.CONFIGS + deployment.TEMPLATES)
        self.assertTrue(required.issubset({row["path"] for row in snapshot["files"]}))

    def test_clean_track_retains_import_time_object_metadata(self):
        required = {"assets/objects/objaverse/list.json", "assets/objects/same.json"}
        self.assertTrue(required.issubset(deployment.EXTRA_FILES))
        self.assertTrue(required.issubset({row["path"] for row in deployment.reference_snapshot()["files"]}))

    def test_prepare_only_relocates_declared_templates_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            reference = root / "reference"
            reference.mkdir()
            rows = []
            for name in sorted(deployment.CONFIGS + deployment.TEMPLATES):
                path = reference / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("urdf_path: ${ASSETS_PATH}/assets/robot.urdf\n" if "_tmp" in name
                                else "urdf_path: /foreign/reference/assets/robot.urdf\n")
                rows.append({"path": name, "size_bytes": path.stat().st_size, "sha256": deployment.digest(path)})
            snapshot = {"schema_version": deployment.SNAPSHOT_SCHEMA, "native_source_revision": None,
                        "files": rows, "inventory_sha256": hashlib.sha256(deployment._canonical(rows)).hexdigest()}
            snapshot_file = root / "snapshot.json"
            snapshot_file.write_text(json.dumps(snapshot))
            with patch.object(deployment, "SNAPSHOT_FILE", snapshot_file):
                target = root / "owned-deployment"
                receipt = deployment.prepare(reference, target)
                self.assertEqual(receipt["file_count"], 4)
                self.assertEqual(receipt["status"], "content_verified_not_native_validated")
                self.assertEqual(len(receipt["derived_files"]), 2)
                self.assertIn(str(target), (target / deployment.CONFIGS[0]).read_text())
                self.assertIn("/foreign/reference", (reference / deployment.CONFIGS[0]).read_text())
                with self.assertRaises(ValueError):
                    deployment.prepare(reference, target)
                with self.assertRaises(ValueError):
                    deployment.prepare(reference, reference / "nested-deployment")
                changed = target / deployment.TEMPLATES[0]
                original = changed.read_bytes()
                changed.write_bytes(original + b"# drift\n")
                with self.assertRaises(ValueError):
                    deployment.verify(target, receipt["deployment_manifest_sha256"])
                changed.write_bytes(original)
                extra = target / "unrecorded.py"
                extra.write_text("pass\n")
                with self.assertRaises(ValueError):
                    deployment.verify(target, receipt["deployment_manifest_sha256"])
                extra.unlink()
                link = target / "unrecorded-link"
                link.symlink_to(changed)
                with self.assertRaises(ValueError):
                    deployment.verify(target, receipt["deployment_manifest_sha256"])


try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, "optional NumPy array checks require NumPy")
class RGBProjectionChecks(unittest.TestCase):
    def test_only_original_rgb_and_explicit_robot_state_leave_native_mapping(self):
        raw = {"observation": {camera: {"rgb": np.arange(240 * 320 * 3, dtype=np.uint8).reshape(240, 320, 3),
                                        "intrinsics": "private"} for camera in adapter.CAMERAS},
               "joint_action": {"vector": [42] * 14}, "endpose": [42], "success": True}
        raw["observation"]["front_camera"] = {"rgb": np.zeros((240, 320, 3), dtype=np.uint8)}
        public = adapter.policy_observation(raw, 0, "instruction", MEASURED_STATE)
        self.assertEqual(tuple(public.images), adapter.CAMERAS)
        self.assertEqual(public.state, MEASURED_STATE)
        self.assertEqual(public.metadata, {})
        self.assertIsNone(public.control_feedback)
        for camera in adapter.CAMERAS:
            self.assertTrue(np.array_equal(public.images[camera], raw["observation"][camera]["rgb"]))
            self.assertFalse(np.shares_memory(public.images[camera], raw["observation"][camera]["rgb"]))
        raw["observation"]["head_camera"]["rgb"] = np.zeros((224, 224, 3), dtype=np.uint8)
        with self.assertRaises(ProtocolError):
            adapter.policy_observation(raw, 0, "instruction", MEASURED_STATE)

    def test_projection_rejects_missing_malformed_or_nonfinite_robot_state(self):
        raw = {"observation": {camera: {"rgb": np.zeros(adapter.IMAGE_SHAPE, dtype=np.uint8)}
                               for camera in adapter.CAMERAS}}
        invalid = [None, (), MEASURED_STATE[:-1], MEASURED_STATE + (0.0,), "0" * 14,
                   {str(i): value for i, value in enumerate(MEASURED_STATE)}]
        for index, value in ((0, True), (0, np.bool_(False)), (1, float("nan")),
                             (7, float("inf")), (8, -float("inf")), (2, "0.1"), (3, 10**400),
                             (6, -0.001), (13, 1.001)):
            state = list(MEASURED_STATE)
            state[index] = value
            invalid.append(state)
        for state in invalid:
            with self.subTest(state=state), self.assertRaises(ProtocolError):
                adapter.policy_observation(raw, 0, "instruction", state)

    def test_measured_joint_state_is_not_clipped_to_action_command_bounds(self):
        raw = {"observation": {camera: {"rgb": np.zeros(adapter.IMAGE_SHAPE, dtype=np.uint8)}
                               for camera in adapter.CAMERAS}}
        state = list(MEASURED_STATE)
        state[0], state[7] = 10.01, -10.01
        public = adapter.policy_observation(raw, 0, "instruction", state)
        self.assertEqual(public.state, tuple(state))
        with self.assertRaises(ValueError):
            server.make_robotwin(example()).action_spec.validate(state)
        state[0] = 0.0
        self.assertEqual(public.state[0], 10.01)  # Public state does not alias native storage.

    def test_state_reader_uses_measured_getters_and_keeps_command_gripper_values(self):
        native = FakeEnv()
        state = runtime.robot_state(native)
        self.assertEqual(state, MEASURED_STATE)
        native.robot.get_left_arm_real_jointState.assert_called_once_with()
        native.robot.get_right_arm_real_jointState.assert_called_once_with()
        native.robot.get_left_arm_jointState.assert_not_called()
        native.robot.get_right_arm_jointState.assert_not_called()
        native.setup_demo.assert_not_called()
        native.check_success.assert_not_called()
        native.play_once.assert_not_called()
        self.assertEqual((native.scene.calls, native.take_action_cnt, native.actions), (0, 0, []))
        self.assertEqual((state[6], state[13]), (0.25, 0.75))

    def test_state_reader_rejects_each_bad_native_side_without_drive_target_fallback(self):
        for side in ("left", "right"):
            for value in (None, [], [0.0] * 6, [0.0] * 8, [True] + [0.0] * 6,
                          [float("nan")] + [0.0] * 6, [10**400] + [0.0] * 6,
                          [0.0] * 6 + [1.01]):
                native = FakeEnv()
                getattr(native.robot, f"get_{side}_arm_real_jointState").return_value = value
                with self.subTest(side=side, value=value), self.assertRaises(CompatibilityError):
                    runtime.robot_state(native)
                native.robot.get_left_arm_jointState.assert_not_called()
                native.robot.get_right_arm_jointState.assert_not_called()
                self.assertEqual(native.scene.calls, 0)

    def test_missing_measured_getter_never_falls_back_to_native_command_vector(self):
        for side in ("left", "right"):
            native = FakeEnv()
            delattr(native.robot, f"get_{side}_arm_real_jointState")
            with self.subTest(side=side), self.assertRaises(CompatibilityError):
                runtime.robot_state(native)
            native.robot.get_left_arm_jointState.assert_not_called()
            native.robot.get_right_arm_jointState.assert_not_called()
            self.assertEqual(native.scene.calls, 0)

    def test_numpy_scalar_encoders_remain_numeric_and_provenance_keeps_mixed_sources(self):
        native = FakeEnv()
        native.robot.get_left_arm_real_jointState.return_value = [np.float64(value)
                                                                for value in MEASURED_STATE[:7]]
        native.robot.get_right_arm_real_jointState.return_value = [np.float64(value)
                                                                 for value in MEASURED_STATE[7:]]
        self.assertEqual(runtime.robot_state(native), MEASURED_STATE)
        with patch.object(runtime, "robot_state", side_effect=AssertionError("provenance is static")):
            declaration = runtime.state_provenance()
        self.assertEqual(declaration["names"], list(EXPECTED_STATE_NAMES))
        self.assertEqual(declaration["measured_arm_joint_indices"], [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12])
        self.assertEqual(declaration["commanded_gripper_indices"], [6, 13])
        self.assertIn("get_qpos", declaration["measured_arm_joint_source"])
        self.assertIn("cached", declaration["commanded_gripper_source"])
        self.assertIn("not measured", declaration["commanded_gripper_semantics"])
        self.assertFalse(declaration["raw_joint_action_vector_used"])
        self.assertFalse(declaration["measured_arm_joint_clipping"])
        self.assertEqual(native.scene.calls, 0)

    def test_failing_native_getter_is_a_compatibility_error_not_a_fallback(self):
        for getter in (None, Mock(side_effect=RuntimeError("fixture sensor failure"))):
            native = FakeEnv()
            native.robot.get_left_arm_real_jointState = getter
            with self.subTest(getter=getter), self.assertRaises(CompatibilityError):
                runtime.robot_state(native)
            native.robot.get_left_arm_jointState.assert_not_called()
            native.robot.get_right_arm_jointState.assert_not_called()
            native.check_success.assert_not_called()
            self.assertEqual(native.scene.calls, 0)

    def test_observation_reads_current_state_once_without_advancing_native_control(self):
        benchmark = server.make_robotwin(example())
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        native = FakeEnv()
        native.get_obs = Mock(return_value={
            "observation": {camera: {"rgb": np.zeros(adapter.IMAGE_SHAPE, dtype=np.uint8)}
                            for camera in adapter.CAMERAS},
            "joint_action": {"vector": [42.0] * 14}, "endpose": [999.0] * 14,
            "success": True, "private_reset_seed": 123,
        })
        session.env = native
        observation = session._observe()  # No artifacts needed; no native constructor/import.
        self.assertEqual(observation.state, MEASURED_STATE)
        self.assertEqual(observation.metadata, {})
        self.assertEqual(observation.step, 0)
        native.get_obs.assert_called_once_with()
        native.robot.get_left_arm_real_jointState.assert_called_once_with()
        native.robot.get_right_arm_real_jointState.assert_called_once_with()
        self.assertEqual((native.scene.calls, native.take_action_cnt), (0, 0))
        native.setup_demo.assert_not_called()
        native.check_success.assert_not_called()
        # A later scheduled observation reads fresh sensors, not cached drive targets.
        native.robot.get_left_arm_real_jointState.return_value = [1.5] * 6 + [0.0]
        session.step_count = 3
        observed = session._observe()
        self.assertEqual(observed.state[:7], (1.5,) * 6 + (0.0,))
        self.assertEqual(observed.step, 3)
        self.assertEqual(native.scene.calls, 0)

    def test_compiled_native_bounds_must_match_authored_contract(self):
        joints = [SimpleNamespace(get_name=lambda name=name: name, get_limits=lambda: np.array([[-10., 10.]]))
                  for name in runtime.JOINT_NAMES]
        robot = SimpleNamespace(left_arm_joints=joints[:6], right_arm_joints=joints[6:],
                                left_gripper_scale=[-0.01, 0.045], right_gripper_scale=[-0.01, 0.045],
                                is_dual_arm=True, communication_flag=False)
        native = SimpleNamespace(robot=robot, step_lim=400, take_action_cnt=0,
                                 scene=SimpleNamespace(get_timestep=lambda: 1 / 250))
        receipt = runtime.verify_compiled_control(native)
        self.assertEqual(receipt["native_horizon"], 400)
        joints[0].get_limits = lambda: np.array([[-3.14, 3.14]])
        with self.assertRaises(CompatibilityError):
            runtime.verify_compiled_control(native)


if __name__ == "__main__":
    unittest.main()
