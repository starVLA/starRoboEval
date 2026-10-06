"""Offline campaign reporting checks; synthetic runner records, never native trials."""

import csv
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.contracts import PolicyDecision
from benchkit.diagnostics.constant import ConstantPolicy
from benchkit.reports import coverage as reporting
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.diagnostics.smoke import ReachBenchmark, ScriptedReachPolicy

class StopPolicy(ScriptedReachPolicy):
    def act(self, observation):
        return PolicyDecision(stop=True, stop_reason="give_up")


class BrokenPolicy(ScriptedReachPolicy):
    def act(self, observation):
        raise RuntimeError("synthetic error")


class CoverageSnapshotChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.campaign = self.root / "campaign"
        self.campaign.mkdir()

    def save(self, path, obj):
        path.write_text(json.dumps(obj))

    def prepare(self, policy=None):
        run = EvaluationRunner().run(
            ReachBenchmark(), policy or ScriptedReachPolicy(),
            RunRequest(output_dir=self.campaign / "case-000", run_id="run", episode_limit=1,
                       max_steps=10, max_policy_calls=2, replan_interval=5))
        source = json.loads((run / "manifest.json").read_text())
        result = json.loads((run / "episodes.jsonl").read_text())
        self.manifest = {
            "schema_version": "starvla-rsi.campaign/v1", "planned_cases": 3,
            "benchmark": source["benchmark"]["name"], "harness_source": source["harness_source"],
            "policy": {key: source["policy"][key] for key in ("name", "kind", "model", "provider")},
            **{k: source["protocol"][k] for k in
               ("seed", "budget_mode", "max_policy_calls", "replan_interval", "max_steps")},
            "cases": [{"index": i, "case_id": f"case-{i:03d}", "episode": result["episode"],
                       "descriptor": source["benchmark"].copy()}
                      for i in range(3)],
        }
        self.freeze()
        summary = json.loads((run / "summary.json").read_text())
        self.outcome = {"case_index": 0, "summary": summary,
                        "status": "completed" if summary["errors"] == 0 else "infrastructure_or_policy_error",
                        "returncode": 0 if summary["errors"] == 0 else 1, "timed_out": False}
        self.save(self.campaign / "case-000/outcome.json", self.outcome)
        (self.campaign / "case-001").mkdir()
        # In-progress contents intentionally malformed: the reporter must not read them.
        (self.campaign / "case-001/run").mkdir()
        (self.campaign / "case-001/run/status.json").write_text("not JSON")
        return run

    def freeze(self):
        self.save(self.campaign / "campaign.json", self.manifest)
        digest = hashlib.sha256((self.campaign / "campaign.json").read_bytes()).hexdigest()
        self.save(self.campaign / "campaign_digest.json", {"sha256": digest})
        self.save(self.campaign / "case-000/attempt.json",
                  {"case_index": 0, "attempt": 1, "campaign_sha256": digest})

    def test_full_denominator_and_no_live_episode_read(self):
        self.prepare()
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"], {"planned": 3, "completed": 1,
            "infrastructure_or_policy_error": 0, "claimed_without_terminal_outcome": 1,
            "unattempted": 1, "invalid_evidence": 0, "native_successes": 1, "native_failures": 0})
        self.assertEqual((report["cases"][0]["controls"], report["cases"][0]["decisions"]), (1, 1))
        self.assertFalse(any(p.startswith("case-001/") for p in report["read_file_sha256"]))
        self.assertIsNone(report["cases"][0]["first_success_control"])  # smoke has no native field
        self.assertEqual((report["cases"][2]["decision_limit"], report["cases"][2]["control_limit"],
                          report["cases"][2]["replan_prefix"]), (2, 10, 5))

    def test_failure_is_completed_not_error_or_removed(self):
        self.prepare(StopPolicy())
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["native_failures"], 1)
        row = report["cases"][0]
        self.assertEqual((row["controls"], row["decisions"], row["termination_reason"]), (0, 1, "policy:give_up"))
        self.assertEqual(row["record_consistency"], "passed")

    def test_error_retains_started_decision(self):
        self.prepare(BrokenPolicy())
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["infrastructure_or_policy_error"], 1)
        self.assertEqual(report["cases"][0]["decisions"], 1)
        self.assertIsNone(report["cases"][0]["native_final_success"])

    def test_terminal_error_without_run_is_retained(self):
        self.prepare()
        directory = self.campaign / "case-002"
        directory.mkdir()
        digest = hashlib.sha256((self.campaign / "campaign.json").read_bytes()).hexdigest()
        self.save(directory / "attempt.json", {"case_index": 2, "attempt": 1, "campaign_sha256": digest})
        self.save(directory / "outcome.json", {"case_index": 2, "status": "infrastructure_or_policy_error"})
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["infrastructure_or_policy_error"], 1)
        self.assertEqual(report["cases"][2]["record_consistency"], "unavailable")

    def test_forged_summary_does_not_promote_success(self):
        self.prepare(StopPolicy())
        self.outcome["summary"]["successes"] = 1
        self.save(self.campaign / "case-000/outcome.json", self.outcome)
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["invalid_evidence"], 1)
        self.assertEqual(report["counts"]["native_successes"], 0)
        self.assertEqual(report["counts"]["planned"], 3)

    def test_wrong_shape_terminal_status_keeps_full_denominator(self):
        run = self.prepare()
        for wrong in (None, [], 42, "closed"):
            with self.subTest(wrong=wrong):
                self.save(run / "status.json", wrong)
                report = reporting.summarize(self.campaign)
                self.assertEqual(report["counts"]["planned"], 3)
                self.assertEqual(report["counts"]["invalid_evidence"], 1)
                self.assertIsNone(report["cases"][0]["native_final_success"])
                self.assertIn("JSON object", report["cases"][0]["issue"])

    def test_nested_wrong_shape_is_invalid_not_an_aborted_snapshot(self):
        run = self.prepare()
        result_path = next((run / "episodes").glob("*/result.json"))
        result = json.loads(result_path.read_text())
        result["metrics"] = []
        self.save(result_path, result)
        self.save(run / "episodes.jsonl", result)
        event_path = result_path.parent / "events.jsonl"
        events = [json.loads(line) for line in event_path.read_text().splitlines()]
        events[-1]["result"] = result
        event_path.write_text("\n".join(json.dumps(event) for event in events))
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["planned"], 3)
        self.assertEqual(report["counts"]["invalid_evidence"], 1)
        self.assertIn("AttributeError", report["cases"][0]["issue"])

    def test_wrong_frozen_episode_is_invalid(self):
        self.prepare()
        self.manifest["cases"][0]["episode"]["task"] = "different"
        self.freeze()
        self.assertEqual(reporting.summarize(self.campaign)["cases"][0]["attempt_status"], "invalid_evidence")

    def test_manifest_digest_tamper_rejected(self):
        self.prepare()
        self.manifest["max_steps"] = 500
        self.save(self.campaign / "campaign.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "digest"):
            reporting.summarize(self.campaign)

    def test_protocol_descriptor_mismatch_is_invalid(self):
        self.prepare()
        self.manifest["cases"][0]["descriptor"]["protocol_version"] = "different-track"
        self.freeze()
        self.assertIn("descriptor mismatch", reporting.summarize(self.campaign)["cases"][0]["issue"])

    def test_reference_horizon_alias_on_unattempted_row(self):
        self.prepare()
        self.manifest["cases"][2]["episode"] = {"task": "future-task", "metadata": {
            "reference_native_horizon": 400, "native_engine_horizon": 1000}}
        self.freeze()
        row = reporting.summarize(self.campaign)["cases"][2]
        self.assertEqual(row["reference_horizon"], 400)
        self.assertIsNone(row["reference_horizon_source"])
        del self.manifest["cases"][2]["episode"]["metadata"]["reference_native_horizon"]
        self.freeze()
        self.assertIsNone(reporting.summarize(self.campaign)["cases"][2]["reference_horizon"])

    def test_frozen_budget_mismatch_is_invalid(self):
        self.prepare()
        self.manifest["max_steps"] = 500
        self.freeze()
        self.assertIn("max_steps", reporting.summarize(self.campaign)["cases"][0]["issue"])

    def test_substituted_diagnostic_is_invalid_and_original_records_are_unchanged(self):
        run = self.prepare(ConstantPolicy([0.0], chunk_length=1))
        self.manifest["policy"] = {"name": "code-agent-development", "kind": "external-code-agent",
                                   "model": None, "provider": None}
        self.freeze()
        before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["planned"], 3)
        self.assertEqual(report["counts"]["invalid_evidence"], 1)
        self.assertEqual((report["counts"]["native_successes"], report["counts"]["native_failures"]), (0, 0))
        self.assertIn("policy name mismatch", report["cases"][0]["issue"])
        self.assertEqual(before, {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()})

    def test_matching_constant_diagnostic_campaign_has_no_participant_coverage_counts(self):
        # The fixed action reaches the tiny smoke fixture's seed-zero target.
        run = self.prepare(ConstantPolicy([0.55], chunk_length=1))
        self.assertEqual(self.outcome["summary"]["successes"], 1)
        self.manifest["policy"] = json.loads((run / "manifest.json").read_text())["policy"]
        self.freeze()
        before = {path.relative_to(self.campaign): path.read_bytes()
                  for path in self.campaign.rglob("*") if path.is_file()}
        with patch.object(reporting, "closed_case") as inspect_case:
            with self.assertRaisesRegex(ValueError, "does not accept infrastructure diagnostic campaigns"):
                reporting.summarize(self.campaign)
            inspect_case.assert_not_called()
        self.assertEqual(before, {path.relative_to(self.campaign): path.read_bytes()
                                 for path in self.campaign.rglob("*") if path.is_file()})

    def test_campaign_diagnostic_purpose_is_rejected_at_either_declared_location(self):
        self.prepare()
        original = deepcopy(self.manifest)
        for location in ("manifest", "parameters"):
            with self.subTest(location=location):
                self.manifest = deepcopy(original)
                target = (self.manifest if location == "manifest"
                          else self.manifest["policy"].setdefault("parameters", {}))
                target["purpose"] = "infrastructure_validation_only"
                self.freeze()
                with self.assertRaisesRegex(ValueError, "does not accept infrastructure diagnostic campaigns"):
                    reporting.summarize(self.campaign)

    def test_top_level_run_diagnostic_purpose_is_invalid_within_participant_denominator(self):
        run = self.prepare()
        self.assertEqual(self.outcome["summary"]["successes"], 1)
        source = json.loads((run / "manifest.json").read_text())
        source["purpose"] = "infrastructure_validation_only"
        self.save(run / "manifest.json", source)
        before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["planned"], 3)
        self.assertEqual(report["counts"]["invalid_evidence"], 1)
        self.assertEqual((report["counts"]["native_successes"], report["counts"]["native_failures"]), (0, 0))
        self.assertIsNone(report["cases"][0]["native_final_success"])
        self.assertIn("diagnostic run cannot count", report["cases"][0]["issue"])
        self.assertEqual(before, {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()})

    def test_wrong_or_missing_policy_identity_never_counts_as_campaign_success(self):
        run = self.prepare()
        source = json.loads((run / "manifest.json").read_text())
        for change in ({"name": "different-agent"}, {"kind": "different-kind"},
                       {"model": "other-model"}, {"provider": "other-provider"}, None):
            with self.subTest(change=change):
                altered = deepcopy(source)
                if change is None:
                    altered.pop("policy")
                else:
                    altered["policy"].update(change)
                self.save(run / "manifest.json", altered)
                report = reporting.summarize(self.campaign)
                self.assertEqual(report["counts"]["planned"], 3)
                self.assertEqual(report["counts"]["invalid_evidence"], 1)
                self.assertEqual(report["counts"]["native_successes"], 0)

    def test_declared_prompt_mismatch_retains_invalid_evidence_in_denominator(self):
        run = self.prepare()
        source = json.loads((run / "manifest.json").read_text())
        self.manifest["policy_prompt"] = "Frozen campaign prompt."
        self.manifest["policy_prompt_sha256"] = hashlib.sha256(self.manifest["policy_prompt"].encode()).hexdigest()
        source["policy"]["parameters"]["prompt_sha256"] = "0" * 64
        self.save(run / "manifest.json", source)
        self.freeze()
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["planned"], 3)
        self.assertEqual(report["counts"]["invalid_evidence"], 1)
        self.assertEqual(report["counts"]["native_successes"], 0)
        self.assertIn("policy prompt mismatch", report["cases"][0]["issue"])

    def test_current_profile_prompt_and_stop_bindings_match_then_reject_substitution(self):
        from benchkit.model_profiles import create_policy

        declared = create_policy("anonymous_code_agent", directory=self.root / "mailbox-fixture",
                                 prompt="Frozen profile prompt.", min_action_decisions_before_give_up=50)
        policy = ScriptedReachPolicy()
        policy.descriptor, policy.prompt = declared.descriptor, declared.prompt
        self.prepare(policy)
        parameters = declared.descriptor.parameters
        self.manifest.update(schema_version="starvla-rsi.campaign/v3",
            model_profile=deepcopy(parameters["model_profile"]), policy_prompt=declared.prompt,
            policy_prompt_sha256=parameters["prompt_sha256"],
            policy_stop_rule=deepcopy(parameters["policy_stop_rule"]),
            policy_parameters={"min_action_decisions_before_give_up": 50})
        self.freeze()
        self.assertEqual(reporting.summarize(self.campaign)["counts"]["native_successes"], 1)
        original = deepcopy(self.manifest)
        changes = (
            ("profile", lambda doc: doc["model_profile"].update(id="different_agent")),
            ("profile source", lambda doc: doc["model_profile"].update(config_sha256="0" * 64)),
            ("missing profile", lambda doc: doc.pop("model_profile")),
            ("prompt digest", lambda doc: doc.update(policy_prompt_sha256="0" * 64)),
            ("stop rule", lambda doc: doc["policy_stop_rule"].update(min_action_decisions_before_give_up=0)),
            ("missing stop rule", lambda doc: doc.pop("policy_stop_rule")),
            ("stop setting", lambda doc: doc["policy_parameters"].update(min_action_decisions_before_give_up=0)),
            ("typed setting", lambda doc: doc["policy_parameters"].update(min_action_decisions_before_give_up=50.0)),
        )
        for label, change in changes:
            with self.subTest(label=label):
                self.manifest = deepcopy(original)
                change(self.manifest)
                self.freeze()
                report = reporting.summarize(self.campaign)
                self.assertEqual(report["counts"]["planned"], 3)
                self.assertEqual(report["counts"]["invalid_evidence"], 1)
                self.assertEqual(report["counts"]["native_successes"], 0)
                self.assertIn("campaign", report["cases"][0]["issue"])

    def test_matching_historical_optional_fields_and_protocol_stopping_remain_supported(self):
        source = {"policy": {"name": "historical-agent", "kind": "external-code-agent",
                             "model": None, "provider": None, "version": "historical-transport",
                             "parameters": {"prompt_sha256": hashlib.sha256(b"Historical prompt.").hexdigest()}},
                  "protocol": {}}
        manifest = {"policy": {"name": "historical-agent", "kind": "external-code-agent"},
                    "policy_prompt": "Historical prompt."}
        reporting.bind_policy(source, manifest)
        manifest["min_action_decisions_before_give_up"] = 0
        reporting.bind_policy(source, manifest)
        legacy_rule = {"min_action_decisions_before_give_up": 50,
                       "stop_constraint_version": "minimum-action-decisions/v1",
                       "early_policy_stop_exception": "safety_stop_with_nonempty_note"}
        manifest.update(legacy_rule)
        source["protocol"].update(legacy_rule)
        reporting.bind_policy(source, manifest)
        source["protocol"]["min_action_decisions_before_give_up"] = 1
        with self.assertRaisesRegex(ValueError, "historical policy configuration"):
            reporting.bind_policy(source, manifest)

    def test_diagnostic_purpose_cannot_be_added_to_matching_agent_identity(self):
        run = self.prepare()
        source = json.loads((run / "manifest.json").read_text())
        source["policy"]["parameters"]["purpose"] = "infrastructure_validation_only"
        self.save(run / "manifest.json", source)
        report = reporting.summarize(self.campaign)
        self.assertEqual(report["counts"]["invalid_evidence"], 1)
        self.assertEqual(report["counts"]["native_successes"], 0)
        self.assertIn("diagnostic purpose mismatch", report["cases"][0]["issue"])

    def test_unsafe_case_identity_rejected(self):
        self.prepare()
        self.manifest["cases"][2]["case_id"] = "../outside"
        self.freeze()
        with self.assertRaisesRegex(ValueError, "case identity"):
            reporting.summarize(self.campaign)

    def test_unplanned_case_is_not_silently_dropped(self):
        self.prepare()
        (self.campaign / "case-099").mkdir()
        with self.assertRaisesRegex(ValueError, "unplanned case"):
            reporting.summarize(self.campaign)

    def test_symlink_claim_is_invalid_without_reading_target(self):
        self.prepare()
        (self.campaign / "case-002").symlink_to(self.root, target_is_directory=True)
        self.assertEqual(reporting.summarize(self.campaign)["counts"]["invalid_evidence"], 1)

    def test_snapshot_is_new_outside_source_and_csv_preserves_null(self):
        self.prepare()
        report = reporting.summarize(self.campaign)
        with self.assertRaisesRegex(ValueError, "outside"):
            reporting.write_snapshot(report, self.campaign / "report")
        output = self.root / "snapshot"
        reporting.write_snapshot(report, output)
        with self.assertRaises(FileExistsError):
            reporting.write_snapshot(report, output)
        with (output / "tasks.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]["native_final_success"], "null")
        self.assertEqual(rows[0]["native_final_success"], "true")
        self.assertEqual(reporting.csv_value(" =1+1"), "' =1+1")

    def caveat_document(self):
        return {"schema_version": "starvla-rsi.evidence-caveats/v1",
                "campaign_sha256": hashlib.sha256((self.campaign / "campaign.json").read_bytes()).hexdigest(),
                "entries": [{"case_index": 0, "category": "rendering_defect",
                    "note": "Native foreground is unusable; retain the original result.",
                    "declared_evidence": [{"reference": "not-read/review.md", "sha256": "a" * 64}]}]}

    def annotated_report(self, document):
        path = self.root / "caveats.json"
        self.save(path, document)
        return reporting.summarize(self.campaign, path)

    def test_caveat_preserves_native_failure_counters_and_denominator(self):
        self.prepare(StopPolicy())
        original = reporting.summarize(self.campaign)
        report = self.annotated_report(self.caveat_document())
        self.assertEqual(report["counts"], original["counts"])
        self.assertEqual(report["read_file_sha256"], original["read_file_sha256"])
        for before, after in zip(original["cases"], report["cases"]):
            for key in before:
                if key != "evidence_caveats":
                    self.assertEqual(after[key], before[key])
        self.assertIs(report["cases"][0]["native_final_success"], False)
        self.assertEqual(report["caveat_source"]["annotated_cases"], 1)
        self.assertEqual(report["caveat_source"]["sha256"], hashlib.sha256((self.root / "caveats.json").read_bytes()).hexdigest())
        output = self.root / "annotated"
        reporting.write_snapshot(report, output)
        with (output / "tasks.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["native_final_success"], "false")
        self.assertEqual(json.loads(rows[0]["evidence_caveats"]), report["cases"][0]["evidence_caveats"])
        self.assertEqual(rows[2]["evidence_caveats"], "[]")

    def test_caveat_cannot_rewrite_score_or_target_wrong_campaign(self):
        self.prepare()
        document = self.caveat_document()
        document["campaign_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "campaign mismatch"):
            self.annotated_report(document)
        document = self.caveat_document()
        document["entries"][0]["native_final_success"] = True
        with self.assertRaisesRegex(ValueError, "entry fields"):
            self.annotated_report(document)

    def test_active_unattempted_and_invalid_case_caveats_are_rejected(self):
        run = self.prepare()
        for index in (1, 2):
            document = self.caveat_document()
            document["entries"][0]["case_index"] = index
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "terminal outcome"):
                self.annotated_report(document)
        self.save(run / "status.json", None)
        with self.assertRaisesRegex(ValueError, "terminal outcome"):
            self.annotated_report(self.caveat_document())

    def test_caveat_indices_duplicates_and_fields_are_strict(self):
        self.prepare()
        for index in (-1, 3, True, 0.0, "0"):
            document = self.caveat_document()
            document["entries"][0]["case_index"] = index
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "case index"):
                self.annotated_report(document)
        document = self.caveat_document()
        document["entries"].append(document["entries"][0].copy())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.annotated_report(document)
        for key, value in (("category", "=1+1"), ("note", " "), ("declared_evidence", [])):
            document = self.caveat_document()
            document["entries"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.annotated_report(document)

    def test_caveat_source_is_external_plain_strict_json(self):
        self.prepare()
        inside = self.campaign / "caveats.json"
        self.save(inside, self.caveat_document())
        with self.assertRaisesRegex(ValueError, "outside campaign"):
            reporting.summarize(self.campaign, inside)
        outside = self.root / "caveats.json"
        outside.symlink_to(inside)
        with self.assertRaises(ValueError):
            reporting.summarize(self.campaign, outside)
        bad = self.root / "bad.json"
        for payload in ('{"entries":[],"entries":[]}', '{"entries":NaN}', 'null'):
            bad.write_text(payload)
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                reporting.summarize(self.campaign, bad)

    def test_caveat_source_change_is_rejected(self):
        self.prepare()
        original = reporting.audit.ClosedFiles.verify_unchanged

        def change_then_verify(files):
            if "caveats.json" in files.hashes:
                (files.root / "caveats.json").write_text("{}")
            original(files)

        with patch.object(reporting.audit.ClosedFiles, "verify_unchanged", change_then_verify):
            with self.assertRaisesRegex(ValueError, "changed during audit"):
                self.annotated_report(self.caveat_document())

    def test_caveat_nested_fields_and_size_are_bounded(self):
        self.prepare()
        for item in (None, [], {}, {"reference": "x", "sha256": "A" * 64},
                     {"reference": "x" + " " * 512, "sha256": "a" * 64}):
            document = self.caveat_document()
            document["entries"][0]["declared_evidence"] = [item]
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.annotated_report(document)
        document = self.caveat_document()
        document["entries"][0]["note"] = "x" + " " * 2048
        with self.assertRaisesRegex(ValueError, "note"):
            self.annotated_report(document)
        document = self.caveat_document()
        document["entries"] = [dict(document["entries"][0], category=f"note_{i}") for i in range(17)]
        with self.assertRaisesRegex(ValueError, "too many caveats"):
            self.annotated_report(document)
        source = self.root / "oversized.json"
        source.write_text(" " * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "exceeds 1 MiB"):
            reporting.summarize(self.campaign, source)

    def test_caveat_does_not_promote_unknown_error_or_follow_references(self):
        self.prepare(BrokenPolicy())
        report = self.annotated_report(self.caveat_document())
        self.assertIsNone(report["cases"][0]["native_final_success"])
        self.assertEqual(report["counts"]["infrastructure_or_policy_error"], 1)
        self.assertEqual(report["caveat_source"]["entries"], 1)
        self.assertFalse((self.root / "not-read").exists())

    def test_caveat_lone_surrogates_rejected_before_output_but_unicode_roundtrips(self):
        self.prepare()
        output = self.root / "unicode-output"
        for field, text in (("note", "bad\ud800"), ("reference", "bad\udfff")):
            document = self.caveat_document()
            target = document["entries"][0]
            if field == "reference":
                target = target["declared_evidence"][0]
            target[field] = text
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"invalid.*{field}"):
                reporting.write_snapshot(self.annotated_report(document), output)
            self.assertFalse(output.exists())
        document = self.caveat_document()
        document["entries"][0]["note"] = "渲染异常 🤖"
        document["entries"][0]["declared_evidence"][0]["reference"] = "复核/图像.png"
        report = self.annotated_report(document)
        reporting.write_snapshot(report, output)
        with (output / "tasks.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(json.loads(rows[0]["evidence_caveats"]), report["cases"][0]["evidence_caveats"])


if __name__ == "__main__":
    unittest.main()
