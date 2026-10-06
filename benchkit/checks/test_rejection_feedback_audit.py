"""Independent closed-record checks; only inert policies and CPU fake sessions."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits import closed_run as audit
from benchkit.contracts import ActionChunk, Observation, PolicyDecision, PolicyDescriptor, Transition, Usage
from benchkit.errors import ActionRejected
from benchkit.diagnostics.smoke import ReachBenchmark
from benchkit.validation import ValidationIssue
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest


KNOWN = Usage(calls=1, input_tokens=17, output_tokens=7, cached_input_tokens=3,
              estimated_cost_usd=.02, latency_s=.1)


def rejection(usage=KNOWN):
    return ActionRejected(ValidationIssue("invalid_length", actual=3, limit=7),
                          usage=usage, metadata={"response_sha256": "a" * 64})


def decision(values=((.2,),), usage=KNOWN):
    return PolicyDecision(action=ActionChunk.from_steps(values), usage=usage)


class FakePolicy:
    descriptor = PolicyDescriptor("rejection-audit-fixture", "scripted", version="1")

    def __init__(self, outcomes, hook_error=None):
        self.outcomes = iter(outcomes)
        self.hook_error = hook_error

    def compatibility_errors(self, *_):
        return []

    def start_episode(self, context):
        pass

    def act(self, observation):
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def observe_rejection(self, feedback):
        if self.hook_error:
            raise self.hook_error

    def end_episode(self):
        pass


class FakeSession:
    def __init__(self, reject_at):
        self.reject_at = reject_at
        self.submitted = self.acknowledged = 0

    def reset(self):
        return Observation(0, "CPU record consistency fixture", state=(0.,))

    def step(self, action):
        self.submitted += 1
        if self.submitted in self.reject_at:
            raise ActionRejected(ValidationIssue("invalid_action"))
        self.acknowledged += 1
        return Transition(Observation(self.acknowledged, "CPU record consistency fixture", state=action),
                          reward=.25)

    def metrics(self):
        return {"success": False}

    def artifacts(self):
        return {}

    def close(self):
        pass


class FakeBenchmark(ReachBenchmark):
    def __init__(self, reject_at=()):
        self.reject_at = reject_at

    def open_episode(self, spec):
        return FakeSession(self.reject_at)


class RejectionFeedbackAuditChecks(unittest.TestCase):
    def fixture(self, outcomes=None, *, reject_at=(), hook_error=None, mode="feedback", calls=2):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run = EvaluationRunner().run(FakeBenchmark(reject_at),
            FakePolicy([rejection(), decision()] if outcomes is None else outcomes, hook_error),
            RunRequest(output_dir=Path(temporary.name), run_id="cpu-rejection-audit",
                       max_steps=10, max_policy_calls=calls, replan_interval=3,
                       episode_limit=1, invalid_action_handling=mode))
        path = next((run / "episodes").glob("*/events.jsonl"))
        events = [json.loads(line) for line in path.read_text().splitlines()]
        protocol = json.loads((run / "manifest.json").read_text())["protocol"]
        return run, deepcopy(events[-1]["result"]), events, protocol

    @staticmethod
    def inspect(result, events, protocol):
        events[-1]["result"] = deepcopy(result)
        return audit.audit_episode(result, events, protocol)

    def test_policy_act_rejection_then_valid_counts_one_failed_and_one_returned_call(self):
        run, result, _, _ = self.fixture()
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["decisions_started"], row["decisions_returned"], row["controls"],
                          row["action_decisions"], row["rejected_actions"]), (2, 1, 1, 1, 1))
        self.assertEqual(result["usage"], (KNOWN + KNOWN).to_dict())
        self.assertFalse(row["success"])

    def test_action_spec_rejection_has_no_extra_usage_or_action_chunk(self):
        run, result, events, _ = self.fixture([decision(((2.,),)), decision()])
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["decisions_returned"], row["action_chunks"], row["controls"]), (2, 1, 1))
        rejected = next(event for event in events if event["event"] == "action_rejected")
        self.assertEqual((rejected["phase"], rejected["usage"]), ("action_spec", Usage().to_dict()))
        self.assertEqual(result["usage"], (KNOWN + KNOWN).to_dict())

    def test_service_rejection_before_ack_then_valid(self):
        run, _, _, _ = self.fixture([decision(), decision()], reject_at={1})
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["action_chunks"], row["controls"], row["action_decisions"],
                          row["rejected_actions"]), (2, 1, 1, 1))

    def test_service_rejection_keeps_acknowledged_prefix_exactly_once(self):
        run, result, events, _ = self.fixture([decision(((.1,), (.2,), (.3,))), decision()], reject_at={3})
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["controls"], row["action_decisions"], row["rejected_actions"]), (3, 2, 1))
        feedback = next(event["feedback"] for event in events if event["event"] == "action_rejected")
        self.assertEqual((feedback["executed_steps"], feedback["environment_steps"],
                          feedback["action_decisions"]), (2, 2, 1))
        self.assertEqual(result["reward_sum"], .75)

    def test_all_rejections_finish_at_call_cap_not_success(self):
        run, result, _, _ = self.fixture([rejection(), rejection()])
        self.assertEqual(audit.audit_run(run)["episodes"][0]["controls"], 0)
        self.assertEqual(result["termination_reason"], "runner:policy_call_limit")
        self.assertEqual(result["rejected_actions"], 2)
        self.assertFalse(result["success"])

    def test_unknown_accounting_remains_unavailable(self):
        run, result, _, _ = self.fixture([rejection(Usage.unavailable(latency_s=.3)), decision()])
        audit.audit_run(run)
        self.assertIsNone(result["usage"]["calls"])
        self.assertIsNone(result["usage"]["input_tokens"])
        self.assertAlmostEqual(result["usage"]["latency_s"], .4)

    def test_multi_provider_usage_does_not_imply_a_method_violation(self):
        run, result, _, _ = self.fixture([rejection(Usage(calls=2, input_tokens=8)), decision()])
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["status"], row["controls"], row["rejected_actions"]), ("completed", 1, 1))
        self.assertEqual(result["usage"]["calls"], 3)

    def test_feedback_hook_failure_is_terminal_not_second_rejection(self):
        for error in (RuntimeError("CPU hook failure"), rejection(Usage())):
            with self.subTest(error=type(error).__name__):
                run, _, _, _ = self.fixture(hook_error=error)
                row = audit.audit_run(run)["episodes"][0]
                self.assertEqual((row["status"], row["rejected_actions"], row["decisions_started"]),
                                 ("error", 1, 1))

    def test_generic_failed_act_after_rejection_has_explicit_unknown_usage(self):
        run, result, _, _ = self.fixture([rejection(), RuntimeError("CPU transport failure")])
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["status"], row["decisions_started"], row["rejected_actions"]), ("error", 2, 1))
        self.assertIsNone(result["usage"]["calls"])

    def test_new_terminate_mode_records_terminal_rejection_without_recovery(self):
        run, result, events, _ = self.fixture([rejection()], mode="terminate")
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["status"], row["rejected_actions"]), ("error", 1))
        self.assertFalse(any(event["event"] == "action_rejected" for event in events))
        self.assertEqual(result["usage"], KNOWN.to_dict())

    def test_callback_action_rejected_is_not_a_new_submission_rejection(self):
        for target, method in ((FakePolicy, "start_episode"), (FakePolicy, "observe_execution"),
                               (FakeSession, "metrics")):
            with self.subTest(method=method), patch.object(target, method, create=True,
                                                         side_effect=rejection(Usage())):
                run, result, _, _ = self.fixture([decision(), decision()])
                row = audit.audit_run(run)["episodes"][0]
                self.assertEqual((row["status"], row["rejected_actions"]), ("error", 0))
                self.assertNotIn("action_rejection_phase", result["error"])

    def test_terminal_rejection_requires_explicit_submission_phase(self):
        _, result, events, protocol = self.fixture([rejection()], mode="terminate")
        next(event for event in events if event["event"] == "error")["error"].pop("action_rejection_phase")
        with self.assertRaisesRegex(audit.AuditError, "rejection counters"):
            self.inspect(result, events, protocol)

    def test_native_terminate_mode_submission_rejection_is_counted_without_fake_ack(self):
        run, _, _, _ = self.fixture([decision()], reject_at={1}, mode="terminate")
        row = audit.audit_run(run)["episodes"][0]
        self.assertEqual((row["status"], row["controls"], row["rejected_actions"]), ("error", 0, 1))

    def test_feedback_requires_explicit_marker_and_finite_integer_call_cap(self):
        _, result, events, protocol = self.fixture()
        changes = ({"invalid_action_handling": "terminate"}, {"action_rejection_feedback_version": "other"},
                   {"execution_feedback_version": None}, {"max_policy_calls": None},
                   {"max_policy_calls": 2.0}, {"max_policy_calls": True})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(audit.AuditError):
                self.inspect(result, events, {**protocol, **change})

    def test_missing_duplicate_or_late_rejection_event_is_rejected(self):
        _, result, events, protocol = self.fixture()
        index = next(i for i, event in enumerate(events) if event["event"] == "action_rejected")
        for change in ("missing", "duplicate", "late"):
            changed = deepcopy(events)
            rejection_event = changed.pop(index)
            if change == "duplicate":
                changed[index:index] = [rejection_event, deepcopy(rejection_event)]
            elif change == "late":
                changed.insert(index + 1, rejection_event)
            with self.subTest(change=change), self.assertRaises(audit.AuditError):
                self.inspect(result, changed, protocol)

    def test_rejection_phase_or_usage_owner_cannot_be_forged(self):
        _, result, events, protocol = self.fixture()
        for change in ({"phase": "session_step"}, {"phase": "other"},
                       {"usage_recorded_in": "policy_decision"}):
            changed = deepcopy(events)
            next(event for event in changed if event["event"] == "action_rejected").update(change)
            with self.subTest(change=change), self.assertRaises(audit.AuditError):
                self.inspect(result, changed, protocol)

    def test_every_feedback_counter_is_bound_to_acknowledged_events(self):
        _, result, events, protocol = self.fixture([decision(((.1,), (.2,), (.3,))), decision()], reject_at={3})
        for key in ("policy_calls", "action_decisions", "environment_steps", "executed_steps", "rejected_actions"):
            changed = deepcopy(events)
            feedback = next(event["feedback"] for event in changed if event["event"] == "action_rejected")
            feedback[key] += 1
            with self.subTest(key=key), self.assertRaisesRegex(audit.AuditError, "counter mismatch"):
                self.inspect(result, changed, protocol)

    def test_result_rejection_counter_cannot_omit_failed_action(self):
        _, result, events, protocol = self.fixture()
        result["rejected_actions"] = 0
        with self.assertRaisesRegex(audit.AuditError, "rejection counters"):
            self.inspect(result, events, protocol)

    def test_feedback_issue_is_closed_scalar_data_not_native_state(self):
        _, result, events, protocol = self.fixture()
        mutations = ({"actual": {"object_pose": [0, 0, 0]}}, {"field": "native.contact"},
                     {"code": "private server exception"}, {"limit": True}, {"actual": float("inf")},
                     {"action_index": -1}, {"action_index": True}, {"action_index": 2**31},
                     {"private": "value"})
        for mutation in mutations:
            changed = deepcopy(events)
            issue = next(event["feedback"]["issue"] for event in changed if event["event"] == "action_rejected")
            issue.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(audit.AuditError):
                self.inspect(result, changed, protocol)

    def test_rejection_event_cannot_claim_reward_or_execution(self):
        _, result, events, protocol = self.fixture()
        for extra in ({"reward": 1}, {"action": [0.]}, {"observation": {}}, {"terminated": True}):
            changed = deepcopy(events)
            next(event for event in changed if event["event"] == "action_rejected").update(extra)
            with self.subTest(extra=extra), self.assertRaisesRegex(audit.AuditError, "event fields"):
                self.inspect(result, changed, protocol)

    def test_control_after_rejection_cannot_execute_unacknowledged_suffix(self):
        _, result, events, protocol = self.fixture([decision(((.1,), (.2,), (.3,))), decision()], reject_at={3})
        index = next(i for i, event in enumerate(events) if event["event"] == "action_rejected")
        fake_ack = deepcopy(events[index - 1])
        fake_ack.update(chunk_index=2, environment_step=3, action=[.3])
        events.insert(index + 1, fake_ack)
        with self.assertRaisesRegex(audit.AuditError, "outside active"):
            self.inspect(result, events, protocol)

    def test_rejection_cannot_credit_unacknowledged_control_or_reward_in_result(self):
        _, result, events, protocol = self.fixture()
        for key in ("environment_steps", "action_decisions", "reward_sum"):
            changed = deepcopy(result)
            changed[key] += 1
            with self.subTest(key=key), self.assertRaises(audit.AuditError):
                self.inspect(changed, deepcopy(events), protocol)

    def test_policy_act_rejection_usage_cannot_be_omitted_or_changed(self):
        _, result, events, protocol = self.fixture()
        for key in ("calls", "input_tokens", "output_tokens", "cached_input_tokens", "latency_s", "estimated_cost_usd"):
            changed = deepcopy(result)
            changed["usage"][key] = 0
            with self.subTest(key=key), self.assertRaisesRegex(audit.AuditError, "usage mismatch"):
                self.inspect(changed, deepcopy(events), protocol)
        changed = deepcopy(events)
        next(event for event in changed if event["event"] == "action_rejected").pop("usage")
        with self.assertRaises(audit.AuditError):
            self.inspect(result, changed, protocol)

    def test_post_decision_rejection_cannot_double_count_provider_usage(self):
        _, result, events, protocol = self.fixture([decision(((2.,),)), decision()])
        next(event for event in events if event["event"] == "action_rejected")["usage"] = KNOWN.to_dict()
        result["usage"] = (KNOWN + KNOWN + KNOWN).to_dict()
        with self.assertRaisesRegex(audit.AuditError, "must not add provider usage"):
            self.inspect(result, events, protocol)

    def test_provider_retry_cannot_hide_inside_recovered_call(self):
        _, result, events, protocol = self.fixture()
        protocol.pop("usage_accounting_version")  # Historical one-inference records retain their contract.
        next(event for event in events if event["event"] == "action_rejected")["usage"]["calls"] = 2
        result["usage"]["calls"] += 1
        with self.assertRaisesRegex(audit.AuditError, "retry violation"):
            self.inspect(result, events, protocol)

    def test_returned_decision_with_multiple_provider_calls_cannot_control_or_continue(self):
        _, result, events, protocol = self.fixture([decision(), decision()])
        protocol.pop("usage_accounting_version")  # Historical contract, not the open-method extension.
        next(event for event in events if event["event"] == "policy_decision")["usage"]["calls"] = 2
        result["usage"]["calls"] += 1
        with self.assertRaisesRegex(audit.AuditError, "retry violation"):
            self.inspect(result, events, protocol)

    def test_missing_terminal_failed_call_usage_cannot_be_hidden_as_unknown_result(self):
        _, result, events, protocol = self.fixture([rejection(), RuntimeError("CPU failure")])
        next(event for event in events if event["event"] == "error")["error"].pop("usage")
        with self.assertRaisesRegex(audit.AuditError, "unmetered policy call"):
            self.inspect(result, events, protocol)

    def test_duplicate_failed_call_usage_after_decision_is_rejected(self):
        _, result, events, protocol = self.fixture([decision()], reject_at={1}, hook_error=RuntimeError("CPU failure"))
        event = next(event for event in events if event["event"] == "error")
        event["error"].update(policy_call=1, usage=KNOWN.to_dict())
        result["usage"] = (KNOWN + KNOWN).to_dict()
        with self.assertRaisesRegex(audit.AuditError, "failed-call accounting"):
            self.inspect(result, events, protocol)

    def test_summary_usage_and_rejection_totals_are_checked(self):
        run, _, _, _ = self.fixture()
        path = run / "summary.json"
        original = json.loads(path.read_text())
        for key in ("rejected_actions", "usage"):
            changed = deepcopy(original)
            if key == "usage":
                changed[key]["input_tokens"] = 0
            else:
                changed[key] = 0
            path.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(audit.AuditError):
                audit.audit_run(run)


if __name__ == "__main__":
    unittest.main()
