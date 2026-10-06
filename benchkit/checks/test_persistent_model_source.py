"""Persistent-method source binding only: no app-server, model or simulator calls."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits.closed_run import AuditError, ClosedFiles, audit_model_source
from benchkit.model_profiles import (
    _allowed_files, _method_extensions, capture_policy_source, create_policy, verify_policy_source,
)


class PersistentModelSourceChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)

    def capture(self, **parameters):
        policy = create_policy("gpt6_astra", control_method="codex-direct/v3", **parameters)
        snapshot = capture_policy_source(self.run, policy)
        return policy.descriptor.to_dict(), snapshot

    def verify(self, descriptor, snapshot):
        # The auditor treats model bytes as data. Factory resolution is not part
        # of offline verification, and neither verification path starts a CLI.
        with patch("importlib.import_module", side_effect=AssertionError("no captured model imports")):
            verify_policy_source(self.run, descriptor, snapshot)
            files = ClosedFiles(self.run)
            count = audit_model_source(files, {"policy": descriptor, "model_source": snapshot})
            files.verify_unchanged()
        return count

    def reject(self, descriptor, snapshot):
        with self.assertRaises(ValueError):
            verify_policy_source(self.run, descriptor, snapshot)
        with self.assertRaises(AuditError):
            audit_model_source(ClosedFiles(self.run), {"policy": descriptor, "model_source": snapshot})

    def test_persistent_capture_exact_file_inventory_and_declared_overrides(self):
        descriptor, snapshot = self.capture(timeout_s=12.5, max_chunk_length=7, image_max_edge=320)
        self.assertEqual(self.verify(descriptor, snapshot), 29)
        self.assertEqual(descriptor["version"], "codex-direct/v3")
        self.assertEqual(descriptor["parameters"]["transport"], "codex-app-server/v1")
        self.assertEqual(descriptor["parameters"]["timeout_s"], 12.5)
        self.assertEqual(descriptor["parameters"]["image_max_edge"], 320)
        self.assertNotIn("enforce_action_guard", descriptor["parameters"]["effective_config"])
        self.assertNotIn("required_protocol", descriptor["parameters"]["effective_config"])
        names = {row["path"] for row in json.loads((self.run / "model_source/index.json").read_text())["files"]}
        self.assertEqual(names, set(_allowed_files("gpt6_astra")) | {"campaign_prompt.txt"})
        self.assertTrue({"AgentPolicies/gpt6_astra/" + name for name in (
            "methods/codex_direct.py", "configs/codex_direct_v3_config.json", "prompts/codex_direct_v3_prompt.txt", "transports/codex_app_server.py",
            "tools/persistent_runtime.py", "tools/public_observation.py")} <= names)
        self.assertNotIn("AgentPolicies/gpt6_astra/run.py", names)  # Separately captured trusted driver.

    def test_descriptor_identity_preset_prompt_and_override_forgery_are_rejected(self):
        original, snapshot = self.capture()
        changes = (("transport", "codex-exec/v1"), ("control_method", "codex-eef/v2"),
                   ("preset_sha256", "0" * 64), ("prompt_sha256", "0" * 64),
                   ("ordinary_give_up", True), ("initial_state_reference", "automatic_home_action"),
                   ("timeout_s", 900.0), ("max_chunk_length", True), ("effective_action_rules", {}))
        for key, value in changes:
            with self.subTest(key=key):
                changed = deepcopy(original)
                changed["parameters"][key] = value
                self.reject(changed, snapshot)

    def test_generic_direct_chunk_bounds_and_native_only_source_are_explicit(self):
        for length in (1, 32):
            with self.subTest(length=length), tempfile.TemporaryDirectory() as temporary:
                self.run = Path(temporary)
                descriptor, snapshot = self.capture(max_chunk_length=length)
                self.assertEqual(self.verify(descriptor, snapshot), 29)
                self.assertEqual(descriptor["parameters"]["max_chunk_length"], length)
                names = {row["path"] for row in json.loads((self.run / "model_source/index.json").read_text())["files"]}
                self.assertFalse(any("eef_contract" in name or "direct_public_context" in name
                                     or "codex_direct_v2" in name for name in names))
        for length in (0, 33, True):
            with self.subTest(length=length), self.assertRaises(ValueError):
                create_policy("gpt6_astra", control_method="codex-direct/v3", max_chunk_length=length)

    def test_effective_configuration_fixed_fields_are_typed_and_cannot_change(self):
        original, snapshot = self.capture()
        for key, value in (("terminal_delivery", "reply_and_continue"), ("ordinary_give_up", 0),
                           ("history", "new_thread_each_action"), ("network_continuations", 21),
                           ("max_translation_per_decision_m", 0.5), ("provider", "other"),
                           ("timeout_s", True), ("timeout_s", 901), ("max_chunk_length", 0),
                           ("max_chunk_length", 33), ("safety_stop", not original["parameters"]["safety_stop"])):
            with self.subTest(key=key, value=value):
                changed = deepcopy(original)
                changed["parameters"]["effective_config"][key] = value
                if key in {"timeout_s", "max_chunk_length"}:
                    changed["parameters"][key] = value
                self.reject(changed, snapshot)

    def test_transport_cannot_be_disguised_as_an_old_or_unknown_method(self):
        original, snapshot = self.capture()
        for version in (None, "codex-direct/v1", "codex-direct/v2", "openai-responses-direct/v1"):
            with self.subTest(version=version):
                changed = deepcopy(original)
                changed["version"] = version
                self.reject(changed, snapshot)

    def test_direct_cannot_omit_its_source_binding_as_an_unprofiled_policy(self):
        for policy in ({"version": "codex-direct/v1"}, {"version": "codex-direct/v2"}, {"version": "codex-direct/v3"},
                       {"parameters": {"control_method": "codex-direct/v1"}},
                       {"parameters": {"control_method": "codex-direct/v2"}},
                       {"parameters": {"transport": "codex-app-server/v1"}}):
            with self.subTest(policy=policy), self.assertRaisesRegex(AuditError, "explicit bound model source"):
                audit_model_source(ClosedFiles(self.run), {"policy": policy})
        self.assertEqual(audit_model_source(ClosedFiles(self.run), {"policy": {"version": "historical-fixture"}}), 0)

    def test_direct_rejects_unknown_or_missing_snapshot_schema(self):
        descriptor, snapshot = self.capture()
        for schema in (None, "starvla-rsi.model-source/v999"):
            with self.subTest(schema=schema):
                changed = {**snapshot, "schema_version": schema}
                self.reject(descriptor, changed)

    def test_each_persistent_runtime_file_is_hash_bound(self):
        descriptor, snapshot = self.capture()
        for name in ("methods/codex_direct.py", "configs/codex_direct_v3_config.json", "prompts/codex_direct_v3_prompt.txt", "transports/codex_app_server.py"):
            source = self.run / "model_source/files/AgentPolicies/gpt6_astra" / name
            original = source.read_bytes()
            with self.subTest(name=name):
                source.write_bytes(original + b"\n# changed")
                self.reject(descriptor, snapshot)
                source.write_bytes(original)
        self.assertEqual(self.verify(descriptor, snapshot), 29)

    def test_extension_marker_is_exact_and_requires_older_declared_layers(self):
        for config in ({"codex_direct_extension": "persistent-tools/v1"},
                       {"enforce_action_guard": True},
                       {"control_method": "responses-native/v1", "codex_direct_extension": "persistent-tools/v1"},
                       {"control_method": "responses-native/v1", "enforce_action_guard": True,
                        "codex_direct_extension": "persistent-tools/v2"}):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, "source extension"):
                _method_extensions(config)

    def test_grouped_14_18_21_25_file_subsets_keep_their_exact_allowlists(self):
        from benchkit.checks.test_grouped_gpt_source import GroupedGPTSourceChecks
        for depth, size in enumerate((14, 18, 21, 25)):
            with self.subTest(size=size):
                self.run, manifest, _ = GroupedGPTSourceChecks.fixture(self, 4, extension_count=depth)
                descriptor, snapshot = manifest["policy"], manifest["model_source"]
                self.assertEqual(self.verify(descriptor, snapshot), size)
                # A restricted source set cannot acquire an undeclared method simply
                # by rewriting the run's selection. No old files are expanded.
                descriptor = deepcopy(descriptor)
                descriptor["version"] = "codex-direct/v2"
                descriptor["parameters"].update(control_method="codex-direct/v2", transport="codex-app-server/v1")
                self.reject(descriptor, snapshot)

    def test_public_context_method_capture_preview_and_closed_schema_are_bound(self):
        for edge in (480, 0):
            with self.subTest(edge=edge), tempfile.TemporaryDirectory() as temporary:
                self.run = Path(temporary)
                policy = create_policy("gpt6_astra", control_method="codex-direct/v3",
                                       image_max_edge=edge)
                snapshot = capture_policy_source(self.run, policy)
                descriptor = policy.descriptor.to_dict()
                self.assertEqual(self.verify(descriptor, snapshot), 29)
                self.assertEqual(descriptor["parameters"]["image_max_edge"], edge)
                self.assertEqual(descriptor["parameters"]["initial_state_reference"], "first_public_observation_not_action")
                for key, value in (("image_max_edge", True), ("image_max_edge", 4097),
                                   ("feedback_projection", "private_metrics/v1"),
                                   ("history", "unknown")):
                    changed = deepcopy(descriptor)
                    changed["parameters"]["effective_config"][key] = value
                    if key == "image_max_edge":
                        changed["parameters"][key] = value
                    self.reject(changed, snapshot)
                for name in ("configs/codex_direct_v3_config.json", "prompts/codex_direct_v3_prompt.txt", "tools/public_observation.py"):
                    path = self.run / "model_source/files/AgentPolicies/gpt6_astra" / name
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n# mutated")
                    self.reject(descriptor, snapshot)
                    path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
