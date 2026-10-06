"""Fake native objects only; optional helper check executes pure verified math."""
from __future__ import annotations

import ast
import base64
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from benchkit.contracts import Observation
from benchkit.errors import CompatibilityError, ProtocolError
from benchmarks.simBenchmarks.calvin import server
from benchmarks.simBenchmarks.calvin.bench_server import adapter
from benchmarks.simBenchmarks.calvin.environment import runtime

DIRECTORY = Path(__file__).resolve().parents[1]


def example():
    return json.loads((DIRECTORY / "server.example.json").read_text())


def fnv_unicode(value):
    result = 0
    for byte in value.encode("utf-16le"):
        result = ((result * 16777619) & 0xffffffff) ^ byte
    return result


class FakeNative:
    def __init__(self, outcomes=()):
        self.trace = SimpleNamespace(phase="construction",
                                    completed_ticks={"construction": 0, "reset": 0, "control": 0},
                                    started_ticks={"construction": 0, "reset": 0, "control": 0})
        self.actions, self.baselines, self.oracle_calls = [], [], []
        self.outcomes = iter(outcomes)
        self.private = {"scene_obs": "never public", "rgb_obs": {}, "future_tasks": "never public"}
        self.env = SimpleNamespace(reset=Mock(side_effect=self.reset), step=Mock(side_effect=self.step),
                                   get_info=Mock(side_effect=self.get_info))
        self.oracle = SimpleNamespace(get_task_info_for_set=Mock(side_effect=self.oracle_query))
        self.construct = Mock()
        self.close = Mock(return_value=({"constructed": True, "native_close_returned": True}, []))

    def reset(self, **kwargs):
        self.trace.started_ticks["reset"] += 1
        self.trace.completed_ticks["reset"] += 1
        return self.private

    def get_info(self):
        baseline = object()
        self.baselines.append(baseline)
        return baseline

    def step(self, action):
        self.actions.append(tuple(action))
        self.trace.started_ticks["control"] += 8
        self.trace.completed_ticks["control"] += 8
        return self.private, 0, False, object()

    def oracle_query(self, baseline, current, tasks):
        self.oracle_calls.append((baseline, current, tasks))
        return set(tasks) if next(self.outcomes, False) else set()


def session_fixture(outcomes=()):
    benchmark = server.make_calvin(example())
    episode, = benchmark.episodes(20260907, 1)
    session = benchmark.open_episode(episode)
    native = FakeNative(outcomes)
    session.native, session.trace = native, native.trace
    session.reset_attempted = session.native_reset_returned = session.reset_completed = True
    session.native_outcome = "in_progress"
    session.start_info = native.get_info()
    session._observe = lambda raw: Observation(step=session.step_count,
        instruction=benchmark.sequence["instructions"][session.subtask_index])
    return session, native


class CalvinServerChecks(unittest.TestCase):
    def test_factory_is_lazy_and_declares_debug_prefix_and_native_ceiling(self):
        benchmark = server.make_calvin(example())
        episode, = benchmark.episodes(20260907, 1)
        self.assertEqual(benchmark.descriptor.name, "calvin")
        self.assertEqual(benchmark.descriptor.source_revision, runtime.NATIVE_REVISION)
        self.assertEqual(benchmark.budget_mode, "horizon")
        self.assertEqual(benchmark.required_replan_interval, 1)
        self.assertFalse(hasattr(benchmark, "max_policy_calls"))
        self.assertEqual(episode.metadata["native_horizon"], 1800)
        self.assertEqual(episode.metadata["native_subtask_horizon"], 360)
        self.assertEqual(benchmark.observation_spec.cameras, adapter.CAMERAS)
        self.assertEqual(benchmark.observation_spec.state_names, ())
        self.assertEqual((benchmark.action_spec.size, benchmark.action_spec.control_hz), (7, 30))
        self.assertEqual(episode.instruction, benchmark.sequence["instructions"][0])
        self.assertNotIn("tasks", episode.metadata)

    def test_factory_rejects_unreviewed_tracks_and_model_parameters(self):
        for update in ({"track": "full"}, {"track": []}, {"evaluation_mode": "full"},
                       {"source_root": "relative"}, {"dataset_root": "/tmp/../data"},
                       {"source_root": True}, {"sequence_index": 1}, {"seed_search": True},
                       {"max_policy_calls": 1800}, {"subtask_horizon": 500}, {"action_mode": "absolute"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                server.make_calvin({**example(), **update})
        with self.assertRaises(ValueError):
            server.make_calvin({})
        benchmark = server.make_calvin(example())
        for seed, limit in ((True, 1), (-1, 1), (1, 2), (1, True), (1, 0)):
            with self.assertRaises(ValueError):
                benchmark.episodes(seed, limit)

    def test_action_validation_rejects_bad_values_without_clipping(self):
        spec = server.make_calvin(example()).action_spec
        self.assertEqual(spec.validate([0] * 6 + [1]), (0.0,) * 6 + (1.0,))
        for value in (True, float("nan"), float("inf"), -1.01, 1.01):
            with self.assertRaises((TypeError, ValueError)):
                spec.validate([value] + [0] * 6)

    def test_attempt_consumed_before_reset_and_never_retried(self):
        benchmark = server.make_calvin(example())
        episode, = benchmark.episodes(0)
        session = benchmark.open_episode(episode)
        with self.assertRaises(ProtocolError):
            benchmark.open_episode(episode)
        with self.assertRaises(ProtocolError):
            session.reset()  # No artifact root: fails before native imports.
        self.assertTrue(session.metrics()["reset_attempted"])
        self.assertFalse(session.metrics()["native_reset_returned"])
        with self.assertRaises(ProtocolError):
            session.reset()

    def test_artifact_binding_rejects_terminal_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            for method in ("close", "artifacts"):
                benchmark = server.make_calvin(example())
                session = benchmark.open_episode(benchmark.episodes(0)[0])
                getattr(session, method)()
                target = Path(temporary) / method
                with self.assertRaises(ProtocolError):
                    session.bind_artifact_dir(target)
                self.assertFalse(target.exists())

    def test_factory_does_not_import_native_numpy_or_models(self):
        script = """
import json,sys
from benchmarks.simBenchmarks.calvin.server import make_calvin
with open('benchmarks/simBenchmarks/calvin/server.example.json') as stream:
    benchmark=make_calvin(json.load(stream))
assert len(benchmark.episodes(0))==1
for name in ('numpy','torch','pybullet','calvin_env','calvin_agent','AgentPolicies'):
    assert not any(key==name or key.startswith(name+'.') for key in sys.modules), name
"""
        result = subprocess.run([sys.executable, "-B", "-S", "-c", script], cwd=DIRECTORY.parents[2],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_literal_readme_command_parses(self):
        from benchkit.cli import build_parser
        blocks = re.findall(r"```sh\n(.*?)\n```", (DIRECTORY / "README.md").read_text(), re.DOTALL)
        command, = [block for block in blocks if block.startswith("python -B -m benchkit run")]
        tokens = shlex.split(command.replace("\\\n", " "))
        args = build_parser().parse_args(tokens[4:])
        self.assertEqual((args.benchmark, args.sim_server), ("calvin", "http://127.0.0.1:8772"))
        self.assertEqual((args.max_policy_calls, args.replan_interval, args.max_steps), (200, 1, 1800))
        self.assertEqual(args.model_profile, "anonymous_code_agent")
        self.assertEqual(args.policy_args, {"directory": "/absolute/opaque-mailbox"})
        self.assertEqual(args.budget_mode, "horizon")

    def test_entrypoint_and_describe_do_not_construct_native(self):
        with patch.object(server, "launch", return_value=0) as launch:
            self.assertEqual(server.main(["--help"]), 0)
            launch.assert_called_once_with(server.make_calvin, supplemental_sources=server.SUPPLEMENTAL_FILES,
                                           argv=["--help"])
        with tempfile.TemporaryDirectory() as temporary:
            http = Mock(server_port=8772)
            descriptions = []
            def connect(service, **kwargs):
                self.assertFalse(service.sessions)
                descriptions.append(service.dispatch("describe", {}))
                return http
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": "x" * 48}))
                stack.enter_context(patch("benchkit.sim_server.launch.make_http_server", side_effect=connect))
                stack.enter_context(patch("benchkit.source_snapshot.capture_harness_source", return_value={"scope": "CPU launcher fixture"}))
                stack.enter_context(patch.object(adapter.CalvinBenchmarkAdapter, "open_episode", side_effect=AssertionError("native")))
                stdout = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                result = server.main(["--parameters", str(DIRECTORY / "server.example.json"), "--seed", "0",
                                      "--episodes", "1", "--port", "8772", "--output-dir", str(Path(temporary) / "service")])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue())["native_resets"], 0)
            self.assertEqual(descriptions[0]["budget"]["required_replan_interval"], 1)
            http.server_close.assert_called_once()


class SequenceBoundaryChecks(unittest.TestCase):
    def test_success_transitions_language_once_without_reset_or_future_data(self):
        session, native = session_fixture([True, False])
        baseline = session.start_info
        with patch.object(adapter, "native_action", side_effect=tuple):
            first = session.step((0.0,) * 7)
            second = session.step((0.0,) * 7)
        self.assertEqual(first.observation.instruction, session.benchmark.sequence["instructions"][1])
        self.assertEqual(second.observation.instruction, first.observation.instruction)
        self.assertIsNone(first.observation.state)
        self.assertEqual(first.observation.metadata, {})
        self.assertFalse(first.terminated or first.truncated)
        self.assertEqual(native.oracle_calls[0][0], baseline)
        self.assertEqual(native.oracle_calls[0][2], {session.benchmark.sequence["tasks"][0]})
        self.assertEqual(native.oracle_calls[1][2], {session.benchmark.sequence["tasks"][1]})
        self.assertIsNot(native.oracle_calls[1][0], baseline)
        native.env.reset.assert_not_called()
        self.assertEqual((session.depth, session.subtask_controls, session.step_count), (1, 1, 2))

    def test_oracle_success_at_control_360_precedes_timeout(self):
        session, native = session_fixture([False] * 359 + [True])
        with patch.object(adapter, "native_action", side_effect=tuple):
            for _ in range(360):
                transition = session.step((0.0,) * 7)
        self.assertFalse(transition.terminated or transition.truncated)
        self.assertEqual((session.depth, session.subtask_controls), (1, 0))
        self.assertEqual(session.metrics()["completed_subtasks"][0]["controls"], 360)
        self.assertEqual(len(native.actions), 360)

    def test_first_failed_subtask_stops_chain_exactly_at_360(self):
        session, native = session_fixture()
        with patch.object(adapter, "native_action", side_effect=tuple):
            for _ in range(360):
                transition = session.step((0.0,) * 7)
            with self.assertRaises(ProtocolError):
                session.step((0.0,) * 7)
        self.assertTrue(transition.truncated)
        self.assertFalse(transition.terminated)
        self.assertEqual(session.metrics()["native_outcome"], "subtask_horizon_failure")
        self.assertEqual((session.depth, len(native.oracle_calls), len(native.actions)), (0, 360, 360))

    def test_five_successes_complete_sequence_and_record_actual_steps(self):
        session, native = session_fixture([True] * 5)
        with patch.object(adapter, "native_action", side_effect=tuple):
            for _ in range(5):
                transition = session.step((0.0,) * 7)
        self.assertTrue(transition.terminated)
        self.assertFalse(transition.truncated)
        self.assertEqual(session.depth, 5)
        self.assertEqual([row["completion_control"] for row in session.completed_subtasks], [1, 2, 3, 4, 5])
        self.assertEqual(session.metrics()["policy_physics_ticks"], 40)
        native.env.reset.assert_not_called()

    def test_error_after_native_step_is_not_replayed_and_keeps_counts(self):
        session, native = session_fixture()
        failure = RuntimeError("private oracle error")
        native.oracle.get_task_info_for_set.side_effect = failure
        with patch.object(adapter, "native_action", side_effect=tuple):
            with self.assertRaises(RuntimeError) as caught:
                session.step((0.0,) * 7)
            with self.assertRaises(ProtocolError):
                session.step((0.0,) * 7)
        self.assertIs(caught.exception, failure)
        self.assertEqual((session.started_controls, session.step_count, session.acknowledged_controls), (1, 1, 0))
        self.assertEqual(session.metrics()["policy_physics_ticks"], 8)
        native.env.step.assert_called_once()

    def test_unexpected_oracle_task_is_an_error_not_success(self):
        session, native = session_fixture()
        native.oracle.get_task_info_for_set.side_effect = lambda *args: {"future_task"}
        with patch.object(adapter, "native_action", side_effect=tuple), self.assertRaises(ProtocolError):
            session.step((0.0,) * 7)
        self.assertFalse(session.success)
        self.assertEqual(session.depth, 0)

    def test_external_early_stop_preserves_depth_without_timeout_claim(self):
        session, native = session_fixture([True])
        with patch.object(adapter, "native_action", side_effect=tuple):
            session.step((0.0,) * 7)
        session.close()
        session.close()
        self.assertEqual(session.metrics()["native_outcome"], "externally_stopped_incomplete")
        self.assertEqual(session.depth, 1)
        native.close.assert_called_once()

    def test_close_failure_is_sticky_and_does_not_repeat_native_close(self):
        session, native = session_fixture()
        native.close.return_value = ({"native_close_returned": False}, [RuntimeError("cleanup")])
        for _ in range(2):
            with self.assertRaises(ProtocolError):
                session.close()
        native.close.assert_called_once()

    def test_partial_reset_failure_keeps_tick_and_attempt(self):
        benchmark = server.make_calvin(example())
        session = benchmark.open_episode(benchmark.episodes(0)[0])
        native = FakeNative()
        failure = RuntimeError("reset render error")
        def reset(**kwargs):
            native.trace.completed_ticks["reset"] += 1
            raise failure
        native.env.reset.side_effect = reset
        fake_numpy = SimpleNamespace(array=lambda value, **kwargs: list(value), float64=float)
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            session.bind_artifact_dir(Path(temporary))
            stack.enter_context(patch.object(runtime, "readiness", return_value={}))
            stack.enter_context(patch.object(runtime, "prepare_native", return_value=native))
            stack.enter_context(patch.dict(sys.modules, {"numpy": fake_numpy}))
            with self.assertRaises(RuntimeError) as caught:
                session.reset()
            self.assertIs(caught.exception, failure)
            metrics = session.metrics()
            self.assertEqual(metrics["initialization_physics_ticks"], 1)
            self.assertFalse(metrics["native_reset_returned"] or metrics["reset_completed"])
            with self.assertRaises(ProtocolError):
                session.reset()
            self.assertTrue((Path(temporary) / "native_provenance.json").is_file())
        native.env.reset.assert_called_once()
        native.close.assert_called_once()

    def test_faulted_service_finish_transfers_partial_reset_counters(self):
        from benchkit.sim_server.server import BenchmarkService, ServiceError
        benchmark = server.make_calvin(example())
        native = FakeNative()
        def reset(**kwargs):
            native.trace.started_ticks["reset"] += 1
            native.trace.completed_ticks["reset"] += 1
            raise RuntimeError("reset rendering failed after its physical tick")
        native.env.reset.side_effect = reset
        fake_numpy = SimpleNamespace(array=lambda value, **kwargs: list(value), float64=float)
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(runtime, "readiness", return_value={}))
            stack.enter_context(patch.object(runtime, "prepare_native", return_value=native))
            stack.enter_context(patch.dict(sys.modules, {"numpy": fake_numpy}))
            service = BenchmarkService(benchmark, root=Path(temporary) / "service", seed=0, limit=1)
            sid = service.dispatch("open", {"episode_id": service.episodes[0].id})["session_id"]
            with self.assertRaises(ServiceError):
                service.dispatch("reset", {"session_id": sid, "sequence": 0})
            with self.assertRaises(ServiceError):
                service.dispatch("metrics", {"session_id": sid})
            final = service.dispatch("finish", {"session_id": sid})
            self.assertIsNone(final["cleanup_error"], (service.sessions[sid]["root"] / "sim_server_errors.jsonl").read_text())
            self.assertIn("native_metrics.json", [row["path"] for row in final["files"]])
            path = final["artifacts"]["native_metrics"]
            response = service.dispatch("read_artifact", {"session_id": sid, "path": path, "offset": 0})
            metrics = json.loads(base64.b64decode(response["data"]))
            self.assertEqual(metrics["completed_physics_ticks_by_phase"]["reset"], 1)
            self.assertEqual(metrics["started_physics_ticks_by_phase"]["reset"], 1)
            self.assertEqual((metrics["started_controls"], metrics["native_steps"], metrics["acknowledged_controls"]), (0, 0, 0))
            self.assertEqual(metrics["native_outcome"], "reset_error")
        native.env.reset.assert_called_once()
        native.close.assert_called_once()


class RuntimeBoundaryChecks(unittest.TestCase):
    def _native_runtime_fixture(self):
        clients = set()
        def connect(*args, **kwargs):
            clients.add(0)
            return 0
        bullet = SimpleNamespace(connect=Mock(side_effect=connect), stepSimulation=Mock(),
                                 isConnected=Mock(side_effect=lambda **kwargs: kwargs["physicsClientId"] in clients),
                                 disconnect=Mock(side_effect=lambda **kwargs: clients.remove(kwargs["physicsClientId"])))
        class BareEnv:
            def __init__(self, **kwargs):
                raise AssertionError("native constructor must not be invoked in CPU cleanup tests")
            def close(self):
                if self.ownsPhysicsClient and self.cid >= 0:
                    self.p.disconnect(physicsClientId=self.cid)
        native = runtime.NativeRuntime(SimpleNamespace(PlayTableSimEnv=BareEnv, p=bullet), None, None)
        return native, bullet, clients

    def test_partial_egl_constructor_orphan_is_disconnected_once(self):
        native, bullet, clients = self._native_runtime_fixture()
        original_connect, original_step = bullet.connect, bullet.stepSimulation
        native.trace.install()
        self.assertEqual(bullet.connect("DIRECT"), 0)
        native.env.ownsPhysicsClient = True
        self.assertEqual(native.env.cid, -1)  # Native assigns cid after EGL loading.
        receipt, errors = native.close()
        self.assertFalse(errors)
        self.assertEqual(receipt["orphan_disconnects"], [0])
        self.assertEqual(receipt["disconnected"], [0])
        bullet.disconnect.assert_called_once_with(physicsClientId=0)
        self.assertFalse(clients)
        self.assertFalse(native.env.ownsPhysicsClient)
        self.assertIs(bullet.connect, original_connect)
        self.assertIs(bullet.stepSimulation, original_step)

    def test_normal_native_close_is_not_repeated_as_orphan_cleanup(self):
        native, bullet, clients = self._native_runtime_fixture()
        native.trace.install()
        native.env.cid = bullet.connect("DIRECT")
        native.env.ownsPhysicsClient = True
        receipt, errors = native.close()
        self.assertFalse(errors)
        self.assertEqual(receipt["orphan_disconnects"], [])
        bullet.disconnect.assert_called_once_with(physicsClientId=0)
        self.assertFalse(clients)

    def test_failed_native_disconnect_is_recorded_without_retry(self):
        native, bullet, clients = self._native_runtime_fixture()
        native.trace.install()
        native.env.cid = bullet.connect("DIRECT")
        native.env.ownsPhysicsClient = True
        error = RuntimeError("disconnect failed")
        bullet.disconnect.side_effect = error
        receipt, errors = native.close()
        self.assertIs(errors[0], error)
        self.assertEqual(receipt["orphan_disconnects"], [])
        self.assertEqual(receipt["disconnected"], [])
        bullet.disconnect.assert_called_once_with(physicsClientId=0)
        self.assertEqual(clients, {0})
        self.assertFalse(native.env.ownsPhysicsClient)

    def test_preexisting_client_rejected_before_native_constructor(self):
        native, bullet, clients = self._native_runtime_fixture()
        clients.add(0)
        with self.assertRaises(CompatibilityError):
            native.construct()
        bullet.connect.assert_not_called()
        bullet.stepSimulation.assert_not_called()
        self.assertFalse(native.trace.installed)
        native.close()
        bullet.disconnect.assert_not_called()
        self.assertEqual(clients, {0})

    def test_nested_trace_rejected_and_wrong_client_id_owned_for_cleanup(self):
        bullet = SimpleNamespace(connect=Mock(return_value=1), stepSimulation=Mock())
        first = runtime.PhysicsTrace(bullet)
        first.install()
        second = runtime.PhysicsTrace(bullet)
        with self.assertRaises(ProtocolError):
            second.install()
        with self.assertRaises(CompatibilityError):
            bullet.connect("DIRECT")
        self.assertEqual(first.clients, [1])
        first.original_connect.assert_called_once_with("DIRECT")
        first.original_step.assert_not_called()
        first.restore()
        self.assertFalse(hasattr(bullet, "_rsi_calvin_trace_owner"))

    def test_passive_tick_and_connect_trace_returns_exact_objects(self):
        token = object()
        bullet = SimpleNamespace(connect=Mock(return_value=0), stepSimulation=Mock(return_value=token))
        original_connect, original_step = bullet.connect, bullet.stepSimulation
        trace = runtime.PhysicsTrace(bullet)
        trace.install()
        self.assertEqual(bullet.connect("DIRECT", options="x"), 0)
        self.assertIs(bullet.stepSimulation(physicsClientId=0), token)
        self.assertEqual(trace.completed_ticks, {"construction": 1, "reset": 0, "control": 0})
        original_connect.assert_called_once_with("DIRECT", options="x")
        original_step.assert_called_once_with(physicsClientId=0)
        failure = RuntimeError("physics")
        original_step.side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            bullet.stepSimulation(physicsClientId=0)
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace.completed_ticks["construction"], 1)
        self.assertEqual(trace.started_ticks["construction"], 2)
        trace.restore()
        self.assertIs(bullet.connect, original_connect)
        self.assertIs(bullet.stepSimulation, original_step)

    def test_frozen_input_drift_rejected(self):
        self.assertEqual(len(runtime.frozen_sequence()["tasks"]), 5)
        with patch.object(Path, "read_bytes", return_value=b"{}"), self.assertRaises(CompatibilityError):
            runtime.frozen_sequence()

    def test_actual_git_blob_bytes_checked_even_if_status_says_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source.py").write_bytes(b"different bytes")
            expected = b"expected bytes"
            blob = hashlib.sha1(b"blob " + str(len(expected)).encode() + b"\0" + expected).hexdigest()
            output = [str(root).encode(), b"a" * 40, b"", f"100644 blob {blob}\tsource.py\0".encode()]
            with patch.object(runtime, "_git", side_effect=output), self.assertRaises(CompatibilityError):
                runtime.verify_tree(root, "a" * 40, 1)

    def test_namespace_package_origins_must_be_exact(self):
        root = Path("/absolute/native/calvin_env/calvin_env")
        with patch.dict(sys.modules, {"calvin_env.envs": SimpleNamespace(__path__=[str(root / "envs")])}):
            runtime.verify_loaded_native_modules(root)
        for paths in (["/another/envs"], [str(root / "envs"), "/another/envs"], []):
            with patch.dict(sys.modules, {"calvin_env.envs": SimpleNamespace(__path__=paths)}), self.assertRaises(CompatibilityError):
                runtime.verify_loaded_native_modules(root)

    def test_ignored_symlink_package_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "calvin_env/calvin_env"
            package.mkdir(parents=True)
            external = root / "unfrozen"
            external.mkdir()
            (package / "envs").symlink_to(external, target_is_directory=True)
            with patch.object(runtime, "_git", return_value=b""), patch.object(runtime.importlib, "import_module") as imported:
                with self.assertRaises(CompatibilityError):
                    runtime._native_imports(root)
            imported.assert_not_called()

    def test_unicode_hash_derivation_and_retained_sequence_identity(self):
        record = runtime.frozen_sequence()
        self.assertEqual(fnv_unicode("hello world"), 3799943344)
        representation = str(record["initial_condition"].values())
        self.assertEqual(representation, record["derivation"]["initial_condition_repr"])
        self.assertEqual(fnv_unicode(representation), record["derivation"]["fnv_seed"])
        self.assertEqual(record["sequence_file"], "environment/eval_sequences.json")
        data = (DIRECTORY / "bench_server/protocol/eval_sequences.json").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), record["sequence_file_sha256"])
        rows = json.loads(data)
        self.assertEqual(len(rows), 1000)
        self.assertEqual(rows[0], [record["initial_condition"], record["tasks"]])

    @unittest.skipUnless(os.environ.get("CALVIN_NATIVE_SOURCE_ROOT"), "optional pinned native-source pure-math parity")
    def test_frozen_initial_state_matches_extracted_native_helper(self):
        import numpy as np
        self.assertEqual(np.__version__, "1.26.4")
        record = runtime.frozen_sequence()
        path = Path(os.environ["CALVIN_NATIVE_SOURCE_ROOT"]) / "calvin_models/calvin_agent/evaluation/utils.py"
        data = path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), record["derivation"]["helper_file_sha256"])
        tree = ast.parse(data)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("temp_seed", "get_env_state_for_initial_condition")]
        self.assertEqual(len(functions), 2)
        namespace = {"np": np, "pi": math.pi, "contextlib": contextlib, "hasher": fnv_unicode}
        before = np.random.get_state()
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
        robot, scene = namespace["get_env_state_for_initial_condition"](record["initial_condition"])
        np.testing.assert_array_equal(robot, record["robot_obs"])
        np.testing.assert_array_equal(scene, record["scene_obs"])
        after = np.random.get_state()
        self.assertEqual(before[0], after[0])
        np.testing.assert_array_equal(before[1], after[1])
        self.assertEqual(before[2:], after[2:])
        self.assertNotIn("calvin_agent", sys.modules)
        self.assertNotIn("torch", sys.modules)


try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, "NumPy optional for CPU array boundary checks")
class ArrayChecks(unittest.TestCase):
    def test_public_rgb_is_exact_nonaliasing_and_drops_private_fields(self):
        raw = {"rgb_obs": {name: np.arange(math.prod(shape), dtype=np.uint8).reshape(shape)
                           for name, shape in adapter.SHAPES.items()},
               "robot_obs": np.ones(15), "scene_obs": np.ones(24), "depth_obs": {}, "oracle": "private"}
        public = adapter.policy_observation(raw, 0, "current language")
        self.assertEqual(tuple(public.images), adapter.CAMERAS)
        self.assertEqual((public.state, public.metadata), (None, {}))
        for name in adapter.CAMERAS:
            np.testing.assert_array_equal(public.images[name], raw["rgb_obs"][name])
            self.assertFalse(np.shares_memory(public.images[name], raw["rgb_obs"][name]))
        raw["rgb_obs"]["rgb_static"] = np.zeros((84, 84, 3), dtype=np.uint8)
        with self.assertRaises(ProtocolError):
            adapter.policy_observation(raw, 0, "current language")

    def test_native_action_is_writable_copy_and_exact_gripper_sign(self):
        for gripper, expected in ((1, 1), (0, -1), (-1, -1)):
            original = np.array([0.5] * 6 + [gripper], dtype=np.float64)
            original.flags.writeable = False
            native = adapter.native_action(original)
            self.assertEqual(native[-1], expected)
            self.assertTrue(native.flags.writeable)
            self.assertFalse(np.shares_memory(native, original))
            native[:3] *= 0.02
            np.testing.assert_array_equal(original[:6], [0.5] * 6)


if __name__ == "__main__":
    unittest.main()
