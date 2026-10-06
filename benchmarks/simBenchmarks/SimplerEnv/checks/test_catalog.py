"""Extensible catalog and evaluation-only directory boundaries; no simulator."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchkit.catalog import CatalogEntry, load_catalog, validate_repository_catalog


class CatalogChecks(unittest.TestCase):
    def test_original_identities_retained_and_simple_added(self):
        original = {"behavior", "domino", "libero", "libero_plus", "metaworld", "robodojo",
                    "robocasa_365", "robocasa_tabletop", "robotwin", "simpler_env", "vla_arena", "vln_ce", "calvin"}
        entries = load_catalog()
        ids = {entry.id for entry in entries}
        self.assertTrue(original <= ids)
        self.assertIn("simple_humanoid", ids)
        self.assertEqual(len(ids), len(entries))

    def test_legacy_model_and_training_paths_are_rejected(self):
        entry = CatalogEntry("fixture", "Fixture", "example", "example/EVALUATION_PROTOCOL.md",
                             "protocol_draft", "planned", ())
        with tempfile.TemporaryDirectory() as temporary, patch("benchkit.catalog.load_catalog", return_value=(entry,)):
            root = Path(temporary)
            (root / "example/legacy/starvla_model_eval").mkdir(parents=True)
            (root / entry.protocol).write_text("# Protocol\n")
            (root / "example/eval_files").mkdir()
            (root / "example/train_files").mkdir()
            errors = validate_repository_catalog(root)
            self.assertEqual(len(errors), 3)
            self.assertTrue(any("local barks/" in error for error in errors))
            self.assertTrue(any("public benchmark tree" in error for error in errors))
            self.assertTrue(any("training directory" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
