"""Coordinator checks; no simulator, policy inference, or scored attempts."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from benchkit.campaigns.workflow import (cases_for, digest, load_campaign, prepare, run_case,
    runtime_namespace, summarize, verify_frozen_package, _preflight_case_policy)


class CampaignChecks(unittest.TestCase):
    def test_full_denominators_and_no_duplicate_tasks(self):
        for benchmark, count in (("libero", 130), ("simpler_env", 15), ("robocasa365", 2),
                                 ("simple_humanoid", 2), ("robocasa_tabletop", 2)):
            cases = cases_for(benchmark, 200, 5)
            self.assertEqual(len(cases), count)
            self.assertEqual(len({case["episode"]["task"] for case in cases}), count)
            self.assertTrue(all(case["attempts"] == 1 for case in cases))
            self.assertTrue(all(case["episode"]["metadata"]["environment_step_cap"] == 1000 for case in cases))

    def test_invalid_budget_does_not_create_a_campaign(self):
        for value in (True, 0, -1, 1.5, "200", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cases_for("libero", value, 5)

    def test_freeze_is_executable_without_native_imports_and_all_entries_start_unattempted(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            manifest = prepare(output, "libero", Path(temporary) / "public", "Use only current RGB and action_spec.")
            verify_frozen_package(output, manifest)
            self.assertEqual(manifest["runtime_namespace"], "benchkit")
            self.assertEqual(summarize(output)["unattempted"], 130)
            self.assertEqual(manifest["policy"]["model"], None)
            endpoints = [case["policy_endpoint"] for case in manifest["cases"]]
            self.assertEqual(len(set(endpoints)), 130)
            self.assertTrue(all(Path(path).name.startswith("mbx-") for path in endpoints))
            self.assertTrue(all(not Path(path).exists() for path in endpoints))
            completed = subprocess.run([sys.executable, "-m", "benchkit", "list", "--json"],
                cwd=output / "frozen", env={**os.environ, "PYTHONPATH": str(output / "frozen"),
                                          "PYTHONDONTWRITEBYTECODE": "1"},
                check=True, capture_output=True, text=True, timeout=30)
            self.assertIn("libero", json.loads(completed.stdout)["benchmarks"])
            with self.assertRaises(FileExistsError):
                prepare(output, "libero", Path(temporary) / "public", "prompt")

    def test_changed_manifest_and_changed_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            manifest = prepare(output, "simpler_env", Path(temporary) / "public", "Use RGB.")
            path = output / "frozen/benchkit/campaigns/workflow.py"
            path.write_text(path.read_text() + "\n# modified\n")
            with self.assertRaises(ValueError):
                verify_frozen_package(output, manifest)
            with self.assertRaises(ValueError):
                run_case(output, 0, 0)
            self.assertFalse((output / "case-000").exists())
            path = output / "campaign.json"
            path.write_text(path.read_text() + "\n")
            with self.assertRaises(ValueError):
                load_campaign(output)

    def test_launch_failure_is_retained_and_never_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            prepare(output, "libero", Path(temporary) / "public", "Use RGB.")
            with patch("benchkit.campaigns.workflow.subprocess.Popen", side_effect=OSError("launch failed")):
                with self.assertRaises(OSError):
                    run_case(output, 0, 0)
            result = json.loads((output / "case-000/outcome.json").read_text())
            self.assertEqual(result["status"], "infrastructure_or_policy_error")
            self.assertEqual(result["error"]["type"], "OSError")
            with self.assertRaises(FileExistsError):
                run_case(output, 0, 0)
            report = summarize(output)
            self.assertEqual(report["unattempted"], 129)
            self.assertEqual(report["planned"], 130)
            self.assertEqual(report["completed"], 0)
            self.assertEqual(report["infrastructure_or_policy_error"], 1)
            self.assertEqual(report["claimed_without_terminal_outcome"], 0)
            self.assertEqual(report["other_status"], 0)

    def test_summary_counts_every_declared_state_without_reading_active_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            prepare(output, "simpler_env", Path(temporary) / "public", "Use RGB.")
            states = ("completed", "infrastructure_or_policy_error", None, "unexpected_status")
            for index, status in enumerate(states):
                directory = output / f"case-{index:03d}"
                directory.mkdir()
                (directory / "run").mkdir()
                (directory / "run/status.json").write_text("deliberately not JSON")
                if status is not None:
                    (directory / "outcome.json").write_text(json.dumps({"status": status}))
            report = summarize(output)
            self.assertEqual(report["planned"], 15)
            self.assertEqual(report["unattempted"], 11)
            for name in ("completed", "infrastructure_or_policy_error",
                         "claimed_without_terminal_outcome", "other_status"):
                self.assertEqual(report[name], 1)
            self.assertEqual(sum(value for key, value in report.items()
                                 if key not in ("planned", "outcomes")), report["planned"])
            self.assertEqual(report["outcomes"][3]["status"], "unexpected_status")
            self.assertFalse(any("success" in row for row in report["outcomes"]))

    def test_simple_freezes_private_worker_pins_and_public_guide(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            manifest = prepare(output, "simple_humanoid", Path(temporary) / "public", "Use declared sensors.")
            verify_frozen_package(output, manifest)
            self.assertEqual(manifest["purpose"], "development_pilot")
            from benchmarks.simBenchmarks.SIMPLE.bench_server.source_inventory import CAMPAIGN_SUPPLEMENTAL_FILES
            self.assertEqual({row["path"] for row in manifest["supplemental_runtime_files"]},
                             set(CAMPAIGN_SUPPLEMENTAL_FILES))
            worker = output / "frozen/benchmarks/simBenchmarks/SIMPLE/environment/native_worker.py"
            self.assertTrue(worker.is_file())
            guide = (worker.parents[1] / "bench_server/protocol/POLICY_GUIDE.md").read_text()
            self.assertTrue(manifest["policy_prompt"].endswith(guide))
            worker.write_text(worker.read_text() + "\n# changed\n")
            with self.assertRaisesRegex(ValueError, "supplemental runtime changed"):
                verify_frozen_package(output, manifest)
            self.assertEqual(summarize(output)["unattempted"], 2)

    def test_unlisted_supplemental_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            manifest = prepare(output, "libero", Path(temporary) / "public", "Use RGB.")
            (output / "frozen/extra.py").write_text("# accidental import source\n")
            with self.assertRaisesRegex(ValueError, "supplemental runtime inventory"):
                verify_frozen_package(output, manifest)

    def test_tabletop_freezes_hash_seed_and_only_public_guide(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            manifest = prepare(output, "robocasa_tabletop", Path(temporary) / "public", "Use declared sensors.")
            verify_frozen_package(output, manifest)
            self.assertEqual(manifest["runtime_environment"], {"PYTHONHASHSEED": "0"})
            self.assertEqual(len(manifest["supplemental_runtime_files"]), 1)
            self.assertTrue(manifest["supplemental_runtime_files"][0]["path"].endswith("POLICY_GUIDE.md"))
            self.assertEqual([case["episode"]["metadata"]["native_task_index"] for case in manifest["cases"]], [0, 19])

    def test_runtime_namespace_is_explicit_for_new_and_preserved_for_historical_campaigns(self):
        for version, namespace in ((1, "starVLA.evaluation"), (2, "starVLA.evaluation"), (3, "harness")):
            manifest = {"schema_version": f"starvla-rsi.campaign/v{version}"}
            self.assertEqual(runtime_namespace(manifest), namespace)
            if version < 3:
                manifest["runtime_namespace"] = "benchkit"
                with self.assertRaises(ValueError):
                    runtime_namespace(manifest)
        for value in (None, True, "unknown", "starVLA.evaluation", [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime_namespace({"schema_version": "starvla-rsi.campaign/v3", "runtime_namespace": value})

    def test_runtime_marker_must_match_captured_source_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            manifest = prepare(output, "libero", Path(temporary) / "public", "Use RGB.")
            for value in ("harness", None):
                changed = dict(manifest)
                if value is None:
                    del changed["runtime_namespace"]
                else:
                    changed["runtime_namespace"] = value
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "inventory metadata"):
                    verify_frozen_package(output, changed)

    def test_historical_harness_namespace_verified_as_data_without_rewriting_history(self):
        from benchkit.source_snapshot import inventory_digest
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "synthetic-historical-campaign"
            manifest = prepare(output, "libero", Path(temporary) / "public", "Use RGB.")
            # Synthetic file layout only; these renamed fixture bytes are never executed.
            for parent in (output / "frozen", output / "harness_source/files"):
                (parent / "benchkit").rename(parent / "harness")
            path = output / "harness_source/index.json"
            index = json.loads(path.read_text())
            index["package"] = "harness"
            for row in index["files"]:
                if row["path"].startswith("benchkit/"):
                    row["path"] = "harness/" + row["path"][len("benchkit/"):]
            index["inventory_sha256"] = inventory_digest(index["files"])
            path.write_text(json.dumps(index))
            manifest["harness_source"].update(index_sha256=digest(path), inventory_sha256=index["inventory_sha256"])
            del manifest["runtime_namespace"]
            verify_frozen_package(output, manifest)
            manifest["runtime_namespace"] = "benchkit"
            with self.assertRaisesRegex(ValueError, "inventory metadata"):
                verify_frozen_package(output, manifest)

    def test_preflight_uses_the_captured_namespace_and_not_a_compatibility_entrypoint(self):
        for namespace in ("benchkit", "harness"):
            manifest = {"schema_version": "starvla-rsi.campaign/v3", "model_profile": {"id": "gpt6_astra"}}
            if namespace == "benchkit":
                manifest["runtime_namespace"] = namespace
            process = MagicMock()
            process.__enter__.return_value.wait.return_value = 0
            with patch("benchkit.model_profiles.verify_model_source", return_value={"runtime_preflight": True}), \
                 patch("benchkit.campaigns.workflow.subprocess.Popen", return_value=process) as launch:
                self.assertTrue(_preflight_case_policy(Path("/unused-fixture"), manifest, {}, {}))
            self.assertEqual(launch.call_args.args[0][3:5], [namespace, "preflight-policy"])

    def test_auditors_accept_known_grouped_layouts_but_not_mixed_or_aliased_paths(self):
        from benchkit.reports.campaign_coverage import AUDIT_FILES, HISTORICAL_AUDIT_FILES, audit_tools
        for layout in (AUDIT_FILES, *HISTORICAL_AUDIT_FILES):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                for relative in layout:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("FIXTURE_ONLY = True\n")
                self.assertEqual([Path(module.__file__) for module in audit_tools(root)],
                                 [root / relative for relative in layout])
                alternate = next(other for other in (AUDIT_FILES, *HISTORICAL_AUDIT_FILES) if other != layout)
                path = root / alternate[0]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("raise AssertionError('mixed layouts must not execute')\n")
                with self.assertRaisesRegex(ValueError, "auditor layout"):
                    audit_tools(root)
                path.unlink()
                source = root / layout[0]
                source.rename(source.with_suffix(".saved"))
                source.symlink_to(source.with_suffix(".saved"))
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    audit_tools(root)


if __name__ == "__main__":
    unittest.main()
