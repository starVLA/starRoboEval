"""Failed-call accounting with CPU fake policies; no provider or native runtime."""

import json
from pathlib import Path
import tempfile
import unittest

from benchkit.audits.closed_run import audit_run
from benchkit.contracts import ActionChunk, PolicyDecision, PolicyDescriptor, Usage
from benchkit.errors import PolicyCallError
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.diagnostics.smoke import ReachBenchmark, ReachEpisode


class TrackedEpisode(ReachEpisode):
    def __init__(self, spec, *, step_error=None, close_error=False):
        super().__init__(spec)
        self.step_error = step_error
        self.close_error = close_error
        self.closed = False
        self.artifacts_read = False
        self.metrics_read = False

    def step(self, action):
        if self.step_error is not None:
            raise self.step_error
        return super().step(action)

    def metrics(self):
        self.metrics_read = True
        # Even an optimistic metric must never turn a failed act into success.
        return {"success": True}

    def artifacts(self):
        self.artifacts_read = True
        return {}

    def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError("synthetic close failure")


class TrackedBenchmark(ReachBenchmark):
    def __init__(self, **options):
        self.options = options
        self.sessions = []

    def open_episode(self, episode):
        session = TrackedEpisode(episode, **self.options)
        self.sessions.append(session)
        return session


class FakePolicy:
    descriptor = PolicyDescriptor("failed-call-fixture", "scripted", version="1")

    def __init__(self, outcomes, *, start_error=None, end_error=False):
        self.outcomes = iter(outcomes)
        self.start_error = start_error
        self.end_error = end_error
        self.ended = 0

    def compatibility_errors(self, observation_spec, action_spec):
        return []

    def start_episode(self, context):
        if self.start_error is not None:
            raise self.start_error

    def act(self, observation):
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def end_episode(self):
        self.ended += 1
        if self.end_error:
            raise RuntimeError("synthetic policy cleanup failure")


class PolicyCallErrorChecks(unittest.TestCase):
    def run_fixture(self, outcomes=(), *, policy=None, benchmark=None, episodes=1):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        policy = policy or FakePolicy(outcomes)
        benchmark = benchmark or TrackedBenchmark()
        run = EvaluationRunner().run(benchmark, policy, RunRequest(
            output_dir=Path(temporary.name), max_steps=5, max_policy_calls=3,
            replan_interval=1, episode_limit=episodes, run_id="synthetic-policy-call"))
        results = [json.loads(line) for line in (run / "episodes.jsonl").read_text().splitlines()]
        events = [json.loads(line) for line in next((run / "episodes").glob("*/events.jsonl")).read_text().splitlines()]
        summary = json.loads((run / "summary.json").read_text())
        return run, results, events, summary, policy, benchmark

    @staticmethod
    def failure(*, calls=1, category="policy"):
        return PolicyCallError("structured response is not a valid action", category=category,
            usage=Usage(calls=calls, input_tokens=17, output_tokens=9, cached_input_tokens=3,
                        estimated_cost_usd=0.02, latency_s=0.4),
            metadata={"request_id": "synthetic-request", "response_id": "synthetic-response",
                      "response_status": "completed", "response_sha256": "a" * 64})

    def test_known_usage_and_receipt_survive_without_a_decision_or_control(self):
        failure = self.failure()
        run, results, events, summary, policy, benchmark = self.run_fixture([failure])
        result = results[0]
        self.assertEqual(result["usage"], failure.usage.to_dict())
        self.assertEqual(summary["usage"], failure.usage.to_dict())
        self.assertEqual(result["error"]["usage"], failure.usage.to_dict())
        self.assertEqual(result["error"]["metadata"], failure.metadata)
        self.assertEqual(result["error"]["policy_call"], 1)
        self.assertEqual(result["error"]["type"], "PolicyCallError")
        self.assertEqual(result["termination_reason"], "error:policy")
        self.assertEqual((result["environment_steps"], result["action_decisions"], result["policy_calls"]), (0, 0, 1))
        self.assertIsNone(result["success"])
        self.assertEqual((summary["successes"], summary["errors"], summary["completed"]), (0, 1, 0))
        self.assertNotIn("traceback", result["error"])
        self.assertEqual([event["event"] for event in events],
                         ["episode_start", "observation", "policy_call_start", "error", "episode_end"])
        self.assertEqual(events[-2]["error"], result["error"])
        self.assertTrue(benchmark.sessions[0].artifacts_read)
        self.assertTrue(benchmark.sessions[0].closed)
        self.assertFalse(benchmark.sessions[0].metrics_read)
        self.assertEqual(policy.ended, 1)
        self.assertEqual(audit_run(run)["record_consistency"], "passed")

    def test_known_usage_accumulates_after_a_returned_action(self):
        previous = Usage(calls=1, input_tokens=10, output_tokens=4, cached_input_tokens=2,
                         estimated_cost_usd=0.01, latency_s=0.2)
        failure = self.failure()
        decision = PolicyDecision(action=ActionChunk.from_steps([[0.0]]), usage=previous)
        run, results, events, summary, _, _ = self.run_fixture([decision, failure])
        result = results[0]
        self.assertEqual(result["usage"], (previous + failure.usage).to_dict())
        self.assertEqual(summary["usage"], result["usage"])
        self.assertEqual(result["error"]["usage"], failure.usage.to_dict())
        self.assertEqual(result["error"]["policy_call"], 2)
        self.assertEqual((result["environment_steps"], result["action_decisions"], result["policy_calls"]), (1, 1, 2))
        self.assertEqual(sum(event["event"] == "policy_decision" for event in events), 1)
        self.assertIsNone(result["success"])
        self.assertEqual(audit_run(run)["record_consistency"], "passed")

    def test_failed_second_episode_keeps_earlier_success_and_total_usage(self):
        previous = Usage(calls=1, input_tokens=10, output_tokens=4, latency_s=0.2)
        decision = PolicyDecision(stop=True, stop_reason="give_up", usage=previous)
        failure = self.failure(category="infrastructure")
        run, results, _, summary, policy, benchmark = self.run_fixture([decision, failure], episodes=2)
        self.assertIs(results[0]["success"], True)  # synthetic metric from first closed episode
        self.assertIsNone(results[1]["success"])
        self.assertEqual(summary["usage"], (previous + failure.usage).to_dict())
        self.assertEqual((summary["completed"], summary["successes"], summary["errors"]), (1, 1, 1))
        self.assertEqual(results[1]["error"]["category"], "infrastructure")
        self.assertEqual(policy.ended, 2)
        self.assertTrue(all(session.closed for session in benchmark.sessions))
        self.assertEqual(audit_run(run)["record_consistency"], "passed")

    def test_unknown_and_partial_usage_remain_unknown(self):
        variants = (Usage.unavailable(), Usage(calls=1, input_tokens=None, output_tokens=7,
                    cached_input_tokens=None, estimated_cost_usd=None, latency_s=0.3))
        for reported in variants:
            with self.subTest(usage=reported):
                failure = PolicyCallError("transport failed", usage=reported, category="infrastructure")
                _, results, _, summary, _, _ = self.run_fixture([failure])
                self.assertEqual(results[0]["usage"], reported.to_dict())
                self.assertEqual(summary["usage"], reported.to_dict())
                self.assertIsNone(results[0]["usage"]["input_tokens"])
                self.assertEqual(results[0]["termination_reason"], "error:infrastructure")

    def test_unknown_failure_after_known_action_propagates_null_totals(self):
        decision = PolicyDecision(action=ActionChunk.from_steps([[0.0]]),
                                  usage=Usage(calls=1, input_tokens=10, latency_s=0.2))
        failure = PolicyCallError("transport response unavailable", usage=Usage.unavailable(latency_s=0.3),
                                  category="infrastructure")
        _, results, events, summary, _, _ = self.run_fixture([decision, failure])
        self.assertIsNone(results[0]["usage"]["calls"])
        self.assertIsNone(summary["usage"]["input_tokens"])
        self.assertAlmostEqual(summary["usage"]["latency_s"], 0.5)
        self.assertEqual(next(e for e in events if e["event"] == "policy_decision")["usage"]["input_tokens"], 10)

    def test_multiple_reported_provider_calls_preserve_original_failure_category(self):
        failure = self.failure(calls=2, category="infrastructure")
        run, results, events, summary, _, _ = self.run_fixture([failure])
        result = results[0]
        self.assertEqual(result["usage"], failure.usage.to_dict())
        self.assertEqual(summary["usage"]["calls"], 2)
        self.assertEqual(result["error"]["type"], "PolicyCallError")
        self.assertEqual(result["error"]["category"], "infrastructure")
        self.assertEqual(result["error"]["metadata"], failure.metadata)
        self.assertEqual(result["environment_steps"], 0)
        self.assertFalse(any(event["event"] == "policy_decision" for event in events))
        self.assertEqual(audit_run(run)["record_consistency"], "passed")

    def test_ordinary_exception_keeps_historical_unavailable_fallback(self):
        for exception in (ValueError("synthetic parse failure"), RuntimeError("synthetic transport failure")):
            with self.subTest(exception=exception):
                _, results, _, _, _, _ = self.run_fixture([exception])
                result = results[0]
                self.assertIsNone(result["usage"]["calls"])
                self.assertIsNone(result["usage"]["input_tokens"])
                self.assertGreaterEqual(result["usage"]["latency_s"], 0)
                self.assertNotIn("metadata", result["error"])
                self.assertIn("traceback", result["error"])

    def test_typed_failure_outside_act_never_credits_receipt_usage(self):
        failure = self.failure()
        previous = Usage(calls=1, input_tokens=10, latency_s=0.2)
        decision = PolicyDecision(action=ActionChunk.from_steps([[0.0]]), usage=previous)
        variants = (
            (FakePolicy([], start_error=failure), TrackedBenchmark(), Usage(), 0),
            (FakePolicy([decision]), TrackedBenchmark(step_error=failure), previous, 1),
        )
        for policy, benchmark, expected, calls in variants:
            with self.subTest(calls=calls):
                _, results, _, _, _, _ = self.run_fixture(policy=policy, benchmark=benchmark)
                result = results[0]
                self.assertEqual(result["usage"], expected.to_dict())
                self.assertEqual(result["policy_calls"], calls)
                self.assertNotIn("usage", result["error"])
                self.assertNotIn("metadata", result["error"])
                self.assertTrue(benchmark.sessions[0].closed)

    def test_provider_exception_chain_is_not_serialized(self):
        failure = self.failure()

        class ChainedPolicy(FakePolicy):
            def act(self, observation):
                try:
                    raise RuntimeError("SYNTHETIC_PRIVATE_ERROR_BODY")
                except RuntimeError as original:
                    raise failure from original

        run, results, events, _, _, _ = self.run_fixture(policy=ChainedPolicy([]))
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR_BODY", json.dumps(results + events))
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR_BODY", (run / "episodes.jsonl").read_text())
        self.assertNotIn("traceback", results[0]["error"])

    def test_cleanup_failures_do_not_replace_primary_failure_or_usage(self):
        failure = self.failure()
        policy = FakePolicy([failure], end_error=True)
        _, results, _, summary, _, benchmark = self.run_fixture(
            policy=policy, benchmark=TrackedBenchmark(close_error=True))
        self.assertEqual(results[0]["error"]["message"], str(failure))
        self.assertEqual(results[0]["error"]["usage"], failure.usage.to_dict())
        self.assertEqual(summary["usage"], failure.usage.to_dict())
        self.assertEqual(len(results[0]["error"]["cleanup_errors"]), 2)
        self.assertTrue(benchmark.sessions[0].closed)

    def test_constructor_copies_metadata_and_rejects_invalid_receipts(self):
        metadata = {"receipt": {"response_id": "original"}}
        failure = PolicyCallError("sanitized failure", usage=Usage(calls=1), metadata=metadata)
        metadata["receipt"]["response_id"] = "changed"
        self.assertEqual(failure.metadata["receipt"]["response_id"], "original")
        invalid = ({"value": float("nan")}, {"value": float("inf")}, {"value": object()},
                   {"value": "x" * (PolicyCallError.MAX_METADATA_BYTES + 1)})
        for receipt in invalid:
            with self.subTest(receipt_type=type(receipt["value"]).__name__), self.assertRaises(ValueError):
                PolicyCallError("failure", usage=Usage(), metadata=receipt)
        with self.assertRaises(TypeError):
            PolicyCallError("failure", usage=Usage(), metadata=[])
        with self.assertRaises(TypeError):
            PolicyCallError("failure", usage={"calls": 1})
        with self.assertRaises(ValueError):
            PolicyCallError("failure", usage=Usage(), category="protocol")
        for message in ("", " ", "x" * 1025):
            with self.assertRaises(ValueError):
                PolicyCallError(message, usage=Usage())


if __name__ == "__main__":
    unittest.main()
