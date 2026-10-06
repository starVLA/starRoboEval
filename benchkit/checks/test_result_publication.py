import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from benchkit.reports.publication import publish
from benchkit.reports.panel_sr import summarize_panel


class ResultPublicationChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = self.root / "raw" / "accepted-run" / "client"
        self.results = self.root / "AgentPolicies" / "gpt6_astra" / "results" / "robodojo"
        self.episode_id = "classify_objects/arx_x5/eval-seed0/layout0"
        episode_dir = self.raw / "episodes" / self.episode_id.replace("/", "_")
        media_dir = episode_dir / "artifacts" / "sim_server_files"
        media_dir.mkdir(parents=True)
        for camera in ("cam_head", "cam_left_wrist", "cam_right_wrist"):
            (media_dir / f"{camera}.mp4").write_bytes((camera + "-video").encode())
        self.row = {
            "schema_version": "starvla-rsi.eval/v1",
            "episode": {"id": self.episode_id, "task": "classify_objects", "seed": 20260907,
                        "metadata": {"layout_id": 0}},
            "status": "completed", "success": True, "error": None,
            "termination_reason": "environment:terminated", "policy_calls": 2,
            "action_decisions": 2, "environment_steps": 10, "rejected_actions": 0,
            "metrics": {"success": True, "native_benchmark_score": 100.0,
                        "native_process_score": 100.0, "native_benchmark_score_scale": "0..100",
                        "first_native_success_control_target": 10},
            "usage": {"calls": None, "input_tokens": 100},
            "artifacts": {f"video_{camera}": f"sim_server_files/{camera}.mp4"
                          for camera in ("cam_head", "cam_left_wrist", "cam_right_wrist")},
        }
        (episode_dir / "result.json").write_text(json.dumps(self.row))
        self.payloads = {
            "summary.json": {"run_id": "accepted-run", "benchmark": "robodojo",
                             "policy": "gpt6-astra-direct", "attempted": 1, "completed": 1,
                             "successes": 1, "errors": 0, "policy_calls": 2,
                             "rejected_actions": 0, "usage": {"calls": None, "input_tokens": 100}},
            "status.json": {"status": "completed", "episodes_written": 1},
            "manifest.json": {"run_id": "accepted-run", "created_at": "2026-09-20T00:00:00Z",
                              "benchmark": {"name": "robodojo", "version": "native/v1",
                                            "protocol_version": "protocol/v1", "source_revision": "upstream"},
                              "protocol": {"episode_ids": [self.episode_id]},
                              "policy": {"name": "gpt6-astra-direct", "provider": "openai",
                                         "model": "gpt-6-astra", "version": "codex-direct/v2",
                                         "parameters": {"model_identity_evidence": "reported",
                                             "model_profile": {"id": "gpt6_astra",
                                                 "profile_sha256": "0" * 64,
                                                 "config_sha256": "1" * 64,
                                                 "dependencies_sha256": "2" * 64,
                                                 "prompt_sha256": "3" * 64,
                                                 "source_inventory_sha256": "4" * 64}}}},
            "panel_declaration.json": {"run_id": "accepted-run", "selected_layouts": [0],
                                       "attempts_per_layout": 1, "official_full_protocol": False,
                                       "automatic_retry": False, "control_method": "codex-direct/v2",
                                       "native_controls": 10, "image_max_edge": 480,
                                       "source_tree": "tree", "local_commit": "local",
                                       "remote_commit": "remote"},
            "panel_plan.json": {"schema_version": "starvla-rsi.panel-plan/v1",
                                "cases": [self.episode_id],
                                "reference": {"successes": 1, "episodes": 1},
                                "reference_url": "https://example.invalid/reference"},
        }
        self.payloads["panel_report.json"] = summarize_panel(self.payloads["panel_plan.json"], [self.row])
        for name, payload in self.payloads.items():
            (self.raw / name).write_text(json.dumps(payload))
        (self.raw / "episodes.jsonl").write_text(json.dumps(self.row) + "\n")

    def run_publish(self):
        return publish(self.raw.parent, self.results, {"classify_objects": "category-sorting"},
                       verify_closed_record=False)

    def test_publishes_small_result_index_and_named_media_without_mutating_raw(self):
        before = hashlib.sha256((self.raw / "episodes.jsonl").read_bytes()).hexdigest()
        result = self.run_publish()
        self.assertEqual(result["result"]["outcome"]["success_rate"], 1.0)
        self.assertEqual(result["index"]["latest_accepted_run"], "accepted-run")
        self.assertEqual(len(result["media"]), 3)
        for item in result["media"]:
            self.assertIn("classify_objects-category-sorting", item["path"])
            self.assertTrue((self.results / item["path"]).is_file())
            source = self.raw / "episodes" / self.episode_id.replace("/", "_") / "artifacts" / "sim_server_files" / Path(item["path"]).name.removeprefix("video_")
            self.assertNotEqual(os.stat(source).st_ino, os.stat(self.results / item["path"]).st_ino)
        self.assertEqual(before, hashlib.sha256((self.raw / "episodes.jsonl").read_bytes()).hexdigest())
        text = (self.results / "reports" / "accepted-run" / "result.json").read_text()
        self.assertNotIn(str(self.root), text)
        self.assertIn("local barks archive", text)

    def test_idempotent_only_for_identical_publication(self):
        first = self.run_publish()
        second = self.run_publish()
        self.assertEqual(first, second)
        index = json.loads((self.results / "index.json").read_text())
        self.assertEqual(len(index["runs"]), 1)

    def test_rejects_incomplete_or_inconsistent_panels(self):
        self.payloads["panel_report.json"]["complete_panel"] = False
        (self.raw / "panel_report.json").write_text(json.dumps(self.payloads["panel_report.json"]))
        with self.assertRaisesRegex(ValueError, "independent recomputation"):
            self.run_publish()

    def test_requires_public_english_task_description(self):
        with self.assertRaisesRegex(ValueError, "description"):
            publish(self.raw.parent, self.results, {}, verify_closed_record=False)

    def test_rejects_infrastructure_diagnostic(self):
        self.payloads["manifest.json"]["policy"]["kind"] = "infrastructure-diagnostic"
        (self.raw / "manifest.json").write_text(json.dumps(self.payloads["manifest.json"]))
        with self.assertRaisesRegex(ValueError, "diagnostics"):
            self.run_publish()

    def test_binds_declared_client_receipt_to_server_claim(self):
        service = {"server_id": "server-one", "descriptor": {"name": "robodojo"}}
        self.payloads["manifest.json"]["benchmark_service"] = service
        (self.raw / "manifest.json").write_text(json.dumps(self.payloads["manifest.json"]))
        episode_dir = self.raw / "episodes" / self.episode_id.replace("/", "_")
        artifact_root = episode_dir / "artifacts" / "sim_server_files"
        claim = {"episode_id": self.episode_id, "session_id": "session-one"}
        native = {"success": True, "native_benchmark_score": 100.0,
                  "native_process_score": 100.0}
        (artifact_root / "claim.json").write_text(json.dumps(claim))
        (artifact_root / "native_result.json").write_text(json.dumps(native))
        (artifact_root / "native_events.jsonl").write_text("{}\n")
        server = self.raw.parent / "server"
        (server / "episodes" / "session-one").mkdir(parents=True)
        (server / "service.json").write_text(json.dumps(service))
        for source in artifact_root.iterdir():
            shutil.copyfile(source, server / "episodes" / "session-one" / source.name)
        inventory = [{"path": source.name, "size_bytes": source.stat().st_size,
                      "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
                     for source in sorted(artifact_root.iterdir())]
        receipt = {"protocol": "starvla-rsi.sim-server/v1", "session_id": "session-one",
                   "server": service, "finish": {"session_id": "session-one", "files": inventory}}
        (episode_dir / "artifacts" / "sim_server_receipt.json").write_text(json.dumps(receipt))
        output = self.run_publish()
        self.assertEqual(output["result"]["source"]["server_binding"]["status"], "outcome_bound")
        self.assertIn("server/service.json", output["result"]["source"]["raw_evidence"])

    def test_declared_server_without_paired_evidence_is_rejected(self):
        self.payloads["manifest.json"]["benchmark_service"] = {"server_id": "missing"}
        (self.raw / "manifest.json").write_text(json.dumps(self.payloads["manifest.json"]))
        with self.assertRaisesRegex(ValueError, "paired server evidence"):
            self.run_publish()

    def test_rejects_missing_planned_case_even_if_stored_counts_are_forged(self):
        plan = self.payloads["panel_plan.json"]
        plan["cases"].append("classify_objects/arx_x5/eval-seed0/layout1")
        (self.raw / "panel_plan.json").write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, "stored panel report|manifest episode schedule"):
            self.run_publish()

    def test_rejects_absolute_private_identity_evidence(self):
        self.payloads["manifest.json"]["policy"]["parameters"]["model_identity_evidence"] = "/Users/alice/private/token-store"
        (self.raw / "manifest.json").write_text(json.dumps(self.payloads["manifest.json"]))
        with self.assertRaisesRegex(ValueError, "absolute path"):
            self.run_publish()

    def test_second_run_is_appended_atomically_to_index(self):
        self.run_publish()
        second = self.raw.parents[1] / "accepted-run-2"
        shutil.copytree(self.raw.parent, second)
        client = second / "client"
        for name in ("summary.json", "manifest.json", "panel_declaration.json"):
            payload = json.loads((client / name).read_text())
            payload["run_id"] = "accepted-run-2"
            (client / name).write_text(json.dumps(payload))
        publish(second, self.results, {"classify_objects": "category-sorting"},
                verify_closed_record=False)
        index = json.loads((self.results / "index.json").read_text())
        self.assertEqual([row["run_id"] for row in index["runs"]], ["accepted-run", "accepted-run-2"])


if __name__ == "__main__":
    unittest.main()
