"""Offline consistency checks: mocks only, never a simulator or model trial."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from benchkit.contracts import ActionChunk, PolicyDecision
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.diagnostics.smoke import ReachBenchmark, ScriptedReachPolicy

MODULE_PATH = Path(__file__).resolve().parents[4] / "benchkit/audits/closed_run.py"
SPEC = importlib.util.spec_from_file_location("closed_audit", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class BrokenPolicy(ScriptedReachPolicy):
    def act(self, observation):
        raise RuntimeError("injected diagnostic failure")


class StopPolicy(ScriptedReachPolicy):
    def act(self, observation):
        return PolicyDecision(stop=True, stop_reason="give_up")


class EarlySuccessPolicy(ScriptedReachPolicy):
    def act(self, observation):
        action = super().act(observation).action.steps[0]
        return PolicyDecision(action=ActionChunk.from_steps([action] * 5))


class NeverReachPolicy(ScriptedReachPolicy):
    def act(self, observation):
        # Mock target is always in [-0.8, 0.8], so absolute 1 cannot succeed.
        return PolicyDecision(action=ActionChunk.from_steps([[1.0]]))


class ClosedAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_fixture(self, policy=None, **kwargs):
        return EvaluationRunner().run(ReachBenchmark(), policy or ScriptedReachPolicy(),
                                      RunRequest(output_dir=self.root, episode_limit=1,
                                                 max_steps=10, max_policy_calls=2,
                                                 replan_interval=5, **kwargs))

    def events(self, run):
        path = next((run / "episodes").glob("*/events.jsonl"))
        return path, [json.loads(line) for line in path.read_text().splitlines()]

    def save_events(self, path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_closed_success(self):
        result = audit.audit_run(self.run_fixture())
        self.assertEqual(result["record_consistency"], "passed")
        self.assertEqual(result["episodes"][0]["controls"], 1)
        self.assertGreater(result["source_files_verified"], 0)

    def test_failed_decision_is_not_hidden(self):
        row = audit.audit_run(self.run_fixture(BrokenPolicy()))["episodes"][0]
        self.assertEqual((row["status"], row["decisions_started"], row["decisions_returned"]),
                         ("error", 1, 0))
        self.assertIsNone(row["success"])

    def test_stop_counts_without_control(self):
        row = audit.audit_run(self.run_fixture(StopPolicy()))["episodes"][0]
        self.assertEqual((row["controls"], row["decisions_started"], row["stop_decisions"]), (0, 1, 1))
        self.assertFalse(row["success"])

    def test_embedded_stop_mismatch_rejected(self):
        run = self.run_fixture(StopPolicy())
        path, rows = self.events(run)
        decision = next(row for row in rows if row["event"] == "policy_decision")
        decision["metadata"] = {"request_id": "request", "structured_response":
                                {"request_id": "request", "actions": [[0.0]]}}
        self.save_events(path, rows)
        with self.assertRaisesRegex(audit.AuditError, "response/stop"):
            audit.audit_run(run)

    def test_embedded_request_id_mismatch_rejected(self):
        run = self.run_fixture(StopPolicy())
        path, rows = self.events(run)
        decision = next(row for row in rows if row["event"] == "policy_decision")
        decision["metadata"] = {"request_id": "request", "structured_response":
                                {"request_id": "other", "stop": True, "stop_reason": "give_up"}}
        self.save_events(path, rows)
        with self.assertRaisesRegex(audit.AuditError, "request ID"):
            audit.audit_run(run)

    def test_native_success_may_shorten_prefix(self):
        row = audit.audit_run(self.run_fixture(EarlySuccessPolicy()))["episodes"][0]
        self.assertEqual((row["controls"], row["decisions_started"], row["action_chunks"]), (1, 1, 1))
        self.assertTrue(row["success"])

    def payload(self, run):
        _, events = self.events(run)
        manifest = json.loads((run / "manifest.json").read_text())
        return copy.deepcopy(events[-1]["result"]), events, manifest["protocol"]

    def test_false_completed_termination_labels_rejected(self):
        result, events, protocol = self.payload(self.run_fixture(NeverReachPolicy()))
        self.assertEqual((result["environment_steps"], result["policy_calls"]), (2, 2))
        self.assertEqual(result["termination_reason"], "runner:policy_call_limit")
        for reason in ("environment:terminated", "environment:truncated", "runner:step_limit", "unknown"):
            with self.subTest(reason=reason):
                result["termination_reason"] = reason
                events[-1]["result"] = result
                with self.assertRaisesRegex(audit.AuditError, "termination reason mismatch"):
                    audit.audit_episode(result, events, protocol)

    def test_completed_without_any_stop_condition_rejected(self):
        result, events, protocol = self.payload(self.run_fixture(NeverReachPolicy()))
        protocol["max_policy_calls"] = 3
        with self.assertRaisesRegex(audit.AuditError, "no applicable termination"):
            audit.audit_episode(result, events, protocol)

    def test_termination_precedence_at_budget_ties(self):
        result, events, protocol = self.payload(self.run_fixture(NeverReachPolicy()))
        last_control = next(event for event in reversed(events) if event["event"] == "environment_step")
        protocol.update(max_steps=2, replan_interval=1)
        for mode, terminated, truncated, reason in (
                ("decisions", False, True, "runner:policy_call_limit"),
                ("decisions", False, False, "runner:policy_call_limit"),
                ("decisions", True, True, "environment:terminated"),
                ("horizon", False, True, "environment:truncated"),
                ("horizon", False, False, "runner:step_limit"),
                ("horizon", True, True, "environment:terminated")):
            with self.subTest(mode=mode, terminated=terminated, truncated=truncated):
                protocol["budget_mode"] = mode
                last_control.update(terminated=terminated, truncated=truncated)
                result["termination_reason"] = reason
                events[-1]["result"] = result
                self.assertEqual(audit.audit_episode(result, events, protocol)["termination_reason"], reason)
                result["termination_reason"] = "wrong:label"
                with self.assertRaisesRegex(audit.AuditError, "termination reason mismatch"):
                    audit.audit_episode(result, events, protocol)

    def test_error_termination_category_must_match(self):
        result, events, protocol = self.payload(self.run_fixture(BrokenPolicy()))
        result["termination_reason"] = "environment:terminated"
        events[-1]["result"] = result
        with self.assertRaisesRegex(audit.AuditError, "error termination reason"):
            audit.audit_episode(result, events, protocol)

    def test_active_run_rejected(self):
        run = self.run_fixture()
        (run / "status.json").write_text(json.dumps({"status": "running"}))
        with self.assertRaisesRegex(audit.AuditError, "only closed"):
            audit.audit_run(run)

    def test_changed_source_rejected(self):
        run = self.run_fixture()
        source = next((run / "harness_source/files").rglob("*.py"))
        source.write_text(source.read_text() + "\n# altered\n")
        with self.assertRaisesRegex(audit.AuditError, "copied source mismatch"):
            audit.audit_run(run)

    def test_extra_copied_source_rejected(self):
        run = self.run_fixture()
        (run / "harness_source/files/unrecorded.py").write_text("# extra\n")
        with self.assertRaisesRegex(audit.AuditError, "extra/missing"):
            audit.audit_run(run)

    def test_result_index_disagreement_rejected(self):
        run = self.run_fixture()
        path = next((run / "episodes").glob("*/result.json"))
        result = json.loads(path.read_text())
        result["policy_calls"] += 1
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(audit.AuditError, "index/result"):
            audit.audit_run(run)

    def test_executed_action_mismatch_rejected(self):
        run = self.run_fixture()
        path, rows = self.events(run)
        next(row for row in rows if row["event"] == "environment_step")["action"] = [0.99]
        self.save_events(path, rows)
        with self.assertRaisesRegex(audit.AuditError, "action differs"):
            audit.audit_run(run)

    def test_duplicate_decision_rejected(self):
        run = self.run_fixture()
        path, rows = self.events(run)
        index = next(i for i, row in enumerate(rows) if row["event"] == "policy_decision")
        rows.insert(index + 1, copy.deepcopy(rows[index]))
        self.save_events(path, rows)
        with self.assertRaisesRegex(audit.AuditError, "duplicate policy decision"):
            audit.audit_run(run)

    def test_control_counter_gap_rejected(self):
        run = self.run_fixture()
        path, rows = self.events(run)
        next(row for row in rows if row["event"] == "environment_step")["environment_step"] = 2
        self.save_events(path, rows)
        with self.assertRaisesRegex(audit.AuditError, "control order"):
            audit.audit_run(run)

    def test_prefix_budget_drift_rejected(self):
        run = self.run_fixture()
        path, rows = self.events(run)
        next(row for row in rows if row["event"] == "action_chunk")["maximum_executed_prefix"] = 2
        self.save_events(path, rows)
        with self.assertRaisesRegex(audit.AuditError, "prefix budget"):
            audit.audit_run(run)

    def test_summary_denominator_mismatch_rejected(self):
        run = self.run_fixture()
        path = run / "summary.json"
        summary = json.loads(path.read_text())
        summary["attempted"] = 0
        path.write_text(json.dumps(summary))
        with self.assertRaisesRegex(audit.AuditError, "summary attempted"):
            audit.audit_run(run)

    def test_symlink_result_rejected(self):
        run = self.run_fixture()
        path = next((run / "episodes").glob("*/result.json"))
        outside = self.root / "outside.json"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaisesRegex(audit.AuditError, "symlink"):
            audit.audit_run(run)

    def test_strict_json(self):
        for text in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}']:
            with self.subTest(text=text), self.assertRaises(audit.AuditError):
                audit.decode(text)

    def test_unsafe_artifact_paths(self):
        files = audit.ClosedFiles(self.root)
        for path in ("../outside.json", "/etc/passwd"):
            with self.subTest(path=path), self.assertRaises(audit.AuditError):
                files.path(path)


if __name__ == "__main__":
    unittest.main()
