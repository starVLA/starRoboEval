"""Source schemas bind one exact policy namespace; old evidence is not migrated."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits import closed_run as audit
from benchkit.source_snapshot import inventory_digest


class PolicyNamespaceAuditChecks(unittest.TestCase):
    def anonymous_bundle(self, schema, namespace, *, factory_namespace=None, extra_source=False):
        """Create inert fixtures, including the historical v1/v2 byte layout."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run = Path(temporary.name)
        prefix = f"{namespace}/anonymous_code_agent/"
        legacy = schema == "starvla-rsi.model-source/v1"
        factory = f"{factory_namespace or namespace}.anonymous_code_agent.policy:create_policy"
        policy = {"name": "code-agent-development", "kind": "external-code-agent",
                  "model": None, "provider": None}
        profile = {"schema_version": "starvla-rsi.model-profile/v1", "id": "anonymous_code_agent",
                   "display_name": "Anonymous code agent", "configured": True,
                   "factory": factory, "policy": policy}
        config = {"schema_version": "starvla-rsi.model-config/v1", "profile_id": "anonymous_code_agent",
                  "transport": "mailbox", "history": "current_observation_only", "max_response_bytes": 8192}
        if not legacy:
            config.update(policy_stop_rule_version="minimum-action-decisions/v2",
                          min_action_decisions_before_give_up=0)
        common = (("__init__.py", "model_profiles.py", "providers/__init__.py", "providers/mailbox.py")
                  if legacy else ("__init__.py", "policy_support/__init__.py", "policy_support/stop_rules.py",
                                  "anonymous_code_agent/mailbox.py",
                                  "anonymous_code_agent/prompts/control_guidance.txt",
                                  "anonymous_code_agent/prompts/actor_instructions.txt",
                                  "anonymous_code_agent/prompts/simpler_development.txt"))
        payloads = {f"{namespace}/{name}": b'raise AssertionError("must not import fixture")\n'
                    for name in common}
        payloads.update({prefix + "__init__.py": b"# inert initializer\n",
                         prefix + "policy.py": b'raise AssertionError("must not execute fixture")\n',
                         prefix + "profile.json": json.dumps(profile).encode(),
                         prefix + "config.json": json.dumps(config).encode(),
                         prefix + "prompt.txt": b"Inert policy prompt.",
                         "campaign_prompt.txt": b"Inert effective prompt."})
        if extra_source:
            payloads[prefix + "results/private.txt"] = b"Excluded neighboring result."
        dependencies = {"schema_version": "starvla-rsi.model-dependencies/v1",
                        "files": sorted((set(payloads) - {"campaign_prompt.txt"}) | {prefix + "dependencies.json"}),
                        "evaluation_dependency": "harness_source/index.json", "provider_sdk": None}
        payloads[prefix + "dependencies.json"] = json.dumps(dependencies).encode()
        rows = []
        for relative, payload in sorted(payloads.items()):
            path = run / "model_source/files" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            rows.append({"path": relative, "size_bytes": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()})
        identity = {"schema_version": "starvla-rsi.model-profile/v1", "id": "anonymous_code_agent",
                    "factory": factory,
                    "source_inventory_sha256": inventory_digest([row for row in rows
                                                                  if row["path"] != "campaign_prompt.txt"])}
        for name in ("profile", "config", "prompt", "dependencies"):
            suffix = ".txt" if name == "prompt" else ".json"
            identity[name + "_sha256"] = hashlib.sha256(payloads[prefix + name + suffix]).hexdigest()
        index = {"schema_version": schema, "profile": identity, "files": rows,
                 "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
                 "inventory_sha256": inventory_digest(rows), "scope": "inert namespace regression fixture"}
        index_path = run / "model_source/index.json"
        index_path.write_text(json.dumps(index))
        snapshot = {key: index[key] for key in ("schema_version", "file_count", "total_bytes", "inventory_sha256")}
        snapshot.update(path="model_source/index.json", index_sha256=hashlib.sha256(index_path.read_bytes()).hexdigest())
        descriptor = {**policy, "parameters": {"model_profile": identity,
                      "prompt_sha256": hashlib.sha256(payloads["campaign_prompt.txt"]).hexdigest()}}
        return run, {"policy": descriptor, "model_source": snapshot}

    def test_historical_v1_v2_and_current_v3_are_read_without_import_or_rewrite(self):
        for version, namespace in ((1, "starVLA"), (2, "starVLA"), (3, "AgentPolicies")):
            with self.subTest(version=version):
                run, manifest = self.anonymous_bundle(f"starvla-rsi.model-source/v{version}", namespace)
                before = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
                files = audit.ClosedFiles(run)
                with patch("importlib.import_module", side_effect=AssertionError("no factory imports")):
                    count = audit.audit_model_source(files, manifest)
                files.verify_unchanged()
                self.assertEqual(count, manifest["model_source"]["file_count"])
                self.assertEqual(before, {path: path.read_bytes() for path in run.rglob("*") if path.is_file()})

    def test_schema_namespace_pairs_cannot_be_substituted(self):
        for version, namespace in ((1, "AgentPolicies"), (2, "AgentPolicies"), (3, "starVLA")):
            with self.subTest(version=version, namespace=namespace):
                run, manifest = self.anonymous_bundle(f"starvla-rsi.model-source/v{version}", namespace)
                with self.assertRaises(audit.AuditError):
                    audit.audit_model_source(audit.ClosedFiles(run), manifest)

    def test_rehashed_profile_cannot_substitute_old_factory_in_new_namespace(self):
        run, manifest = self.anonymous_bundle("starvla-rsi.model-source/v3", "AgentPolicies",
                                              factory_namespace="starVLA")
        with self.assertRaisesRegex(audit.AuditError, "profile semantics"):
            audit.audit_model_source(audit.ClosedFiles(run), manifest)

    def test_rehashed_new_namespace_does_not_expand_captured_allowlist(self):
        run, manifest = self.anonymous_bundle("starvla-rsi.model-source/v3", "AgentPolicies", extra_source=True)
        with self.assertRaisesRegex(audit.AuditError, "reviewed allowlist"):
            audit.audit_model_source(audit.ClosedFiles(run), manifest)

    def test_new_namespace_does_not_promote_anonymous_results_to_named_identity(self):
        run, manifest = self.anonymous_bundle("starvla-rsi.model-source/v3", "AgentPolicies")
        for key in ("model", "provider"):
            changed = deepcopy(manifest)
            changed["policy"][key] = "claimed-by-directory-name"
            with self.subTest(key=key), self.assertRaisesRegex(audit.AuditError, "captured model identity"):
                audit.audit_model_source(audit.ClosedFiles(run), changed)

    def test_current_named_profile_keeps_model_provider_identity_checks(self):
        from benchkit.model_profiles import capture_policy_source, create_policy

        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            with patch("AgentPolicies.gpt6_astra.transports.codex_cli.send", side_effect=AssertionError("no inference")):
                policy = create_policy("gpt6_astra")
                snapshot = capture_policy_source(run, policy)
            self.assertEqual(snapshot["schema_version"], "starvla-rsi.model-source/v6")
            manifest = {"policy": policy.descriptor.to_dict(), "model_source": snapshot}
            with patch("importlib.import_module", side_effect=AssertionError("no captured imports")):
                self.assertEqual(audit.audit_model_source(audit.ClosedFiles(run), manifest), snapshot["file_count"])
                for key in ("model", "provider"):
                    changed = deepcopy(manifest)
                    changed["policy"][key] = "not-the-captured-identity"
                    with self.subTest(key=key), self.assertRaisesRegex(audit.AuditError, "captured model identity"):
                        audit.audit_model_source(audit.ClosedFiles(run), changed)


if __name__ == "__main__":
    unittest.main()
