"""Offline native-vector source/audit guards; no CLI or simulator requests."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits.closed_run import AuditError, ClosedFiles, audit_model_source
from benchkit.model_profiles import (
    _allowed_files, capture_policy_source, create_policy, verify_policy_source,
)


class NativeModelSourceChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def capture(self, **kwargs):
        policy = create_policy("gpt6_astra", control_method="codex-native/v1", **kwargs)
        return policy.descriptor.to_dict(), capture_policy_source(self.root, policy)

    def verify(self, descriptor, snapshot):
        with patch("importlib.import_module", side_effect=AssertionError("must not import model")):
            verify_policy_source(self.root, descriptor, snapshot)
            files = ClosedFiles(self.root)
            count = audit_model_source(files, {"policy": descriptor, "model_source": snapshot})
            files.verify_unchanged()
        return count

    def reject(self, descriptor, snapshot):
        with self.assertRaises(ValueError):
            verify_policy_source(self.root, descriptor, snapshot)
        with self.assertRaises(AuditError):
            audit_model_source(ClosedFiles(self.root), {"policy": descriptor, "model_source": snapshot})

    def test_exact_capture_and_declared_overrides(self):
        descriptor, snapshot = self.capture(timeout_s=22.5, max_chunk_length=3,
                                            min_action_decisions_before_give_up=4)
        self.assertEqual(self.verify(descriptor, snapshot), 29)
        self.assertIsNone(descriptor["parameters"]["max_output_tokens"])
        names = {row["path"] for row in json.loads((self.root / "model_source/index.json").read_text())["files"]}
        self.assertEqual(names, set(_allowed_files("gpt6_astra")) | {"campaign_prompt.txt"})
        self.assertNotIn("AgentPolicies/gpt6_astra/run.py", names)
        self.assertFalse(any("results/" in name for name in names))

    def test_descriptor_and_effective_config_mutations_rejected(self):
        original, snapshot = self.capture()
        for key, value in (("control_method", "responses-native/v1"), ("transport", "other"),
                           ("preset_sha256", "0" * 64), ("prompt_sha256", "0" * 64),
                           ("timeout_s", 999), ("max_chunk_length", 99),
                           ("max_output_tokens", 4096), ("invalid_action_handling", "terminate")):
            with self.subTest(key=key):
                changed = deepcopy(original)
                changed["parameters"][key] = value
                self.reject(changed, snapshot)
        for retry in (None, {"max_attempts": 10},
                      {"scope": "same_policy_decision_before_action_submission", "max_attempts": 11,
                       "retry_backoff_s": 10.0},
                      {"scope": "replay_native_action", "max_attempts": 10, "retry_backoff_s": 10.0}):
            with self.subTest(retry=retry):
                changed = deepcopy(original)
                changed["parameters"]["automatic_retry"] = retry
                self.reject(changed, snapshot)
        for key, value in (("history", "all_private_state"), ("model", "other"),
                           ("timeout_s", True), ("max_chunk_length", 0),
                           ("max_chunk_length", 6), ("reasoning_effort", "low"),
                           ("max_attempts", 11), ("retry_backoff_s", 0)):
            with self.subTest(effective=key, value=value):
                changed = deepcopy(original)
                changed["parameters"]["effective_config"][key] = value
                self.reject(changed, snapshot)

    def test_wrong_method_cannot_skip_preset_checks(self):
        original, snapshot = self.capture()
        for version in (None, "codex-native/v999", "openai-responses-direct/v1", "codex-eef/v1"):
            with self.subTest(version=version):
                changed = deepcopy(original)
                changed["version"] = version
                changed["parameters"]["effective_config"]["max_chunk_length"] = 999
                self.reject(changed, snapshot)

    def test_numeric_descriptor_overrides_cannot_be_booleans(self):
        original, snapshot = self.capture(timeout_s=1, max_chunk_length=1)
        for key in ("timeout_s", "max_chunk_length"):
            with self.subTest(key=key):
                changed = deepcopy(original)
                changed["parameters"][key] = True
                self.reject(changed, snapshot)

    def test_native_method_cannot_omit_source_bundle(self):
        for policy in ({"version": "codex-native/v1"},
                       {"parameters": {"control_method": "codex-native/v1"}}):
            with self.subTest(policy=policy), self.assertRaisesRegex(AuditError, "explicit bound model source"):
                audit_model_source(ClosedFiles(self.root), {"policy": policy})

    def test_each_native_source_is_hash_bound(self):
        descriptor, snapshot = self.capture()
        for name in ("methods/codex_native.py", "configs/codex_native_config.json", "prompts/codex_native_prompt.txt"):
            path = self.root / "model_source/files/AgentPolicies/gpt6_astra" / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b"\n# changed")
                self.reject(descriptor, snapshot)
                path.write_bytes(original)
        self.assertEqual(self.verify(descriptor, snapshot), 29)

    def test_grouped_context_subset_without_native_marker_has_28_files(self):
        # A historical fixture must not be synthesized from the cleaned live tree.
        from benchkit.checks.test_grouped_gpt_source import GroupedGPTSourceChecks
        self.root, manifest, _ = GroupedGPTSourceChecks.fixture(self, 4, extension_count=4)
        self.assertEqual(self.verify(manifest["policy"], manifest["model_source"]), 28)
        names = {row["path"] for row in json.loads((self.root / "model_source/index.json").read_text())["files"]}
        self.assertFalse(any("codex_native" in name for name in names))


if __name__ == "__main__":
    unittest.main()
