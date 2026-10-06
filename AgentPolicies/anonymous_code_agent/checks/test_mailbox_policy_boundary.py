"""Policy-side persistence checks without images, simulator or provider calls."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchkit.contracts import (
    ActionSpec, BenchmarkDescriptor, EpisodeContext, ExecutionFeedback,
    Observation, ObservationSpec, PolicyEpisodeSpec,
)
from benchkit.errors import PolicyError
from benchkit.audits.mailbox_artifacts import audit_policy_fields
from AgentPolicies.anonymous_code_agent.mailbox import MailboxPolicy
from AgentPolicies.policy_support.stop_rules import VoluntaryStopRule, with_stop_rule_prompt


class MailboxPolicyBoundaryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.policy = MailboxPolicy(Path(self.temp.name).resolve() / "mailbox",
                                    min_action_decisions_before_give_up=50)
        self.context = EpisodeContext(
            BenchmarkDescriptor("fixture", "1", "fixture/v1", "fixture"),
            PolicyEpisodeSpec("opaque", "fixture", "Fixture task"),
            ObservationSpec(), ActionSpec("fixture", 1), 1000, 200, 5,
        )
        self.policy.start_episode(self.context)

    def public(self):
        return self.policy._export_observation(Observation(0, "Fixture task"), "opaque", self.policy.directory)

    def test_actual_premature_stop_is_retained_and_not_retried(self):
        def response(path):
            return {"request_id": path.parent.name, "stop": True,
                    "stop_reason": "give_up", "usage": None}
        with patch("AgentPolicies.anonymous_code_agent.mailbox.os.path.lexists", return_value=True), \
                patch.object(self.policy, "_read_response", side_effect=response) as read:
            with self.assertRaisesRegex(PolicyError, "only 0 completed"):
                self.policy.act(Observation(0, "Fixture task"))
            accepted = list(self.policy.directory.glob("*/accepted_response.json"))
            self.assertEqual(len(accepted), 1)
            self.assertEqual(json.loads(accepted[0].read_text())["stop_reason"], "give_up")
            with self.assertRaisesRegex(PolicyError, "cannot retry"):
                self.policy.act(Observation(1, "Fixture task"))
            self.assertEqual(read.call_count, 1)
        self.policy.end_episode()

    def test_auditor_accepts_only_policy_scoped_counter_fields(self):
        public = self.public()
        protocol = {"execution_feedback_version": "starvla-rsi.execution-feedback/v1"}
        feedback = {"policy_calls": 0, "action_decisions": 0, "environment_steps": 0, "executed_steps": 0}
        audit_policy_fields(public, self.policy.descriptor.version,
                            self.policy.descriptor.parameters, protocol, feedback)
        public["control_feedback"]["action_decisions"] = 50
        with self.assertRaisesRegex(ValueError, "feedback differs"):
            audit_policy_fields(public, self.policy.descriptor.version,
                                self.policy.descriptor.parameters, protocol, feedback)

    def test_private_state_cannot_be_added_to_execution_feedback(self):
        with self.assertRaises(TypeError):
            ExecutionFeedback(1, 1, 5, 5, success=True)
        for fields in ((True, 1, 5, 5), (1, 2, 5, 5), (1, 1, 0, 0)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ExecutionFeedback(*fields)

    def test_execution_receipts_must_be_consecutive_and_reset_each_episode(self):
        rule = VoluntaryStopRule(50)
        rule.start_episode(self.context)
        with self.assertRaisesRegex(PolicyError, "not consecutive"):
            rule.observe_execution(ExecutionFeedback(2, 2, 10, 5))
        rule.observe_execution(ExecutionFeedback(1, 1, 5, 5))
        self.assertEqual(rule.completed, 1)
        with self.assertRaisesRegex(PolicyError, "not consecutive"):
            rule.observe_execution(ExecutionFeedback(1, 1, 5, 5))
        rule.start_episode(self.context)
        self.assertEqual(rule.completed, 0)

    def test_effective_prompt_is_frozen_once_and_default_has_no_floor(self):
        prompt = with_stop_rule_prompt("Fixture", 50)
        self.assertEqual(with_stop_rule_prompt(prompt, 50), prompt)
        self.assertEqual(with_stop_rule_prompt("Fixture", 0), "Fixture")
        self.assertIn("policy's persistence setting", prompt)


if __name__ == "__main__":
    unittest.main()
