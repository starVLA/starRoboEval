"""Closed-log success timing never queries a simulator or replaces final scoring."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("record_progress", Path(__file__).resolve().parents[4] / "benchkit/reports/progress.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProgressChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.episode = self.run / "episodes/task"
        self.episode.mkdir(parents=True)
        (self.run / "status.json").write_text(json.dumps({"status": "completed", "episodes_written": 1}))
        (self.run / "manifest.json").write_text(json.dumps({"benchmark": {"name": "simpler_env"}, "protocol": {}}))
        (self.episode / "result.json").write_text(json.dumps({
            "episode": {"id": "task"}, "status": "completed", "success": False,
            "environment_steps": 3, "policy_calls": 2, "termination_reason": "step_limit", "error": None,
        }))
        self.events = [{"event": "environment_step", "environment_step": step,
                        "policy_call": 1 if step <= 2 else 2, "timestamp": f"time-{step}",
                        "info": {"success": step == 2}, "terminated": True}
                       for step in (1, 2, 3)]

    def report(self):
        (self.episode / "events.jsonl").write_text("\n".join(json.dumps(event) for event in self.events))
        return MODULE.summarize_progress(self.run)["episodes"][0]

    def test_transient_first_success_does_not_replace_final_failure(self):
        row = self.report()
        self.assertTrue(row["complete_step_coverage"])
        self.assertEqual(row["first_native_success_step"], 2)
        self.assertEqual(row["policy_call_at_first_native_success"], 1)
        self.assertIs(row["final_success"], False)
        self.assertEqual(row["consecutive_success_steps_at_end"], 0)

    def test_missing_steps_do_not_claim_the_actual_first_success(self):
        self.events = self.events[1:]
        row = self.report()
        self.assertFalse(row["complete_step_coverage"])
        self.assertIsNone(row["first_native_success_step"])
        self.assertEqual(row["first_logged_success_step"], 2)

    def test_termination_does_not_imply_success(self):
        for event in self.events:
            event["info"] = {}
        row = self.report()
        self.assertIsNone(row["first_native_success_step"])
        self.assertFalse(row["complete_step_coverage"])

    def test_no_success_is_null_not_the_final_step(self):
        for event in self.events:
            event["info"]["success"] = False
        row = self.report()
        self.assertTrue(row["complete_step_coverage"])
        self.assertIsNone(row["first_native_success_step"])
        self.assertEqual(row["final_environment_steps"], 3)

    def test_active_run_is_rejected(self):
        (self.run / "status.json").write_text(json.dumps({"status": "running"}))
        with self.assertRaisesRegex(ValueError, "closed"):
            self.report()

    def test_new_adapters_use_logged_native_success_and_actual_call(self):
        for benchmark in ("robocasa365", "simple_humanoid", "robocasa_tabletop", "robodojo"):
            with self.subTest(benchmark=benchmark):
                (self.run / "manifest.json").write_text(json.dumps({"benchmark": {"name": benchmark}, "protocol": {}}))
                for event in self.events:
                    event["info"] = {"native_success": event["environment_step"] == 3}
                row = self.report()
                self.assertTrue(row["complete_step_coverage"])
                self.assertEqual(row["first_native_success_step"], 3)
                self.assertEqual(row["policy_call_at_first_native_success"], 2)

    def dojo_manifest(self):
        (self.run / "manifest.json").write_text(json.dumps({"benchmark": {"name": "robodojo"}, "protocol": {}}))

    def test_dojo_success_uses_control_target_not_physics_or_reset_alive(self):
        self.dojo_manifest()
        self.events.insert(0, {"event": "observation", "observation": {"step": 0},
                               "info": {"native_success": True, "native_alive_flag": True}})
        for event in self.events[1:]:
            step = event["environment_step"]
            event["info"] = {"native_success": step == 3, "control_targets": step,
                             "physics_ticks": 10 * step, "native_alive_flag": True}
        row = self.report()
        self.assertEqual(row["native_success_field"], "native_success")
        self.assertEqual(row["first_native_success_step"], 3)
        self.assertEqual(row["policy_call_at_first_native_success"], 2)
        self.assertEqual(row["first_native_success_timestamp"], "time-3")
        self.assertIs(row["final_success"], False)

    def test_dojo_missing_or_nonnative_flag_never_estimates_first_success(self):
        self.dojo_manifest()
        for event in self.events:
            event["info"] = {"native_success": 1, "native_alive_flag": True, "success": True}
        row = self.report()
        self.assertFalse(row["complete_step_coverage"])
        self.assertIsNone(row["first_native_success_step"])
        self.events[1]["info"]["native_success"] = True
        row = self.report()
        self.assertEqual(row["first_logged_success_step"], 2)
        self.assertIsNone(row["first_native_success_step"])
        self.assertIsNone(row["policy_call_at_first_native_success"])

    def test_dojo_zero_control_policy_error_keeps_null_success_and_one_call(self):
        self.dojo_manifest()
        (self.run / "status.json").write_text(json.dumps({"status": "completed_with_errors", "episodes_written": 1}))
        result_path = self.episode / "result.json"
        result = json.loads(result_path.read_text())
        result.update(status="error", success=None, environment_steps=0, policy_calls=1,
                      termination_reason="error:policy", error={"category": "policy", "message": "synthetic malformed response"})
        result_path.write_text(json.dumps(result))
        original = result_path.read_bytes()
        self.events = [{"event": "policy_call_start", "policy_call": 1}, {"event": "policy_error"}]
        row = self.report()
        self.assertEqual(row["final_policy_calls"], 1)
        self.assertEqual(row["final_environment_steps"], 0)
        self.assertIsNone(row["first_native_success_step"])
        self.assertIsNone(row["policy_call_at_first_native_success"])
        self.assertIsNone(row["final_success"])
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], result["error"])
        self.assertEqual(result_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
