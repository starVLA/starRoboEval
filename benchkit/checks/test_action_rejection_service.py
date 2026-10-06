"""Real loopback RPC, synthetic native owner: no model or simulator execution."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.RoboDojo.bench_server.adapter import ACTION_SPEC, DirectEEFBenchmarkAdapter
from benchkit.sim_server.client import SimServerBenchmarkAdapter
from benchkit.sim_server.server import BenchmarkService, ServiceActionRejected, ServiceError, make_http_server
from benchkit.sim_server.wire import dumps
from benchkit.contracts import BenchmarkDescriptor, EpisodeSpec, Observation, ObservationSpec, Transition
from benchkit.errors import ActionRejected, InfrastructureError
from benchkit.validation import ValidationIssue


VALID = (0., 0., 0., 1., 0., 0., 0., 0.5) * 2


class Native:
    def __init__(self):
        self.controls = self.resets = self.metric_reads = 0

    def reset(self):
        self.resets += 1
        return Observation(0, "Synthetic fixture")

    def step(self, action):
        self.controls += 1
        return Transition(Observation(self.controls, "Synthetic fixture"))

    def metrics(self):
        self.metric_reads += 1
        return {"success": False}

    def artifacts(self):
        return {}

    def close(self):
        pass


class Adapter:
    descriptor = BenchmarkDescriptor("fixture", "1", "fixture/v1", "fixture")
    observation_spec = ObservationSpec()
    action_spec = ACTION_SPEC
    validate_action_input = staticmethod(DirectEEFBenchmarkAdapter.validate_action_input)

    def __init__(self):
        self.native = Native()

    def episodes(self, seed, limit=None):
        return [EpisodeSpec("case", "fixture", seed, "Synthetic fixture")]

    def open_episode(self, episode):
        return self.native


@contextmanager
def connected(*, rejection_capability=True):
    with tempfile.TemporaryDirectory(prefix="rsi-reject-service-check-") as directory:
        root = Path(directory)
        adapter = Adapter()
        service = BenchmarkService(adapter, root=root / "server", seed=0)
        if not rejection_capability:
            service.description.pop("action_rejection")
        httpd = make_http_server(service, token="x" * 32, port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            client = SimServerBenchmarkAdapter(f"http://127.0.0.1:{httpd.server_port}", "x" * 32)
            session = client.open_episode(client.episodes(0)[0])
            (root / "artifacts").mkdir()
            session.bind_artifact_dir(root / "artifacts")
            session.reset()
            yield service, adapter, client, session
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()


class ActionRejectionServiceChecks(unittest.TestCase):
    def test_bad_quaternion_returns_issue_no_control_and_corrected_input_can_execute(self):
        with connected() as (service, adapter, client, session):
            bad = list(VALID)
            bad[3] = 2
            with self.assertRaises(ActionRejected) as caught:
                session.step(bad)
            self.assertEqual(caught.exception.issue.code, "quaternion_not_unit")
            self.assertEqual(caught.exception.issue.field, "left.quaternion_norm")
            self.assertEqual(caught.exception.issue.actual, 2)
            self.assertEqual(caught.exception.issue.limit, 1e-4)
            self.assertEqual(adapter.native.controls, 0)
            self.assertEqual(adapter.native.metric_reads, 0)
            record = next(iter(service.sessions.values()))
            self.assertEqual((record["sequence"], record["controls"], record["rejections"]), (1, 0, 1))
            self.assertEqual(record["state"], "running")
            self.assertFalse(session._faulted)
            self.assertEqual(session.step(VALID).observation.step, 1)
            self.assertEqual((adapter.native.resets, adapter.native.controls), (1, 1))
            session.close()

    def test_local_invalid_shape_never_sends_a_step_rpc_or_poison_session(self):
        with connected() as (service, adapter, client, session):
            with patch.object(client, "_rpc", wraps=client._rpc) as rpc:
                for action in ([], (True,) + VALID[1:], (float("nan"),) + VALID[1:]):
                    with self.subTest(action=action), self.assertRaises(ActionRejected):
                        session.step(action)
                rpc.assert_not_called()
            self.assertEqual(adapter.native.controls, 0)
            self.assertEqual(session.step(VALID).observation.step, 1)
            session.close()

    def test_benchmark_checks_opening_range_not_model_binary_preference(self):
        with connected() as (service, adapter, client, session):
            for value in (-0.1, 1.1):
                bad = list(VALID)
                bad[15] = value
                with self.assertRaises(ActionRejected) as caught:
                    session.step(bad)
                self.assertEqual(caught.exception.issue.field, "right.opening")
            # 0.5 is valid at the benchmark boundary irrespective of model guard.
            self.assertEqual(session.step(VALID).observation.step, 1)
            self.assertEqual(adapter.native.controls, 1)
            session.close()

    def test_service_does_not_impose_model_per_decision_motion_guard(self):
        values = list(VALID)
        values[0] = 1.0
        values[8] = -1.0
        self.assertEqual(DirectEEFBenchmarkAdapter.validate_action_input(values), tuple(values))

    def test_unknown_validation_hook_failure_is_not_recoverable(self):
        with connected() as (service, adapter, client, session):
            with patch.object(adapter, "validate_action_input", side_effect=RuntimeError("private native data")):
                with self.assertRaises(InfrastructureError) as caught:
                    session.step(VALID)
            self.assertNotIn("private", str(caught.exception))
            self.assertTrue(session._faulted)
            record = next(iter(service.sessions.values()))
            self.assertEqual((record["state"], record["error"]), ("faulted", "service_request_failed"))
            self.assertEqual((record["sequence"], record["controls"], record["rejections"]), (1, 0, 0))
            self.assertTrue((record["root"] / "sim_server_errors.jsonl").is_file())
            with self.assertRaisesRegex(ServiceError, "invalid_session_state"):
                service.dispatch("step", {"session_id": record["id"], "sequence": 1, "action": list(VALID)})
            with self.assertRaises(InfrastructureError):
                session.step(VALID)
            self.assertEqual(adapter.native.controls, 0)
            session.close()

    def test_invalid_validation_hooks_fault_the_server_without_changing_actions(self):
        for hook in ("not callable", lambda action: action[:-1]):
            with self.subTest(hook=hook), connected() as (service, adapter, client, session):
                with patch.object(adapter, "validate_action_input", hook):
                    with self.assertRaises(InfrastructureError):
                        session.step(VALID)
                record = next(iter(service.sessions.values()))
                self.assertEqual(record["state"], "faulted")
                self.assertEqual((record["sequence"], record["controls"], record["rejections"]), (1, 0, 0))
                with self.assertRaisesRegex(ServiceError, "invalid_session_state"):
                    service.dispatch("step", {"session_id": record["id"], "sequence": 1, "action": list(VALID)})
                self.assertEqual(adapter.native.controls, 0)
                session.close()

    def test_uncertain_native_failure_still_consumes_sequence_and_faults(self):
        with connected() as (service, adapter, client, session):
            def uncertain(_):
                adapter.native.controls += 1
                raise RuntimeError("lost native response")
            with patch.object(adapter.native, "step", side_effect=uncertain):
                with self.assertRaises(InfrastructureError):
                    session.step(VALID)
            record = next(iter(service.sessions.values()))
            self.assertEqual(record["sequence"], 2)
            self.assertEqual(record["state"], "faulted")
            with self.assertRaises(InfrastructureError):
                session.step(VALID)
            self.assertEqual(adapter.native.controls, 1)
            session.close()

    def test_wrong_rejection_sequence_never_allows_another_control(self):
        with connected() as (service, adapter, client, session):
            dispatch = service.dispatch
            def forged(op, params):
                if op == "step":
                    raise ServiceActionRejected(ValidationIssue("invalid_action"), params["sequence"] + 1)
                return dispatch(op, params)
            with patch.object(service, "dispatch", side_effect=forged):
                with self.assertRaises(InfrastructureError):
                    session.step(VALID)
            self.assertTrue(session._faulted)
            with self.assertRaises(InfrastructureError):
                session.step(VALID)
            self.assertEqual(adapter.native.controls, 0)
            session.close()

    def test_legacy_description_cannot_authorize_recoverable_remote_rejections(self):
        with connected(rejection_capability=False) as (service, adapter, client, session):
            self.assertEqual(session.step(VALID).observation.step, 1)
            bad = list(VALID)
            bad[3] = 2
            with self.assertRaises(InfrastructureError):
                session.step(bad)
            self.assertTrue(session._faulted)
            with self.assertRaises(InfrastructureError):
                session.step(VALID)
            self.assertEqual(adapter.native.controls, 1)
            session.close()

    def test_malformed_rejection_envelopes_fail_closed_without_private_feedback(self):
        mutations = (
            {"executed": True}, {"executed": 0}, {"next_sequence": True},
            {"code": "native_or_observation_failed"}, {"unknown": "private data"},
            {"rejection": {"code": "invalid_action", "actual": "private data"}},
            {"rejection": {"code": "invalid_action", "field": "hidden_object_pose"}},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), connected() as (service, adapter, client, session):
                def altered(value):
                    if value.get("ok") is False and "rejection" in value.get("error", {}):
                        value = {**value, "error": {**value["error"], **mutation}}
                    return dumps(value)
                bad = list(VALID)
                bad[3] = 2
                with patch("benchkit.sim_server.server.dumps", side_effect=altered):
                    with self.assertRaises(InfrastructureError) as caught:
                        session.step(bad)
                self.assertNotIn("private", str(caught.exception))
                self.assertTrue(session._faulted)
                with self.assertRaises(InfrastructureError):
                    session.step(VALID)
                self.assertEqual(adapter.native.controls, 0)
                session.close()


if __name__ == "__main__":
    unittest.main()
