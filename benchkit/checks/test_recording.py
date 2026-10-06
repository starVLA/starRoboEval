"""CPU-only optional retention: same actions and outcomes, no model/native run."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.contracts import PolicyDecision, Usage
from benchkit.recording import (
    FIELDS, InteractionRecorder, RecordingOptions, add_recording_arguments,
    recording_from_arguments,
)
from benchkit.diagnostics.smoke import ReachBenchmark
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.checks.test_action_rejection_feedback import Policy, Session, decision, rejection


class ArtifactPolicy(Policy):
    def __init__(self, *args, fail_start=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_start = fail_start
        self.path = None
        self.present_at_end = False

    def bind_artifact_dir(self, path):
        self.path = path
        path.mkdir()
        (path / "needed-by-actor.txt").write_text("runtime-memory", encoding="utf-8")

    def start_episode(self, context):
        super().start_episode(context)
        if self.fail_start:
            raise RuntimeError("synthetic partially started actor")

    def act(self, observation):
        assert (self.path / "needed-by-actor.txt").read_text() == "runtime-memory"
        return super().act(observation)

    def end_episode(self):
        self.present_at_end = (self.path / "needed-by-actor.txt").exists()
        super().end_episode()


class RecordingChecks(unittest.TestCase):
    def fixture(self, options, *, outcomes=None, policy=None, session=None, method=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        policy = policy or Policy(outcomes or [decision(.2, calls=2)])
        session = session or Session(terminate_after=1)
        benchmark = ReachBenchmark()
        benchmark.open_episode = lambda _: session
        run = EvaluationRunner().run(benchmark, policy, RunRequest(output_dir=root,
            run_id="recording-fixture", episode_limit=1, max_steps=3, max_policy_calls=4,
            invalid_action_handling="feedback", recording=options, method=method))
        result = json.loads((run / "episodes.jsonl").read_text())
        return run, result, policy, session

    def test_presets_and_independent_overrides(self):
        self.assertFalse(RecordingOptions().retain_all)
        self.assertFalse(RecordingOptions().images)
        self.assertTrue(RecordingOptions().videos)
        self.assertFalse(RecordingOptions().copy_server_media)
        self.assertTrue(RecordingOptions().retain_unknown_artifacts)
        self.assertTrue(RecordingOptions(images=True).retain_all)
        self.assertFalse(any(getattr(RecordingOptions("minimal"), name) for name in FIELDS))
        options = RecordingOptions("minimal", model_io=True, images=True)
        self.assertTrue(options.model_io)
        self.assertTrue(options.images)
        self.assertFalse(options.interactions)
        self.assertEqual(options.to_dict()["schema_version"], "starvla-rsi.recording/v2")
        for value in (0, 1, "false", [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RecordingOptions(images=value)
            with self.subTest(copy_server_media=value), self.assertRaises(ValueError):
                RecordingOptions(copy_server_media=value)
        with self.assertRaises(ValueError):
            RecordingOptions("unknown")
        with self.assertRaises(TypeError):
            RunRequest(Path("unused"), recording={})

    def test_cli_switches_override_without_changing_inputs(self):
        parser = argparse.ArgumentParser()
        add_recording_arguments(parser)
        options = recording_from_arguments(parser.parse_args([
            "--recording-mode", "minimal", "--record-model-io", "--no-record-images"]))
        self.assertTrue(options.model_io)
        self.assertFalse(options.images)
        self.assertFalse(options.videos)
        self.assertFalse(options.copy_server_media)
        copied = recording_from_arguments(parser.parse_args(["--copy-server-media", "--record-images"]))
        self.assertTrue(copied.copy_server_media)
        self.assertTrue(copied.images)

    def test_minimal_and_standard_have_identical_controls_results_and_usage(self):
        rows = []
        for mode in ("standard", "minimal"):
            run, result, policy, session = self.fixture(RecordingOptions(mode),
                outcomes=[rejection(calls=2), decision(.2, calls=3)])
            rows.append((result, session.controls, len(policy.rejections)))
            episode = run / "episodes" / "reach-000"
            self.assertEqual((episode / "events.jsonl").exists(), mode == "standard")
            self.assertTrue((episode / "result.json").is_file())
            self.assertEqual((result["policy_calls"], result["usage"]["calls"]), (2, 5))
            self.assertEqual((session.resets, session.closes), (1, 1))
            self.assertEqual(json.loads((run / "manifest.json").read_text())["recording"]["mode"], mode)
            self.assertEqual(json.loads((run / "manifest.json").read_text())["method_origin"],
                             "legacy_policy_projection")
        for field in ("status", "success", "termination_reason", "environment_steps", "policy_calls",
                      "action_decisions", "rejected_actions", "usage", "metrics", "error"):
            self.assertEqual(rows[0][0][field], rows[1][0][field], field)
        self.assertEqual(rows[0][1:], rows[1][1:])

    def test_unknown_policy_artifacts_are_temporary_but_live_until_end(self):
        for options in (RecordingOptions("minimal"), RecordingOptions(model_io=False)):
            policy = ArtifactPolicy([decision(.2)])
            run, result, _, _ = self.fixture(options, policy=policy)
            self.assertTrue(policy.present_at_end)
            self.assertFalse(policy.path.exists())
            self.assertFalse((run / "episodes" / "reach-000" / "policy_artifacts").exists())
            self.assertEqual(result["status"], "completed")

    def test_default_keeps_existing_policy_artifact_binding(self):
        policy = ArtifactPolicy([decision(.2)])
        run, result, _, _ = self.fixture(RecordingOptions(), policy=policy)
        self.assertTrue(policy.path.exists())
        self.assertEqual(policy.path, run / "episodes" / "reach-000" / "policy_artifacts")
        self.assertIn("policy_media_retention_unsupported_preserved_artifacts", result["recording"]["warnings"])

    def test_partial_policy_start_still_cleans_runtime_and_preserves_error(self):
        policy = ArtifactPolicy([], fail_start=True)
        _, result, _, session = self.fixture(RecordingOptions("minimal"), policy=policy)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["policy_calls"], 0)
        self.assertTrue(policy.present_at_end)
        self.assertFalse(policy.path.exists())
        self.assertEqual((policy.ended, session.closes), (1, 1))

    def test_model_io_off_does_not_keep_note_or_structured_payload(self):
        outcome = PolicyDecision(stop=True, stop_reason="give_up", note="PRIVATE-VISIBLE-NOTE",
            metadata={"structured_output": {"private": "PRIVATE-VISIBLE-OUTPUT"}}, usage=Usage(calls=1))
        run, result, _, _ = self.fixture(RecordingOptions(model_io=False), outcomes=[outcome])
        text = (run / "episodes" / "reach-000" / "events.jsonl").read_text()
        self.assertNotIn("PRIVATE-VISIBLE", text)
        self.assertEqual(result["policy_calls"], 1)

    def test_sink_filters_categories_and_never_infers_backend_consumption(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "agent_interactions.jsonl"
            sink = InteractionRecorder(path, RecordingOptions(model_io=False))
            self.assertFalse(sink.record("model_io", {"input": "not retained"}))
            self.assertFalse(sink.record("memory", {"update": "not retained"}))
            self.assertTrue(sink.record("tool_traces", {"tool": "calculator", "result": 2}, policy_call=1))
            event = json.loads(path.read_text())
            self.assertEqual(event["category"], "tool_traces")
            self.assertEqual(event["policy_call"], 1)
            with self.assertRaises(ValueError):
                sink.record("hidden_reasoning", {})
            self.assertEqual(sink.events_written, 1)

    def test_optional_record_failure_does_not_change_robot_outcome(self):
        for error in (OSError("synthetic disk failure"), ValueError("synthetic serialization failure")):
            with self.subTest(error=type(error).__name__), \
                    patch("benchkit.recording.append_jsonl", side_effect=error):
                run, result, _, session = self.fixture(RecordingOptions())
            self.assertEqual(result["status"], "completed")
            self.assertEqual(session.controls, [(.2,)])
            self.assertIn("trajectory_recording_failed", result["recording"]["warnings"])
            self.assertEqual(json.loads((run / "episodes" / "reach-000" / "result.json").read_text()), result)

    def test_declared_policy_configure_and_sink_hooks_receive_no_simulator(self):
        class ConfiguredPolicy(ArtifactPolicy):
            recording_configurable = True

            def configure_recording(self, options):
                self.options = options

            def bind_interaction_recorder(self, recorder):
                self.recorder = recorder

            def act(self, observation):
                self.recorder.record("model_io", {"actual_visible_output": "synthetic"}, policy_call=1)
                return super().act(observation)

        policy = ConfiguredPolicy([decision(.2)])
        options = RecordingOptions("minimal", model_io=True)
        run, result, _, _ = self.fixture(options, policy=policy)
        self.assertIs(policy.options, options)
        self.assertTrue((run / "episodes" / "reach-000" / "agent_interactions.jsonl").is_file())
        self.assertEqual(result["recording"]["agent_events_written"], 1)

    def test_declared_components_keep_separate_usage_without_aggregate_allocation(self):
        method = {"schema_version": "starvla-rsi.method/v1", "id": "two-model-method",
            "version": "1", "models": [{"id": name, "role": role, "model": "fixture-" + name,
            "provider": "synthetic"} for name, role in (("planner", "planning"), ("actor", "control"))],
            "configuration": {"memory": "window"}}
        component_usage = {"planner": Usage(calls=2, input_tokens=12).to_dict(),
                           "actor": Usage(calls=1, input_tokens=4).to_dict()}
        outcome = PolicyDecision(action=decision(.2).action, usage=Usage(calls=3, input_tokens=16),
                                 metadata={"component_usage": component_usage})
        run, result, _, _ = self.fixture(RecordingOptions("minimal"), outcomes=[outcome], method=method)
        self.assertEqual(result["component_usage"], component_usage)
        self.assertEqual(json.loads((run / "summary.json").read_text())["component_usage"], component_usage)
        self.assertEqual(json.loads((run / "manifest.json").read_text())["method"]["id"], method["id"])
        self.assertEqual(json.loads((run / "manifest.json").read_text())["method_origin"],
                         "participant_declaration")
        self.assertEqual(result["policy_calls"], 1)
        _, missing, _, _ = self.fixture(RecordingOptions("minimal"), method=method)
        self.assertIsNone(missing["component_usage"]["planner"]["calls"])
        self.assertIsNone(missing["component_usage"]["actor"]["calls"])

    def test_invalid_optional_component_accounting_does_not_change_control(self):
        outcome = PolicyDecision(action=decision(.2).action, usage=Usage(calls=2),
                                 metadata={"component_usage": {"undeclared": {"calls": 2}}})
        _, result, _, session = self.fixture(RecordingOptions("minimal"), outcomes=[outcome])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(session.controls, [(.2,)])
        self.assertEqual(result["usage"]["calls"], 2)
        self.assertIn("invalid_component_usage_unavailable", result["recording"]["warnings"])


if __name__ == "__main__":
    unittest.main()
