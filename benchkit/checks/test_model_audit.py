"""Independent offline audit guards for new model-source bundles."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.source_snapshot import inventory_digest
from benchkit.model_profiles import capture_policy_source, create_policy


AUDITOR_PATH = Path(__file__).resolve().parents[2] / "benchkit/audits/closed_run.py"
SPEC = importlib.util.spec_from_file_location("model_source_audit_checks", AUDITOR_PATH)
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


class ModelAuditChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        policy = create_policy("anonymous_code_agent", directory=self.root / "endpoint")
        self.run = self.root / "run"
        self.run.mkdir()
        self.snapshot = capture_policy_source(self.run, policy)
        self.descriptor = policy.descriptor.to_dict()
        self.index_path = self.run / "model_source/index.json"
        self.index = json.loads(self.index_path.read_text())

    def publish_index(self):
        self.index_path.write_text(json.dumps(self.index))
        self.snapshot["index_sha256"] = hashlib.sha256(self.index_path.read_bytes()).hexdigest()

    def audit(self):
        files = AUDITOR.ClosedFiles(self.run)
        count = AUDITOR.audit_model_source(files, {"policy": self.descriptor, "model_source": self.snapshot})
        files.verify_unchanged()
        return count, files

    def test_valid_bundle_includes_root_initializer_and_audits_without_factory_import(self):
        paths = {row["path"] for row in self.index["files"]}
        self.assertIn("AgentPolicies/__init__.py", paths)
        self.assertIn("campaign_prompt.txt", paths)
        self.assertFalse(any("results/" in path or ".env" in path for path in paths))
        with patch("importlib.import_module", side_effect=AssertionError("auditor must not import model factories")):
            count, files = self.audit()
        self.assertEqual(count, self.snapshot["file_count"])
        self.assertIn("model_source/files/AgentPolicies/__init__.py", files.hashes)

    def test_rehashed_index_cannot_lie_about_model_source_identity(self):
        self.descriptor["parameters"]["model_profile"]["source_inventory_sha256"] = "0" * 64
        self.index["profile"]["source_inventory_sha256"] = "0" * 64
        self.publish_index()
        with self.assertRaisesRegex(AUDITOR.AuditError, "source identity inventory"):
            self.audit()

    def test_rehashed_config_cannot_add_secret_or_untyped_parameter_fields(self):
        relative = "AgentPolicies/anonymous_code_agent/config.json"
        config_path = self.run / "model_source/files" / relative
        original = json.loads(config_path.read_text())
        for change in ({"api_key": "not-a-real-secret-review-fixture"}, {"max_response_bytes": True}):
            with self.subTest(change=change):
                config_path.write_text(json.dumps({**original, **change}))
                payload = config_path.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                for row in self.index["files"]:
                    if row["path"] == relative:
                        row.update(size_bytes=len(payload), sha256=digest)
                identity = self.descriptor["parameters"]["model_profile"]
                identity["config_sha256"] = digest
                identity["source_inventory_sha256"] = inventory_digest(
                    [row for row in self.index["files"] if row["path"] != "campaign_prompt.txt"])
                self.index["profile"] = identity
                self.index["inventory_sha256"] = inventory_digest(self.index["files"])
                self.index["total_bytes"] = sum(row["size_bytes"] for row in self.index["files"])
                self.snapshot.update(inventory_sha256=self.index["inventory_sha256"],
                                     total_bytes=self.index["total_bytes"])
                self.publish_index()
                with self.assertRaisesRegex(AUDITOR.AuditError, "config semantics"):
                    self.audit()


if __name__ == "__main__":
    unittest.main()
