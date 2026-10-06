"""CPU-only checks for bounded public action-rejection data."""

import json
import unittest

from benchkit.contracts import ActionRejectionFeedback, ActionSpec, Usage
from benchkit.errors import ActionRejected, PolicyCallError
from benchkit.validation import ValidationIssue, validate_action_vector


class ValidationIssueChecks(unittest.TestCase):
    def test_closed_code_and_field_round_trip(self):
        for code in ValidationIssue.CODES:
            for field in ValidationIssue.FIELDS:
                issue = ValidationIssue(code, field, actual=0.2, limit=0.1, action_index=1)
                self.assertEqual(ValidationIssue.from_dict(json.loads(json.dumps(issue.to_dict()))), issue)
        self.assertEqual(ValidationIssue.from_dict({"code": "invalid_json"}),
                         ValidationIssue("invalid_json"))

    def test_rejects_arbitrary_payloads_and_nonfinite_numbers(self):
        for key, value in (("code", "private-native-text"), ("field", "object.pose"),
                           ("field", "left.pose[PRIVATE]"), ("actual", True),
                           ("actual", "private response"), ("limit", [0, 1]),
                           ("actual", {"native_score": 100}), ("actual", float("nan")),
                           ("actual", float("inf")), ("limit", 10**1000),
                           ("action_index", True), ("action_index", -1),
                           ("action_index", 2**31), ("action_index", 1.0)):
            with self.subTest(key=key, value_type=type(value).__name__), self.assertRaises(ValueError):
                ValidationIssue.from_dict({"code": "invalid_action", key: value})

    def test_dict_shape_is_strict(self):
        for value in (None, [], "error", {}, {"code": "invalid_action", "raw_error": "private"}):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                ValidationIssue.from_dict(value)

    def test_action_rejected_has_generated_message_and_private_receipt(self):
        issue = ValidationIssue("translation_limit", "left.translation_m", actual=0.06, limit=0.05)
        receipt = {"receipt": {"id": "sanitized"}}
        error = ActionRejected(issue, usage=Usage(calls=1), metadata=receipt)
        receipt["receipt"]["id"] = "changed"
        self.assertIsInstance(error, PolicyCallError)
        self.assertEqual(str(error), "Action rejected: translation_limit")
        self.assertEqual(error.category, "policy")
        self.assertEqual(error.metadata["receipt"]["id"], "sanitized")
        self.assertEqual(ActionRejected(issue).usage, Usage())
        self.assertEqual(error.issue, issue)
        with self.assertRaises(TypeError):
            ActionRejected({"code": "invalid_action"})
        with self.assertRaises(ValueError):
            ActionRejected(issue, metadata={"secret": "x" * (16 * 1024)})


class ActionVectorChecks(unittest.TestCase):
    spec = ActionSpec("synthetic", 2, low=(-1.0, 0.0), high=(1.0, 1.0))

    def test_normalizes_valid_vector_without_clipping(self):
        self.assertEqual(validate_action_vector(self.spec, [1, 0]), (1.0, 0.0))
        self.assertEqual(validate_action_vector(self.spec, (-0.3, 0.7)), (-0.3, 0.7))
        self.assertEqual(validate_action_vector(ActionSpec("unbounded", 1), [1e100]), (1e100,))

    def test_known_input_errors_have_safe_codes(self):
        cases = ((None, "invalid_type", None, None, None),
                 ("private string", "invalid_type", None, None, None),
                 ([0], "invalid_length", 1, 2, None),
                 ([True, 0], "invalid_type", None, None, 0),
                 ([0, "private string"], "invalid_type", None, None, 1),
                 ([float("nan"), 0], "non_finite", None, None, 0),
                 ([0, float("inf")], "non_finite", None, None, 1),
                 ([10**1000, 0], "non_finite", None, None, 0),
                 ([-1.2, 0], "out_of_bounds", -1.2, -1.0, 0),
                 ([0, 1.2], "out_of_bounds", 1.2, 1.0, 1))
        for value, code, actual, limit, index in cases:
            with self.subTest(code=code), self.assertRaises(ActionRejected) as caught:
                validate_action_vector(self.spec, value)
            self.assertEqual(caught.exception.issue, ValidationIssue(code, "action", actual, limit, index))
            self.assertNotIn("private string", str(caught.exception))

    def test_unknown_spec_failure_is_not_reclassified(self):
        class BrokenSpec:
            @property
            def size(self):
                raise RuntimeError("synthetic infrastructure uncertainty")
        with self.assertRaises(RuntimeError):
            validate_action_vector(BrokenSpec(), [0])


class RejectionFeedbackChecks(unittest.TestCase):
    def test_zero_and_partial_prefix_round_trip(self):
        for counters in ((1, 0, 0, 0, 1), (2, 1, 3, 0, 2), (2, 2, 4, 2, 1)):
            row = ActionRejectionFeedback(ValidationIssue("invalid_action"), *counters)
            self.assertEqual(ActionRejectionFeedback.from_dict(row.to_dict()), row)
            self.assertEqual(set(row.to_dict()), {"schema_version", "issue", "policy_calls",
                "action_decisions", "environment_steps", "executed_steps", "rejected_actions"})

    def test_rejects_inconsistent_or_bool_counters(self):
        good = dict(issue=ValidationIssue("invalid_action"), policy_calls=2, action_decisions=1,
                    environment_steps=3, executed_steps=0, rejected_actions=1)
        for key, value in (("policy_calls", True), ("policy_calls", 0),
                           ("rejected_actions", 0), ("rejected_actions", 3),
                           ("action_decisions", 2), ("executed_steps", 4),
                           ("environment_steps", 0), ("action_decisions", -1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                ActionRejectionFeedback(**{**good, key: value})
        with self.assertRaises(ValueError):
            ActionRejectionFeedback(ValidationIssue("invalid_action"), 1, 0, 2, 1, 1)

    def test_feedback_wire_schema_cannot_expand_actor_access(self):
        wire = ActionRejectionFeedback(ValidationIssue("invalid_action"), 1, 0, 0, 0, 1).to_dict()
        for value in ({**wire, "native_score": 100}, {**wire, "schema_version": "unknown"},
                      {key: value for key, value in wire.items() if key != "executed_steps"}):
            with self.assertRaises(ValueError):
                ActionRejectionFeedback.from_dict(value)


if __name__ == "__main__":
    unittest.main()
