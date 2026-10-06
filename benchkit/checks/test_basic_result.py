"""Synthetic closed records; no model, native initialization or source snapshots."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits.closed_run import AuditError, audit_run
from benchkit.checks.test_interaction_history import fixture, SECRET, write_json
from benchkit.checks.test_methods import declaration
from benchkit.methods import normalize_component_usage
from benchkit.reports.basic_result import build_result, export_result, main, render_html


class BasicResultChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.run = fixture(self.root / "run")
        # Intentionally remove optional events. Sources were never present.
        next((self.run / "episodes").glob("*/events.jsonl")).unlink()

    def edit(self, name, change):
        path = self.run / name
        data = json.loads(path.read_text())
        change(data)
        write_json(path, data)

    def edit_result(self, change):
        self.edit("episodes.jsonl", change)
        self.edit(next((self.run / "episodes").glob("*/result.json")).relative_to(self.run), change)

    def snapshot(self):
        return {str(path.relative_to(self.run)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.run.rglob("*") if path.is_file()}

    def test_result_needs_neither_events_nor_source_audit(self):
        result = build_result(self.run)
        self.assertEqual(result["outcome"]["successes"], 1)
        self.assertEqual(result["outcome"]["environment_steps"], 2)
        self.assertEqual(result["method_origin"], "legacy_policy_projection")
        with self.assertRaises((AuditError, FileNotFoundError, KeyError)):
            audit_run(self.run)

    def test_real_reference_runner_minimal_output_exports_without_events(self):
        from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
        from benchkit.recording import RecordingOptions
        from benchkit.diagnostics.smoke import ReachBenchmark
        from benchkit.checks.test_action_rejection_feedback import Policy, Session, decision
        benchmark = ReachBenchmark()
        session = Session(terminate_after=1)
        benchmark.open_episode = lambda _: session
        run = EvaluationRunner().run(benchmark, Policy([decision(.2, calls=3)]),
            RunRequest(output_dir=self.root, run_id="actual-minimal-record",
                       episode_limit=1, max_steps=3, max_policy_calls=4,
                       recording=RecordingOptions("minimal")))
        report = build_result(run)
        self.assertEqual(report["outcome"]["policy_calls"], 1)
        self.assertEqual(report["usage"]["calls"], 3)
        self.assertEqual(report["method_origin"], "legacy_policy_projection")
        self.assertEqual(report["recording"]["configuration"]["mode"], "minimal")
        self.assertFalse(list(run.glob("episodes/*/events.jsonl")))

    def test_projection_excludes_native_private_fields_and_receipts(self):
        result = build_result(self.run)
        text = json.dumps(result)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("harness_source", text)
        self.assertNotIn("provider_receipt", text)
        self.assertNotIn("traceback", text)

    def test_explicit_numeric_metric_only(self):
        self.edit_result(lambda row: row["metrics"].update(score=40))
        self.assertEqual(build_result(self.run)["episodes"][0]["native_metrics"], {})
        metrics = build_result(self.run, metrics=["score", "missing"])["episodes"][0]["native_metrics"]
        self.assertEqual(metrics, {"score": 40, "missing": None})
        with self.assertRaises(ValueError):
            build_result(self.run, metrics=["oracle"])

    def test_metric_names_and_duplicates_rejected(self):
        for keys in (["../secret"], ["score", "score"], ["/tmp"]):
            with self.assertRaises(ValueError):
                build_result(self.run, metrics=keys)

    def test_method_composition_and_component_usage(self):
        method = declaration()
        self.edit("manifest.json", lambda row: row.update(method=method))
        usage = normalize_component_usage({"planner": {"calls": 3, "input_tokens": 7}}, method)
        self.edit_result(lambda row: row.update(component_usage=usage))
        self.edit("summary.json", lambda row: row.update(component_usage=usage))
        result = build_result(self.run)
        self.assertEqual(result["method"]["id"], method["id"])
        self.assertEqual(result["component_usage"]["planner"]["calls"], 3)
        self.assertIsNone(result["component_usage"]["checker"]["calls"])

    def test_invalid_component_summary_rejected(self):
        self.edit("manifest.json", lambda row: row.update(method=declaration()))
        self.edit("summary.json", lambda row: row.update(component_usage={"planner": {"calls": 500}}))
        with self.assertRaises(ValueError):
            build_result(self.run)

    def test_minimal_recording_not_a_publication_gate(self):
        options = {"schema_version": "starvla-rsi.recording/v1", "mode": "minimal",
                   "interactions": False, "model_io": False, "tool_traces": False,
                   "images": False, "videos": False,
                   "scope": "client-retention; server-native capture configured separately",
                   "source_capture": "internal source/config snapshots retained independently of preset"}
        self.edit("manifest.json", lambda row: row.update(recording=options))
        self.edit_result(lambda row: row.update(recording={**options, "agent_events_written": 0,
                                                         "warnings": ["interaction_recording_failed"]}))
        report = export_result(self.run, self.root / "published")
        self.assertFalse(report["recording"]["publication_requirement"])
        self.assertEqual(report["recording"]["configuration"]["mode"], "minimal")
        self.assertEqual(report["episodes"][0]["recording"]["configuration"]["agent_events_written"], 0)

    def test_scheduled_unattempted_not_hidden(self):
        self.edit("manifest.json", lambda row: row["protocol"]["episode_ids"].append("unattempted"))
        with self.assertRaises(ValueError):
            build_result(self.run)
        self.edit("manifest.json", lambda row: row["protocol"].update(fail_fast=True))
        self.edit_result(lambda row: row.update(status="error", success=None,
            termination_reason="error:infrastructure", error={"type": "InfrastructureError", "category": "infrastructure"}))
        self.edit("status.json", lambda row: row.update(status="completed_with_errors"))
        self.edit("summary.json", lambda row: row.update(completed=0, successes=0, errors=1))
        outcome = build_result(self.run)["outcome"]
        self.assertEqual((outcome["planned"], outcome["attempted"], outcome["unattempted"]), (2, 1, 1))
        self.assertIsNone(outcome["success_rate"])
        self.assertEqual(outcome["selected_success_rate"], 0)

    def test_selected_success_rate_retains_errors_and_unattempted_denominator(self):
        first = json.loads((self.run / "episodes.jsonl").read_text())
        failed = copy.deepcopy(first)
        failed["episode"]["id"] = "task/seed8"
        failed.update(status="error", success=None, termination_reason="error:infrastructure",
                      error={"type": "InfrastructureError", "category": "infrastructure"})
        folder = self.run / "episodes" / "second-error"
        folder.mkdir()
        write_json(folder / "result.json", failed)
        (self.run / "episodes.jsonl").write_text(json.dumps(first) + "\n" + json.dumps(failed) + "\n")
        self.edit("manifest.json", lambda row: row["protocol"].update(
            fail_fast=True, episode_ids=[first["episode"]["id"], failed["episode"]["id"], "unattempted"]))
        self.edit("status.json", lambda row: row.update(status="completed_with_errors", episodes_written=2))
        usage = {key: None if value is None else value * 2 for key, value in first["usage"].items()}
        self.edit("summary.json", lambda row: row.update(attempted=2, completed=1, errors=1,
                                                         successes=1, policy_calls=2, usage=usage))
        report = build_result(self.run)
        outcome = report["outcome"]
        self.assertEqual(outcome["success_rate"], 1)
        self.assertEqual(outcome["attempt_success_rate"], .5)
        self.assertAlmostEqual(outcome["selected_success_rate"], 1 / 3)
        self.assertEqual(outcome["rate_denominators"]["selected_success_rate"], "selected_cases")
        page = render_html(report)
        self.assertIn("1 / 3 successes / selected cases", page)
        self.assertIn("1 errors; 1 unattempted", page)

    def test_summary_count_usage_and_rate_mismatch_rejected(self):
        for key, value in (("successes", 0), ("policy_calls", True), ("usage", {"calls": 99}),
                           ("success_rate", 0.0), ("success_rate", True), ("run_id", "another")):
            original = (self.run / "summary.json").read_text()
            self.edit("summary.json", lambda row: row.update({key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_result(self.run)
            (self.run / "summary.json").write_text(original)

    def test_lifecycle_and_result_inconsistency_rejected(self):
        self.edit("status.json", lambda row: row.update(status="running"))
        with self.assertRaises(ValueError):
            build_result(self.run)
        self.edit("status.json", lambda row: row.update(status="completed"))
        self.edit("episodes.jsonl", lambda row: row.update(environment_steps=3))
        with self.assertRaises(ValueError):
            build_result(self.run)

    def test_budget_overrun_and_impossible_counters_rejected(self):
        for values in ({"environment_steps": 20}, {"action_decisions": 9}, {"policy_calls": 6}):
            with self.subTest(values=values):
                before = json.loads((self.run / "episodes.jsonl").read_text())
                self.edit_result(lambda row: row.update(values))
                with self.assertRaises(ValueError):
                    build_result(self.run)
                self.edit_result(lambda row: row.update(before))

    def test_unbounded_action_prefix_is_valid(self):
        self.edit("manifest.json", lambda row: row["protocol"].update(replan_interval=None))
        self.assertIsNone(build_result(self.run)["protocol"]["replan_interval"])

    def test_missing_success_cannot_be_published_as_completed(self):
        self.edit_result(lambda row: row.update(success=None))
        with self.assertRaises(ValueError):
            build_result(self.run)

    def test_html_escapes_method_configuration(self):
        method = declaration()
        method["configuration"]["prompt"] = '<script>alert("unsafe")</script>'
        self.edit("manifest.json", lambda row: row.update(method=method))
        page = render_html(build_result(self.run))
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_fresh_destination_and_source_bytes_preserved(self):
        before = self.snapshot()
        target = self.root / "result"
        report = export_result(self.run, target)
        self.assertEqual(json.loads((target / "result.json").read_text()), report)
        self.assertEqual(before, self.snapshot())
        for path in (target, self.run / "presentation"):
            with self.assertRaises(ValueError):
                export_result(self.run, path)

    def test_symlink_input_and_output_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.run, target_is_directory=True)
        with self.assertRaises(ValueError):
            build_result(alias)
        outside = self.root / "outside.json"
        outside.write_bytes((self.run / "summary.json").read_bytes())
        (self.run / "summary.json").unlink()
        (self.run / "summary.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            build_result(self.run)

    def test_duplicate_json_and_nonfinite_rejected(self):
        path = self.run / "summary.json"
        original = path.read_text()
        for text in ('{"run_id":"a","run_id":"b"}', '{"n":NaN}'):
            path.write_text(text)
            with self.assertRaises(ValueError):
                build_result(self.run)
        path.write_text(original)

    def test_change_during_export_fails_before_publication(self):
        from benchkit.reports import basic_result
        original = basic_result.render_html

        def change(report):
            self.edit("summary.json", lambda row: row.update(successes=0))
            return original(report)

        with patch.object(basic_result, "render_html", side_effect=change):
            with self.assertRaises(ValueError):
                export_result(self.run, self.root / "result")
        self.assertFalse((self.root / "result").exists())

    def test_cli_success_without_optional_evidence(self):
        self.assertEqual(main(["--run-dir", str(self.run), "--output-dir", str(self.root / "view")]), 0)


if __name__ == "__main__":
    unittest.main()
