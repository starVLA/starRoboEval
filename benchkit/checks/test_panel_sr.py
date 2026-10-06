"""Synthetic-only panel reporting; no policy, simulator or source result edits."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from benchkit.reports import panel_sr


def plan(cases=None):
    return {"schema_version": panel_sr.PLAN_SCHEMA, "cases": cases or [f"case{i}" for i in range(5)],
        "reference": {"successes": 5, "episodes": 5}, "reference_url": "https://example.test/report",
        "operator_notes": "Declared fixture, not equivalent-condition evidence."}


def result(case, success=False, error=None):
    return {"schema_version": panel_sr.RESULT_SCHEMA, "episode": {"id": case, "task": "synthetic"},
        "status": "error" if error is not None else "completed", "success": None if error is not None else success,
        "metrics": {} if error is not None else {"success": success}, "error": error,
        "environment_steps": 10, "policy_calls": 3, "action_decisions": 2}


class PanelSRChecks(unittest.TestCase):
    def test_complete_all_success_never_claims_equivalence(self):
        rows = [result(f"case{i}", True) for i in range(5)]
        report = panel_sr.summarize_panel(plan(), rows)
        self.assertTrue(report["complete_panel"])
        self.assertEqual(report["full_panel_success_rate"], 1)
        self.assertEqual(report["counts"]["planned"], 5)
        self.assertTrue(report["comparison"]["same_numeric_rate"])
        self.assertFalse(report["comparison"]["same_conditions_verified"])
        self.assertFalse(report["comparison"]["statistical_equivalence_established"])

    def test_policy_and_model_errors_are_failures_in_full_planned_denominator(self):
        rows = [result("case0", True), result("case1", False), result("case2", True),
            result("case3", error={"category": "policy", "message": "invalid output"}),
            result("case4", error={"category": "model", "message": "invalid action"})]
        original = deepcopy(rows)
        report = panel_sr.summarize_panel(plan(), rows)
        self.assertTrue(report["complete_panel"])
        self.assertEqual(report["full_panel_success_rate"], 2 / 5)
        self.assertEqual(report["counts"]["policy_failures"], 2)
        self.assertEqual(report["completed_native_success_rate"]["episodes"], 3)
        self.assertEqual(report["completed_native_success_rate"]["rate"], 2 / 3)
        self.assertEqual(report["records"], original)
        self.assertEqual(rows, original)

    def test_missing_and_infrastructure_cases_prevent_full_panel_claim(self):
        rows = [result("case0", True), result("case1", error={"category": "infrastructure"}),
                result("case2", error={"category": "policy"})]
        report = panel_sr.summarize_panel(plan(), rows)
        self.assertEqual(report["counts"]["missing_closed_results"], 2)
        self.assertEqual(report["counts"]["infrastructure_errors"], 1)
        self.assertEqual(report["counts"]["policy_failures"], 1)
        self.assertFalse(report["complete_panel"])
        self.assertIsNone(report["full_panel_success_rate"])
        self.assertIsNone(report["comparison"]["same_numeric_rate"])
        self.assertEqual(report["successful_over_planned"]["rate"], 1 / 5)
        self.assertEqual(report["successful_over_planned"]["interpretation"], "coverage_lower_bound_only")
        self.assertEqual([r["case_id"] for r in report["cases"] if r["outcome"] == "missing_closed_result"], ["case3", "case4"])

    def test_unknown_and_protocol_errors_are_not_guessed_to_be_model_failures(self):
        for error in ({"category": "protocol"}, {"category": "evaluation"}, {"category": "unknown"}, {}):
            with self.subTest(error=error):
                report = panel_sr.summarize_panel(plan(["case0"]), [result("case0", error=error)])
                self.assertFalse(report["complete_panel"])
                self.assertEqual(report["counts"]["infrastructure_errors"], 1)
                self.assertEqual(report["counts"]["policy_failures"], 0)

    def test_secondary_infrastructure_is_retained_even_for_policy_failure(self):
        for detail in ({"artifact_error": {"category": "infrastructure"}},
                       {"cleanup_errors": ["close failed"]},
                       {"policy_call_error": {"category": "infrastructure"}}):
            with self.subTest(detail=detail):
                row = result("case0", error={"category": "policy", **detail})
                report = panel_sr.summarize_panel(plan(["case0"]), [row])
                self.assertEqual(report["counts"]["policy_failures"], 1)
                self.assertEqual(report["counts"]["infrastructure_errors"], 1)
                self.assertFalse(report["complete_panel"])
                self.assertEqual(report["records"], [row])

    def test_empty_results_keep_full_plan_and_no_secondary_zero_denominator(self):
        report = panel_sr.summarize_panel(plan(), [])
        self.assertEqual(report["counts"]["missing_closed_results"], 5)
        self.assertEqual(report["successful_over_planned"]["rate"], 0)
        self.assertIsNone(report["completed_native_success_rate"]["rate"])
        self.assertFalse(report["complete_panel"])

    def _assert_nested_infrastructure_blocks_full_sr(self, nested):
        row = result("case0", error={"category": "policy", "policy_call_error": nested})
        report = panel_sr.summarize_panel(plan(["case0"]), [row])
        self.assertEqual(report["counts"]["policy_failures"], 1)
        self.assertGreater(report["counts"]["infrastructure_errors"], 0)
        self.assertFalse(report["complete_panel"])
        self.assertIsNone(report["full_panel_success_rate"])
        self.assertEqual(report["successful_over_planned"]["episodes"], 1)
        self.assertEqual(report["records"], [row])

    def test_nested_policy_cleanup_error_blocks_full_sr(self):
        self._assert_nested_infrastructure_blocks_full_sr({"category": "policy", "cleanup_errors": ["close failed"]})

    def test_nested_policy_artifact_error_blocks_full_sr(self):
        self._assert_nested_infrastructure_blocks_full_sr({"category": "policy", "artifact_error": {"category": "infrastructure"}})

    def test_two_level_nested_infrastructure_blocks_full_sr(self):
        self._assert_nested_infrastructure_blocks_full_sr({"category": "policy", "policy_call_error": {"category": "infrastructure"}})

    def test_error_chain_does_not_scan_arbitrary_metadata(self):
        row = result("case0", error={"category": "policy", "metadata": {
            "category": "infrastructure", "cleanup_errors": ["quoted example"],
            "artifact_error": {}, "policy_call_error": {"category": "infrastructure"}}})
        report = panel_sr.summarize_panel(plan(["case0"]), [row])
        self.assertTrue(report["complete_panel"])
        self.assertEqual(report["counts"]["infrastructure_errors"], 0)

    def test_unsupported_error_chain_depth_is_rejected(self):
        error = {"category": "policy"}
        for _ in range(33):
            error = {"category": "policy", "policy_call_error": error}
        with self.assertRaisesRegex(ValueError, "depth32"):
            panel_sr.summarize_panel(plan(["case0"]), [result("case0", error=error)])

    def test_absent_closed_result_does_not_assert_unattempted_or_allow_retry(self):
        # A process may already have executed this case and died before writing
        # its result. The same input is therefore insufficient to infer no try.
        report = panel_sr.summarize_panel(plan(["case-with-lost-process"]), [])
        self.assertEqual(report["cases"][0]["outcome"], "missing_closed_result")
        self.assertEqual(report["counts"]["missing_closed_results"], 1)
        self.assertNotIn("unattempted", report["counts"])
        self.assertFalse(any(row["outcome"] == "unattempted" for row in report["cases"]))
        self.assertNotIn("retry", report["cases"][0])
        self.assertEqual(report["successful_over_planned"]["episodes"], 1)
        self.assertIsNone(report["full_panel_success_rate"])

    def test_duplicate_unplanned_and_open_records_rejected(self):
        row = result("case0")
        for rows in ([row, row], [result("not-planned")], [{**row, "status": "running"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                panel_sr.summarize_panel(plan(), rows)

    def test_plan_schema_and_integer_booleans_rejected(self):
        for change in ({"cases": []}, {"cases": ["a", "a"]}, {"cases": [True]}, {"cases": [" a"]},
                       {"schema_version": "unknown"}, {"extra": "not part of schema"},
                       {"operator_notes": []}, {"reference_url": 1},
                       {"reference": {"successes": True, "episodes": 5}},
                       {"reference": {"successes": 1, "episodes": True}},
                       {"reference": {"successes": 6, "episodes": 5}},
                       {"reference": {"successes": 0, "episodes": 0}},
                       {"reference": {"successes": 1.0, "episodes": 5}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                panel_sr.summarize_panel({**plan(), **change}, [])

    def test_result_schema_success_consistency_and_nonfinite_values_rejected(self):
        row = result("case0", True)
        for change in ({"success": 1}, {"metrics": {"success": 1}}, {"success": False},
                       {"error": {}}, {"schema_version": "unknown"}, {"metrics": []},
                       {"duration_s": float("nan")}, {"environment_steps": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                panel_sr.summarize_panel(plan(), [{**row, **change}])
        with self.assertRaises(ValueError):
            panel_sr.summarize_panel(plan(), [{**result("case0", error={}), "success": False}])
        with self.assertRaises(ValueError):
            panel_sr.summarize_panel(plan(), [result("case0", error={"category": True})])

    def test_explicit_counter_names_only_and_first_success_never_rescores(self):
        row = result("case0", False)
        row["metrics"].update(controls=10, first_native_success_control=7,
            native_take_action_count=999, first_native_success_control_target=999)
        report = panel_sr.summarize_panel(plan(["case0"]), [row])
        self.assertEqual(report["counts"]["successes"], 0)
        self.assertEqual(report["cases"][0]["counters"], {"environment_steps": 10, "policy_calls": 3,
            "action_decisions": 2, "controls": 10, "first_native_success_control": 7})
        for key in ("controls", "first_native_success_control"):
            bad = deepcopy(row)
            bad["metrics"][key] = True
            with self.assertRaises(ValueError):
                panel_sr.summarize_panel(plan(), [bad])
        row["metrics"]["first_native_success_control"] = 11
        with self.assertRaises(ValueError):
            panel_sr.summarize_panel(plan(), [row])

    def test_optional_unknown_counters_are_omitted_not_inferred(self):
        row = result("case0")
        del row["action_decisions"]
        row["policy_calls"] = None
        row["metrics"]["native_take_action_count"] = 50
        counters = panel_sr.summarize_panel(plan(["case0"]), [row])["cases"][0]["counters"]
        self.assertEqual(counters, {"environment_steps": 10})

    def test_cli_create_only_input_hashes_and_original_bytes_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p, e, out = root / "plan.json", root / "episodes.jsonl", root / "report.json"
            p.write_text(json.dumps(plan(["case0"])))
            e.write_text(json.dumps(result("case0", True)) + "\n")
            originals = (p.read_bytes(), e.read_bytes())
            args = ["--plan", str(p), "--episodes", str(e), "--output", str(out)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(panel_sr.main(args), 0)
            report = json.loads(out.read_text())
            self.assertEqual(len(report["inputs"]["plan"]["sha256"]), 64)
            original_report = out.read_bytes()
            with self.assertRaises(FileExistsError):
                panel_sr.main(args)
            self.assertEqual(out.read_bytes(), original_report)
            self.assertEqual((p.read_bytes(), e.read_bytes()), originals)
            out.unlink()
            out.symlink_to(p.name)
            with self.assertRaises(FileExistsError):
                panel_sr.main(args)
            self.assertEqual(p.read_bytes(), originals[0])

    def test_decoder_rejects_duplicate_keys_and_nonfinite_json(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                panel_sr._decode(text)

    def test_import_is_dependency_free_without_policy_or_simulator(self):
        script = """
import sys
from benchkit.reports.panel_sr import summarize_panel
for prefix in ('numpy', 'scipy', 'torch', 'AgentPolicies', 'benchmarks', 'isaacsim', 'isaaclab', 'omni'):
 assert not any(m == prefix or m.startswith(prefix + '.') for m in sys.modules), prefix
"""
        completed = subprocess.run([sys.executable, "-B", "-S", "-c", script],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
