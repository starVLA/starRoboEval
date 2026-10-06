"""Select immutable ledger helper layouts as data; no execution of frozen code."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchkit.reports.task_ledger import audit, frozen_helper_names


CURRENT = ("benchkit.campaigns.workflow", "benchkit.reports.campaign_coverage")
HISTORICAL = ("harness.campaigns.workflow", "harness.reports.campaign_coverage")
FLAT = ("harness.campaign", "harness.campaign_coverage")


class FrozenLedgerLayoutChecks(unittest.TestCase):
    def fixture(self, names):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rows = []
        for name in names:
            relative = name.replace(".", "/") + ".py"
            payload = b"# Immutable fixture bytes; do not execute.\n"
            path = root / "frozen" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            rows.append({"path": relative, "size_bytes": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()})
        (root / "harness_source").mkdir()
        index = json.dumps({"schema_version": "starvla-rsi.harness-source/v2", "files": rows}).encode()
        (root / "harness_source/index.json").write_bytes(index)
        manifest = {"schema_version": "starvla-rsi.campaign/v3", "harness_source": {
            "path": "harness_source/index.json",
            "index_sha256": hashlib.sha256(index).hexdigest()}}
        if any(name.startswith("benchkit.") for name in names):
            manifest["runtime_namespace"] = "benchkit"
        return root, manifest

    def test_grouped_and_historical_flat_v3_follow_captured_inventory(self):
        for names in (CURRENT, HISTORICAL, FLAT):
            with self.subTest(names=names):
                root, manifest = self.fixture(names)
                files = audit.ClosedFiles(root)
                self.assertEqual(frozen_helper_names(files, manifest), names)
                self.assertEqual(len(files.hashes), 3)
                files.verify_unchanged()

    def test_original_v1_v2_keep_original_namespace(self):
        for version in (1, 2):
            self.assertEqual(frozen_helper_names(None, {"schema_version": f"starvla-rsi.campaign/v{version}"}),
                             ("starVLA.evaluation.campaign", "starVLA.evaluation.campaign_coverage"))

    def test_missing_half_mixed_and_ambiguous_layouts_rejected(self):
        for names in ((), CURRENT[:1], (FLAT[0], CURRENT[1]), CURRENT + FLAT, CURRENT + FLAT[:1],
                      CURRENT + HISTORICAL, HISTORICAL + FLAT):
            with self.subTest(names=names):
                root, manifest = self.fixture(names)
                with self.assertRaisesRegex(ValueError, "helper layout"):
                    frozen_helper_names(audit.ClosedFiles(root), manifest)

    def test_runtime_marker_cannot_relabel_frozen_helpers(self):
        for names, namespace in ((CURRENT, "harness"), (HISTORICAL, "benchkit"), (FLAT, "benchkit"),
                                 (CURRENT, None), (CURRENT, "unknown")):
            with self.subTest(names=names, namespace=namespace):
                root, manifest = self.fixture(names)
                manifest["runtime_namespace"] = namespace
                with self.assertRaisesRegex(ValueError, "runtime namespace"):
                    frozen_helper_names(audit.ClosedFiles(root), manifest)

    def test_mutated_index_or_helper_fails_before_import(self):
        for relative in ("harness_source/index.json", "frozen/benchkit/campaigns/workflow.py"):
            with self.subTest(relative=relative):
                root, manifest = self.fixture(CURRENT)
                path = root / relative
                path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaisesRegex(ValueError, "digest mismatch|changed before import"):
                    frozen_helper_names(audit.ClosedFiles(root), manifest)

    def test_source_path_and_index_schema_are_not_guessed(self):
        root, manifest = self.fixture(CURRENT)
        manifest["harness_source"]["path"] = "arbitrary.json"
        with self.assertRaisesRegex(ValueError, "source layout"):
            frozen_helper_names(audit.ClosedFiles(root), manifest)
        manifest["harness_source"]["path"] = "harness_source/index.json"
        path = root / "harness_source/index.json"
        index = json.loads(path.read_text())
        index["schema_version"] = "starvla-rsi.harness-source/v999"
        payload = json.dumps(index).encode()
        path.write_bytes(payload)
        manifest["harness_source"]["index_sha256"] = hashlib.sha256(payload).hexdigest()
        with self.assertRaisesRegex(ValueError, "index schema"):
            frozen_helper_names(audit.ClosedFiles(root), manifest)


if __name__ == "__main__":
    unittest.main()
