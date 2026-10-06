"""No simulator/provider requests: opt-in policy persistence checks."""

import json
import importlib.util
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from benchkit.contracts import (
    ActionChunk, ActionSpec, BenchmarkDescriptor, EpisodeSpec, Observation,
    ObservationSpec, PolicyDecision, PolicyDescriptor, Transition,
)
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from AgentPolicies.policy_support.stop_rules import (
    MinimumActionDecisionsPolicy, VoluntaryStopRule, stop_constraint_prompt,
)


class Session:
    def __init__(self, terminal=None, fail=None):
        self.steps = 0
        self.terminal = terminal
        self.fail = fail
        self.closed = False

    def reset(self):
        return Observation(0, "Fixture task")

    def step(self, action):
        if self.steps == self.fail:
            raise RuntimeError("fixture environment error")
        self.steps += 1
        return Transition(Observation(self.steps, "Fixture task"),
                          terminated=self.steps == self.terminal)

    def metrics(self):
        return {"success": self.steps == self.terminal}

    def artifacts(self):
        return {}

    def close(self):
        self.closed = True


class Benchmark:
    descriptor = BenchmarkDescriptor("fixture", "1", "fixture/v1", "fixture")
    observation_spec = ObservationSpec()
    action_spec = ActionSpec("fixture", 1, low=(-1.0,), high=(1.0,))

    def __init__(self, terminal=None, fail=None):
        self.session = Session(terminal, fail)

    def episodes(self, seed, limit=None):
        return [EpisodeSpec("fixture-episode", "fixture", seed, "Fixture task")]

    def open_episode(self, episode):
        return self.session


class Policy:
    descriptor = PolicyDescriptor("fixture", "fixture")

    def __init__(self, actions=50, stop="give_up", note=None, chunk=5):
        self.actions, self.stop, self.note, self.chunk = actions, stop, note, chunk
        self.calls = 0

    def compatibility_errors(self, *args):
        return []

    def start_episode(self, context):
        self.context = context

    def act(self, observation):
        self.calls += 1
        if self.calls > self.actions:
            return PolicyDecision(stop=True, stop_reason=self.stop, note=self.note)
        return PolicyDecision(action=ActionChunk.from_steps([[0.0]] * self.chunk))

    def end_episode(self):
        pass


class StopRuleChecks(unittest.TestCase):
    def test_cli_stop_preference_is_given_to_policy_not_request_or_benchmark(self):
        from benchkit.cli import _run, build_parser

        args = build_parser().parse_args([
            "run", "--benchmark", "fixture", "--model-profile", "anonymous_code_agent",
            "--policy-min-action-decisions-before-give-up", "50",
        ])
        with patch("benchkit.cli.create_benchmark") as benchmark, \
                patch("benchkit.model_profiles.create_policy") as policy, \
                patch("benchkit.cli.EvaluationRunner.run") as run:
            _run(args)
        policy.assert_called_once_with("anonymous_code_agent", min_action_decisions_before_give_up=50)
        benchmark.assert_called_once_with("fixture", {})
        self.assertFalse(hasattr(run.call_args.args[2], "min_action_decisions_before_give_up"))

    def test_cli_duplicate_policy_preference_is_rejected_before_factories(self):
        from benchkit.cli import _run, build_parser

        args = build_parser().parse_args([
            "run", "--benchmark", "fixture", "--model-profile", "anonymous_code_agent",
            "--policy-min-action-decisions-before-give-up", "50",
            "--policy-args", '{"min_action_decisions_before_give_up": 30}',
        ])
        with patch("benchkit.cli.create_benchmark") as benchmark, \
                patch("benchkit.model_profiles.create_policy") as policy:
            with self.assertRaisesRegex(ValueError, "set once"):
                _run(args)
            benchmark.assert_not_called()
            policy.assert_not_called()

    def test_cli_default_output_belongs_to_selected_model(self):
        from benchkit.cli import _repository_root, _run, build_parser

        for selection, extra, expected in (
            (["--model-profile", "anonymous_code_agent"], [],
             _repository_root() / "AgentPolicies/anonymous_code_agent/results/fixture/raw"),
            (["--policy", "mailbox"], [],
             _repository_root() / "AgentPolicies/anonymous_code_agent/results/fixture/raw"),
            (["--policy", "scripted"], [], Path("results/rsi")),
            (["--model-profile", "anonymous_code_agent"], ["--output-dir", "explicit-output"],
             Path("explicit-output")),
        ):
            with self.subTest(selection=selection, extra=extra), patch(
                    "benchkit.cli.create_benchmark"), patch(
                    "benchkit.cli.create_policy"), patch(
                    "benchkit.model_profiles.create_policy"), patch(
                    "benchkit.cli.EvaluationRunner.run") as run:
                _run(build_parser().parse_args(["run", "--benchmark", "fixture", *selection, *extra]))
                self.assertEqual(run.call_args.args[2].output_dir, expected)

    def test_cli_mailbox_alias_cannot_bypass_model_source_capture(self):
        from benchkit.cli import _run, build_parser

        for alias in ("mailbox", "MAILBOX", " mailbox "):
            args = build_parser().parse_args(["run", "--benchmark", "fixture", "--policy", alias])
            with self.subTest(alias=alias), patch("benchkit.cli.create_benchmark"), \
                    patch("benchkit.cli.create_policy") as unbound_factory, \
                    patch("benchkit.model_profiles.create_policy") as profile_factory, \
                    patch("benchkit.cli.EvaluationRunner.run"):
                _run(args)
            profile_factory.assert_called_once_with("anonymous_code_agent")
            unbound_factory.assert_not_called()

    def test_cli_mailbox_alias_cannot_claim_an_unverified_model_identity(self):
        from benchkit.cli import _run, build_parser

        args = build_parser().parse_args([
            "run", "--benchmark", "fixture", "--policy", "mailbox",
            "--policy-args", '{"model":"claimed-provider-model"}',
        ])
        with patch("benchkit.cli.create_benchmark") as benchmark:
            with self.assertRaisesRegex(ValueError, "unsupported profile policy parameters"):
                _run(args)
            benchmark.assert_not_called()

    def run_case(self, policy=None, benchmark=None, minimum=50, **overrides):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        request = RunRequest(Path(temporary.name), max_steps=1000,
                             max_policy_calls=200, replan_interval=5)
        request = replace(request, **overrides)
        policy, benchmark = policy or Policy(), benchmark or Benchmark()
        selected = MinimumActionDecisionsPolicy(policy, minimum) if minimum else policy
        run = EvaluationRunner().run(benchmark, selected, request)
        result = json.loads((run / "episodes.jsonl").read_text())
        manifest = json.loads((run / "manifest.json").read_text())
        events = [json.loads(line) for line in
                  (run / "episodes/fixture-episode/events.jsonl").read_text().splitlines()]
        self.assertTrue(benchmark.session.closed)
        return result, manifest, events, policy

    def test_fifty_action_decisions_then_stop_is_51_calls(self):
        result, manifest, _, policy = self.run_case()
        self.assertEqual((result["policy_calls"], result["action_decisions"], result["environment_steps"]),
                         (51, 50, 250))
        self.assertEqual(result["termination_reason"], "policy:give_up")
        self.assertFalse(result["success"])
        self.assertIsNone(result["error"])
        self.assertNotIn("min_action_decisions_before_give_up", manifest["protocol"])
        self.assertFalse(hasattr(policy.context, "min_action_decisions_before_give_up"))
        self.assertEqual(manifest["policy"]["parameters"]["policy_stop_rule"], {
            "stop_constraint_version": "minimum-action-decisions/v2",
            "min_action_decisions_before_give_up": 50,
            "early_policy_stop_exception": "safety_stop_with_nonempty_note", "scope": "policy",
        })

    def test_49_actions_then_stop_is_preserved_error_without_extra_request(self):
        result, _, events, policy = self.run_case(Policy(actions=49))
        self.assertEqual((result["policy_calls"], result["action_decisions"], result["environment_steps"]),
                         (50, 49, 245))
        self.assertEqual(result["error"]["category"], "policy")
        self.assertIsNone(result["success"])
        self.assertEqual(policy.calls, 50)
        self.assertEqual(sum(e["event"] == "policy_decision" for e in events), 49)
        self.assertEqual(sum(e["event"] == "policy_call_start" for e in events), 50)

    def test_renaming_stop_does_not_bypass_floor(self):
        for reason in ("done", "success", "cannot_continue", "GIVE_UP"):
            with self.subTest(reason=reason):
                result, _, _, _ = self.run_case(Policy(actions=0, stop=reason))
                self.assertEqual(result["error"]["category"], "policy")
                self.assertEqual(result["environment_steps"], 0)

    def test_safety_stop_requires_note_and_does_not_award_success(self):
        for note in (None, "", "   "):
            with self.subTest(note=note):
                result, _, _, _ = self.run_case(Policy(actions=0, stop="safety_stop", note=note))
                self.assertEqual(result["error"]["category"], "policy")
        result, _, _, _ = self.run_case(Policy(actions=0, stop="safety_stop", note="Visible unsafe contact"))
        self.assertEqual(result["termination_reason"], "policy:safety_stop")
        self.assertFalse(result["success"])
        self.assertEqual(result["action_decisions"], 0)

    def test_native_termination_before_floor_is_not_delayed(self):
        result, _, _, _ = self.run_case(benchmark=Benchmark(terminal=7))
        self.assertTrue(result["success"])
        self.assertEqual((result["policy_calls"], result["action_decisions"], result["environment_steps"]), (2, 2, 7))
        self.assertEqual(result["termination_reason"], "environment:terminated")

    def test_environment_error_before_floor_remains_error(self):
        result, _, _, _ = self.run_case(benchmark=Benchmark(fail=0))
        self.assertEqual((result["policy_calls"], result["action_decisions"], result["environment_steps"]), (1, 0, 0))
        self.assertEqual(result["status"], "error")

    def test_controls_are_not_action_decisions(self):
        result, _, _, _ = self.run_case(Policy(actions=10))
        self.assertEqual((result["environment_steps"], result["action_decisions"]), (50, 10))
        self.assertEqual(result["status"], "error")

    def test_single_action_chunks_count_once_each(self):
        result, _, _, _ = self.run_case(Policy(chunk=1))
        self.assertEqual((result["environment_steps"], result["action_decisions"], result["policy_calls"]), (50, 50, 51))

    def test_step_limit_may_end_before_floor(self):
        result, _, _, _ = self.run_case(max_steps=3)
        self.assertEqual(result["termination_reason"], "runner:step_limit")
        self.assertIsNone(result["error"])

    def test_unwrapped_policy_has_no_persistence_requirement(self):
        result, manifest, _, _ = self.run_case(Policy(actions=0), minimum=0)
        self.assertEqual(result["termination_reason"], "policy:give_up")
        self.assertEqual(result["action_decisions"], 0)
        self.assertNotIn("stop_constraint_version", manifest["protocol"])
        self.assertNotIn("policy_stop_rule", manifest["policy"]["parameters"])

    def test_floor_validation(self):
        for value in (True, -1, 0.5, "50"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                VoluntaryStopRule(value)
        with self.assertRaises(TypeError):
            RunRequest(Path("unused"), min_action_decisions_before_give_up=50)
        self.assertIn("additional decision", stop_constraint_prompt(50))

    def test_unreachable_policy_preference_does_not_extend_evaluation_budget(self):
        result, _, _, _ = self.run_case(max_policy_calls=2)
        self.assertEqual((result["policy_calls"], result["action_decisions"]), (2, 2))
        self.assertEqual(result["termination_reason"], "runner:policy_call_limit")
        self.assertIsNone(result["error"])

    def test_cli_rejects_unknown_profile_before_benchmark(self):
        from benchkit.cli import build_parser, _run
        args = build_parser().parse_args(["run", "--benchmark", "smoke", "--model-profile", "absent"])
        # Profile implementation is supplied by the separate refactor module.
        with patch("benchkit.cli.create_benchmark") as factory:
            with self.assertRaises((ValueError, ImportError)):
                _run(args)
            factory.assert_not_called()

    def test_generic_closed_audit_accepts_valid_and_error_floor_records(self):
        path = Path(__file__).resolve().parents[3] / "benchkit/audits/closed_run.py"
        spec = importlib.util.spec_from_file_location("stop_fixture_auditor", path)
        auditor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(auditor)
        for actions in (0, 49, 50):
            with self.subTest(actions=actions):
                result, manifest, events, _ = self.run_case(Policy(actions=actions))
                row = auditor.audit_episode(result, events, manifest["protocol"])
                self.assertEqual(row["action_decisions"], actions)
        result, manifest, events, _ = self.run_case(Policy(actions=49), minimum=0)
        manifest["protocol"].update({
            "min_action_decisions_before_give_up": 50,
            "stop_constraint_version": "minimum-action-decisions/v1",
            "early_policy_stop_exception": "safety_stop_with_nonempty_note",
        })
        result["action_decisions"] = 49
        with self.assertRaises(auditor.AuditError):
            auditor.audit_episode(result, events, manifest["protocol"])

    def test_mailbox_uses_confirmed_execution_not_number_of_submitted_chunks(self):
        from benchkit.contracts import EpisodeContext, ExecutionFeedback, PolicyEpisodeSpec
        from AgentPolicies.anonymous_code_agent.mailbox import MailboxPolicy
        with tempfile.TemporaryDirectory() as temp:
            policy = MailboxPolicy(Path(temp).resolve() / "mailbox", min_action_decisions_before_give_up=50)
            context = EpisodeContext(Benchmark.descriptor, PolicyEpisodeSpec("opaque", "fixture", "Fixture task"),
                                     Benchmark.observation_spec, Benchmark.action_spec, 1000, 200, 5)
            policy.start_episode(context)
            for turn in (1, 50, 51):
                policy._turn_index = turn
                exported = policy._export_observation(Observation(turn, "Fixture task"), "opaque", policy.directory)
                self.assertEqual(exported["control_feedback"]["action_decisions"], 0)
                self.assertFalse(exported["policy_constraints"]["voluntary_stop_allowed"])
                self.assertNotIn("min_action_decisions_before_give_up", exported["budgets"])
                self.assertNotIn("success", exported)
            for count in range(1, 51):
                policy.observe_execution(ExecutionFeedback(count, count, count * 3, 3))
            exported = policy._export_observation(Observation(150, "Fixture task"), "opaque", policy.directory)
            self.assertEqual(exported["control_feedback"], {
                "policy_calls": 50, "action_decisions": 50, "environment_steps": 150, "executed_steps": 3,
            })
            self.assertTrue(exported["policy_constraints"]["voluntary_stop_allowed"])
            policy.end_episode()


if __name__ == "__main__":
    unittest.main()
