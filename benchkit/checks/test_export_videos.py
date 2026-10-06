"""Archive checks use synthetic bytes, not a simulator or a model attempt."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "reports" / "export_videos.py"


class VideoArchiveChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.output = self.root / "archive"
        self.video = self.run / "source.mp4"
        self.video.write_bytes(b"synthetic-video-fixture")
        self.record = {
            "episode": {"id": "task-0"}, "status": "completed", "success": False,
            "metrics": {"success": False}, "termination_reason": "runner:step_limit",
            "error": None, "environment_steps": 120, "policy_calls": 24,
            "usage": {"calls": None}, "artifacts": {"video": str(self.video)},
        }
        self.write("status.json", {"status": "completed"})
        self.write("manifest.json", {"run_id": "fixture", "benchmark": {}, "protocol": {}, "policy": {}})
        self.write("episodes.jsonl", self.record)

    def write(self, name, payload):
        (self.run / name).write_text(json.dumps(payload) + "\n")

    def export(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(self.run),
                               "--output-dir", str(self.output)], capture_output=True, text=True)

    def test_copy_preserves_failure_unknown_usage_and_original(self):
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / "video.mp4").read_bytes(), self.video.read_bytes())
        report = json.loads((self.output / "index.json").read_text())
        self.assertIs(report["episodes"][0]["success"], False)
        self.assertIsNone(report["episodes"][0]["usage"]["calls"])
        self.assertEqual(len(report["episodes"][0]["videos"][0]["sha256"]), 64)
        self.assertNotEqual(self.export().returncode, 0)

    def test_active_run_is_not_exported(self):
        self.write("status.json", {"status": "running"})
        self.assertNotEqual(self.export().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_artifact_outside_run_is_rejected(self):
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"not-an-artifact")
        self.record["artifacts"]["video"] = str(outside)
        self.write("episodes.jsonl", self.record)
        self.assertNotEqual(self.export().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_missing_video_is_recorded_not_hidden(self):
        self.record["artifacts"] = {}
        self.write("episodes.jsonl", self.record)
        self.assertEqual(self.export().returncode, 0)
        report = json.loads((self.output / "index.json").read_text())
        self.assertEqual(report["episodes"][0]["video_status"], "not_produced")

    def bind_worker_video(self, source="head.mp4"):
        directory = self.run / "episodes/task-0"
        (directory / "artifacts").mkdir(parents=True)
        (directory / "artifacts/head.mp4").write_bytes(self.video.read_bytes())
        self.record["artifacts"] = {"video_head": source, "video_manifest": "video_manifest.json"}
        (directory / "result.json").write_text(json.dumps(self.record))
        self.write("episodes.jsonl", self.record)
        return directory

    def test_relative_worker_video_and_prefix_key_are_exported_without_editing_results(self):
        directory = self.bind_worker_video()
        original = (directory / "result.json").read_bytes()
        exported = self.export()
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual((self.output / "video_head.mp4").read_bytes(), self.video.read_bytes())
        self.assertEqual((directory / "result.json").read_bytes(), original)
        report = json.loads((self.output / "index.json").read_text())
        self.assertEqual(len(report["episodes"][0]["videos"]), 1)

    def test_relative_worker_video_cannot_escape_to_another_episode_or_run_file(self):
        self.bind_worker_video("../../../source.mp4")
        self.assertNotEqual(self.export().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_relative_worker_video_requires_matching_episode_records(self):
        directory = self.bind_worker_video()
        (directory / "result.json").write_text(json.dumps({**self.record, "policy_calls": 999}))
        self.assertNotEqual(self.export().returncode, 0)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
