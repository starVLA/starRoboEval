"""Reject altered, omitted or injected files in an archived native runtime."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "environment" / "verify_environment.py"
SPEC = importlib.util.spec_from_file_location("tabletop_environment_verifier", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SourceInventoryChecks(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        root = base / "archive"
        (root / "robosuite" / "models").mkdir(parents=True)
        (base / "external_assets").mkdir()
        (root / "robosuite" / "models" / "assets").symlink_to(base / "external_assets", target_is_directory=True)
        contents = {"README.md": b"pinned source", "robosuite/__init__.py": b"# native package\n"}
        for relative, data in contents.items():
            (root / relative).write_bytes(data)
        manifest = {"revision": "pin", "files": {
            relative: {"git_blob_sha1": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}
            for relative, data in contents.items()
        }}
        context = patch.object(Path, "read_text", return_value=json.dumps(manifest))
        context.start()
        self.addCleanup(context.stop)
        return root

    def test_archive_is_attested_as_archive_not_checkout(self):
        root = self.fixture()
        result = MODULE.verify_source(root, "pin", "robosuite")
        self.assertEqual(len(result["tracked_code_sha256"]), 2)
        self.assertIn("archive", result["source_layout"])
        self.assertIn("not established", result["assets_complete"])

    def test_content_tampering_fails_git_blob_identity(self):
        root = self.fixture()
        (root / "robosuite" / "__init__.py").write_bytes(b"# changed source\n")
        with self.assertRaisesRegex(RuntimeError, "differs from pinned git blob"):
            MODULE.verify_source(root, "pin", "robosuite")

    def test_unmanifested_private_override_is_rejected(self):
        root = self.fixture()
        (root / "robosuite" / "macros_private.py").write_text("OVERRIDE = True\n")
        with self.assertRaisesRegex(RuntimeError, "unmanifested"):
            MODULE.verify_source(root, "pin", "robosuite")

    def test_unmanifested_symlink_package_is_rejected(self):
        root = self.fixture()
        (root / "robosuite" / "injected").symlink_to(root.parent / "external_assets", target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "unmanifested"):
            MODULE.verify_source(root, "pin", "robosuite")

    def test_missing_archived_file_is_rejected(self):
        root = self.fixture()
        (root / "README.md").rename(root / "renamed.md")
        with self.assertRaisesRegex(RuntimeError, "missing tracked source file"):
            MODULE.verify_source(root, "pin", "robosuite")


if __name__ == "__main__":
    unittest.main()
