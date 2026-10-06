"""Offline source-boundary checks for the generic planned native-vector method."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits.closed_run import AuditError, ClosedFiles, audit_model_source
from benchkit.model_profiles import (
    GROUPED_SOURCE_SCHEMA, _allowed_files, _method_extensions, capture_policy_source, create_policy,
    verify_policy_source,
)


class PlannedModelSourceChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def capture(self, **overrides):
        policy = create_policy("gpt6_astra", control_method="codex-planned/v1", **overrides)
        return policy.descriptor.to_dict(), capture_policy_source(self.root, policy)

    def verify(self, descriptor, snapshot):
        # Captured executable files are data to both verifiers, never imports.
        with patch("importlib.import_module", side_effect=AssertionError("model import during audit")):
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

    def test_exact_capture_and_declared_overrides_without_benchmark_sources(self):
        descriptor, snapshot = self.capture(timeout_s=22.5, max_chunk_length=7, image_max_edge=320)
        self.assertEqual(self.verify(descriptor, snapshot), 29)
        names = {row["path"] for row in json.loads((self.root / "model_source/index.json").read_text())["files"]}
        self.assertEqual(names, set(_allowed_files("gpt6_astra")) | {"campaign_prompt.txt"})
        for prefix in ("benchmarks/", "results/", "barks/", ".codex/"):
            self.assertFalse(any(prefix in name for name in names), prefix)
        self.assertNotIn("AgentPolicies/gpt6_astra/run.py", names)
        self.assertEqual(descriptor["version"], "codex-planned/v1")
        self.assertFalse(descriptor["parameters"]["ordinary_give_up"])

    def test_descriptor_and_effective_config_tampering_are_rejected(self):
        original, snapshot = self.capture()
        for key, value in (("control_method", "codex-native/v1"), ("transport", "other"),
                           ("preset_sha256", "0" * 64), ("prompt_sha256", "0" * 64),
                           ("timeout_s", 999), ("max_chunk_length", 33),
                           ("image_max_edge", -1), ("ordinary_give_up", True)):
            with self.subTest(parameter=key):
                changed = deepcopy(original)
                changed["parameters"][key] = value
                self.reject(changed, snapshot)
        for key, value in (("model", "other"), ("reasoning_effort", "low"),
                           ("timeout_s", True), ("max_chunk_length", 0),
                           ("max_chunk_length", 33), ("image_max_edge", -1)):
            with self.subTest(effective=key, value=value):
                changed = deepcopy(original)
                changed["parameters"]["effective_config"][key] = value
                self.reject(changed, snapshot)

    def test_wrong_method_version_cannot_bypass_configuration_checks(self):
        original, snapshot = self.capture()
        for version in (None, "codex-planned/v999", "codex-native/v1", "codex-direct/v2"):
            with self.subTest(version=version):
                changed = deepcopy(original)
                changed["version"] = version
                changed["parameters"]["effective_config"]["max_chunk_length"] = 999
                self.reject(changed, snapshot)

    def test_scalar_overrides_cannot_be_booleans(self):
        original, snapshot = self.capture(timeout_s=1, max_chunk_length=1, image_max_edge=1)
        for key in ("timeout_s", "max_chunk_length", "image_max_edge"):
            with self.subTest(key=key):
                changed = deepcopy(original)
                changed["parameters"][key] = True
                self.reject(changed, snapshot)

    def test_planned_method_requires_explicit_bound_source(self):
        for descriptor in ({"version": "codex-planned/v1"},
                           {"parameters": {"control_method": "codex-planned/v1"}},
                           {"version": "codex-planned/v999"}):
            with self.subTest(descriptor=descriptor), self.assertRaisesRegex(AuditError, "explicit bound model source"):
                audit_model_source(ClosedFiles(self.root), {"policy": descriptor})

    def test_each_new_source_and_shared_transport_are_hash_bound(self):
        descriptor, snapshot = self.capture()
        for name in ("methods/codex_planned.py", "configs/codex_planned_config.json",
                     "prompts/codex_planned_prompt.txt", "methods/codex_direct.py",
                     "transports/codex_app_server.py"):
            path = self.root / "model_source/files/AgentPolicies/gpt6_astra" / name
            original = path.read_bytes()
            try:
                with self.subTest(name=name):
                    path.write_bytes(original + b"\n# fixture mutation")
                    self.reject(descriptor, snapshot)
            finally:
                path.write_bytes(original)
        self.assertEqual(self.verify(descriptor, snapshot), 29)

    def test_extension_is_explicit_and_does_not_expand_older_inventory(self):
        prior = {"control_method": "responses-native/v1", "enforce_action_guard": True,
                 "codex_direct_extension": "persistent-tools/v1",
                 "codex_direct_context_extension": "public-context/v2",
                 "codex_native_extension": "native-vectors/v1"}
        self.assertFalse(_method_extensions(prior)["planned_extensions"])
        declared = {**prior, "codex_planned_extension": "planned-native/v1"}
        self.assertTrue(_method_extensions(declared)["planned_extensions"])
        old = set(_allowed_files("gpt6_astra", source_schema=GROUPED_SOURCE_SCHEMA, **_method_extensions(prior)))
        current = set(_allowed_files("gpt6_astra", source_schema=GROUPED_SOURCE_SCHEMA, **_method_extensions(declared)))
        self.assertEqual(current - old, {
            "AgentPolicies/gpt6_astra/methods/codex_planned.py",
            "AgentPolicies/gpt6_astra/configs/codex_planned_config.json",
            "AgentPolicies/gpt6_astra/prompts/codex_planned_prompt.txt",
        })
        for mutate in ({"codex_planned_extension": "planned-native/v999"},
                       {"codex_native_extension": None}, {"codex_direct_context_extension": None}):
            bad = {**declared, **mutate}
            bad = {key: value for key, value in bad.items() if value is not None}
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                _method_extensions(bad)


if __name__ == "__main__":
    unittest.main()
