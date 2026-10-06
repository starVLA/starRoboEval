"""Native-vector model boundary, no actual model or simulator invocation."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from benchkit.contracts import ActionRejectionFeedback, ExecutionFeedback, Observation, ObservationSpec
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError
from benchkit.model_profiles import create_policy, _method_extensions
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.checks.fixtures import context


def cli_result(value=None):
    return {"text": json.dumps(value or {"stop": False, "stop_reason": None,
            "actions": [[0.25, -0.5], [0.4, 0.5]], "note": "approach"}),
            "usage": {"calls": 1, "input_tokens": 12, "output_tokens": 8},
            "receipt": {"requested_model": "gpt-6-astra", "accounting_source": "cli_reported"}}


class NativePolicyChecks(unittest.TestCase):
    def setUp(self):
        self.policy = create_policy("gpt6_astra", control_method="codex-native/v1")
        self.policy.start_episode(context())
        self.observation = Observation(0, "Move to the target", metadata={"private-marker": "hidden"})

    def call(self, value=None, observation=None):
        with patch("AgentPolicies.gpt6_astra.transports.codex_cli.send", return_value=cli_result(value)) as send:
            decision = self.policy.act(observation or self.observation)
        self.assertEqual(send.call_count, 1)
        return decision, send.call_args.args[0]

    def test_native_vectors_no_dojo_convention_or_provider_envelope(self):
        decision, prompt = self.call()
        self.assertEqual(decision.action.steps, ((0.25, -0.5), (0.4, 0.5)))
        self.assertEqual(decision.usage.input_tokens, 12)
        for private in ("private-marker", "private-source-do-not-send", "seed", "reward"):
            self.assertNotIn(private, prompt)
        self.assertNotIn("returned_model", decision.metadata["provider_receipt"])
        self.assertEqual(self.policy.descriptor.version, "codex-native/v1")

    def test_requires_ack_and_records_only_executed_prefix(self):
        self.call()
        with self.assertRaises(PolicyCallError): self.call()
        self.policy.observe_execution(ExecutionFeedback(1, 1, 1, 1))
        _, prompt = self.call(observation=replace(self.observation, step=1))
        public = json.loads(prompt.split("PUBLIC_OBSERVATION_JSON\n")[1])
        self.assertEqual(public["recent_confirmed_actions"][0]["actions"], [[0.25, -0.5]])
        self.assertEqual(public["control_feedback"]["environment_steps"], 1)

    def test_invalid_response_rejected_then_next_call_same_observation(self):
        with self.assertRaises(ActionRejected) as caught:
            self.call({"stop": False, "stop_reason": None, "actions": [[99, 0]], "note": None})
        self.assertEqual(caught.exception.usage.input_tokens, 12)
        self.policy.observe_rejection(ActionRejectionFeedback(caught.exception.issue, 1, 0, 0, 0, 1))
        decision, prompt = self.call()
        self.assertTrue(decision.action)
        public = json.loads(prompt.split("PUBLIC_OBSERVATION_JSON\n")[1])
        self.assertEqual(public["recent_confirmed_actions"], [])
        self.assertEqual(public["last_action_rejection"]["rejected_actions"], 1)
        self.policy.observe_execution(ExecutionFeedback(2, 1, 2, 2))

    def test_partial_prefix_before_service_rejection_remains_real(self):
        self.call()
        self.policy.observe_rejection(ActionRejectionFeedback(ValidationIssue("invalid_action"), 1, 1, 1, 1, 1))
        self.assertEqual(self.policy.rule.completed, 1)
        self.assertEqual(list(self.policy.history)[0]["actions"], ((0.25, -0.5),))
        self.call(observation=replace(self.observation, step=1))

    def test_transport_failure_never_reinvoked(self):
        error = PolicyCallError("offline fixture", usage=cli_result_usage(), category="infrastructure")
        with patch("AgentPolicies.gpt6_astra.transports.codex_cli.send", side_effect=error) as send:
            with self.assertRaises(PolicyCallError): self.policy.act(self.observation)
        self.assertEqual(send.call_count, 1)

    def test_early_give_up_remains_terminal_policy_rule_error(self):
        policy = create_policy("gpt6_astra", control_method="codex-native/v1",
                               min_action_decisions_before_give_up=5)
        policy.start_episode(context())
        with patch("AgentPolicies.gpt6_astra.transports.codex_cli.send", return_value=cli_result(
                {"stop": True, "stop_reason": "give_up", "actions": [], "note": "stop"})):
            with self.assertRaises(PolicyCallError) as caught: policy.act(self.observation)
        self.assertNotIsInstance(caught.exception, ActionRejected)

    def test_reset_clears_memory_and_rejects_privileged_input(self):
        self.call()
        self.policy.observe_execution(ExecutionFeedback(1, 1, 2, 2))
        self.policy.end_episode()
        self.assertFalse(self.policy.history)
        with self.assertRaises(PolicyError):
            self.policy.start_episode(context(observation_spec=ObservationSpec(privileged=True)))

    def test_extension_is_opt_in_for_historical_bundles(self):
        self.assertFalse(_method_extensions({"control_method": "responses-native/v1"})["native_extensions"])
        self.assertTrue(_method_extensions({"control_method": "responses-native/v1",
                                           "codex_native_extension": "native-vectors/v1"})["native_extensions"])


def cli_result_usage():
    from benchkit.contracts import Usage
    return Usage(calls=1)


if __name__ == "__main__":
    unittest.main()
