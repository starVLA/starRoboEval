"""No-SIM/no-model regression for counted, explicit invalid-action feedback."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.contracts import ActionChunk, Observation, PolicyDecision, PolicyDescriptor, Transition, Usage
from benchkit.errors import ActionRejected, CompatibilityError, InfrastructureError, PolicyCallError
from benchkit.diagnostics.smoke import ReachBenchmark
from benchkit.validation import ValidationIssue
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest


def decision(*values, calls=1):
    return PolicyDecision(action=ActionChunk(tuple((value,) for value in values)),
                          usage=Usage(calls=calls, input_tokens=7, output_tokens=3, latency_s=0.2))


def rejection(*, calls=1):
    return ActionRejected(ValidationIssue("invalid_json", "response"),
                          usage=Usage(calls=calls, input_tokens=11, output_tokens=5, latency_s=0.3),
                          metadata={"receipt_id": "synthetic-private-receipt"})


class Session:
    def __init__(self, *, failures=None, terminate_after=None):
        self.failures = failures or {}
        self.terminate_after = terminate_after
        self.controls = []
        self.attempts = self.resets = self.closes = self.metric_reads = 0

    def reset(self):
        self.resets += 1
        return Observation(step=0, instruction="synthetic fixture", state=(0.0,))

    def step(self, action):
        self.attempts += 1
        if self.attempts in self.failures:
            raise self.failures[self.attempts]
        self.controls.append(action)
        return Transition(Observation(step=len(self.controls), instruction="synthetic fixture",
                           state=(action[0],)), reward=0.0,
                          terminated=len(self.controls) == self.terminate_after)

    def metrics(self):
        self.metric_reads += 1
        return {"success": len(self.controls) == self.terminate_after}

    def artifacts(self):
        return {}

    def close(self):
        self.closes += 1


class Policy:
    descriptor = PolicyDescriptor("rejection-fixture", "scripted", version="1")

    def __init__(self, outcomes, *, hook_error=None):
        self.outcomes = iter(outcomes)
        self.hook_error = hook_error
        self.observations, self.rejections, self.executions = [], [], []
        self.ended = 0

    def compatibility_errors(self, observation_spec, action_spec):
        return []

    def start_episode(self, context):
        self.context = context

    def act(self, observation):
        self.observations.append(observation)
        result = next(self.outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    def observe_rejection(self, feedback):
        self.rejections.append(feedback)
        if self.hook_error is not None:
            raise self.hook_error

    def observe_execution(self, feedback):
        self.executions.append(feedback)

    def end_episode(self):
        self.ended += 1


class RejectionRunnerChecks(unittest.TestCase):
    def run_fixture(self, outcomes, *, session=None, policy=None, mode="feedback",
                    max_calls=3, max_steps=6, prefix=3):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        policy, session = policy or Policy(outcomes), session or Session()
        benchmark = ReachBenchmark()
        benchmark.open_episode = lambda _: session
        run = EvaluationRunner().run(benchmark, policy, RunRequest(output_dir=Path(temporary.name),
            run_id="synthetic", episode_limit=1, max_steps=max_steps, max_policy_calls=max_calls,
            replan_interval=prefix, invalid_action_handling=mode))
        result = json.loads((run / "episodes.jsonl").read_text())
        events = [json.loads(s) for s in (run / "episodes" / "reach-000" / "events.jsonl").read_text().splitlines()]
        return result, events, json.loads((run / "summary.json").read_text()), policy, session, run

    def test_failed_parse_gets_one_feedback_and_one_new_counted_call(self):
        failed = rejection()
        result, events, summary, policy, session, run = self.run_fixture(
            [failed, decision(0.3)], session=Session(terminate_after=1))
        self.assertEqual((result["policy_calls"], result["action_decisions"], result["environment_steps"],
                          result["rejected_actions"]), (2, 1, 1, 1))
        self.assertIs(result["success"], True)
        self.assertEqual(result["usage"], (failed.usage + decision(0.3).usage).to_dict())
        self.assertEqual(summary["rejected_actions"], 1)
        self.assertEqual(summary["by_task"]["reach"]["rejected_actions"], 1)
        self.assertIs(policy.observations[0], policy.observations[1])
        self.assertEqual(len(policy.rejections), 1)
        self.assertEqual(len(policy.executions), 1)
        self.assertEqual(policy.rejections[0].executed_steps, 0)
        self.assertNotIn("synthetic-private-receipt", json.dumps(policy.rejections[0].to_dict()))
        rejected = next(e for e in events if e["event"] == "action_rejected")
        self.assertEqual(rejected["phase"], "policy_act")
        self.assertEqual(rejected["usage_recorded_in"], "action_rejected")
        self.assertEqual(rejected["usage"], failed.usage.to_dict())
        self.assertEqual((session.resets, session.closes), (1, 1))
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["protocol"]["action_rejection_feedback_version"],
                         "starvla-rsi.action-rejection-feedback/v1")
        self.assertEqual(policy.context.invalid_action_handling, "feedback")

    def test_repeated_rejections_exhaust_call_budget_without_controls_or_resets(self):
        result, events, _, policy, session, _ = self.run_fixture([rejection() for _ in range(3)])
        self.assertEqual(result["termination_reason"], "runner:policy_call_limit")
        self.assertEqual((result["policy_calls"], result["rejected_actions"], result["action_decisions"],
                          result["environment_steps"]), (3, 3, 0, 0))
        self.assertEqual(len({id(x) for x in policy.observations}), 1)
        self.assertEqual((session.attempts, session.resets, session.metric_reads), (0, 1, 1))
        self.assertEqual([f.rejected_actions for f in policy.rejections], [1, 2, 3])
        self.assertEqual(result["usage"]["calls"], 3)

    def test_whole_chunk_prevalidated_even_beyond_allowed_prefix(self):
        for invalid in (2.0, float("nan"), float("inf")):
            with self.subTest(invalid=str(invalid)):
                stop = PolicyDecision(stop=True, stop_reason="give_up", usage=Usage(calls=1))
                result, events, _, policy, session, _ = self.run_fixture([decision(0.2, invalid), stop], prefix=1)
                self.assertEqual(session.controls, [])
                self.assertEqual(result["action_decisions"], 0)
                self.assertEqual(result["rejected_actions"], 1)
                self.assertEqual(result["usage"]["calls"], 2)
                reject = next(e for e in events if e["event"] == "action_rejected")
                self.assertEqual(reject["phase"], "action_spec")
                self.assertEqual(reject["usage"], Usage().to_dict())
                self.assertEqual(reject["usage_recorded_in"], "policy_decision")
                self.assertFalse(any(e["event"] == "action_chunk" for e in events))

    def test_zero_control_service_rejection_keeps_observation_and_usage(self):
        session = Session(failures={1: ActionRejected(ValidationIssue("quaternion_not_unit"))}, terminate_after=1)
        result, events, _, policy, session, _ = self.run_fixture([decision(0.1), decision(0.2)], session=session)
        self.assertEqual(session.controls, [(0.2,)])
        self.assertEqual(result["usage"]["calls"], 2)
        self.assertEqual(result["action_decisions"], 1)
        self.assertIs(policy.observations[0], policy.observations[1])
        self.assertEqual(policy.rejections[0].executed_steps, 0)
        self.assertEqual(next(e for e in events if e["event"] == "action_rejected")["phase"], "session_step")

    def test_partial_prefix_is_acknowledged_once_and_never_replayed(self):
        session = Session(failures={2: ActionRejected(ValidationIssue("invalid_action"))}, terminate_after=2)
        result, events, _, policy, session, _ = self.run_fixture(
            [decision(0.1, 0.2, 0.3), decision(0.4)], session=session)
        self.assertEqual(session.controls, [(0.1,), (0.4,)])
        self.assertEqual((result["action_decisions"], result["environment_steps"], result["rejected_actions"]), (2, 2, 1))
        self.assertEqual(policy.observations[1].state, (0.1,))
        self.assertEqual((policy.rejections[0].action_decisions, policy.rejections[0].environment_steps,
                          policy.rejections[0].executed_steps), (1, 1, 1))
        self.assertEqual(len(policy.executions), 1)  # ONLY the second call gets ordinary execution feedback.
        self.assertEqual(policy.executions[0].policy_calls, 2)
        self.assertEqual(sum(e["usage"]["calls"] for e in events if "usage" in e), 2)

    def test_unknown_or_infrastructure_failure_after_ack_is_terminal(self):
        for failure in (InfrastructureError("lost ACK"), RuntimeError("native uncertainty"),
                        PolicyCallError("unexpected transport failure", usage=Usage(), category="infrastructure")):
            with self.subTest(failure=type(failure).__name__):
                session = Session(failures={2: failure})
                result, _, _, policy, session, _ = self.run_fixture([decision(0.1, 0.2, 0.3)], session=session)
                self.assertEqual(result["status"], "error")
                self.assertEqual((result["action_decisions"], result["environment_steps"], result["policy_calls"]), (1, 1, 1))
                self.assertEqual((result["rejected_actions"], len(policy.rejections)), (0, 0))
                self.assertEqual(session.controls, [(0.1,)])
                self.assertEqual(session.closes, 1)

    def test_policy_infrastructure_and_untyped_parse_error_never_recover(self):
        failures = (PolicyCallError("transport unavailable", usage=Usage.unavailable(), category="infrastructure"),
                    ValueError("untyped failure"), RuntimeError("unknown failure"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                result, _, _, policy, session, _ = self.run_fixture([failure])
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["policy_calls"], 1)
                self.assertEqual(result["rejected_actions"], 0)
                self.assertEqual(policy.rejections, [])
                self.assertEqual(session.attempts, 0)
                self.assertEqual(result["error"]["policy_call"], 1)
                self.assertEqual(result["error"]["usage"], result["usage"])

    def test_multiple_inferences_can_return_a_recoverable_typed_rejection(self):
        result, _, _, policy, session, _ = self.run_fixture(
            [rejection(calls=2), decision(0.1)], session=Session(terminate_after=1))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage"]["calls"], 3)
        self.assertEqual(result["policy_calls"], 2)
        self.assertEqual(result["rejected_actions"], 1)
        self.assertEqual((len(policy.rejections), session.attempts), (1, 1))

    def test_returned_multi_inference_decision_executes_normally(self):
        result, _, _, policy, session, _ = self.run_fixture(
            [decision(0.1, calls=2)], session=Session(terminate_after=1))
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["usage"]["calls"], result["policy_calls"]), (2, 1))
        self.assertEqual(result["rejected_actions"], 0)
        self.assertEqual((len(policy.rejections), session.attempts), (0, 1))

    def test_service_rejection_cannot_add_or_hide_policy_usage(self):
        session = Session(failures={1: ActionRejected(ValidationIssue("invalid_action"), usage=Usage(calls=1))})
        result, _, _, policy, session, _ = self.run_fixture([decision(0.1)], session=session)
        self.assertEqual(result["error"]["category"], "protocol")
        self.assertEqual((result["usage"]["calls"], result["rejected_actions"]), (1, 0))
        self.assertEqual(policy.rejections, [])

    def test_rejection_hook_failure_is_terminal_without_double_accounting(self):
        policy = Policy([rejection()], hook_error=ActionRejected(ValidationIssue("invalid_action")))
        result, events, _, policy, session, _ = self.run_fixture([], policy=policy)
        self.assertEqual(result["status"], "error")
        self.assertEqual((result["usage"]["calls"], result["rejected_actions"], result["policy_calls"]), (1, 1, 1))
        self.assertEqual(sum(e["event"] == "action_rejected" for e in events), 1)
        self.assertNotIn("action_rejection_phase", result["error"])
        self.assertEqual(session.attempts, 0)

    def test_default_terminate_does_not_enable_feedback(self):
        result, events, _, policy, _, run = self.run_fixture([rejection()], mode="terminate")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "ActionRejected")
        self.assertEqual(result["error"]["issue"]["code"], "invalid_json")
        self.assertEqual(result["error"]["action_rejection_phase"], "policy_act")
        self.assertEqual(result["rejected_actions"], 1)
        self.assertEqual(policy.rejections, [])
        self.assertFalse(any(e["event"] == "action_rejected" for e in events))
        self.assertNotIn("action_rejection_feedback_version", json.loads((run / "manifest.json").read_text())["protocol"])

    def test_terminate_service_rejection_has_explicit_submission_phase(self):
        session = Session(failures={2: ActionRejected(ValidationIssue("invalid_action"))})
        result, _, _, policy, _, _ = self.run_fixture([decision(0.1, 0.2)], session=session, mode="terminate")
        self.assertEqual(result["error"]["action_rejection_phase"], "session_step")
        self.assertEqual((result["rejected_actions"], result["environment_steps"]), (1, 1))
        self.assertEqual(policy.rejections, [])

    def test_typed_callback_exceptions_do_not_invent_rejected_submissions(self):
        for phase in ("start_episode", "observe_execution", "metrics"):
            with self.subTest(phase=phase):
                policy, session = Policy([decision(0.1)]), Session(terminate_after=1)
                target = session if phase == "metrics" else policy
                with patch.object(target, phase, side_effect=ActionRejected(ValidationIssue("invalid_action"))):
                    result, _, _, _, _, _ = self.run_fixture([], policy=policy, session=session)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["rejected_actions"], 0)
                self.assertNotIn("action_rejection_phase", result["error"])

    def test_feedback_requires_finite_integer_calls_before_any_open(self):
        for cap in (None, True, 0, -1, 2.0, float("inf"), float("nan"), "3"):
            with self.subTest(cap_type=type(cap).__name__), self.assertRaises(ValueError):
                RunRequest(output_dir=Path("unused"), max_policy_calls=cap, invalid_action_handling="feedback")
        self.assertEqual(RunRequest(output_dir=Path("unused")).invalid_action_handling, "terminate")
        with self.assertRaises(ValueError):
            RunRequest(output_dir=Path("unused"), invalid_action_handling="retry")

    def test_hook_capability_checked_before_schedule_output_or_native_open(self):
        for hook in (None, 1):
            with tempfile.TemporaryDirectory() as directory:
                policy, benchmark = Policy([]), ReachBenchmark()
                policy.observe_rejection = hook
                output = Path(directory) / "not-created"
                with patch.object(benchmark, "episodes", side_effect=AssertionError("no schedule")):
                    with self.assertRaises(CompatibilityError):
                        EvaluationRunner().run(benchmark, policy, RunRequest(output_dir=output,
                            max_policy_calls=1, invalid_action_handling="feedback"))
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
