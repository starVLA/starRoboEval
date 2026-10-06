"""No simulator or model required for the one-control diagnostic contract."""
from dataclasses import replace
import unittest
from benchkit.contracts import (ActionSpec, BenchmarkDescriptor, EpisodeContext, Observation,
                               ObservationSpec, PolicyEpisodeSpec)
from benchkit.diagnostics.robot_state_hold import StateEchoDiagnostic, completed_echo
from benchkit.errors import PolicyError


class StateEchoChecks(unittest.TestCase):
    def setUp(self):
        self.policy = StateEchoDiagnostic()
        self.context = EpisodeContext(BenchmarkDescriptor("fixture", "v", "p", "r"),
            PolicyEpisodeSpec("opaque", "fixture", "No task evaluation"),
            ObservationSpec(state_names=("joint_b", "joint_a")),
            ActionSpec("absolute-fixture", 2, names=("joint_a", "joint_b"), low=(-1, -1), high=(1, 1)),
            max_steps=1, max_policy_calls=1, replan_interval=1)
        self.policy.start_episode(self.context)

    def test_exact_state_mapping_once_without_model_or_metadata(self):
        observation = Observation(0, "No task evaluation", state=(.1, .2), metadata={"oracle": 9})
        decision = self.policy.act(observation)
        self.assertEqual(decision.action.steps, ((.2, .1),))
        self.assertEqual(decision.usage.calls, 0)
        self.assertFalse(self.policy.descriptor.parameters["capability_evaluation"])
        with self.assertRaises(PolicyError):
            self.policy.act(observation)

    def test_undeclared_or_privileged_or_ambiguous_sensors_fail(self):
        for spec in (ObservationSpec(state_names=("joint_a",)),
                     ObservationSpec(state_names=("joint_a", "joint_b"), privileged=True),
                     ObservationSpec(state_names=("joint_a", "joint_a", "joint_b"))):
            with self.assertRaises(PolicyError):
                self.policy.start_episode(replace(self.context, observation_spec=spec))

    def test_no_action_clamping_or_noninitial_echo(self):
        for obs in (Observation(1, "fixture", state=(0, 0)), Observation(0, "fixture", state=None),
                    Observation(0, "fixture", state=(0,)), Observation(0, "fixture", state=(0, 3))):
            with self.assertRaises((PolicyError, ValueError)):
                self.policy.act(obs)

    def test_closed_error_or_no_control_is_not_a_pass_and_success_is_irrelevant(self):
        result = {"status": "completed", "error": None, "environment_steps": 1,
                  "action_decisions": 1, "policy_calls": 1, "usage": {"calls": 0}, "success": False}
        self.assertTrue(completed_echo(result))
        self.assertTrue(completed_echo({**result, "success": None}))
        for change in ({"status": "error"}, {"error": {"category": "infrastructure"}},
                       {"environment_steps": 0}, {"environment_steps": True}, {"action_decisions": 0},
                       {"policy_calls": 2}, {"usage": {"calls": 1}}, {"usage": {"calls": None}}):
            self.assertFalse(completed_echo({**result, **change}))


if __name__ == "__main__":
    unittest.main()
