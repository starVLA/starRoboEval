"""Independent direct-model source audits using inert synthetic captured bytes."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits import closed_run as audit
from benchkit.source_snapshot import inventory_digest


class DirectModelAuditChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        self.run.mkdir()
        self.prefix = "starVLA/gpt6_astra/"
        self.policy = {"name": "direct-fixture", "kind": "direct-model", "provider": "fixture-provider",
                       "model": "fixture-model"}
        self.config = {"schema_version": "starvla-rsi.model-config/v1", "profile_id": "gpt6_astra",
                       "provider": "fixture-provider", "model": "fixture-model", "transport": "direct-fixture",
                       "timeout_s": 120, "max_chunk_length": 5, "max_output_tokens": 4096,
                       "policy_stop_rule_version": "minimum-action-decisions/v2",
                       "min_action_decisions_before_give_up": 0}
        self.schema = {"schema_version": "starvla-rsi.configuration-schema/v1", "profile_id": "gpt6_astra",
                       "execution": "direct", "factory_parameters": ["prompt", "timeout_s", "max_chunk_length",
                                                                       "min_action_decisions_before_give_up"],
                       "fields": {key: {"type": "string", "const": value} if isinstance(value, str) else
                                  {"type": "integer", "minimum": 0, "maximum": 8192}
                                  for key, value in self.config.items()}}
        self.profile = {"schema_version": "starvla-rsi.model-profile/v1", "id": "gpt6_astra",
                        "display_name": "GPT6Astra", "configured": True,
                        "factory": "starVLA.gpt6_astra.policy:create_policy", "policy": self.policy}
        # A captured policy containing executable failure text must never load.
        self.payloads = {relative: b'raise AssertionError("captured code must not execute")\n' for relative in (
            "starVLA/__init__.py", "starVLA/policy_support/__init__.py", "starVLA/policy_support/stop_rules.py",
            self.prefix + "__init__.py", self.prefix + "policy.py", self.prefix + "responses.py")}
        self.payloads.update({self.prefix + "prompt.txt": b"Synthetic direct prompt.",
                              "campaign_prompt.txt": b"Synthetic effective prompt."})
        self.put("profile.json", self.profile)
        self.put("config.json", self.config)
        self.put("configuration.schema.json", self.schema)
        self.dependencies = {"schema_version": "starvla-rsi.model-dependencies/v1",
            "files": sorted((set(self.payloads) - {"campaign_prompt.txt"}) | {self.prefix + "dependencies.json"}),
            "evaluation_dependency": "harness_source/index.json", "provider_sdk": {"name": "fixture-sdk", "version": None}}
        self.put("dependencies.json", self.dependencies)
        self.publish()

    def put(self, name, value):
        self.payloads[self.prefix + name] = json.dumps(value).encode()

    def publish(self):
        rows = []
        for relative, payload in sorted(self.payloads.items()):
            path = self.run / "model_source/files" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            rows.append({"path": relative, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        identity = {"schema_version": "starvla-rsi.model-profile/v1", "id": "gpt6_astra",
                    "factory": "starVLA.gpt6_astra.policy:create_policy",
                    "source_inventory_sha256": inventory_digest([r for r in rows if r["path"] != "campaign_prompt.txt"])}
        for name in ("profile", "config", "prompt", "dependencies"):
            suffix = ".txt" if name == "prompt" else ".json"
            identity[name + "_sha256"] = hashlib.sha256(self.payloads[self.prefix + name + suffix]).hexdigest()
        self.index = {"schema_version": "starvla-rsi.model-source/v2", "profile": identity, "files": rows,
                      "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
                      "inventory_sha256": inventory_digest(rows), "scope": "synthetic direct source bundle"}
        index_path = self.run / "model_source/index.json"
        index_path.write_text(json.dumps(self.index))
        self.snapshot = {key: self.index[key] for key in (
            "schema_version", "file_count", "total_bytes", "inventory_sha256")}
        self.snapshot.update(path="model_source/index.json", index_sha256=hashlib.sha256(index_path.read_bytes()).hexdigest())
        self.descriptor = {**self.policy, "parameters": {"model_profile": identity,
            "prompt_sha256": hashlib.sha256(self.payloads["campaign_prompt.txt"]).hexdigest()}}

    def inspect(self):
        files = audit.ClosedFiles(self.run)
        count = audit.audit_model_source(files, {"policy": self.descriptor, "model_source": self.snapshot})
        files.verify_unchanged()
        return count, files

    def test_direct_captured_schema_is_read_as_data_without_importing_policy_or_sdk(self):
        before = {path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()}
        with patch("importlib.import_module", side_effect=AssertionError("no dynamic imports")):
            count, files = self.inspect()
        self.assertEqual(count, self.snapshot["file_count"])
        self.assertIn("model_source/files/" + self.prefix + "configuration.schema.json", files.hashes)
        self.assertEqual(before, {path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()})

    def test_current_direct_factory_source_bundle_passes_without_dispatch(self):
        from benchkit.model_profiles import capture_policy_source, create_policy

        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            with patch("AgentPolicies.gpt6_astra.transports.codex_cli.send", side_effect=AssertionError("no provider dispatch")):
                policy = create_policy("gpt6_astra")
                snapshot = capture_policy_source(run, policy)
                files = audit.ClosedFiles(run)
                count = audit.audit_model_source(files, {"policy": policy.descriptor.to_dict(), "model_source": snapshot})
                files.verify_unchanged()
            self.assertEqual(count, snapshot["file_count"])

    def test_current_codex_versions_capture_rules_without_inference_or_model_import_by_auditor(self):
        from benchkit.model_profiles import capture_policy_source, create_policy

        for method, parameters in (("codex-native/v1", {}), ("codex-planned/v1", {}),
                                    ("codex-planned/v1", {"safety_stop": True}),
                                    ("codex-planned/v1", {"safety_stop": False}),
                                    ("codex-direct/v3", {"max_chunk_length": 7}),
                                    ("codex-direct/v3", {"safety_stop": True}),
                                    ("codex-direct/v3", {"safety_stop": False})):
            with self.subTest(method=method, parameters=parameters), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                with patch("AgentPolicies.gpt6_astra.transports.codex_cli.send", side_effect=AssertionError("no model calls")):
                    policy = create_policy("gpt6_astra", control_method=method, **parameters)
                    snapshot = capture_policy_source(run, policy)
                    manifest = {"policy": policy.descriptor.to_dict(), "model_source": snapshot}
                    with patch("importlib.import_module", side_effect=AssertionError("no captured imports")):
                        count = audit.audit_model_source(audit.ClosedFiles(run), manifest)
                self.assertEqual(count, snapshot["file_count"])

    def test_direct_v3_native_configuration_and_overrides_are_independently_bound(self):
        from benchkit.model_profiles import capture_policy_source, create_policy

        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            policy = create_policy("gpt6_astra", control_method="codex-direct/v3")
            snapshot = capture_policy_source(run, policy)
            original = {"policy": policy.descriptor.to_dict(), "model_source": snapshot}
            mutations = (
                ("initial_state_reference", "automatic_home_action"),
                ("effective_action_rules", {}),
                ("effective_action_rules", {"private_state_access": True}),
                ("effective_config", {**original["policy"]["parameters"]["effective_config"],
                                      "safety_stop": not original["policy"]["parameters"]["safety_stop"]}),
                ("safety_stop", 0),
                ("effective_config", {**original["policy"]["parameters"]["effective_config"],
                                      "max_translation_per_decision_m": 5.0}),
                ("control_method", "codex-eef/v1"),
            )
            for key, value in mutations:
                changed = deepcopy(original)
                changed["policy"]["parameters"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), changed)

    def test_direct_stop_modes_are_bound_in_both_auditors(self):
        from benchkit.model_profiles import capture_policy_source, create_policy, verify_policy_source

        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                policy = create_policy("gpt6_astra", control_method="codex-direct/v3", safety_stop=enabled)
                snapshot = capture_policy_source(run, policy)
                descriptor = policy.descriptor.to_dict()
                self.assertIs(descriptor["parameters"]["safety_stop"], enabled)
                verify_policy_source(run, descriptor, snapshot)
                audit.audit_model_source(audit.ClosedFiles(run), {"policy": descriptor, "model_source": snapshot})
                for bad in (0, 1, "false", None):
                    changed = deepcopy(descriptor)
                    changed["parameters"]["safety_stop"] = bad
                    changed["parameters"]["effective_config"]["safety_stop"] = bad
                    with self.subTest(bad=bad), self.assertRaises(ValueError):
                        verify_policy_source(run, changed, snapshot)
                    with self.subTest(bad=bad), self.assertRaises(audit.AuditError):
                        audit.audit_model_source(audit.ClosedFiles(run), {"policy": changed, "model_source": snapshot})

    def test_historical_direct_v3_stop_remains_enabled_and_non_overridable(self):
        from benchkit import model_profiles as profiles

        # Synthetic historical declaration, never executed: v3 originally had
        # no configurable stop field and its captured preset required True.
        data = profiles.load_profile("gpt6_astra")
        payloads = deepcopy(data["payloads"])
        prefix = "AgentPolicies/gpt6_astra/"
        config = json.loads(payloads[prefix + "configs/config.json"])
        config.pop("safety_stop", None)
        schema = json.loads(payloads[prefix + "configuration.schema.json"])
        schema["fields"].pop("safety_stop", None)
        schema["factory_parameters"] = [key for key in schema["factory_parameters"] if key != "safety_stop"]
        preset = json.loads(payloads[prefix + "configs/codex_direct_v3_config.json"])
        preset["safety_stop"] = True
        for path, value in (("configs/config.json", config), ("configuration.schema.json", schema),
                            ("configs/codex_direct_v3_config.json", preset)):
            payloads[prefix + path] = json.dumps(value).encode()
        historical = profiles._profile_data("gpt6_astra", payloads, require_configured=True)
        policy = profiles.create_policy("gpt6_astra", control_method="codex-direct/v3")
        descriptor = policy.descriptor.to_dict()
        descriptor["parameters"].update(model_profile=historical["identity"], safety_stop=True,
            effective_config=preset,
            preset_sha256=hashlib.sha256(payloads[prefix + "configs/codex_direct_v3_config.json"]).hexdigest())
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            with patch.object(profiles, "load_profile", return_value=historical):
                _, snapshot = profiles.capture_model_source(run, "gpt6_astra", policy.prompt, freeze=False)
            profiles.verify_policy_source(run, descriptor, snapshot)
            audit.audit_model_source(audit.ClosedFiles(run), {"policy": descriptor, "model_source": snapshot})
            descriptor["parameters"]["safety_stop"] = False
            descriptor["parameters"]["effective_config"]["safety_stop"] = False
            with self.assertRaises(ValueError):
                profiles.verify_policy_source(run, descriptor, snapshot)
            with self.assertRaises(audit.AuditError):
                audit.audit_model_source(audit.ClosedFiles(run), {"policy": descriptor, "model_source": snapshot})

    def test_planned_stop_modes_are_strictly_bound_in_both_auditors(self):
        from benchkit import model_profiles as profiles

        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                policy = profiles.create_policy("gpt6_astra", control_method="codex-planned/v1", safety_stop=enabled)
                snapshot = profiles.capture_policy_source(run, policy)
                descriptor = policy.descriptor.to_dict()
                self.assertIs(descriptor["parameters"]["safety_stop"], enabled)
                self.assertEqual(descriptor["parameters"]["effective_config"]["schema_version"],
                                 "starvla-rsi.codex-planned-config/v2")
                profiles.verify_policy_source(run, descriptor, snapshot)
                audit.audit_model_source(audit.ClosedFiles(run), {"policy": descriptor, "model_source": snapshot})
                for bad in (0, 1, "false", None, not enabled):
                    changed = deepcopy(descriptor)
                    changed["parameters"]["safety_stop"] = bad
                    # A mismatched boolean is independently rejected; other
                    # invalid types must fail even if both locations agree.
                    if type(bad) is not bool:
                        changed["parameters"]["effective_config"]["safety_stop"] = bad
                    with self.subTest(bad=bad), self.assertRaises(ValueError):
                        profiles.verify_policy_source(run, changed, snapshot)
                    with self.subTest(bad=bad), self.assertRaises(audit.AuditError):
                        audit.audit_model_source(audit.ClosedFiles(run), {"policy": changed, "model_source": snapshot})

    def test_historical_planned_stop_is_fixed_even_with_direct_stop_declaration(self):
        from benchkit import model_profiles as profiles

        for global_stop_field in (False, True):
            for preset_stop in (True, False, 1):
                with self.subTest(global_stop_field=global_stop_field, preset_stop=preset_stop):
                    data = profiles.load_profile("gpt6_astra")
                    payloads = deepcopy(data["payloads"])
                    prefix = "AgentPolicies/gpt6_astra/"
                    preset_path = prefix + "configs/codex_planned_config.json"
                    preset = json.loads(payloads[preset_path])
                    preset.update(schema_version="starvla-rsi.codex-planned-config/v1", safety_stop=preset_stop)
                    payloads[preset_path] = json.dumps(preset).encode()
                    if not global_stop_field:
                        config = json.loads(payloads[prefix + "configs/config.json"])
                        config.pop("safety_stop", None)
                        schema = json.loads(payloads[prefix + "configuration.schema.json"])
                        schema["fields"].pop("safety_stop", None)
                        schema["factory_parameters"].remove("safety_stop")
                        payloads[prefix + "configs/config.json"] = json.dumps(config).encode()
                        payloads[prefix + "configuration.schema.json"] = json.dumps(schema).encode()
                    historical = profiles._profile_data("gpt6_astra", payloads, require_configured=True)
                    policy = profiles.create_policy("gpt6_astra", control_method="codex-planned/v1")
                    descriptor = policy.descriptor.to_dict()
                    descriptor["parameters"].pop("safety_stop", None)  # Historical descriptors omit it.
                    descriptor["parameters"].update(model_profile=historical["identity"], effective_config=preset,
                        preset_sha256=hashlib.sha256(payloads[preset_path]).hexdigest())
                    with tempfile.TemporaryDirectory() as temporary:
                        run = Path(temporary)
                        with patch.object(profiles, "load_profile", return_value=historical):
                            _, snapshot = profiles.capture_model_source(run, "gpt6_astra", policy.prompt, freeze=False)
                        if preset_stop is True:
                            profiles.verify_policy_source(run, descriptor, snapshot)
                            audit.audit_model_source(audit.ClosedFiles(run), {"policy": descriptor, "model_source": snapshot})
                            descriptor["parameters"]["effective_config"]["safety_stop"] = False
                            descriptor["parameters"]["safety_stop"] = False
                        with self.assertRaises(ValueError):
                            profiles.verify_policy_source(run, descriptor, snapshot)
                        with self.assertRaises(audit.AuditError):
                            audit.audit_model_source(audit.ClosedFiles(run), {"policy": descriptor, "model_source": snapshot})

    def test_planned_v2_requires_own_declared_boolean_factory_capability(self):
        from benchkit import model_profiles as profiles

        data = profiles.load_profile("gpt6_astra")
        prefix = "AgentPolicies/gpt6_astra/"
        for missing in ("field", "factory_parameter"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                payloads = deepcopy(data["payloads"])
                schema = json.loads(payloads[prefix + "configuration.schema.json"])
                config = json.loads(payloads[prefix + "configs/config.json"])
                if missing == "field":
                    schema["fields"].pop("safety_stop")
                    config.pop("safety_stop", None)
                schema["factory_parameters"].remove("safety_stop")
                payloads[prefix + "configuration.schema.json"] = json.dumps(schema).encode()
                payloads[prefix + "configs/config.json"] = json.dumps(config).encode()
                captured = profiles._profile_data("gpt6_astra", payloads, require_configured=True)
                policy = profiles.create_policy("gpt6_astra", control_method="codex-planned/v1")
                descriptor = policy.descriptor.to_dict()
                descriptor["parameters"]["model_profile"] = captured["identity"]
                with patch.object(profiles, "load_profile", return_value=captured):
                    _, snapshot = profiles.capture_model_source(run, "gpt6_astra", policy.prompt, freeze=False)
                with self.assertRaises(ValueError):
                    profiles.verify_policy_source(run, descriptor, snapshot)
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), {"policy": descriptor, "model_source": snapshot})

    def test_historical_selectable_codex_bundle_without_feedback_marker_keeps_old_allowlist(self):
        self.config["control_method"] = "codex-eef/v1"
        self.schema["fields"]["control_method"] = {"type": "string", "const": "codex-eef/v1"}
        self.schema["factory_parameters"].append("control_method")
        self.put("config.json", self.config)
        self.put("configuration.schema.json", self.schema)
        for name in ("codex_cli.py", "codex_policy.py", "codex_prompt.txt"):
            self.payloads[self.prefix + name] = b"# inert historical method source\n"
        preset = {"control_method": "codex-eef/v1", "timeout_s": 900, "max_chunk_length": 5}
        self.put("codex_config.json", preset)
        self.dependencies["files"] = sorted(set(self.payloads) - {"campaign_prompt.txt"})
        self.put("dependencies.json", self.dependencies)
        self.publish()
        self.descriptor["version"] = "codex-eef/v1"
        self.descriptor["parameters"].update(control_method="codex-eef/v1", transport="codex-exec/v1",
            ordinary_give_up=False, timeout_s=900, max_chunk_length=5, effective_config=preset,
            preset_sha256=hashlib.sha256(self.payloads[self.prefix + "codex_config.json"]).hexdigest())
        self.assertEqual(self.inspect()[0], 16)

    def test_standalone_auditor_needs_no_current_or_frozen_package_import(self):
        selection = self.run / "selection.json"
        selection.write_text(json.dumps({"policy": self.descriptor, "model_source": self.snapshot}))
        code = """
import json, runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1], run_name='standalone_audit')
run = Path(sys.argv[2])
files = module['ClosedFiles'](run)
module['audit_model_source'](files, json.loads((run / 'selection.json').read_text()))
files.verify_unchanged()
assert not any(name.split('.')[0] in {'benchkit', 'starVLA', 'AgentPolicies', 'openai'} for name in sys.modules)
"""
        process = subprocess.run([sys.executable, "-B", "-c", code, str(Path(audit.__file__).resolve()), str(self.run)],
            cwd=self.run, env={**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_rehashed_invalid_config_values_cannot_pass_validation(self):
        for change in ({"max_output_tokens": True}, {"max_output_tokens": 8193}, {"timeout_s": 120.5},
                       {"extra": "value"}, {"provider": "different-provider"}):
            with self.subTest(change=change):
                self.put("config.json", {**self.config, **change})
                self.publish()
                with self.assertRaises(audit.AuditError):
                    self.inspect()

    def test_rehashed_schema_cannot_allow_credentials_or_executable_validators(self):
        for field in ("api_key", "authorization", "credentials", "access_token", "token", "api_token",
                      "provider_token", "openai_api_key", "provider_secret", "provider_password", "provider_credentials"):
            with self.subTest(field=field):
                schema = deepcopy(self.schema)
                schema["fields"][field] = {"type": "string"}
                self.put("configuration.schema.json", schema)
                self.put("config.json", {**self.config, field: "synthetic-private-value"})
                self.publish()
                with self.assertRaisesRegex(audit.AuditError, "unsafe"):
                    self.inspect()
        self.put("config.json", self.config)
        self.put("configuration.schema.json", {**self.schema, "validator": "arbitrary.module:execute"})
        self.publish()
        with self.assertRaisesRegex(audit.AuditError, "configuration schema"):
            self.inspect()

    def test_rehashed_transport_and_directory_override_are_not_direct_schema(self):
        for change in ({"execution": "mailbox"}, {"factory_parameters": ["directory"]}):
            with self.subTest(change=change):
                self.put("configuration.schema.json", {**self.schema, **change})
                self.publish()
                with self.assertRaisesRegex(audit.AuditError, "configuration"):
                    self.inspect()

    def test_source_and_effective_prompt_tampering_are_rejected(self):
        source = self.run / "model_source/files" / self.prefix / "responses.py"
        source.write_bytes(source.read_bytes() + b"# changed")
        with self.assertRaisesRegex(audit.AuditError, "copied source mismatch"):
            self.inspect()
        self.publish()
        self.descriptor["parameters"]["prompt_sha256"] = "0" * 64
        with self.assertRaisesRegex(audit.AuditError, "effective model prompt mismatch"):
            self.inspect()

    def test_rehashed_extra_source_is_outside_independent_allowlist(self):
        relative = self.prefix + "unexpected.py"
        self.payloads[relative] = b"# extra captured code\n"
        self.put("dependencies.json", {**self.dependencies, "files": sorted(self.dependencies["files"] + [relative])})
        self.publish()
        with self.assertRaisesRegex(audit.AuditError, "reviewed allowlist"):
            self.inspect()

    def test_profile_and_sdk_declarations_are_checked_without_claiming_provider_identity(self):
        for change in ({"configured": False}, {"factory": "other.module:create_policy"},
                       {"policy": {**self.policy, "model": "unbound-model"}}):
            with self.subTest(change=change):
                self.put("profile.json", {**self.profile, **change})
                self.publish()
                with self.assertRaises(audit.AuditError):
                    self.inspect()
        self.put("profile.json", self.profile)
        self.put("dependencies.json", {**self.dependencies, "provider_sdk": {"name": "fixture-sdk", "version": True}})
        self.publish()
        with self.assertRaisesRegex(audit.AuditError, "provider SDK"):
            self.inspect()


if __name__ == "__main__":
    unittest.main()
