"""Full-ledger reporting fixtures; never spend a native capability attempt."""

import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "benchkit/reports/task_ledger.py"
spec = importlib.util.spec_from_file_location("ledger_pilot_fixtures", Path(__file__).with_name("test_campaign_expansion.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class TaskLedgerSnapshotChecks(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.CampaignExpansionChecks()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def prepare(self, benchmark="robocasa365", error=False):
        prior = self.fixture.prior(benchmark, error=error)
        manifest = self.fixture.expand(prior, benchmark)
        return prior, self.root / "expanded", manifest

    def cli(self, campaign, output=None, *, frozen=True, success=True):
        output = output or self.root / "snapshot"
        package = campaign / "frozen" if frozen else ROOT
        result = subprocess.run([sys.executable, str(SCRIPT), "--campaign", str(campaign),
                                 "--output-dir", str(output)], cwd=package,
                                env={**os.environ, "PYTHONPATH": str(package), "PYTHONDONTWRITEBYTECODE": "1"},
                                text=True, capture_output=True, timeout=60)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads((output / "coverage.json").read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        return result.stderr

    def test_full50_group_counts_source_protocols_csv_and_no_input_mutation(self):
        prior, campaign, manifest = self.prepare()
        before = {str(p): fixture.digest(p) for root in (prior, campaign) for p in root.rglob("*") if p.is_file()}
        report = self.cli(campaign)
        self.assertEqual((report["selected_total"], report["carried_attempts"], report["planned_new_cases"]), (50, 2, 48))
        self.assertEqual(report["counts"]["completed"], 2)
        self.assertEqual(report["counts"]["native_failures"], 2)
        self.assertEqual(report["counts"]["unattempted"], 48)
        self.assertEqual({k: v["planned"] for k, v in report["by_task_group"].items()},
                         {"atomic_seen": 18, "composite_seen": 16, "composite_unseen": 16})
        rows = report["cases"]
        self.assertEqual([r["selection_index"] for r in rows], list(range(50)))
        self.assertEqual([r["task"] for r in rows], [r["task"] for r in manifest["coverage_ledger"]["entries"]])
        carried = [r for r in rows if r["disposition"] == "carried_attempt"]
        self.assertEqual({r["selection_index"] for r in carried}, {4, 6})
        self.assertTrue(all(r["protocol_version"] != r["selected_protocol_version"] for r in carried))
        self.assertTrue(all(r["source_campaign"] == str(prior.resolve()) for r in carried))
        self.assertEqual(sum(r["planned"] for r in report["by_original_protocol"].values()), 50)
        with (self.root / "snapshot/tasks.csv").open() as stream:
            csv_rows = list(csv.DictReader(stream))
        self.assertEqual(len(csv_rows), 50)
        self.assertEqual(csv_rows[0]["native_final_success"], "null")
        self.assertEqual(csv_rows[4]["native_final_success"], "false")
        self.assertIn("task_ledger.py", report["tool_sha256"])
        self.assertEqual(before, {str(p): fixture.digest(p) for root in (prior, campaign) for p in root.rglob("*") if p.is_file()})

    def test_simple_full12_retains_two_backend_groups_and_original_attempts(self):
        _, campaign, _ = self.prepare("simple_humanoid")
        report = self.cli(campaign)
        self.assertEqual(report["counts"]["planned"], 12)
        self.assertEqual(report["counts"]["unattempted"], 10)
        self.assertEqual({k: v["planned"] for k, v in report["by_task_group"].items()}, {"amo": 2, "sonic": 10})
        self.assertEqual(len([r for r in report["cases"] if r["disposition"] == "carried_attempt"]), 2)

    def test_live_invalid_and_unattempted_rows_keep_full_denominator_without_reading_live_events(self):
        _, campaign, _ = self.prepare()
        live = campaign / "case-000/run/episodes/opaque"
        live.mkdir(parents=True)
        (live / "events.jsonl").write_text("INVALID PRIVATE LIVE CONTENT THAT MUST NOT BE PARSED")
        bad = campaign / "case-001"
        bad.mkdir()
        (bad / "outcome.json").write_text("not JSON")
        report = self.cli(campaign)
        self.assertEqual(report["counts"]["planned"], 50)
        self.assertEqual(report["counts"]["claimed_without_terminal_outcome"], 1)
        self.assertEqual(report["counts"]["invalid_evidence"], 1)
        self.assertEqual(report["counts"]["unattempted"], 46)
        self.assertIsNone(report["cases"][0]["native_final_success"])
        self.assertFalse(any("events/opaque" in k or "episodes/opaque" in k
                             for source in report["source_snapshots"] for k in source["read_file_sha256"]))

    def test_carried_errors_remain_null_score_attempts(self):
        _, campaign, _ = self.prepare(error=True)
        report = self.cli(campaign)
        self.assertEqual(report["counts"]["infrastructure_or_policy_error"], 2)
        self.assertEqual(report["counts"]["native_failures"], 0)
        self.assertEqual(report["counts"]["native_successes"], 0)
        self.assertTrue(all(r["native_final_success"] is None for r in report["cases"]))

    def test_true_outcomes_count_without_converting_unknown_first_success_to_zero(self):
        with patch.object(fixture.FixtureSession, "metrics", return_value={"success": True}):
            _, campaign, _ = self.prepare()
        report = self.cli(campaign)
        self.assertEqual(report["counts"]["native_successes"], 2)
        self.assertTrue(all(r["first_success_control"] is None for r in report["cases"]))

    def test_changed_prior_bytes_abort_without_new_snapshot_or_attempt(self):
        prior, campaign, _ = self.prepare()
        artifact = next(prior.glob("case-000/run/episodes/*/artifacts/synthetic-video.mp4"))
        artifact.write_bytes(b"changed")
        self.assertIn("bound prior evidence changed", self.cli(campaign, success=False))
        self.assertFalse(list(campaign.glob("case-*")))

    def test_mutable_coordinator_import_is_rejected(self):
        _, campaign, _ = self.prepare()
        self.assertIn("frozen cwd", self.cli(campaign, frozen=False, success=False))

    def test_fresh_full_scope_has_no_fabricated_carried_attempts(self):
        campaign = self.root / "fresh-full"
        fixture.prepare(campaign, "robocasa365", self.fixture.public, "Synthetic future policy.",
                        task_scope="target50")
        report = self.cli(campaign)
        self.assertEqual((report["selected_total"], report["carried_attempts"], report["planned_new_cases"]), (50, 0, 50))
        self.assertEqual(report["counts"]["unattempted"], 50)
        self.assertEqual(len(report["source_snapshots"]), 1)

    def test_terminal_launch_error_without_run_remains_attempt_not_capability_failure(self):
        _, campaign, _ = self.prepare()
        case = campaign / "case-000"
        case.mkdir()
        fixture.atomic_write_json(case / "attempt.json", {"case_index": 0, "attempt": 1,
                                  "campaign_sha256": fixture.digest(campaign / "campaign.json")})
        fixture.atomic_write_json(case / "outcome.json", {"case_index": 0,
                                  "status": "infrastructure_or_policy_error", "returncode": 1,
                                  "timed_out": False, "summary": None})
        report = self.cli(campaign)
        self.assertEqual(report["counts"]["infrastructure_or_policy_error"], 1)
        self.assertEqual(report["counts"]["native_failures"], 2)  # the two original fixtures only
        self.assertIsNone(report["cases"][0]["native_final_success"])
        self.assertEqual(report["cases"][0]["record_consistency"], "unavailable")

    def test_changed_ledger_denominator_is_rejected_even_with_updated_local_digest(self):
        _, campaign, _ = self.prepare()
        self.fixture.mutate(campaign / "campaign.json", lambda doc: doc.update(selected_total=48))
        self.fixture.rewrite_campaign_digest(campaign)
        self.assertIn("coverage denominator counters changed", self.cli(campaign, success=False))

    def test_output_cannot_be_inside_either_source_or_overwrite_snapshot(self):
        prior, campaign, _ = self.prepare()
        for root in (prior, campaign):
            self.assertIn("outside every source", self.cli(campaign, root / "bad-snapshot", success=False))
        self.cli(campaign)
        snapshot = self.root / "snapshot"
        before = {p.name: p.read_bytes() for p in snapshot.iterdir()}
        result = subprocess.run([sys.executable, str(SCRIPT), "--campaign", str(campaign),
                                 "--output-dir", str(snapshot)], cwd=campaign / "frozen",
                                env={**os.environ, "PYTHONPATH": str(campaign / "frozen"), "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in snapshot.iterdir()})


if __name__ == "__main__":
    unittest.main()
