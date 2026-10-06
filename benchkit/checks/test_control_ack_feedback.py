"""Independent CPU/loopback checks: public per-control ACKs, never SIM state.

The native owner below is synthetic. No model, real benchmark or Codex process
is created. A real service/client boundary tests the trusted driver projection.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from benchkit.sim_server.client import SimServerBenchmarkAdapter
from benchkit.sim_server.server import BenchmarkService, make_http_server
from benchkit.sim_server.wire import WireError, decode_observation, encode_observation
from benchkit.audits.closed_run import AuditError, audit_episode, audit_run
from benchkit.contracts import (
    ActionChunk, ActionRejectionFeedback, ActionSpec, BenchmarkDescriptor,
    ControlAcknowledgement, EpisodeSpec, ExecutionFeedback, Observation,
    ObservationSpec, PolicyDecision, PolicyDescriptor, Transition, Usage,
)
from benchkit.errors import ActionRejected
from benchkit.validation import ValidationIssue
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest


SCHEMA = "test.robot-control-feedback/v1"
PRIVATE = "PRIVATE-SCENE-METRICS-NOT-POLICY-INPUT"


def payload(step):
    return {"schema": SCHEMA, "control_target": step, "joint_command": [step / 10]}


def decision(*values):
    return PolicyDecision(action=ActionChunk.from_steps([(x,) for x in values]),
                          usage=Usage(calls=1, input_tokens=1, output_tokens=1))


class Native:
    def __init__(self, adapter):
        self.adapter = adapter
        self.controls = []
        self.resets = self.closes = 0

    def reset(self):
        self.resets += 1
        return Observation(0, "Synthetic robot ACK fixture", state=(0.,))

    def step(self, action):
        self.controls.append(tuple(action))
        step = len(self.controls)
        ack = payload(step) if self.adapter.enabled else None
        if self.adapter.corrupt_feedback is not None:
            ack = self.adapter.corrupt_feedback(ack)
        return Transition(Observation(step, "Synthetic robot ACK fixture", state=tuple(action),
                                      control_feedback=ack),
                          reward=.25, terminated=step >= self.adapter.terminal_after,
                          info={"secret": PRIVATE, "object_pose": [7., 8., 9.], "native_score": 42.})

    def metrics(self):
        return {"success": len(self.controls) >= self.adapter.terminal_after, "private": PRIVATE}

    def artifacts(self):
        return {}

    def close(self):
        self.closes += 1


class Adapter:
    descriptor = BenchmarkDescriptor("ack-fixture", "1", "ack-fixture/v1", "synthetic")
    action_spec = ActionSpec("joint", 1, low=(0.,), high=(1.,))

    def __init__(self, *, enabled=True, terminal_after=3, cases=1, corrupt_feedback=None):
        self.enabled, self.terminal_after, self.cases = enabled, terminal_after, cases
        self.corrupt_feedback = corrupt_feedback
        self.observation_spec = ObservationSpec(state_names=("joint",), modalities=("language", "state"),
                                               control_feedback_schema=SCHEMA if enabled else None)
        self.natives = []

    def episodes(self, seed, limit=None):
        return [EpisodeSpec(f"case-{i}", "fixture", seed, "Synthetic robot ACK fixture",
                            metadata={"layout_secret": PRIVATE}) for i in range(min(limit or self.cases, self.cases))]

    def open_episode(self, episode):
        native = Native(self)
        self.natives.append(native)
        return native

    @staticmethod
    def validate_action_input(action):
        if action[0] == .6:
            raise ActionRejected(ValidationIssue("invalid_action", "action"))
        return action


class Policy:
    descriptor = PolicyDescriptor("ack-sink", "scripted", version="1")

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.contexts, self.observations, self.executions, self.rejections = [], [], [], []

    def compatibility_errors(self, observation_spec, action_spec):
        return []

    def start_episode(self, context):
        self.contexts.append(context)

    def act(self, observation):
        self.observations.append(observation)
        value = next(self.outcomes)
        if isinstance(value, Exception):
            raise value
        return value

    def observe_execution(self, feedback):
        self.executions.append(feedback)

    def observe_rejection(self, feedback):
        self.rejections.append(feedback)

    def end_episode(self):
        pass


@contextmanager
def connected(adapter):
    with tempfile.TemporaryDirectory(prefix="rsi-control-ack-check-") as directory:
        root = Path(directory)
        service = BenchmarkService(adapter, root=root / "server", seed=0)
        httpd = make_http_server(service, token="x" * 32, port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            client = SimServerBenchmarkAdapter(f"http://127.0.0.1:{httpd.server_port}", "x" * 32)
            yield client, root
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
            service.close()
            if thread.is_alive():
                raise RuntimeError("synthetic service thread did not close")


class ControlAckFeedbackChecks(unittest.TestCase):
    def run_fixture(self, outcomes, *, enabled=True, terminal_after=3, cases=1, corrupt_feedback=None):
        adapter = Adapter(enabled=enabled, terminal_after=terminal_after, cases=cases,
                          corrupt_feedback=corrupt_feedback)
        policy = Policy(outcomes)
        with connected(adapter) as (client, root):
            run = EvaluationRunner().run(client, policy, RunRequest(
                output_dir=root / "runs", run_id="synthetic", episode_limit=cases,
                max_steps=terminal_after, max_policy_calls=4, replan_interval=3,
                invalid_action_handling="feedback"))
            results = [json.loads(line) for line in (run / "episodes.jsonl").read_text().splitlines()]
            events = [json.loads(line) for p in sorted((run / "episodes").glob("*/events.jsonl"))
                      for line in p.read_text().splitlines()]
            manifest = json.loads((run / "manifest.json").read_text())
            self.assertEqual(audit_run(run)["record_consistency"], "passed")
        return adapter, policy, results, events, manifest

    def test_entire_control_prefix_crosses_boundary_without_private_transition_info(self):
        adapter, policy, results, events, _ = self.run_fixture([decision(.1, .2, .3)])
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[0]["environment_steps"], 3)
        acks = policy.executions[0].control_acks
        self.assertEqual([a.environment_step for a in acks], [1, 2, 3])
        self.assertEqual([a.observation_step for a in acks], [1, 2, 3])
        self.assertEqual([a.payload for a in acks], [payload(i) for i in (1, 2, 3)])
        self.assertEqual(adapter.natives[0].controls, [(.1,), (.2,), (.3,)])
        self.assertTrue(any(PRIVATE in json.dumps(e.get("info", {})) for e in events))
        public = [f.to_dict() for f in policy.executions + policy.rejections]
        public += [o.log_view() for o in policy.observations]
        public += [c.episode.to_dict() for c in policy.contexts]
        self.assertNotIn(PRIVATE, json.dumps(public))
        self.assertNotIn("native_score", json.dumps(public))
        self.assertNotIn("object_pose", json.dumps(public))

    def test_partial_server_rejection_delivers_only_executed_prefix_once(self):
        adapter, policy, results, events, _ = self.run_fixture(
            [decision(.1, .6, .3), decision(.4)], terminal_after=2)
        self.assertEqual(results[0]["environment_steps"], 2)
        self.assertEqual(results[0]["rejected_actions"], 1)
        self.assertEqual(adapter.natives[0].controls, [(.1,), (.4,)])
        self.assertEqual([a.environment_step for a in policy.rejections[0].control_acks], [1])
        self.assertEqual([a.environment_step for a in policy.executions[0].control_acks], [2])
        self.assertEqual(policy.observations[1].step, 1)
        rejected = next(e for e in events if e["event"] == "action_rejected")
        self.assertEqual(rejected["phase"], "session_step")
        self.assertEqual(len(rejected["feedback"]["control_acks"]), 1)

    def test_all_zero_execution_rejection_paths_use_empty_trace_not_previous_ack(self):
        rejected = ActionRejected(ValidationIssue("invalid_json", "response"), usage=Usage(calls=1))
        for first, phase in ((rejected, "policy_act"), (decision(2.), "action_spec"),
                             (decision(.6), "session_step")):
            with self.subTest(phase=phase):
                adapter, policy, results, events, _ = self.run_fixture(
                    [decision(.1), first, decision(.2)], terminal_after=2)
                self.assertEqual(results[0]["status"], "completed")
                self.assertEqual(adapter.natives[0].controls, [(.1,), (.2,)])
                self.assertEqual(policy.rejections[0].control_acks, ())
                self.assertEqual(policy.rejections[0].environment_steps, 1)
                self.assertEqual(policy.observations[1].step, policy.observations[2].step)
                event = next(e for e in events if e["event"] == "action_rejected")
                self.assertEqual(event["phase"], phase)
                self.assertEqual(event["feedback"]["control_acks"], [])

    def test_new_episode_resets_trace_and_never_reuses_previous_case_controls(self):
        adapter, policy, results, _, _ = self.run_fixture([decision(.1), decision(.2)], terminal_after=1, cases=2)
        self.assertEqual([r["environment_steps"] for r in results], [1, 1])
        self.assertEqual([o.step for o in policy.observations], [0, 0])
        self.assertTrue(all(o.control_feedback is None for o in policy.observations))
        self.assertEqual([f.control_acks[0].environment_step for f in policy.executions], [1, 1])
        self.assertTrue(all(len(f.control_acks) == 1 for f in policy.executions))
        self.assertTrue(all(n.resets == 1 for n in adapter.natives))

    def test_legacy_no_channel_has_no_new_serialized_keys(self):
        _, policy, results, events, manifest = self.run_fixture([decision(.1)], enabled=False, terminal_after=1)
        self.assertEqual(results[0]["status"], "completed")
        self.assertIsNone(policy.executions[0].control_acks)
        self.assertNotIn("control_acks", policy.executions[0].to_dict())
        self.assertNotIn("control_feedback_schema", manifest["observation_spec"])
        self.assertTrue(all("control_feedback" not in e.get("observation", {}) for e in events))

    def test_wire_requires_declared_channel_and_preserves_independent_payload(self):
        old = ObservationSpec()
        spec = ObservationSpec(control_feedback_schema=SCHEMA)
        observation = Observation(1, "fixture", control_feedback=payload(1))
        encoded = encode_observation(observation, spec)
        decoded = decode_observation(encoded, spec)
        self.assertEqual(decoded.control_feedback, payload(1))
        for callback in (lambda: encode_observation(observation, old),
                         lambda: decode_observation(encoded, old)):
            with self.assertRaises(WireError):
                callback()
        encoded["control_feedback"]["joint_command"][0] = 99.
        self.assertEqual(decoded.control_feedback, payload(1))

    def test_wire_rejects_missing_mismatched_stale_or_reset_feedback(self):
        spec = ObservationSpec(control_feedback_schema=SCHEMA)
        encoded = encode_observation(Observation(1, "fixture", control_feedback=payload(1)), spec)
        for value in (None, {**payload(1), "schema": "other/v1"}, payload(2),
                      {**payload(1), "control_target": True}):
            forged = deepcopy(encoded)
            forged["control_feedback"] = value
            with self.subTest(value=value), self.assertRaises(WireError):
                decode_observation(forged, spec)
        forged = deepcopy(encoded)
        forged.pop("control_feedback")
        with self.assertRaises(WireError):
            decode_observation(forged, spec)
        forged = deepcopy(encoded)
        forged["step"] = 0
        with self.assertRaises(WireError):
            decode_observation(forged, spec)
        reset = encode_observation(Observation(0, "fixture"), spec)
        self.assertIsNone(decode_observation(reset, spec).control_feedback)

    def test_malformed_server_ack_is_terminal_and_never_becomes_execution_feedback(self):
        for corrupt in (lambda value: None, lambda value: {**value, "control_target": 99}):
            with self.subTest(corrupt=corrupt):
                adapter, policy, results, _, _ = self.run_fixture(
                    [decision(.1, .2, .3)], corrupt_feedback=corrupt)
                self.assertEqual(results[0]["status"], "error")
                self.assertEqual(results[0]["environment_steps"], 0)
                self.assertEqual(results[0]["policy_calls"], 1)
                self.assertEqual(adapter.natives[0].controls, [(.1,)])
                self.assertEqual(policy.executions, [])
                self.assertEqual(policy.rejections, [])

    def test_feedback_dto_rejects_missing_duplicate_out_of_order_or_cross_step_acks(self):
        one = ControlAcknowledgement(environment_step=1, observation_step=1, payload=payload(1))
        two = ControlAcknowledgement(environment_step=2, observation_step=2, payload=payload(2))
        valid = ExecutionFeedback(1, 1, 2, 2, control_acks=(one, two))
        self.assertEqual(len(valid.control_acks), 2)
        for acks in ((), (one,), (one, one), (two, one), (two, two)):
            with self.subTest(acks=acks), self.assertRaises(ValueError):
                ExecutionFeedback(1, 1, 2, 2, control_acks=acks)
        with self.assertRaises(ValueError):
            ControlAcknowledgement(environment_step=1, observation_step=2, payload=payload(1))
        with self.assertRaises(ValueError):
            ActionRejectionFeedback(ValidationIssue("invalid_action"), 2, 1, 1, 0, 1, control_acks=(one,))

    def test_closed_auditor_rejects_bool_or_float_aliases_in_rejected_ack_trace(self):
        _, _, results, events, manifest = self.run_fixture(
            [decision(.1, .6, .3), decision(.4)], terminal_after=2)
        audit_episode(results[0], events, manifest["protocol"], manifest["policy"])
        for key in ("environment_step", "observation_step", "control_target"):
            for value in (True, 1.0):
                forged = deepcopy(events)
                ack = next(e for e in forged if e["event"] == "action_rejected")["feedback"]["control_acks"][0]
                target = ack["payload"] if key == "control_target" else ack
                target[key] = value
                with self.subTest(key=key, value_type=type(value).__name__), self.assertRaises(AuditError):
                    audit_episode(results[0], forged, manifest["protocol"], manifest["policy"])


if __name__ == "__main__":
    unittest.main()
