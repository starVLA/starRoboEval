"""Adoption preserves anonymous historical evidence without touching source runs."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from benchkit.reports import result_index


class ResultIndexChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "source-run"
        self.episode = self.run / "episodes" / "episode-001"
        self.episode.mkdir(parents=True)
        self.result = {
            "episode": {"id": "episode-001", "task": "stack_bowls", "seed": 123},
            "status": "completed", "success": False, "error": None,
            "environment_steps": 3, "policy_calls": 2, "termination_reason": "policy:give_up",
            "usage": {"calls": None, "input_tokens": None}, "metrics": {"success": False},
            "artifacts": {"video_cam_head": "cam_head.mp4"},
        }
        self.manifest = {"run_id": "run", "created_at": "2026-09-07T12:00:00+00:00",
                         "benchmark": {"name": "robodojo", "version": "test/v1"}, "protocol": {"seed": 123},
                         "policy": {"name": "code-agent-development", "kind": "external-code-agent",
                                    "model": None, "provider": None}}
        self.steps = [{"event": "environment_step", "environment_step": step,
                       "policy_call": 1 if step < 3 else 2, "timestamp": str(step),
                       "info": {"native_success": step == 2}} for step in range(1, 4)]
        self.write_run()
        (self.episode / "artifacts").mkdir()
        (self.episode / "artifacts" / "cam_head.mp4").write_bytes(b"original-video-bytes")
        self.output = self.root / "new-index"

    def write_json(self, path, payload):
        path.write_text(json.dumps(payload))

    def write_run(self):
        self.write_json(self.run / "manifest.json", self.manifest)
        self.write_json(self.run / "status.json", {
            "status": "completed" if self.result["error"] is None else "completed_with_errors", "episodes_written": 1})
        self.write_json(self.episode / "result.json", self.result)
        (self.run / "episodes.jsonl").write_text(json.dumps(self.result) + "\n")
        events = [{"event": "episode_start", "episode": self.result["episode"]}, *self.steps,
                  {"event": "episode_end", "result": self.result}]
        (self.episode / "events.jsonl").write_text("\n".join(json.dumps(row) for row in events) + "\n")
        self.write_json(self.run / "summary.json", {
            "attempted": 1, "completed": int(self.result["error"] is None),
            "errors": int(self.result["error"] is not None), "successes": int(self.result["success"] is True),
            "policy_calls": self.result["policy_calls"]})

    def selections(self, videos=False):
        result = {"run_dir": str(self.run)}
        if videos:
            result["videos"] = [{"episode_id": "episode-001", "artifact": "video_cam_head",
                                  "camera": "cam_head", "description": "bowl-stacking"}]
        return [result]

    def hashes(self):
        return {str(path.relative_to(self.run)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.run.rglob("*") if path.is_file()}

    def test_preserves_unknown_identity_transient_success_and_original_bytes(self):
        original = self.hashes()
        report = result_index.adopt(self.selections(), self.output)
        self.assertEqual(original, self.hashes())
        self.assertIsNone(report["model"])
        row = report["runs"][0]["episodes"][0]
        self.assertIs(row["success"], False)
        self.assertEqual(row["progress"]["first_native_success_step"], 2)
        self.assertEqual(row["progress"]["policy_call_at_first_native_success"], 1)
        self.assertIsNone(row["usage"]["calls"])
        self.assertEqual({path.name for path in self.output.iterdir()}, {"index.json"})
        self.assertEqual(report["runs"][0]["source_files_sha256"]["manifest.json"], original["manifest.json"])

    def test_selected_video_exact_copy_keeps_task_description_and_camera(self):
        original = self.hashes()
        report = result_index.adopt(self.selections(videos=True), self.output)
        video = report["runs"][0]["videos"][0]
        self.assertIn("stack_bowls-bowl-stacking", video["path"])
        self.assertIn("cam_head", Path(video["path"]).name)
        self.assertFalse(report["runs"][0]["diagnostic"])
        self.assertFalse(video["diagnostic"])
        self.assertEqual(video["archive_reasons"], [])
        self.assertNotIn("media/archive/", video["path"])
        self.assertEqual((self.output / video["path"]).read_bytes(), b"original-video-bytes")
        self.assertEqual(original, self.hashes())

    def test_profile_source_and_executed_decision_extension_are_preserved(self):
        identity = {"id": "anonymous_code_agent", "source_inventory_sha256": "a" * 64}
        source = {"path": "model_source/index.json", "index_sha256": "b" * 64}
        self.manifest["policy"]["parameters"] = {"model_profile": identity}
        self.manifest["model_profile"] = identity
        self.manifest["model_source"] = source
        self.result["action_decisions"] = 2
        self.write_run()
        row = result_index.adopt(self.selections(), self.output)["runs"][0]
        self.assertEqual(row["model_profile"], identity)
        self.assertEqual(row["model_source"], source)
        self.assertEqual(row["episodes"][0]["action_decisions"], 2)
        # This index records manifest references; it does not claim a full source audit.
        self.assertNotIn("model_source/index.json", row["source_files_sha256"])

    def test_legacy_records_do_not_gain_model_or_action_count_fields(self):
        row = result_index.adopt(self.selections(), self.output)["runs"][0]
        self.assertNotIn("model_profile", row)
        self.assertNotIn("model_source", row)
        self.assertNotIn("action_decisions", row["episodes"][0])

    def test_impossible_executed_decision_counter_is_rejected(self):
        self.result["action_decisions"] = 3
        self.write_run()
        with self.assertRaisesRegex(ValueError, "exceed calls or controls"):
            result_index.adopt(self.selections(), self.output)

    def test_error_remains_null_and_zero_control_media_is_archived(self):
        self.result.update(status="error", success=None, environment_steps=0, policy_calls=1,
                           error={"category": "policy", "message": "malformed action"})
        self.steps = []
        self.write_run()
        report = result_index.adopt(self.selections(videos=True), self.output)
        self.assertIsNone(report["runs"][0]["episodes"][0]["success"])
        self.assertEqual(report["runs"][0]["summary"]["errors"], 1)
        self.assertIn("media/archive/", report["runs"][0]["videos"][0]["path"])
        self.assertFalse(report["runs"][0]["diagnostic"])
        self.assertEqual(report["runs"][0]["videos"][0]["archive_reasons"], ["zero_controls", "episode_error"])

    def test_completed_constant_diagnostic_archives_executed_controls_and_preserves_success(self):
        from benchkit.diagnostics.constant import ConstantPolicy

        self.manifest["policy"] = ConstantPolicy([0.] * 14).descriptor.to_dict()
        self.result.update(success=True, action_decisions=2, termination_reason="native_success")
        self.write_run()
        original = self.hashes()
        report = result_index.adopt(self.selections(videos=True), self.output)
        row = report["runs"][0]
        self.assertTrue(row["diagnostic"])
        self.assertEqual(row["purpose"], "infrastructure_validation_only")
        self.assertEqual(row["policy"], self.manifest["policy"])
        self.assertTrue(row["episodes"][0]["success"])
        self.assertEqual(row["episodes"][0]["environment_steps"], 3)
        self.assertEqual(row["episodes"][0]["action_decisions"], 2)
        self.assertEqual(row["summary"]["successes"], 1)
        video = row["videos"][0]
        self.assertTrue(video["diagnostic"])
        self.assertEqual(video["archive_reasons"], ["infrastructure_validation_only"])
        self.assertIn("media/archive/", video["path"])
        self.assertEqual((self.output / video["path"]).read_bytes(), b"original-video-bytes")
        self.assertEqual(original, self.hashes())

    def test_manifest_or_policy_diagnostic_purpose_archives_completed_media(self):
        for location in ("manifest", "parameters"):
            with self.subTest(location=location):
                self.manifest.pop("purpose", None)
                self.manifest["policy"]["parameters"] = {}
                target = self.manifest if location == "manifest" else self.manifest["policy"]["parameters"]
                target["purpose"] = "infrastructure_validation_only"
                self.write_run()
                row, _, videos = result_index.inspect_run(self.selections(videos=True)[0])
                self.assertTrue(row["diagnostic"])
                self.assertEqual(row["purpose"], "infrastructure_validation_only")
                self.assertIn("media/archive/", videos[0]["path"])

    def test_constant_identity_is_diagnostic_without_a_purpose_marker(self):
        self.manifest["policy"]["name"] = "constant-action-diagnostic"
        self.write_run()
        row, _, videos = result_index.inspect_run(self.selections(videos=True)[0])
        self.assertTrue(row["diagnostic"])
        self.assertEqual(row["purpose"], "infrastructure_validation_only")
        self.assertIn("media/archive/", videos[0]["path"])

    def test_manifest_purpose_is_preserved_without_overriding_policy_diagnostic(self):
        self.manifest["purpose"] = "development_pilot"
        self.manifest["policy"]["parameters"] = {"purpose": "infrastructure_validation_only"}
        self.write_run()
        row, _, videos = result_index.inspect_run(self.selections(videos=True)[0])
        self.assertEqual(row["purpose"], "development_pilot")
        self.assertEqual(row["policy"]["parameters"]["purpose"], "infrastructure_validation_only")
        self.assertTrue(row["diagnostic"])
        self.assertIn("media/archive/", videos[0]["path"])

    def test_incomplete_step_evidence_does_not_claim_first_success(self):
        self.steps = self.steps[1:]
        self.write_run()
        row = result_index.adopt(self.selections(), self.output)["runs"][0]["episodes"][0]
        self.assertFalse(row["progress"]["complete_step_coverage"])
        self.assertIsNone(row["progress"]["first_native_success_step"])

    def test_canonical_result_index_and_event_end_require_typed_equality(self):
        for location in ("index", "event_end"):
            for value in (0, 0.0):
                with self.subTest(location=location, value=value):
                    self.write_run()
                    changed = json.loads(json.dumps(self.result))
                    changed["success"] = value
                    if location == "index":
                        (self.run / "episodes.jsonl").write_text(json.dumps(changed) + "\n")
                    else:
                        path = self.episode / "events.jsonl"
                        events = [json.loads(line) for line in path.read_text().splitlines()]
                        events[-1]["result"] = changed
                        path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
                    with self.assertRaisesRegex(ValueError, "disagree|mismatch"):
                        result_index.inspect_run(self.selections()[0])

    def test_lifecycle_episode_counter_rejects_boolean_and_float_aliases(self):
        for count in (True, 1.0):
            with self.subTest(count=count):
                self.write_json(self.run / "status.json", {"status": "completed", "episodes_written": count})
                with self.assertRaisesRegex(ValueError, "invalid episodes_written"):
                    result_index.inspect_run(self.selections()[0])

    def test_invalid_step_or_call_counters_leave_progress_unknown(self):
        for key, value in (("environment_step", True), ("environment_step", 1.0),
                           ("policy_call", True), ("policy_call", 1.0), ("policy_call", 0),
                           ("policy_call", -1), ("policy_call", 3), ("policy_call", None)):
            with self.subTest(key=key, value=value):
                steps = json.loads(json.dumps(self.steps))
                steps[0][key] = value
                progress = result_index._progress(steps, self.result, "robodojo")
                self.assertFalse(progress["complete_step_coverage"])
                self.assertIsNone(progress["first_native_success_step"])
                self.assertIsNone(progress["policy_call_at_first_native_success"])
                self.assertIsNone(progress["first_native_success_timestamp"])

    def test_active_rejected_before_reading_other_records_or_creating_output(self):
        self.write_json(self.run / "status.json", {"status": "running"})
        (self.run / "manifest.json").write_text("not JSON")
        with self.assertRaisesRegex(ValueError, "only closed"):
            result_index.adopt(self.selections(), self.output)
        self.assertFalse(self.output.exists())

    def test_named_identity_cannot_be_relabelled_anonymous(self):
        self.manifest["policy"]["model"] = "actual-model-id"
        self.write_run()
        with self.assertRaisesRegex(ValueError, "named model"):
            result_index.adopt(self.selections(), self.output)

    def test_named_profiles_with_unknown_provider_cannot_be_relabelled_anonymous(self):
        for location in ("manifest", "parameters"):
            for profile in ("gpt6_astra", "opus", "another_explicit_profile"):
                with self.subTest(location=location, profile=profile):
                    self.manifest.pop("model_profile", None)
                    self.manifest["policy"]["parameters"] = {}
                    target = self.manifest if location == "manifest" else self.manifest["policy"]["parameters"]
                    target["model_profile"] = {"id": profile, "source_inventory_sha256": "a" * 64}
                    self.write_run()
                    original = self.hashes()
                    with self.assertRaisesRegex(ValueError, "anonymous_code_agent model profile"):
                        result_index.adopt(self.selections(), self.output)
                    self.assertFalse(self.output.exists())
                    self.assertEqual(original, self.hashes())

    def test_conflicting_or_invalid_explicit_profiles_are_rejected(self):
        self.manifest["policy"]["parameters"] = {"model_profile": {
            "id": "anonymous_code_agent", "source_inventory_sha256": "a" * 64}}
        self.manifest["model_profile"] = {"id": "anonymous_code_agent", "source_inventory_sha256": "b" * 64}
        self.write_run()
        with self.assertRaisesRegex(ValueError, "model profiles disagree"):
            result_index.adopt(self.selections(), self.output)
        for profile in (None, {}, "gpt6_astra", {"factory": "AgentPolicies.gpt6_astra.policy:create_policy"}):
            with self.subTest(profile=profile):
                self.manifest["model_profile"] = profile
                self.write_run()
                with self.assertRaisesRegex(ValueError, "anonymous_code_agent model profile"):
                    result_index.adopt(self.selections(), self.output)
                self.assertFalse(self.output.exists())

    def test_existing_index_bytes_are_never_rewritten(self):
        self.output.mkdir()
        index = self.output / "index.json"
        original = b'{"schema_version": "starvla-rsi.result-index/v1", "historical": true}\n'
        index.write_bytes(original)
        sources = self.hashes()
        with self.assertRaisesRegex(ValueError, "new directory"):
            result_index.adopt(self.selections(), self.output)
        self.assertEqual(index.read_bytes(), original)
        self.assertEqual(self.hashes(), sources)

    def test_duplicate_sources_and_existing_output_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            result_index.adopt(self.selections() * 2, self.output)
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "new directory"):
            result_index.adopt(self.selections(), self.output)

    def test_source_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            result_index.adopt(self.selections(), self.run / "new-index")

    def test_manifest_or_video_symlink_rejected(self):
        real = self.run / "original-manifest.json"
        (self.run / "manifest.json").rename(real)
        (self.run / "manifest.json").symlink_to(real)
        with self.assertRaisesRegex(ValueError, "symlink"):
            result_index.adopt(self.selections(), self.output)
        (self.run / "manifest.json").unlink()
        real.rename(self.run / "manifest.json")
        video = self.episode / "artifacts" / "cam_head.mp4"
        video.unlink()
        video.symlink_to(real)
        with self.assertRaisesRegex(ValueError, "symlink"):
            result_index.adopt(self.selections(videos=True), self.output)

    def test_outside_video_missing_artifact_and_collision_rejected(self):
        self.result["artifacts"]["video_cam_head"] = str(self.root / "outside.mp4")
        self.write_run()
        with self.assertRaisesRegex(ValueError, "inside selected run"):
            result_index.adopt(self.selections(videos=True), self.output)
        self.result["artifacts"]["video_cam_head"] = "cam_head.mp4"
        self.write_run()
        selections = self.selections(videos=True)
        selections[0]["videos"] *= 2
        with self.assertRaisesRegex(ValueError, "collide"):
            result_index.adopt(selections, self.output)

    def test_summary_and_result_inconsistency_rejected(self):
        self.write_json(self.run / "summary.json", {"attempted": 2})
        with self.assertRaisesRegex(ValueError, "summary"):
            result_index.adopt(self.selections(), self.output)

    def test_changed_source_after_inspection_rejected(self):
        _, files, _ = result_index.inspect_run(self.selections()[0])
        (self.run / "manifest.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "changed since inspection"):
            files.verify_unchanged()

    def test_duplicate_and_nonfinite_json_rejected(self):
        for payload in (b'{"key":1,"key":2}', b'{"value":NaN}', b'{"value":1e999}'):
            with self.assertRaises(ValueError):
                result_index.decode(payload)


if __name__ == "__main__":
    unittest.main()
