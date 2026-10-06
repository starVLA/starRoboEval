"""Exact policy source namespaces, including immutable historical bundles."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.artifacts import atomic_write_json
from benchkit.model_profiles import (
    LEGACY_SOURCE_SCHEMA, PREVIOUS_SOURCE_SCHEMA, FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA,
    _allowed_files, _captured_driver_paths, _profile_data, load_profile,
    capture_model_source, verify_model_source, verify_policy_source,
)
from benchkit.source_snapshot import inventory_digest
from AgentPolicies.policy_support.stop_rules import stop_constraint


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _bundle(output, schema):
    """Build deterministic old-layout data, without executing historical code."""
    namespace = "AgentPolicies" if schema in (FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA) else "starVLA"
    current = load_profile("anonymous_code_agent")
    allowed = _allowed_files("anonymous_code_agent", source_schema=schema)
    payloads = {path: current["payloads"].get(
        path.replace("starVLA/", "AgentPolicies/", 1), b"# historical fixture only\n")
        for path in allowed}
    prefix = namespace + "/anonymous_code_agent/"
    profile = json.loads(payloads[prefix + "profile.json"])
    profile["factory"] = namespace + ".anonymous_code_agent.policy:create_policy"
    payloads[prefix + "profile.json"] = json.dumps(profile).encode()
    config = json.loads(payloads[prefix + "config.json"])
    if schema == LEGACY_SOURCE_SCHEMA:
        config.pop("policy_stop_rule_version")
        config.pop("min_action_decisions_before_give_up")
    payloads[prefix + "config.json"] = json.dumps(config).encode()
    dependencies = json.loads(payloads[prefix + "dependencies.json"])
    dependencies["files"] = list(allowed)
    payloads[prefix + "dependencies.json"] = json.dumps(dependencies).encode()
    data = _profile_data("anonymous_code_agent", payloads, require_configured=True,
                         source_schema=schema)
    prompt = b"Read declared sensors only."
    payloads["campaign_prompt.txt"] = prompt
    rows = []
    for relative, payload in sorted(payloads.items()):
        target = output / "model_source/files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if relative != "campaign_prompt.txt":
            frozen = output / "frozen" / relative
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes(payload)
        rows.append({"path": relative, "size_bytes": len(payload), "sha256": _sha(payload)})
    index = {"schema_version": schema, "profile": data["identity"], "files": rows,
             "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
             "inventory_sha256": inventory_digest(rows), "scope": "synthetic historical fixture"}
    atomic_write_json(output / "model_source/index.json", index)
    snapshot = {key: index[key] for key in
                ("schema_version", "inventory_sha256", "file_count", "total_bytes")}
    snapshot.update(path="model_source/index.json",
                    index_sha256=_sha((output / "model_source/index.json").read_bytes()))
    manifest = {"model_source": snapshot, "model_profile": data["identity"],
                "policy": data["profile"]["policy"], "policy_prompt": prompt.decode(),
                "policy_prompt_sha256": _sha(prompt)}
    descriptor = {**data["profile"]["policy"], "parameters": {
        "model_profile": data["identity"], "prompt_sha256": _sha(prompt),
        "policy_stop_rule": stop_constraint(0)}}
    return manifest, descriptor, data


class PolicyNamespaceChecks(unittest.TestCase):
    def test_new_capture_uses_v5_namespace_and_no_legacy_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity, snapshot = capture_model_source(root, "anonymous_code_agent", "bounded prompt")
            self.assertEqual(snapshot["schema_version"], "starvla-rsi.model-source/v6")
            self.assertEqual(identity["factory"], "AgentPolicies.anonymous_code_agent.policy:create_policy")
            index = json.loads((root / snapshot["path"]).read_text())
            self.assertTrue(all(row["path"].startswith("AgentPolicies/")
                                or row["path"] == "campaign_prompt.txt" for row in index["files"]))
            self.assertFalse((root / "frozen/starVLA").exists())

    def test_each_schema_verifies_original_namespace_without_importing_captured_code(self):
        for schema in (LEGACY_SOURCE_SCHEMA, PREVIOUS_SOURCE_SCHEMA, FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest, descriptor, _ = _bundle(root, schema)
                original_index = (root / "model_source/index.json").read_bytes()
                with patch("benchkit.model_profiles.importlib.import_module",
                           side_effect=AssertionError("captured source must not execute")):
                    verified = verify_model_source(root, manifest)
                    verify_policy_source(root, descriptor, manifest["model_source"])
                self.assertEqual(verified["identity"], manifest["model_profile"])
                self.assertEqual((root / "model_source/index.json").read_bytes(), original_index)

    def test_historical_v2_still_checks_stop_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, descriptor, _ = _bundle(root, PREVIOUS_SOURCE_SCHEMA)
            descriptor["parameters"]["policy_stop_rule"] = {}
            with self.assertRaises(ValueError):
                verify_policy_source(root, descriptor, manifest["model_source"])

    def test_corrupted_and_mixed_frozen_namespaces_fail_for_every_schema(self):
        for schema in (LEGACY_SOURCE_SCHEMA, PREVIOUS_SOURCE_SCHEMA, FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA):
            for kind in ("corrupted", "mixed"):
                with self.subTest(schema=schema, kind=kind), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    manifest, _, _ = _bundle(root, schema)
                    namespace = "AgentPolicies" if schema in (FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA) else "starVLA"
                    if kind == "corrupted":
                        path = root / "frozen" / namespace / "anonymous_code_agent/prompt.txt"
                        path.write_bytes(path.read_bytes() + b"changed")
                    else:
                        other = "starVLA" if namespace == "AgentPolicies" else "AgentPolicies"
                        (root / "frozen" / other).mkdir()
                    with self.assertRaises(ValueError):
                        verify_model_source(root, manifest)

    def test_relabeling_schema_does_not_migrate_a_bundle(self):
        for original, changed in ((SOURCE_SCHEMA, PREVIOUS_SOURCE_SCHEMA),
                                  (PREVIOUS_SOURCE_SCHEMA, SOURCE_SCHEMA),
                                  (LEGACY_SOURCE_SCHEMA, SOURCE_SCHEMA)):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest, descriptor, _ = _bundle(root, original)
                index = json.loads((root / "model_source/index.json").read_text())
                index["schema_version"] = changed
                atomic_write_json(root / "model_source/index.json", index)
                snapshot = deepcopy(manifest["model_source"])
                snapshot.update(schema_version=changed,
                                index_sha256=_sha((root / "model_source/index.json").read_bytes()))
                with self.assertRaises(ValueError):
                    verify_policy_source(root, descriptor, snapshot)

    def test_factory_and_dependency_namespace_are_exact_not_alternatives(self):
        for schema in (LEGACY_SOURCE_SCHEMA, PREVIOUS_SOURCE_SCHEMA, FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA):
            for field in ("profile.json", "dependencies.json"):
                with self.subTest(schema=schema, field=field), tempfile.TemporaryDirectory() as temporary:
                    _, _, data = _bundle(Path(temporary), schema)
                    namespace = "AgentPolicies" if schema in (FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA) else "starVLA"
                    other = "starVLA" if namespace == "AgentPolicies" else "AgentPolicies"
                    path = namespace + "/anonymous_code_agent/" + field
                    payloads = dict(data["payloads"])
                    value = json.loads(payloads[path])
                    if field == "profile.json":
                        value["factory"] = other + ".anonymous_code_agent.policy:create_policy"
                    else:
                        value["files"][0] = value["files"][0].replace(namespace + "/", other + "/", 1)
                    payloads[path] = json.dumps(value).encode()
                    with self.assertRaises(ValueError):
                        _profile_data("anonymous_code_agent", payloads, require_configured=True,
                                      source_schema=schema)

    def test_driver_allowlist_is_schema_specific(self):
        for schema in (PREVIOUS_SOURCE_SCHEMA, FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA):
            for mixed in (False, True):
                with self.subTest(schema=schema, mixed=mixed), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    namespace = "AgentPolicies" if schema in (FLAT_AGENT_SOURCE_SCHEMA, SOURCE_SCHEMA) else "starVLA"
                    if mixed:
                        namespace = "starVLA" if namespace == "AgentPolicies" else "AgentPolicies"
                    path = namespace + "/policy_support/runner.py"
                    payload = b"# captured driver, never executed\n"
                    rows = [{"path": path, "size_bytes": len(payload), "sha256": _sha(payload)}]
                    for base in ("harness_source/files", "frozen"):
                        target = root / base / path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(payload)
                    index = {"schema_version": "starvla-rsi.harness-source/v2", "files": rows}
                    atomic_write_json(root / "harness_source/index.json", index)
                    reference = {"path": "harness_source/index.json", "files_root": "harness_source/files",
                        "index_sha256": _sha((root / "harness_source/index.json").read_bytes()),
                        "inventory_sha256": inventory_digest(rows)}
                    if mixed:
                        with self.assertRaises(ValueError):
                            _captured_driver_paths(root, reference, source_schema=schema)
                    else:
                        self.assertEqual(_captured_driver_paths(root, reference, source_schema=schema), {path})


if __name__ == "__main__":
    unittest.main()
