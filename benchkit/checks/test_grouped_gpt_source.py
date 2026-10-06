"""Independent inert fixtures bind old flat and current grouped source layouts.

Inventories and path mappings are declared here, not derived from the producer's
allowlist. Captured Python raises if executed; verification must read it as data.
"""

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
from benchkit.model_profiles import load_profile, verify_policy_source


BASE = ("__init__.py", "profile.json", "config.json", "prompt.txt", "dependencies.json",
        "policy.py", "responses.py", "configuration.schema.json")
EXTENSIONS = (
    ("codex_cli.py", "codex_policy.py", "codex_config.json", "codex_prompt.txt"),
    ("action_validation.py", "codex_v2_config.json", "codex_v2_prompt.txt"),
    ("codex_direct.py", "codex_direct_config.json", "codex_direct_prompt.txt", "codex_app_server.py"),
    ("codex_direct_v2_config.json", "codex_direct_v2_prompt.txt", "direct_public_context.py"),
    ("codex_native.py", "codex_native_config.json", "codex_native_prompt.txt"),
    ("codex_planned.py", "codex_planned_config.json", "codex_planned_prompt.txt"),
)
GROUPS = {
    "methods": {"policy.py", "codex_policy.py", "codex_direct.py", "codex_native.py", "codex_planned.py",
                "action_validation.py", "direct_public_context.py"},
    "transports": {"responses.py", "codex_cli.py", "codex_app_server.py"},
    "configs": {"config.json", "codex_config.json", "codex_v2_config.json",
                "codex_direct_config.json", "codex_direct_v2_config.json", "codex_native_config.json", "codex_planned_config.json"},
    "prompts": {"prompt.txt", "codex_prompt.txt", "codex_v2_prompt.txt",
                "codex_direct_prompt.txt", "codex_direct_v2_prompt.txt", "codex_native_prompt.txt", "codex_planned_prompt.txt"},
}
V5_NAMES = (
    "__init__.py", "profile.json", "configuration.schema.json", "dependencies.json",
    "configs/config.json", "configs/codex_native_config.json", "configs/codex_direct_v2_config.json",
    "configs/codex_planned_config.json", "prompts/codex_native_prompt.txt",
    "prompts/codex_direct_v2_prompt.txt", "prompts/codex_planned_prompt.txt",
    "methods/__init__.py", "methods/codex_native.py", "methods/codex_direct.py", "methods/codex_planned.py",
    "tools/__init__.py", "tools/factory.py", "tools/json_io.py", "tools/native_io.py",
    "tools/eef_contract.py", "tools/runtime_preflight.py", "tools/direct_public_context.py",
    "transports/__init__.py", "transports/codex_cli.py", "transports/codex_app_server.py",
)
V6_NAMES = (
    "__init__.py", "profile.json", "configuration.schema.json", "dependencies.json",
    "configs/config.json", "configs/codex_native_config.json", "configs/codex_direct_v3_config.json",
    "configs/codex_planned_config.json", "prompts/codex_native_prompt.txt",
    "prompts/codex_direct_v3_prompt.txt", "prompts/codex_planned_prompt.txt",
    "methods/__init__.py", "methods/codex_native.py", "methods/codex_direct.py", "methods/codex_planned.py",
    "tools/__init__.py", "tools/factory.py", "tools/json_io.py", "tools/native_io.py",
    "tools/persistent_runtime.py", "tools/runtime_preflight.py", "tools/public_observation.py",
    "transports/__init__.py", "transports/codex_cli.py", "transports/codex_app_server.py",
)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


class GroupedGPTSourceChecks(unittest.TestCase):
    def fixture(self, version, *, extension_count=5, declared_version=None,
                factory_override=None, extra_source=False, config_changes=None,
                selected_method="codex-native/v1"):
        temporary = tempfile.TemporaryDirectory(prefix="rsi-inert-source-")
        self.addCleanup(temporary.cleanup)
        run = Path(temporary.name)
        namespace = "starVLA" if version == 2 else "AgentPolicies"
        prefix = namespace + "/gpt6_astra/"

        def relative(name):
            if version in (5, 6):
                if name == "prompt.txt":
                    return "prompts/codex_native_prompt.txt"
                paths = V6_NAMES if version == 6 else V5_NAMES
                return next((path for path in paths if path.rsplit("/", 1)[-1] == name), name)
            if version == 4:
                for group, names in GROUPS.items():
                    if name in names:
                        return group + "/" + name
            return name

        factory = factory_override or (namespace + ".gpt6_astra."
                    + ("tools.factory" if version in (5, 6) else "methods.policy" if version == 4 else "policy")
                    + ":create_policy")
        policy = {"name": "inert-fixture", "kind": "direct-model", "provider": "fixture-provider",
                  "model": "fixture-model"}
        profile = {"schema_version": "starvla-rsi.model-profile/v1", "id": "gpt6_astra",
                   "display_name": "GPT6Astra", "configured": True,
                   "factory": factory, "policy": policy}
        config = {"schema_version": "starvla-rsi.model-config/v1", "profile_id": "gpt6_astra",
                  "provider": "fixture-provider", "model": "fixture-model", "transport": "inert-fixture",
                  "timeout_s": 120, "max_chunk_length": 5, "max_output_tokens": 4096,
                  "policy_stop_rule_version": "minimum-action-decisions/v2",
                  "min_action_decisions_before_give_up": 0}
        markers = (("control_method", "fixture-responses/v1"), ("enforce_action_guard", True),
                   ("codex_direct_extension", "persistent-tools/v1"),
                   ("codex_direct_context_extension", "public-context/v2"),
                   ("codex_native_extension", "native-vectors/v1"),
                   ("codex_planned_extension", "planned-native/v1"))
        config.update({"control_method": "codex-native/v1"} if version in (5, 6) else markers[:extension_count])
        for key, value in (config_changes or {}).items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        schema = {"schema_version": "starvla-rsi.configuration-schema/v1", "profile_id": "gpt6_astra",
                  "execution": "direct", "factory_parameters": ["prompt", "timeout_s", "max_chunk_length",
                                                                  "min_action_decisions_before_give_up"],
                  "fields": {name: ({"type": "boolean"} if type(value) is bool else
                                    {"type": "string", "const": value} if isinstance(value, str) else
                                    {"type": "integer", "minimum": 0, "maximum": 8192})
                             for name, value in config.items()}}
        names = list(BASE) + [name for group in EXTENSIONS[:extension_count] for name in group]
        paths = [namespace + "/" + name for name in
                 ("__init__.py", "policy_support/__init__.py", "policy_support/stop_rules.py")]
        paths += ([prefix + name for name in (V6_NAMES if version == 6 else V5_NAMES)]
                  if version in (5, 6) else [prefix + relative(name) for name in names])
        if version == 4:
            paths += [prefix + "methods/__init__.py", prefix + "transports/__init__.py"]
        if extra_source:
            paths.append(prefix + "private_experiment.py")
        payloads = {path: (b'raise AssertionError("captured Python must never execute")\n'
                          if path.endswith(".py") else b"{}" if path.endswith(".json")
                          else b"Inert prompt, not an evaluation.") for path in paths}
        payloads[prefix + "profile.json"] = encoded(profile)
        payloads[prefix + relative("config.json")] = encoded(config)
        payloads[prefix + "configuration.schema.json"] = encoded(schema)
        if version in (5, 6):
            preset = {"control_method": "codex-native/v1", "transport": "codex-exec/v1",
                      "timeout_s": 120, "max_chunk_length": 5, "min_action_decisions_before_give_up": 0,
                      "history": "fixture-public-history", "reasoning_effort": "fixture-effort",
                      "model": "fixture-model", "provider": "fixture-provider",
                      "max_attempts": 10, "retry_backoff_s": 10.0}
            preset_name = "codex_native_config.json"
            if selected_method in ("codex-direct/v2", "codex-planned/v1"):
                planned = selected_method == "codex-planned/v1"
                preset_name = "codex_planned_config.json" if planned else "codex_direct_v2_config.json"
                preset = {"schema_version": "starvla-rsi.codex-planned-config/v1" if planned else "starvla-rsi.codex-direct-config/v2",
                          "control_method": selected_method, "transport": "codex-app-server/v1",
                          "provider": "fixture-provider", "model": "fixture-model", "timeout_s": 120,
                          "max_chunk_length": 5, "image_max_edge": 480, "ordinary_give_up": False,
                          "history": "persistent_same_episode_thread_with_bounded_public_summary" if planned else "persistent_same_episode_thread",
                          "terminal_delivery": "cancel_without_continuation"}
                if planned:
                    # Historical Planned v1's constructor required this True;
                    # the synthetic fixture must preserve that actual preset.
                    preset["safety_stop"] = True
                else:
                    preset.update(enforce_action_guard=True,
                                  public_feedback_schema="robodojo.robot-control-feedback/v1",
                                  workspace_context_version="reference-direct/v2",
                                  required_protocol="robodojo-direct-v2-rgb-proprio28-eef16-robot-feedback-v1")
            payloads[prefix + "configs/" + preset_name] = encoded(preset)
        payloads[prefix + "dependencies.json"] = encoded({
            "schema_version": "starvla-rsi.model-dependencies/v1", "files": sorted(paths),
            "evaluation_dependency": "harness_source/index.json",
            "provider_sdk": {"name": "inert-sdk", "version": None},
        })
        payloads["campaign_prompt.txt"] = b"Inert effective prompt."
        rows = []
        for path, payload in sorted(payloads.items()):
            target = run / "model_source/files" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            rows.append({"path": path, "size_bytes": len(payload), "sha256": digest(payload)})
        identity = {"schema_version": "starvla-rsi.model-profile/v1", "id": "gpt6_astra", "factory": factory,
                    "source_inventory_sha256": digest(encoded([row for row in rows
                                                               if row["path"] != "campaign_prompt.txt"]))}
        for name in ("profile", "config", "prompt", "dependencies"):
            identity[name + "_sha256"] = digest(payloads[prefix + relative(
                name + (".txt" if name == "prompt" else ".json"))])
        source_schema = "starvla-rsi.model-source/v" + str(declared_version or version)
        index = {"schema_version": source_schema, "profile": identity, "files": rows,
                 "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
                 "inventory_sha256": digest(encoded(rows)), "scope": "independent inert source fixture"}
        index_payload = encoded(index)
        (run / "model_source/index.json").write_bytes(index_payload)
        snapshot = {key: index[key] for key in ("schema_version", "file_count", "total_bytes", "inventory_sha256")}
        snapshot.update(path="model_source/index.json", index_sha256=digest(index_payload))
        descriptor = {**policy, "parameters": {"model_profile": identity,
            "prompt_sha256": digest(payloads["campaign_prompt.txt"]),
            "policy_stop_rule": {"stop_constraint_version": "minimum-action-decisions/v2",
                                 "min_action_decisions_before_give_up": 0,
                                 "early_policy_stop_exception": "safety_stop_with_nonempty_note",
                                 "scope": "policy"}}}
        if version in (5, 6):
            descriptor["version"] = selected_method
            descriptor["parameters"].update({
                **{key: preset[key] for key in ("control_method", "transport", "timeout_s", "max_chunk_length",
                                               "history")},
                "effective_config": preset, "preset_sha256": digest(payloads[prefix + "configs/" + preset_name]),
            })
            if selected_method == "codex-native/v1":
                descriptor["parameters"].update({
                "reasoning_effort": preset["reasoning_effort"],
                "max_output_tokens": None, "invalid_action_handling": "feedback",
                "automatic_retry": {"scope": "same_policy_decision_before_action_submission",
                                    "max_attempts": 10, "retry_backoff_s": 10.0},
                })
            else:
                descriptor["parameters"].update(ordinary_give_up=False, image_max_edge=480)
                if selected_method == "codex-direct/v2":
                    descriptor["parameters"].update({key: preset[key] for key in
                        ("enforce_action_guard", "public_feedback_schema", "workspace_context_version")})
        return run, {"policy": descriptor, "model_source": snapshot}, paths

    def inspect_both(self, run, manifest):
        before = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
        with patch("importlib.import_module", side_effect=AssertionError("no dynamic source imports")):
            verify_policy_source(run, manifest["policy"], manifest["model_source"])
            files = audit.ClosedFiles(run)
            count = audit.audit_model_source(files, manifest)
            files.verify_unchanged()
        self.assertEqual(before, {path: path.read_bytes() for path in run.rglob("*") if path.is_file()})
        return count

    def test_exact_historical_v2_v3_and_grouped_v4_extension_inventories(self):
        # Includes campaign_prompt.txt; the grouped layout adds two package markers.
        old_counts = (12, 16, 19, 23, 26, 29)
        for version in (2, 3, 4):
            for depth, old_count in enumerate(old_counts):
                with self.subTest(version=version, extensions=depth):
                    run, manifest, paths = self.fixture(version, extension_count=depth)
                    count = old_count + (2 if version == 4 else 0)
                    self.assertEqual(len(paths) + 1, count)
                    self.assertEqual(self.inspect_both(run, manifest), count)

    def test_current_profile_matches_independent_v6_inventory(self):
        run, manifest, paths = self.fixture(6)
        current = load_profile("gpt6_astra")
        self.assertEqual({row["path"] for row in current["files"]}, set(paths))
        self.assertEqual(current["profile"]["factory"], manifest["policy"]["parameters"]["model_profile"]["factory"])
        self.assertNotIn("AgentPolicies/gpt6_astra/policy.py", paths)
        self.assertEqual(self.inspect_both(run, manifest), 29)
        self.assertFalse(any("extension" in key for key in current["config"]))

    def test_frozen_v5_native_direct_v2_and_planned_keep_exact_sources_and_semantics(self):
        from copy import deepcopy
        for method in ("codex-native/v1", "codex-direct/v2", "codex-planned/v1"):
            run, manifest, paths = self.fixture(5, selected_method=method)
            with self.subTest(method=method):
                self.assertEqual(self.inspect_both(run, manifest), 29)
                self.assertIn("AgentPolicies/gpt6_astra/tools/eef_contract.py", paths)
                self.assertNotIn("AgentPolicies/gpt6_astra/tools/persistent_runtime.py", paths)
                changed = deepcopy(manifest)
                changed["policy"]["parameters"]["effective_config"]["max_chunk_length"] = 33
                with self.assertRaises(ValueError):
                    verify_policy_source(run, changed["policy"], changed["model_source"])
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), changed)
                if method == "codex-direct/v2":
                    for fields in ({"max_chunk_length": 7}, {"enforce_action_guard": False}):
                        changed = deepcopy(manifest)
                        changed["policy"]["parameters"].update(fields)
                        with self.subTest(historical_fields=fields):
                            with self.assertRaises(ValueError):
                                verify_policy_source(run, changed["policy"], changed["model_source"])
                            with self.assertRaises(audit.AuditError):
                                audit.audit_model_source(audit.ClosedFiles(run), changed)

    def test_historical_v4_planned_marker_keeps_34_file_inventory(self):
        run, manifest, paths = self.fixture(4, extension_count=6)
        self.assertEqual(self.inspect_both(run, manifest), 34)
        self.assertIn("AgentPolicies/gpt6_astra/methods/policy.py", paths)
        self.assertNotIn("AgentPolicies/gpt6_astra/tools/factory.py", paths)

    def test_v5_rejects_retired_method_identity_even_when_other_binding_is_valid(self):
        from copy import deepcopy
        run, manifest, _ = self.fixture(5)
        for method in ("responses-native/v1", "openai-responses-direct/v1", "codex-eef/v1",
                       "codex-eef/v2", "codex-direct/v1", "codex-direct/v3", None):
            changed = deepcopy(manifest)
            changed["policy"]["version"] = method
            changed["policy"]["parameters"]["control_method"] = method
            with self.subTest(method=method):
                with self.assertRaises(ValueError):
                    verify_policy_source(run, changed["policy"], changed["model_source"])
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), changed)

    def test_rehashed_v5_registry_cannot_omit_selector_or_restore_historical_markers(self):
        for changes in ({"control_method": None}, {"control_method": "responses-native/v1"},
                        {"codex_native_extension": "native-vectors/v1"}):
            run, manifest, _ = self.fixture(5, config_changes=changes)
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    verify_policy_source(run, manifest["policy"], manifest["model_source"])
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), manifest)

    def test_v6_registry_rejects_retired_direct_v2_and_guard_without_changing_v5(self):
        for changes in ({"control_method": "codex-direct/v2"}, {"enforce_action_guard": True}):
            run, manifest, _ = self.fixture(6, config_changes=changes)
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    verify_policy_source(run, manifest["policy"], manifest["model_source"])
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), manifest)
            run, manifest, _ = self.fixture(5, config_changes=changes)
            self.assertEqual(self.inspect_both(run, manifest), 29)

    def test_rehashed_schema_relabeling_cannot_migrate_paths(self):
        for version, declared in ((2, 3), (3, 2), (3, 4), (4, 3), (4, 5), (5, 4), (5, 6), (6, 5)):
            run, manifest, _ = self.fixture(version, declared_version=declared)
            with self.subTest(version=version, declared=declared):
                with self.assertRaises(ValueError):
                    verify_policy_source(run, manifest["policy"], manifest["model_source"])
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), manifest)

    def test_rehashed_new_factory_is_not_valid_for_historical_flat_bundle(self):
        for version, factory in ((2, "starVLA.gpt6_astra.methods.policy:create_policy"),
                                 (3, "AgentPolicies.gpt6_astra.methods.policy:create_policy"),
                                 (4, "AgentPolicies.gpt6_astra.policy:create_policy"),
                                 (4, "AgentPolicies.gpt6_astra.tools.factory:create_policy"),
                                 (5, "AgentPolicies.gpt6_astra.methods.policy:create_policy")):
            run, manifest, _ = self.fixture(version, factory_override=factory)
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    verify_policy_source(run, manifest["policy"], manifest["model_source"])
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), manifest)

    def test_rehashed_extra_source_does_not_expand_allowlist(self):
        for version in (2, 3, 4, 5, 6):
            run, manifest, _ = self.fixture(version, extra_source=True)
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    verify_policy_source(run, manifest["policy"], manifest["model_source"])
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), manifest)

    def test_standalone_auditor_reads_all_layouts_without_package_imports(self):
        code = """
import json, runpy, sys
from pathlib import Path
auditor = runpy.run_path(sys.argv[1], run_name='isolated_source_audit')
run = Path(sys.argv[2])
files = auditor['ClosedFiles'](run)
auditor['audit_model_source'](files, json.loads((run / 'selection.json').read_text()))
files.verify_unchanged()
assert not any(name.split('.')[0] in {'benchkit','starVLA','AgentPolicies','openai'} for name in sys.modules)
"""
        for version in (2, 3, 4, 5, 6):
            run, manifest, _ = self.fixture(version)
            (run / "selection.json").write_bytes(encoded(manifest))
            result = subprocess.run([sys.executable, "-B", "-S", "-c", code,
                                     str(Path(audit.__file__).resolve()), str(run)], cwd=run,
                                    env={**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
