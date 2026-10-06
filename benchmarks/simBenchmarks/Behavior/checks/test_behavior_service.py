import json
import math
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from benchkit.errors import ProtocolError
from benchkit.sim_server.wire import encode_observation, dumps
from benchmarks.simBenchmarks.Behavior.bench_server.adapter import make_behavior
from benchmarks.simBenchmarks.Behavior.bench_server.protocol import (
    ACTION_SPEC, CAMERA_KEYS, CONTROLLER_INDICES, HORIZON, HUMAN_LENGTH, INSTANCE,
    OBSERVATION_SPEC, PROPRIO_FIELDS, STATE_NAMES,
)
from benchmarks.simBenchmarks.Behavior.bench_server.native_worker_client import NativeOperationError, NativeWorkerClient
from benchmarks.simBenchmarks.Behavior.environment.native_bridge import (
    ExternalAction, initialize_evaluator, metric_json, public_observation, validate_loaded,
)
from benchmarks.simBenchmarks.Behavior.environment.native_worker import NativeSession
from benchmarks.simBenchmarks.Behavior.environment import deployment


def raw_obs():
    return {**{key: np.zeros((224, 224, 4), dtype=np.uint8) for key in CAMERA_KEYS.values()},
            "robot_r1::proprio": np.zeros(61, dtype=np.float32),
            "task_id": np.array([0]), "robot_r1::cam_rel_poses": np.ones(21),
            "objects": {"target": [1, 2, 3]}, "reward": 1.0}


def benchmark(**overrides):
    return make_behavior({"deployment_manifest": "/not-loaded/manifest.json",
                          "deployment_manifest_sha256": "0" * 64,
                          "worker_python": "/not-loaded/python", **overrides})


class ContractTests(unittest.TestCase):
    def test_lazy_one_case_and_resolved_cap(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("no files")), patch("subprocess.Popen", side_effect=AssertionError("no worker")):
            adapter = benchmark()
            self.assertEqual(adapter.environment_step_cap, int(HUMAN_LENGTH * 1.5))
            self.assertEqual(adapter.environment_step_cap, 3224)
            self.assertEqual(adapter.required_replan_interval, 1)
            self.assertEqual(len(adapter.episodes(5)), 1)
            self.assertEqual(adapter.episodes(5)[0].metadata["native_seed"], 0)
            self.assertEqual(adapter.episodes(5)[0].metadata["native_instance"], 301)

    def test_unknown_configuration_and_schedule_rejected(self):
        for parameters in ({"max_steps": 5}, {"task": "anything"}, {"gpu_id": True},
                           {"worker_timeout": 0}, {"worker_python": "python"}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                benchmark(**parameters)
        for limit in (0, 2, True):
            with self.assertRaises(ValueError):
                benchmark().episodes(0, limit)

    def test_one_attempt_even_without_reset(self):
        adapter = benchmark()
        case = adapter.episodes(1)[0]
        adapter.open_episode(case)
        with self.assertRaises(ProtocolError):
            adapter.open_episode(case)

    def test_native_action_no_added_motion_bounds(self):
        values = (200.0,) * 23
        self.assertEqual(ACTION_SPEC.validate(values), values)
        self.assertIsNone(ACTION_SPEC.low)
        self.assertIsNone(ACTION_SPEC.high)
        for action in ([0.0] * 22, [float("nan")] * 23, [True] * 23):
            with self.assertRaises((TypeError, ValueError, ProtocolError)):
                ACTION_SPEC.validate(action)

    def test_observation_allowlist_and_alpha_only(self):
        raw = raw_obs()
        raw[CAMERA_KEYS["head"]][..., 0] = 42
        raw[CAMERA_KEYS["head"]][..., 3] = 199
        observed = public_observation(raw, 0)
        self.assertEqual(set(observed.images), set(CAMERA_KEYS))
        self.assertEqual(len(observed.state), 61)
        self.assertEqual(observed.images["head"].shape, (224, 224, 3))
        self.assertEqual(int(observed.images["head"][0, 0, 0]), 42)
        self.assertEqual(set(observed.metadata), {"state_provenance"})
        raw[CAMERA_KEYS["head"]][...] = 99
        self.assertEqual(int(observed.images["head"][0, 0, 0]), 42)
        self.assertNotIn("objects", observed.log_view())
        self.assertEqual(len(STATE_NAMES), 61)

    def test_wrong_sensor_shapes_or_state_rejected(self):
        for value in (np.zeros((224, 224, 3), np.uint8), np.zeros((224, 224, 4), np.float32)):
            raw = raw_obs()
            raw[CAMERA_KEYS["head"]] = value
            with self.assertRaises(ProtocolError):
                public_observation(raw, 0)
        for state in (np.zeros(60), np.zeros(61, dtype=int), np.full(61, np.inf)):
            raw = raw_obs()
            raw["robot_r1::proprio"] = state
            with self.assertRaises(ProtocolError):
                public_observation(raw, 0)

    def test_nonfinite_metrics_preserved_not_zero(self):
        value = metric_json({"finite": np.float32(1), "time": math.inf, "negative": -math.inf, "nan": math.nan})
        self.assertEqual(value["time"], {"native_nonfinite": "+inf"})
        self.assertEqual(value["negative"], {"native_nonfinite": "-inf"})
        self.assertEqual(value["nan"], {"native_nonfinite": "nan"})
        json.dumps(value, allow_nan=False)

    def test_native_preparation_order(self):
        evaluator = Mock()
        initialize_evaluator(evaluator)
        self.assertEqual([call[0] for call in evaluator.mock_calls], ["reset", "load_task_instance", "reset"])
        evaluator.load_task_instance.assert_called_once_with(INSTANCE)

    def test_external_bridge_consumes_one_supplied_action(self):
        bridge = ExternalAction(tuple)
        with self.assertRaises(ProtocolError):
            bridge.forward({"oracle": True})
        bridge.queue([0.0] * 23)
        with self.assertRaises(ProtocolError):
            bridge.queue([1.0] * 23)
        with self.assertRaises(ProtocolError):
            bridge.reset()
        self.assertEqual(bridge.forward({"ignored": "anything"}), (0.0,) * 23)
        self.assertEqual(bridge.calls, 1)
        bridge.reset()
        with self.assertRaises(ProtocolError):
            bridge.forward({})

    def test_loaded_controller_mapping_and_horizon_gate(self):
        cfg = {name: {"name": "JointController", "use_delta_commands": False, "use_impedances": False}
               for name in ("trunk", "arm_left", "arm_right")}
        cfg.update({name: {"name": "MultiFingerGripperController", "mode": "smooth"}
                    for name in ("gripper_left", "gripper_right")})
        cfg["base"] = {"name": "HolonomicBaseJointController"}
        robot = SimpleNamespace(action_dim=23, controller_action_idx=CONTROLLER_INDICES, model="r1pro",
                                _grasping_mode="assisted", _proprio_obs=PROPRIO_FIELDS, _controller_config=cfg)
        evaluator = SimpleNamespace(robot=robot, human_stats={"length": HUMAN_LENGTH},
                                    env=SimpleNamespace(task=SimpleNamespace(_termination_config={"max_steps": HORIZON})))
        sim = SimpleNamespace(get_physics_dt=lambda: 1 / 120, get_sim_step_dt=lambda: 1 / 30)
        self.assertEqual(validate_loaded(evaluator, sim)["action_dimension"], 23)
        robot._controller_config["arm_left"]["use_delta_commands"] = True
        with self.assertRaises(ProtocolError):
            validate_loaded(evaluator, sim)


class ExecutionTests(unittest.TestCase):
    def make_session(self, directory, delta=4, error=False):
        session = NativeSession({"artifact_dir": str(directory)})
        session.ready = True
        session.policy = ExternalAction(tuple)
        sim = SimpleNamespace(current_time_step_index=100)
        session.og = SimpleNamespace(sim=sim)
        def native_step():
            session.policy.forward({"private": True})
            sim.current_time_step_index += delta
            if error:
                raise RuntimeError("native operation failed after possible motion")
            return False, False
        session.evaluator = SimpleNamespace(step=native_step, env=SimpleNamespace(task=SimpleNamespace(success=False)))
        session.observe = lambda: session.summary()
        return session

    def test_native_control_one_call_four_ticks(self):
        with tempfile.TemporaryDirectory() as temp:
            session = self.make_session(temp)
            result = session.step([0.0] * 23)
            self.assertEqual((result["control_steps"], result["physics_ticks"], session.policy.calls), (1, 4, 1))
            self.assertFalse(result["native_episode_complete"])

    def test_post_execution_validation_failure_preserves_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            session = self.make_session(temp, delta=5)
            with self.assertRaises(ProtocolError):
                session.step([0.0] * 23)
            self.assertEqual(session.summary()["control_steps"], 1)
            self.assertEqual(session.summary()["physics_ticks"], 5)
            self.assertFalse(session.execution_unknown)
            self.assertEqual(json.loads((Path(temp) / "native_controls.jsonl").read_text())["physics_delta"], 5)

    def test_mid_native_exception_reports_uncertain_not_zero_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            session = self.make_session(temp, error=True)
            with self.assertRaises(RuntimeError):
                session.step([0.0] * 23)
            self.assertTrue(session.summary()["in_flight_native_execution_unknown"])
            self.assertEqual(session.policy.calls, 1)

    def test_invalid_action_never_calls_worker(self):
        episode = benchmark().open_episode(benchmark().episodes(1)[0])
        episode.ready = True
        episode.worker.rpc = Mock()
        with self.assertRaises((ValueError, ProtocolError)):
            episode.step([0.0])
        episode.worker.rpc.assert_not_called()

    def test_correlated_error_allows_only_cleanup_not_actions(self):
        client = NativeWorkerClient(benchmark())
        client.process = object()
        client._rpc = Mock(side_effect=NativeOperationError("native error"))
        with self.assertRaises(NativeOperationError):
            client.rpc("step", action=[0.0] * 23)
        self.assertTrue(client.poisoned)
        self.assertFalse(client.uncertain)
        client._rpc = Mock(return_value={"safe": True})
        for op in ("reset", "step"):
            with self.assertRaises(ProtocolError):
                client.rpc(op)
        self.assertEqual(client.rpc("metrics"), {"safe": True})
        self.assertEqual(client.rpc("finalize"), {"safe": True})

    def test_transport_error_forbids_all_further_rpc(self):
        client = NativeWorkerClient(benchmark())
        client.process = object()
        client._rpc = Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            client.rpc("step", action=[0.0] * 23)
        self.assertTrue(client.uncertain)
        client._rpc = Mock()
        for op in ("reset", "step", "metrics", "finalize"):
            with self.assertRaises(ProtocolError):
                client.rpc(op)
        client._rpc.assert_not_called()

    def test_close_without_worker_is_idempotent(self):
        client = NativeWorkerClient(benchmark())
        client.close()
        client.close()

    def test_partial_constructor_cleanup_closes_env_without_video_writer(self):
        class PartialEvaluator:
            def __init__(self):
                self.env = SimpleNamespace(close=Mock())

            @property
            def video_writer(self):
                return self._video_writer

            @video_writer.setter
            def video_writer(self, value):
                raise AssertionError("constructor never initialized this property")

        with tempfile.TemporaryDirectory() as temp:
            session = NativeSession({"artifact_dir": temp})
            session.evaluator = PartialEvaluator()
            receipt = session.close_prepare()["cleanup_prepared"]
            session.evaluator.env.close.assert_called_once()
            self.assertTrue(receipt["native_env_close_returned"])
            self.assertFalse(receipt["reset_completed"])
            self.assertEqual(receipt["error_types"], [])

    def test_deployment_digest_mismatch_before_native_import(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text("{}")
            with self.assertRaises(ValueError):
                deployment.verify(path, "0" * 64)

    def test_adapter_does_not_forward_private_metrics(self):
        adapter = benchmark()
        episode = adapter.open_episode(adapter.episodes(1)[0])
        episode.ready = True
        public = public_observation(raw_obs(), 1)
        result = {"observation": encode_observation(public, OBSERVATION_SPEC), "terminated": False,
                  "truncated": False, "metrics": {"control_steps": 1, "physics_ticks": 4,
                                                    "success": False, "private_object_pose": [1, 2, 3]}}
        episode.worker.rpc = Mock(return_value=result)
        transition = episode.step([0.0] * 23)
        self.assertEqual(transition.observation.log_view(), public.log_view())
        self.assertEqual(transition.info, {})
        self.assertNotIn("private_object_pose", transition.observation.metadata)

    def test_correlated_error_metrics_survive_failed_reset(self):
        adapter = benchmark()
        episode = adapter.open_episode(adapter.episodes(1)[0])
        episode.worker.error_metrics = {"control_steps": 1, "physics_ticks": 5,
                                        "in_flight_native_execution_unknown": False}
        # Reset failed after native work but before the public observation ACK.
        episode.ready = False
        self.assertEqual(episode.metrics()["control_steps"], 1)
        self.assertEqual(episode.metrics()["physics_ticks"], 5)


FAKE_CHILD = r'''
import json, os, pathlib, sys, time
root, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
for line in sys.stdin:
    request = json.loads(line)
    op = request["op"]
    with (root / "fake_requests.jsonl").open("a") as f:
        f.write(json.dumps(request) + "\n")
    response = {"protocol": request["protocol"], "id": request["id"], "ok": True,
                "result": {"echo": op}}
    if op == "close":
        prepared = {"pid": os.getpid(), "native_env_close_returned": True,
                    "reset_completed": True, "error_types": []}
        (root / "native_cleanup_prepared.json").write_text(json.dumps(prepared))
        response["result"] = {"cleanup_prepared": prepared}
        print(json.dumps(response), flush=True)
        (root / "native_shutdown.json").write_text(json.dumps({"pid": os.getpid(),
            "shutdown_started": True, "shutdown_return_observed": True}))
        break
    if mode == "timeout":
        time.sleep(30)
    elif mode == "wrong-id":
        response["id"] = "wrong"
        print(json.dumps(response), flush=True)
    elif mode == "duplicate-key":
        payload = json.dumps(response)
        print(payload[:-1] + ', "id": "duplicate"}', flush=True)
    elif mode == "unsolicited":
        sys.stdout.write(json.dumps(response) + "\n" + json.dumps(response) + "\n")
        sys.stdout.flush()
    elif mode == "operation-error":
        response = {"protocol": request["protocol"], "id": request["id"], "ok": False,
                    "error_type": "ProtocolError", "metrics": {"control_steps": 1, "physics_ticks": 5}}
        print(json.dumps(response), flush=True)
    else:
        print(json.dumps(response), flush=True)
'''


class SubprocessRPCTests(unittest.TestCase):
    def test_launch_enables_crash_handler_before_native_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "deployment.json"
            manifest.write_text(json.dumps({"source_root": str(root), "runtime": {
                "executable": sys.executable,
                "executable_sha256": deployment.digest(sys.executable)}}))
            client = NativeWorkerClient(benchmark(deployment_manifest=str(manifest),
                deployment_manifest_sha256=deployment.digest(manifest), worker_python=sys.executable))
            real_popen = subprocess.Popen
            def probe_launch(command, **kwargs):
                self.assertEqual(command[:5], [sys.executable, "-X", "faulthandler", "-B", "-m"])
                self.assertEqual(command[5], "benchmarks.simBenchmarks.Behavior.environment.native_worker")
                self.assertIs(kwargs["stderr"], client.log)
                self.assertTrue(kwargs["start_new_session"])
                for key in ("RSI_SIM_SERVER_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
                    self.assertNotIn(key, kwargs["env"])
                # Exercise the exact interpreter flags, without importing SIM.
                return real_popen(command[:4] + ["-c",
                    "import faulthandler; assert faulthandler.is_enabled(); "
                    "faulthandler.enable(); print('real-handler-enabled')"], **kwargs)
            with patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": "test-only",
                    "OPENAI_API_KEY": "test-only", "ANTHROPIC_API_KEY": "test-only"}), \
                    patch("subprocess.Popen", side_effect=probe_launch):
                client.start(root)
            self.addCleanup(self.force_reap, client)
            stdout, _ = client.process.communicate(timeout=10)
            self.assertEqual(client.process.returncode, 0)
            self.assertEqual(stdout.strip(), b"real-handler-enabled")

    def client(self, directory, mode):
        client = NativeWorkerClient(benchmark(worker_timeout=1))
        client.root = Path(directory)
        client.log = (client.root / "fake-child.log").open("wb")
        client.process = subprocess.Popen([sys.executable, "-B", "-c", FAKE_CHILD, str(directory), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=client.log,
            bufsize=0, start_new_session=True)
        self.addCleanup(self.force_reap, client)
        return client

    @staticmethod
    def force_reap(client):
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait(timeout=5)
        for stream in (client.process.stdin, client.process.stdout, client.log):
            if stream and not stream.closed:
                stream.close()

    def test_live_correlated_reply_and_graceful_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            client = self.client(temp, "valid")
            self.assertEqual(client.rpc("metrics"), {"echo": "metrics"})
            client.close()
            client.close()
            self.assertEqual(client.process.poll(), 0)
            receipt = json.loads((Path(temp) / "worker_cleanup.json").read_text())
            self.assertTrue(receipt["prepare_ack"])
            self.assertFalse(receipt["forced_termination"])
            self.assertEqual(receipt["errors"], [])

    def test_live_wrong_id_duplicate_and_unsolicited_poison_channel(self):
        for mode in ("wrong-id", "duplicate-key", "unsolicited"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                client = self.client(temp, mode)
                with self.assertRaises(Exception):
                    client.rpc("metrics")
                self.assertTrue(client.uncertain)
                with self.assertRaises(ProtocolError):
                    client.close()
                self.assertIsNotNone(client.process.poll())
                requests = (Path(temp) / "fake_requests.jsonl").read_text().splitlines()
                self.assertEqual(len(requests), 1)

    def test_live_timeout_is_not_replayed_and_child_is_reaped(self):
        with tempfile.TemporaryDirectory() as temp:
            client = self.client(temp, "timeout")
            with self.assertRaises(TimeoutError):
                client.rpc("step", action=[0.0] * 23)
            with self.assertRaises(ProtocolError):
                client.rpc("step", action=[0.0] * 23)
            with self.assertRaises(ProtocolError):
                client.close()
            self.assertIsNotNone(client.process.poll())
            self.assertEqual(len((Path(temp) / "fake_requests.jsonl").read_text().splitlines()), 1)
            receipt = json.loads((Path(temp) / "worker_cleanup.json").read_text())
            self.assertTrue(receipt["forced_termination"])

    def test_live_native_operation_error_preserves_metrics_and_clean_close(self):
        with tempfile.TemporaryDirectory() as temp:
            client = self.client(temp, "operation-error")
            with self.assertRaises(NativeOperationError):
                client.rpc("step", action=[0.0] * 23)
            self.assertEqual(client.error_metrics, {"control_steps": 1, "physics_ticks": 5})
            self.assertFalse(client.uncertain)
            with self.assertRaises(ProtocolError):
                client.rpc("step", action=[0.0] * 23)
            client.close()
            self.assertEqual(client.process.poll(), 0)
            requests = [json.loads(line) for line in (Path(temp) / "fake_requests.jsonl").read_text().splitlines()]
            self.assertEqual([row["op"] for row in requests], ["step", "close"])


if __name__ == "__main__":
    unittest.main()
