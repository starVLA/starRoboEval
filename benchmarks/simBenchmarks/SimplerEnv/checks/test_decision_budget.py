"""Decision-primary runner contracts; fixtures are not model evaluations."""

import json
import tempfile
import unittest
from pathlib import Path

from benchkit.contracts import ActionChunk, PolicyDecision, Transition
from benchkit.errors import ProtocolError
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from test_runner_boundary import FixtureBenchmark, FixturePolicy, FixtureSession


class DecisionBenchmark(FixtureBenchmark):
    budget_mode = "decisions"
    max_policy_calls = 3
    replan_interval = 2
    environment_step_cap = 6

    def __init__(self, native_success=False):
        super().__init__()
        self.native_success = native_success

    def open_episode(self, episode):
        session = FixtureSession()
        old_step = session.step

        def step(action):
            transition = old_step(action)
            return Transition(observation=transition.observation,
                              terminated=self.native_success,
                              truncated=session.native_steps >= self.environment_step_cap)

        session.step = step
        self.sessions.append(session)
        return session


class DecisionBudgetChecks(unittest.TestCase):
    def run_fixture(self, chunk_size=2, stop=False, native_success=False):
        with tempfile.TemporaryDirectory() as directory:
            policy = FixturePolicy(lambda: PolicyDecision(stop=True, stop_reason="giveup")
                                   if stop else PolicyDecision(action=ActionChunk.from_steps([[0.1]] * chunk_size)))
            run = EvaluationRunner().run(DecisionBenchmark(native_success), policy, RunRequest(
                Path(directory), max_steps=6, max_policy_calls=3, replan_interval=2,
                budget_mode="decisions"))
            result = json.loads((run / "episodes.jsonl").read_text().splitlines()[0])
            manifest = json.loads((run / "manifest.json").read_text())
            self.assertEqual(manifest["protocol"]["primary_budget"], "policy_decisions")
            self.assertEqual(policy.contexts[0].budget_mode, "decisions")
            return result

    def test_full_chunks_exhaust_decisions_even_if_time_limit_coincides(self):
        result = self.run_fixture()
        self.assertEqual((result["policy_calls"], result["environment_steps"]), (3, 6))
        self.assertEqual(result["termination_reason"], "runner:policy_call_limit")

    def test_short_chunks_do_not_buy_extra_decisions(self):
        result = self.run_fixture(chunk_size=1)
        self.assertEqual((result["policy_calls"], result["environment_steps"]), (3, 3))
        self.assertEqual(result["termination_reason"], "runner:policy_call_limit")

    def test_stop_consumes_one_decision_and_no_steps(self):
        result = self.run_fixture(stop=True)
        self.assertEqual((result["policy_calls"], result["environment_steps"]), (1, 0))

    def test_native_success_can_end_before_budget(self):
        result = self.run_fixture(native_success=True)
        self.assertEqual(result["termination_reason"], "environment:terminated")
        self.assertEqual((result["policy_calls"], result["environment_steps"]), (1, 1))

    def test_invalid_product_or_missing_decision_settings_rejected(self):
        for kwargs in ({"max_steps": 5, "max_policy_calls": 3, "replan_interval": 2},
                       {"max_steps": 6, "max_policy_calls": 3},
                       {"max_steps": 6, "max_policy_calls": True, "replan_interval": 6}):
            with self.assertRaises(ValueError):
                RunRequest(Path("unused"), budget_mode="decisions", **kwargs)

    def test_mismatch_rejected_before_opening_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ("horizon", "decisions"):
                benchmark = DecisionBenchmark()
                request = RunRequest(Path(directory), max_steps=4, max_policy_calls=2,
                                     replan_interval=2, budget_mode=mode)
                with self.assertRaises(ProtocolError):
                    EvaluationRunner().run(benchmark, FixturePolicy(), request)
                self.assertFalse(benchmark.sessions)
                self.assertFalse(list(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
