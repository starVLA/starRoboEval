"""Synthetic loopback transport checks; no native simulator or model calls."""

import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from benchkit.contracts import (ActionChunk, ActionSpec, BenchmarkDescriptor, EpisodeSpec,
                               Observation, ObservationSpec, PolicyDecision, PolicyDescriptor, Transition)
from benchkit.errors import InfrastructureError, ProtocolError
from benchkit.sim_server.client import SimServerBenchmarkAdapter, SimServerError
from benchkit.sim_server.wire import PROTOCOL, MAX_MESSAGE_BYTES


DESCRIPTION = {
    "server_id": "synthetic-server",
    "descriptor": BenchmarkDescriptor("fixture", "1", "1", "abc").to_dict(),
    "observation_spec": ObservationSpec().to_dict(),
    "action_spec": ActionSpec("joint", 1, low=(-1,), high=(1,)).to_dict(),
    "budget": {"budget_mode": "decisions", "max_policy_calls": 2,
               "replan_interval": 1, "environment_step_cap": 2},
    "seed": 0, "episodes": [EpisodeSpec("task-0", "task", 0, "Do task").to_dict()],
    "source": {"revision": "synthetic"}, "parameters": {},
}


def observation(step):
    return {"step": step, "instruction": "Do task", "images": {}, "state": None, "metadata": {}}


class Fixture:
    def __init__(self):
        self.calls = []
        self.description = deepcopy(DESCRIPTION)
        self.override = {}
        self.payload = b"closed artifact bytes"
        self.files = [{"path": "nested/data.bin", "size_bytes": len(self.payload),
                       "sha256": hashlib.sha256(self.payload).hexdigest()}]
        self.cleanup_error = None
        self.terminal = False
        self.response_mode = None
        self.error_code = "SECRET-NOT-FOR-LOGS"

    def result(self, request):
        op, params = request["op"], request["params"]
        self.calls.append(deepcopy(request))
        if op in self.override:
            return self.override[op]
        if op == "describe":
            return self.description
        if op == "open":
            return {"session_id": "session-0"}
        if op == "reset":
            return {"observation": observation(0)}
        if op == "step":
            return {"transition": {"observation": observation(params["sequence"]),
                "reward": 0, "terminated": self.terminal, "truncated": False, "info": {}}}
        if op == "metrics":
            return {"metrics": {"success": False}}
        if op == "finish":
            return {"session_id": "session-0", "files": self.files,
                "artifacts": {"data": self.files[0]["path"]} if self.files else {},
                "cleanup_error": self.cleanup_error}
        if op == "read_artifact":
            return {"data": base64.b64encode(self.payload[params["offset"]:]).decode("ascii")}
        raise AssertionError(op)


@contextmanager
def fixture():
    state = Fixture()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.server.auth.append(self.headers.get("Authorization"))
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            result = state.result(request)
            body = {"protocol": PROTOCOL, "request_id": request["request_id"], "ok": True, "result": result}
            if state.response_mode == "mismatch":
                body["request_id"] = "other"
            if state.response_mode == "error":
                body = {"protocol": PROTOCOL, "request_id": request["request_id"],
                        "ok": False, "error": {"code": state.error_code}}
            raw = json.dumps(body).encode()
            self.send_response(302 if state.response_mode == "redirect" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(MAX_MESSAGE_BYTES + 1 if state.response_mode == "oversize" else len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.auth = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class SimServerClientTests(unittest.TestCase):
    def test_endpoint_and_credential_validation_never_connects(self):
        endpoints = ["https://127.0.0.1:1", "http://localhost:1", "http://evil.test:1",
                     "http://127.0.0.1", "http://127.0.0.1:0", "http://u:p@127.0.0.1:1",
                     "http://127.0.0.1:1/rpc", "http://127.0.0.1:1?q=x",
                     "http://127.0.0.1:1#x", "http://[::1]:1"]
        with patch("http.client.HTTPConnection", side_effect=AssertionError("no network")):
            for endpoint in endpoints:
                with self.subTest(endpoint=endpoint), self.assertRaises(InfrastructureError):
                    SimServerBenchmarkAdapter(endpoint, "secret")
            for token in ("", "has space", "new\nline", None):
                with self.subTest(token=token), self.assertRaises(InfrastructureError):
                    SimServerBenchmarkAdapter("http://127.0.0.1:1", token)
            for timeout in (0, -1, True, float("nan"), "10"):
                with self.subTest(timeout=timeout), self.assertRaises(InfrastructureError):
                    SimServerBenchmarkAdapter("http://127.0.0.1:1", "secret", timeout=timeout)

    def test_schedule_queries_are_local_and_frozen(self):
        with fixture() as (state, server, endpoint):
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            episodes = adapter.episodes(0)
            self.assertEqual(adapter.episodes(0, 1), episodes)
            self.assertEqual(len(state.calls), 1)
            self.assertEqual(server.auth, ["Bearer credential"])
            self.assertIsNone(state.calls[0]["server_id"])
            mutated = adapter.describe_data
            mutated["episodes"][0]["task"] = "other"
            self.assertEqual(adapter.episodes(0), episodes)
            for args in ((1,), (True,), (0, 0), (0, True)):
                with self.assertRaises(InfrastructureError):
                    adapter.episodes(*args)

    def test_complete_lifecycle_downloads_receipt_and_exact_bytes(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            session.bind_artifact_dir(Path(directory))
            self.assertEqual(session.reset().step, 0)
            self.assertEqual(session.step((0.25,)).observation.step, 1)
            self.assertEqual(session.metrics(), {"success": False})
            artifacts = session.artifacts()
            self.assertEqual((Path(directory) / artifacts["data"]).read_bytes(), state.payload)
            receipt = (Path(directory) / artifacts["sim_server_receipt"]).read_text()
            self.assertNotIn("credential", receipt)
            self.assertNotIn(endpoint, receipt)
            self.assertEqual(session.artifacts(), artifacts)
            session.close()
            session.close()
            self.assertEqual([c["op"] for c in state.calls],
                ["describe", "open", "reset", "step", "metrics", "finish", "read_artifact"])
            self.assertEqual([c["params"]["sequence"] for c in state.calls if c["op"] in ("reset", "step")], [0, 1])
            self.assertTrue(all(c["server_id"] == "synthetic-server" for c in state.calls[1:]))

    def test_invalid_descriptions_rejected(self):
        mutations = [lambda d: d["budget"].update(environment_step_cap=3),
                     lambda d: d["observation_spec"].update(privileged=True),
                     lambda d: d["action_spec"].update(size=True),
                     lambda d: d["episodes"].append(d["episodes"][0]),
                     lambda d: d.update(seed=True), lambda d: d.update(extra="forbidden")]
        with fixture() as (state, server, endpoint):
            for mutate in mutations:
                state.description = deepcopy(DESCRIPTION)
                mutate(state.description)
                with self.subTest(mutation=mutate), self.assertRaises(InfrastructureError):
                    SimServerBenchmarkAdapter(endpoint, "credential")

    def test_open_is_single_attempt_even_when_reply_invalid(self):
        with fixture() as (state, server, endpoint):
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            episode = adapter.episodes(0)[0]
            state.override["open"] = {"session_id": "../invalid"}
            for _ in range(2):
                with self.assertRaises(InfrastructureError):
                    adapter.open_episode(episode)
            self.assertEqual([c["op"] for c in state.calls].count("open"), 1)

    def test_no_controls_before_reset_after_terminal_or_repeated_reset(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            with self.assertRaises(InfrastructureError):
                session.reset()
            with self.assertRaises(InfrastructureError):
                session.step((0,))
            session.bind_artifact_dir(Path(directory))
            session.reset()
            with self.assertRaises(InfrastructureError):
                session.reset()
            state.terminal = True
            session.step((0,))
            with self.assertRaises(InfrastructureError):
                session.step((0,))
            self.assertEqual([c["op"] for c in state.calls].count("step"), 1)

    def test_failed_step_poisoned_without_retry_but_can_finalize(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            session.bind_artifact_dir(Path(directory))
            session.reset()
            state.response_mode = "error"
            with self.assertRaises(InfrastructureError) as failure:
                session.step((0,))
            self.assertNotIn("SECRET", str(failure.exception))
            state.response_mode = None
            with self.assertRaises(InfrastructureError):
                session.step((0,))
            session.close()
            self.assertEqual([c["op"] for c in state.calls].count("step"), 1)

    def test_finish_transport_error_not_retried_by_close(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            session.bind_artifact_dir(Path(directory))
            state.response_mode = "error"
            for method in (session.artifacts, session.close, session.artifacts):
                with self.assertRaises(InfrastructureError):
                    method()
            self.assertEqual([c["op"] for c in state.calls].count("finish"), 1)

    def test_native_action_contract_rejection_is_protocol_failure(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            session.bind_artifact_dir(Path(directory))
            session.reset()
            state.error_code, state.response_mode = "invalid_action", "error"
            with self.assertRaises(ProtocolError):
                session.step((0,))
            state.response_mode = None
            with self.assertRaises(InfrastructureError):
                session.step((0,))
            self.assertEqual([c["op"] for c in state.calls].count("step"), 1)

    def test_remote_errors_use_closed_code_vocabulary(self):
        with fixture() as (state, server, endpoint):
            for code, expected in (("server_identity_mismatch", "server_identity_mismatch"),
                                   ("secret_token_also_lowercase", "remote_failure")):
                state.error_code, state.response_mode = code, "error"
                with self.subTest(code=code), self.assertRaises(SimServerError) as failure:
                    SimServerBenchmarkAdapter(endpoint, "credential")
                self.assertEqual(failure.exception.code, expected)
                self.assertNotIn("secret_token", str(failure.exception))

    def test_horizon_description_may_have_no_adapter_cap(self):
        with fixture() as (state, server, endpoint):
            state.description["budget"] = {"budget_mode": "horizon", "environment_step_cap": None,
                "max_policy_calls": None, "replan_interval": None}
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            self.assertIsNone(adapter.environment_step_cap)

    def test_cleanup_error_retains_download_and_receipt(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            session.bind_artifact_dir(Path(directory))
            state.cleanup_error = "native_close_failed"
            with self.assertRaises(InfrastructureError):
                session.artifacts()
            self.assertEqual((Path(directory) / "sim_server_files/nested/data.bin").read_bytes(), state.payload)
            self.assertIn("native_close_failed", (Path(directory) / "sim_server_receipt.json").read_text())
            session.close()

    def test_traversal_duplicate_collision_and_oversize_inventory_rejected(self):
        with fixture() as (state, server, endpoint):
            variants = ["../outside", "/outside", "nested//data", "a\\b", "./data"]
            for path in variants:
                with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                    adapter = SimServerBenchmarkAdapter(endpoint, "credential")
                    session = adapter.open_episode(adapter.episodes(0)[0])
                    session.bind_artifact_dir(Path(directory))
                    state.files = [{"path": path, "size_bytes": 0, "sha256": "0" * 64}]
                    with self.assertRaises(InfrastructureError):
                        session.artifacts()
                    self.assertFalse((Path(directory) / "sim_server_files").exists())
            for files in ([{"path": "a", "size_bytes": 0, "sha256": "0" * 64}] * 2,
                          [{"path": p, "size_bytes": 0, "sha256": "0" * 64} for p in ("a", "a/b")],
                          [{"path": "huge", "size_bytes": 16 * 1024 ** 3 + 1, "sha256": "0" * 64}]):
                with tempfile.TemporaryDirectory() as directory:
                    adapter = SimServerBenchmarkAdapter(endpoint, "credential")
                    session = adapter.open_episode(adapter.episodes(0)[0])
                    session.bind_artifact_dir(Path(directory))
                    state.files = files
                    with self.assertRaises(InfrastructureError):
                        session.artifacts()

    def test_existing_symlink_destination_is_not_followed(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            session.bind_artifact_dir(Path(directory))
            (Path(directory) / "sim_server_files").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(InfrastructureError):
                session.artifacts()
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_bad_digest_retains_partial_evidence_without_retry(self):
        with fixture() as (state, server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            session.bind_artifact_dir(Path(directory))
            state.files[0]["sha256"] = "0" * 64
            with self.assertRaises(InfrastructureError):
                session.artifacts()
            self.assertTrue((Path(directory) / "sim_server_receipt.json").exists())
            with self.assertRaises(InfrastructureError):
                session.artifacts()
            self.assertEqual([c["op"] for c in state.calls].count("read_artifact"), 1)

    def test_transport_rejects_redirect_correlation_oversize_without_retry(self):
        with fixture() as (state, server, endpoint):
            for mode in ("redirect", "mismatch", "oversize"):
                state.response_mode = mode
                count = len(state.calls)
                with self.subTest(mode=mode), self.assertRaises(InfrastructureError):
                    SimServerBenchmarkAdapter(endpoint, "credential")
                self.assertEqual(len(state.calls), count + 1)

    def test_real_service_and_client_preserve_native_closed_artifacts(self):
        from benchkit.sim_server.server import BenchmarkService, make_http_server
        from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest

        class NativeEpisode:
            def __init__(self):
                self.calls = []

            def bind_artifact_dir(self, path):
                self.root = path

            def reset(self):
                self.calls.append("reset")
                return Observation(0, "Do task")

            def step(self, action):
                self.calls.append(("step", action))
                return Transition(Observation(1, "Do task"), terminated=True)

            def metrics(self):
                return {"success": False}

            def artifacts(self):
                self.calls.append("artifacts")
                (self.root / "native.txt").write_bytes(b"native artifact")
                return {"native": str(self.root / "native.txt")}

            def close(self):
                self.calls.append("close")
                (self.root / "closed.txt").write_bytes(b"closed after artifacts")

        class NativeAdapter:
            descriptor = BenchmarkDescriptor("synthetic", "1", "1", "abc")
            observation_spec = ObservationSpec()
            action_spec = ActionSpec("joint", 1)
            budget_mode, max_policy_calls, replan_interval, environment_step_cap = "decisions", 2, 1, 2

            def episodes(self, seed, limit=None):
                return [EpisodeSpec("synthetic-0", "task", seed, "Do task")]

            def open_episode(self, episode):
                self.native = NativeEpisode()
                return self.native

        class DiagnosticPolicy:
            descriptor = PolicyDescriptor("synthetic", "diagnostic")

            def compatibility_errors(self, observation_spec, action_spec):
                return []

            def start_episode(self, context):
                self.context = context

            def act(self, observation):
                return PolicyDecision(action=ActionChunk.from_steps([[0.25]]))

            def end_episode(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            native = NativeAdapter()
            service = BenchmarkService(native, root=Path(directory) / "server", seed=0)
            server = make_http_server(service, token="x" * 32, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                adapter = SimServerBenchmarkAdapter(f"http://127.0.0.1:{server.server_port}", "x" * 32)
                provenance = adapter.execution_provenance()
                self.assertEqual(provenance["descriptor"]["name"], "synthetic")
                provenance["source"].clear()
                self.assertTrue(adapter.execution_provenance()["source"])
                run = EvaluationRunner().run(adapter, DiagnosticPolicy(), RunRequest(
                    output_dir=Path(directory) / "client", seed=0, max_steps=2,
                    max_policy_calls=2, replan_interval=1, budget_mode="decisions"))
                result_path = next(run.glob("episodes/*/result.json"))
                result = json.loads(result_path.read_text())
                self.assertEqual(result["status"], "completed", result.get("error"))
                self.assertEqual((result["policy_calls"], result["action_decisions"], result["environment_steps"]), (1, 1, 1))
                self.assertFalse(result["success"])
                manifest = json.loads((run / "manifest.json").read_text())
                self.assertEqual(manifest["benchmark_service"]["server_id"], adapter.describe_data["server_id"])
                destination, artifacts = result_path.parent / "artifacts", result["artifacts"]
                self.assertEqual((destination / artifacts["native"]).read_bytes(), b"native artifact")
                self.assertEqual((destination / "sim_server_files/closed.txt").read_bytes(), b"closed after artifacts")
                self.assertTrue((destination / "sim_server_files/sim_server_session.json").is_file())
                self.assertEqual(native.native.calls, ["reset", ("step", (0.25,)), "artifacts", "close"])
                with self.assertRaises(InfrastructureError):
                    adapter.open_episode(adapter.episodes(0)[0])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                service.close()


if __name__ == "__main__":
    unittest.main()
