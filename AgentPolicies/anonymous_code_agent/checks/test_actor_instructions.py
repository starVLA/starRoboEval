"""Validate canonical operator wire examples against the real mailbox parser."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from benchkit.contracts import (
    ActionSpec, BenchmarkDescriptor, EpisodeContext, ObservationSpec, PolicyEpisodeSpec,
)
from benchkit.errors import PolicyError
from AgentPolicies.anonymous_code_agent.mailbox import MailboxPolicy


class ActorInstructionChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        path = Path(__file__).resolve().parents[1] / "prompts/actor_instructions.txt"
        self.text = path.read_text()
        self.examples = [json.loads(s.replace("ACTION_VECTOR", "[0,0,0,0,0,0,0]"))
                         for s in re.findall(r"```json\n(.*?)\n```", self.text, re.S)]
        self.policy = MailboxPolicy(self.root / "mbx-fixture", timeout_s=1)
        self.policy.start_episode(EpisodeContext(
            benchmark=BenchmarkDescriptor("fixture", "1", "fixture/v1", "source"),
            episode=PolicyEpisodeSpec("opaque", "fixture", "Use the observation."),
            observation_spec=ObservationSpec(),
            action_spec=ActionSpec("fixture", 7, low=(-1.,)*7, high=(1.,)*7),
            max_steps=1000, max_policy_calls=200, replan_interval=5))

    def parse(self, value):
        return self.policy._parse_response(value, "CURRENT_REQUEST_ID", 0., self.root)

    def test_both_canonical_examples_are_accepted_without_optional_fields(self):
        self.assertEqual(len(self.examples), 2)
        action, stop = [self.parse(example) for example in self.examples]
        self.assertFalse(action.stop)
        self.assertTrue(stop.stop)
        self.assertEqual(stop.stop_reason, "give_up")
        self.assertIsNone(action.usage.calls)
        self.assertEqual(set(self.examples[0]), {"request_id", "actions", "usage"})
        self.assertEqual(set(self.examples[1]), {"request_id", "stop", "stop_reason", "usage"})

    def test_root_historical_notes_and_reason_typos_are_rejected(self):
        action = {**self.examples[0], "notes": "move"}
        with self.assertRaisesRegex(PolicyError, "unknown response keys"):
            self.parse(action)
        stop = dict(self.examples[1])
        stop["reason"] = stop.pop("stop_reason")
        with self.assertRaisesRegex(PolicyError, "unknown response keys"):
            self.parse(stop)

    def test_shape_validation_uses_current_spec_and_rejects_invalid_second_vector(self):
        response = dict(self.examples[0])
        response["actions"] = [[0.]*7, [0.]*6]
        with self.assertRaisesRegex(PolicyError, "expected action size 7, got 6"):
            self.parse(response)

    def test_transport_placeholders_do_not_contain_task_specific_context(self):
        self.assertEqual(self.text.count("{{HOST}}"), 1)
        self.assertEqual(self.text.count("{{MAILBOX}}"), 1)
        self.assertNotIn("20260907", self.text)
        self.assertNotIn("case-", self.text)
        self.assertNotIn("Simpler", self.text)
        self.assertNotIn("LIBERO", self.text)

    def test_reference_control_guidance_is_owned_by_the_model_profile(self):
        path = Path(__file__).resolve().parents[1] / "prompts/control_guidance.txt"
        self.assertTrue(path.read_text().strip())


if __name__ == "__main__":
    unittest.main()
