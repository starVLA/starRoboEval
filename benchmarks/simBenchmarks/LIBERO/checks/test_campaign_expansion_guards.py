"""Launch guard regressions using temporary source snapshots, never a simulator."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchkit.campaigns.workflow import digest, prepare, run_case, verify_frozen_package


class CampaignExpansionGuardChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def make_campaign(self, benchmark="robocasa365", **kwargs):
        output = self.root / benchmark
        manifest = prepare(output, benchmark, self.root / "unused-public", "Synthetic guard-test prompt.", **kwargs)
        return output, manifest

    def assert_no_claim(self, output):
        self.assertFalse(any(output.glob("case-*")))

    def save_manifest(self, output, manifest):
        (output / "campaign.json").write_text(json.dumps(manifest))
        (output / "campaign_digest.json").write_text(json.dumps({"sha256": digest(output / "campaign.json")}))

    def test_each_remaining_expansion_marker_requires_scope_and_ledger(self):
        for benchmark in ("robocasa365", "simple_humanoid"):
            output, original = self.make_campaign(benchmark)
            markers = {"selected_total": 50, "carried_attempts": 2, "planned_new_cases": 48,
                       "coverage_reporting": "executable cases only", "purpose": "development_task_coverage"}
            for key, value in markers.items():
                with self.subTest(benchmark=benchmark, marker=key):
                    manifest = copy.deepcopy(original)
                    manifest[key] = value
                    self.save_manifest(output, manifest)
                    with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                        with self.assertRaisesRegex(ValueError, "expansion markers require"):
                            run_case(output, 0, 0)
                        launch.assert_not_called()
                    self.assert_no_claim(output)

    def test_stripped_scope_fields_cannot_reclassify_expansion_as_pilot(self):
        for benchmark, scope in (("robocasa365", "target50"), ("simple_humanoid", "released-12")):
            output, manifest = self.make_campaign(benchmark, task_scope=scope)
            manifest.pop("task_scope")
            manifest.pop("coverage_ledger")
            for case in manifest["cases"]:
                case["benchmark_args"].pop("task_scope")
                case["episode"]["metadata"].pop("task_scope")
            self.save_manifest(output, manifest)
            with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                with self.assertRaisesRegex(ValueError, "expansion markers require"):
                    run_case(output, 0, 0)
                launch.assert_not_called()
            self.assert_no_claim(output)

    def test_original_pilots_and_existing_coverage_purposes_keep_launch_path(self):
        for benchmark in ("robocasa365", "simple_humanoid", "libero", "simpler_env"):
            output, manifest = self.make_campaign(benchmark)
            self.assertFalse(any(key in manifest for key in ("task_scope", "coverage_ledger", "selected_total")))
            with patch("benchkit.campaigns.workflow.subprocess.Popen", side_effect=OSError("synthetic launch intercepted")) as launch:
                with self.assertRaisesRegex(OSError, "synthetic launch intercepted"):
                    run_case(output, 0, 0)
                launch.assert_called_once()
            self.assertTrue((output / "case-000/attempt.json").is_file())

    def test_symlinked_frozen_roots_ancestors_index_and_initializers_rejected(self):
        output, manifest = self.make_campaign("simple_humanoid", task_scope="released-12")
        paths = ("frozen", "frozen/AgentPolicies", "frozen/benchkit",
                 "harness_source", "harness_source/index.json", "frozen/AgentPolicies/__init__.py",
                 "frozen/benchmarks", "frozen/benchmarks/simBenchmarks/SIMPLE/environment")
        for index, relative in enumerate(paths):
            with self.subTest(path=relative):
                original = output / relative
                saved = self.root / f"saved-{index}"
                original.rename(saved)
                original.symlink_to(saved, target_is_directory=saved.is_dir())
                try:
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        verify_frozen_package(output, manifest)
                    with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                        with self.assertRaisesRegex(ValueError, "symlink"):
                            run_case(output, 0, 0)
                        launch.assert_not_called()
                    self.assert_no_claim(output)
                finally:
                    original.unlink()
                    saved.rename(original)
        verify_frozen_package(output, manifest)

    def test_campaign_root_symlink_rejected_before_resolve_or_manifest_read(self):
        output, manifest = self.make_campaign()
        alias = self.root / "campaign-alias"
        alias.symlink_to(output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "campaign root"):
            verify_frozen_package(alias, manifest)
        with patch("benchkit.campaigns.workflow.load_campaign") as load:
            with self.assertRaisesRegex(ValueError, "campaign root"):
                run_case(alias, 0, 0)
            load.assert_not_called()
        self.assert_no_claim(output)

    def test_source_index_link_rejected_before_digest_reads_its_target(self):
        output, manifest = self.make_campaign()
        original = output / "harness_source/index.json"
        saved = self.root / "saved-index.json"
        original.rename(saved)
        original.symlink_to(saved)
        with patch("benchkit.campaigns.workflow.digest") as hash_file:
            with self.assertRaisesRegex(ValueError, "symlink"):
                verify_frozen_package(output, manifest)
            hash_file.assert_not_called()
        self.assert_no_claim(output)


if __name__ == "__main__":
    unittest.main()
