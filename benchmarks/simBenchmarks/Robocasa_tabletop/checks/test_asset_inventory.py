"""Dependency-free checks for complete reused-asset inventory verification."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "environment" / "inventory_assets.py"
SPEC = importlib.util.spec_from_file_location("tabletop_asset_inventory", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AssetInventoryChecks(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for registry in ("objaverse", "sketchfab", "lightwheel"):
            (root / registry).mkdir()
            (root / registry / "model.xml").write_bytes(b"original")
        return root

    def test_all_three_registries_are_required(self):
        root = self.fixture()
        (root / "lightwheel").rename(root / "missing")
        with self.assertRaisesRegex(RuntimeError, "missing registry"):
            MODULE.inventory(root)

    def test_same_size_changes_are_detected_by_content_hash(self):
        root = self.fixture()
        original = MODULE.inventory(root)
        (root / "objaverse" / "model.xml").write_bytes(b"modified")
        altered = MODULE.inventory(root)
        self.assertEqual(original["total_regular_bytes"], altered["total_regular_bytes"])
        self.assertNotEqual(original["inventory_sha256"], altered["inventory_sha256"])

    def test_symlink_targets_are_recorded_without_following_them(self):
        root = self.fixture()
        (root / "objaverse" / "external").symlink_to("/unavailable/read-only/asset")
        inventory = MODULE.inventory(root)
        self.assertEqual(inventory["file_count"], 4)
        self.assertEqual(inventory["files"]["objaverse/external"]["kind"], "symlink")
        self.assertEqual(inventory["total_regular_bytes"], 24)

    def test_missing_and_extra_paths_fail_comparison(self):
        root = self.fixture()
        reference = root / "reference.json"
        reference.write_text(json.dumps(MODULE.inventory(root)))
        (root / "objaverse" / "model.xml").rename(root / "objaverse" / "renamed.xml")
        result = root / "result.json"
        process = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(root), "--reference", str(reference),
             "--output", str(result)], capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 1)
        comparison = json.loads(result.read_text())["comparison"]
        self.assertFalse(comparison["matches"])
        self.assertEqual(comparison["difference_count"], 2)


if __name__ == "__main__":
    unittest.main()
