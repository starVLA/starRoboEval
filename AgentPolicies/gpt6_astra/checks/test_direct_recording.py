"""Recording preferences do not change Direct robot/model interactions."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from benchkit.contracts import ExecutionFeedback
from benchkit.recording import InteractionRecorder, RecordingOptions
from AgentPolicies.gpt6_astra.tools import persistent_runtime as subject
from AgentPolicies.gpt6_astra.checks import test_codex_direct as fixtures


class DirectRecordingChecks(unittest.TestCase):
    setUp = fixtures.DirectChecks.setUp
    next = fixtures.DirectChecks.next

    def restart(self, options):
        self.policy.end_episode()
        self.policy.configure_recording(options)
        self.recorder = InteractionRecorder(Path(self.temp.name) / "visible.jsonl", options)
        self.policy.bind_interaction_recorder(self.recorder)
        self.destination = Path(self.temp.name) / "selected"
        self.policy.bind_artifact_dir(self.destination)
        self.policy.start_episode(self.context)

    def test_minimal_preserves_live_inputs_and_removes_optional_artifacts(self):
        self.restart(RecordingOptions(mode="minimal"))
        first = self.policy.act(self.obs)
        public = self.policy.public
        self.assertTrue((public / "000000/camera-000.png").is_file())
        self.assertEqual(len(self.fake.requests[0][1]["input"]), 4)
        second = self.next()
        self.assertEqual(first.action, second.action)
        self.assertEqual(len(self.fake.replies), 1)
        self.policy.end_episode()
        self.assertFalse(public.exists())
        self.assertFalse(list(self.destination.rglob("*")))
        self.assertFalse(self.recorder.path.exists())

    def test_disable_images_retains_text_without_changing_attached_pixels(self):
        self.restart(RecordingOptions(images=False))
        self.policy.act(self.obs)
        self.assertEqual(len(self.fake.requests[0][1]["input"]), 4)
        self.policy.end_episode()
        self.assertFalse(list(self.destination.rglob("*.png")))
        self.assertTrue((self.destination / "public_observations/000000/observation.json").is_file())
        manifest = json.loads((self.destination / "public_manifest.json").read_text())
        self.assertFalse(any(name.endswith(".png") for name in manifest))
        events = [json.loads(line) for line in self.recorder.path.read_text().splitlines()]
        self.assertEqual(events[0]["payload"]["image_attachments"], 3)
        self.assertNotIn("data:image", self.recorder.path.read_text())

    def test_disable_model_io_retains_controls_but_not_notes(self):
        self.restart(RecordingOptions(model_io=False))
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 5, 5))
        self.policy.end_episode()
        self.assertTrue((self.destination / "ack-000001.json").is_file())
        self.assertFalse(list(self.destination.glob("submission-*")))
        self.assertFalse(list((self.destination / "public_observations").rglob("*.json")))
        self.assertFalse(self.recorder.path.exists())

    def test_visible_item_allowlist_excludes_reasoning_and_extra_fields(self):
        self.restart(RecordingOptions())
        for item in (
            {"type": "reasoning", "text": "hidden-marker"},
            {"type": "agentMessage", "text": "visible output", "encryptedContent": "hidden-marker"},
            {"type": "commandExecution", "command": "analyze image", "aggregatedOutput": "visible result",
             "exitCode": 0, "arbitrary": {"credential": "hidden-marker"}},
            {"type": "fileChange", "status": "completed", "changes": [{"diff": "not-copied"}]},
        ):
            self.policy._record_visible_item(item)
        text = self.recorder.path.read_text()
        self.assertNotIn("hidden-marker", text)
        self.assertNotIn("not-copied", text)
        self.assertIn("visible result", text)
        self.assertEqual(len(text.splitlines()), 3)

    def test_optional_artifact_failure_does_not_interrupt_actions(self):
        self.restart(RecordingOptions())
        original = subject._write
        def failing_audit(path, value):
            # The policy resolves its destination; macOS /var may be a symlink.
            if Path(path).resolve().is_relative_to(self.destination.resolve()):
                raise OSError("fixture full destination")
            return original(path, value)
        with patch.object(subject, "_write", side_effect=failing_audit):
            decision = self.policy.act(self.obs)
            self.assertEqual(len(decision.action.steps), 5)
            self.policy.observe_execution(ExecutionFeedback(1, 1, 5, 5))
        self.assertIn("direct_optional_artifact_failed", self.recorder.warnings)

    def test_preferences_cannot_change_during_episode(self):
        with self.assertRaises(ValueError):
            self.policy.configure_recording(RecordingOptions(mode="minimal"))


if __name__ == "__main__":
    unittest.main()
