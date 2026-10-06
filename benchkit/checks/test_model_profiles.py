"""CPU-only profile/source guards; no provider request or native episode."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from benchkit.campaigns.workflow import prepare, run_case, verify_frozen_package
from benchkit.model_profiles import (
    UnconfiguredModelProfile, capture_model_source, capture_policy_source, create_policy,
    load_profile, verify_policy_source,
)


class ModelProfileChecks(unittest.TestCase):
    def prepare_profile(self, root, **parameters):
        return prepare(root / "campaign", "libero", root / "mailboxes", "Use declared sensors.",
                       model_profile="anonymous_code_agent", **parameters)

    def test_frozen_factory_and_descriptor_are_self_contained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_profile(root)
            verify_frozen_package(root / "campaign", manifest)
            frozen = root / "campaign/frozen"
            code = (
                "import json,sys; from pathlib import Path; "
                "from benchkit.model_profiles import create_policy; "
                "p=create_policy('anonymous_code_agent',directory=sys.argv[1]); "
                "import AgentPolicies.anonymous_code_agent.policy as factory; "
                "import AgentPolicies.anonymous_code_agent.mailbox as bridge; "
                "print(json.dumps({'descriptor':p.descriptor.to_dict(),"
                "'factory':factory.__file__,'bridge':bridge.__file__})); "
                "assert not {'torch','openai','anthropic'} & set(sys.modules)"
            )
            result = subprocess.run([sys.executable, "-c", code, str(root / "endpoint")], cwd=frozen,
                env={**os.environ, "PYTHONPATH": str(frozen), "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, text=True, check=True, timeout=30)
            recorded = json.loads(result.stdout)
            for field in ("factory", "bridge"):
                self.assertTrue(Path(recorded[field]).is_relative_to(frozen.resolve()))
            descriptor = recorded["descriptor"]
            self.assertEqual(descriptor["parameters"]["model_profile"], manifest["model_profile"])
            self.assertIsNone(descriptor["model"])
            self.assertIsNone(descriptor["provider"])
            self.assertNotIn("min_action_decisions_before_give_up", manifest)
            self.assertEqual(manifest["schema_version"], "starvla-rsi.campaign/v3")

    def test_all_source_types_and_both_copies_reject_tampering_before_claim(self):
        for relative in (
            "frozen/AgentPolicies/anonymous_code_agent/policy.py",
            "frozen/AgentPolicies/anonymous_code_agent/config.json",
            "frozen/AgentPolicies/anonymous_code_agent/prompt.txt",
            "frozen/AgentPolicies/anonymous_code_agent/dependencies.json",
            "frozen/AgentPolicies/anonymous_code_agent/mailbox.py",
            "model_source/files/AgentPolicies/anonymous_code_agent/prompt.txt",
            "model_source/files/campaign_prompt.txt",
            "model_source/index.json",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.prepare_profile(root)
                path = root / "campaign" / relative
                path.write_bytes(path.read_bytes() + b"\nchanged")
                with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                    with self.assertRaises(ValueError):
                        run_case(root / "campaign", 0, 0)
                    launch.assert_not_called()
                self.assertFalse((root / "campaign/case-000").exists())

    def test_unlisted_hidden_extensionless_and_nested_result_files_are_rejected(self):
        for relative in ("frozen/AgentPolicies/policy_support/.env", "frozen/AgentPolicies/policy_support/extra",
                         "frozen/AgentPolicies/anonymous_code_agent/results/run/result.json",
                         "model_source/files/AgentPolicies/anonymous_code_agent/extra.txt"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest = self.prepare_profile(root)
                path = root / "campaign" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unexpected")
                with self.assertRaises(ValueError):
                    verify_frozen_package(root / "campaign", manifest)

    def test_dependency_allowlist_excludes_results_and_rejects_external_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = load_profile("anonymous_code_agent")
            for relative, payload in data["payloads"].items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            results = root / "AgentPolicies/anonymous_code_agent/results/oldrun"
            results.mkdir(parents=True)
            (results / "secret.json").write_text('{"must_not_copy": true}')
            (root / "AgentPolicies/anonymous_code_agent/.env").write_text("MUST_NOT_COPY=1")
            output = root / "AgentPolicies/anonymous_code_agent/results/newrun/campaign"
            output.mkdir(parents=True)
            _, snapshot = capture_model_source(output, "anonymous_code_agent", "prompt", repository=root)
            index = json.loads((output / snapshot["path"]).read_text())
            self.assertEqual({row["path"] for row in index["files"]}, set(data["payloads"]) | {"campaign_prompt.txt"})
            declaration = root / "AgentPolicies/anonymous_code_agent/dependencies.json"
            changed = json.loads(declaration.read_text())
            changed["files"].append("../credentials.json")
            declaration.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "dependency declaration"):
                load_profile("anonymous_code_agent", repository=root)

    def test_source_and_frozen_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_profile(root)
            path = root / "campaign/frozen/AgentPolicies/anonymous_code_agent/prompt.txt"
            saved = path.read_bytes()
            path.unlink()
            outside = root / "outside.txt"
            outside.write_bytes(saved)
            path.symlink_to(outside)
            with self.assertRaises(ValueError):
                verify_frozen_package(root / "campaign", manifest)

    def test_empty_unlisted_directory_is_not_a_valid_frozen_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_profile(root)
            (root / "campaign/frozen/AgentPolicies/policy_support/extra").mkdir()
            with self.assertRaisesRegex(ValueError, "unexpected directory"):
                verify_frozen_package(root / "campaign", manifest)

    def test_undeclared_config_fields_are_not_captured(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, payload in load_profile("anonymous_code_agent")["payloads"].items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            config = root / "AgentPolicies/anonymous_code_agent/config.json"
            changed = json.loads(config.read_text())
            changed["api_key"] = "must-not-capture"
            config.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                load_profile("anonymous_code_agent", repository=root)

    def test_named_scaffolds_refuse_before_cases_factory_and_endpoint(self):
        for profile_id in ("opus",):
            with self.subTest(profile_id=profile_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.assertFalse(load_profile(profile_id, require_configured=False)["profile"]["configured"])
                with patch("benchkit.campaigns.workflow.cases_for") as native, patch(
                        "benchkit.model_profiles.importlib.import_module") as factory:
                    with self.assertRaises(UnconfiguredModelProfile):
                        create_policy(profile_id, directory=root / "endpoint")
                    with self.assertRaises(UnconfiguredModelProfile):
                        prepare(root / "campaign", "libero", root / "mailboxes", "prompt", model_profile=profile_id)
                    native.assert_not_called()
                    factory.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_config_identity_and_source_identity_cannot_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_profile(root)
            for key in ("config_sha256", "source_inventory_sha256", "dependencies_sha256"):
                changed = deepcopy(manifest)
                changed["model_profile"][key] = "0" * 64
                with self.assertRaises(ValueError):
                    verify_frozen_package(root / "campaign", changed)
            changed = deepcopy(manifest)
            changed.pop("model_profile")
            changed.pop("model_source")
            with self.assertRaises(ValueError):
                verify_frozen_package(root / "campaign", changed)
            with self.assertRaisesRegex(ValueError, "unsupported profile policy parameters"):
                create_policy("anonymous_code_agent", directory=root / "endpoint", model="Opus")

    def test_profile_schema_downgrade_and_removed_extensions_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_profile(root)
            manifest["schema_version"] = "starvla-rsi.campaign/v1"
            with self.assertRaisesRegex(ValueError, "legacy campaign cannot override runtime namespace"):
                verify_frozen_package(root / "campaign", manifest)
            manifest.pop("runtime_namespace")
            with self.assertRaisesRegex(ValueError, "require campaign/v2"):
                verify_frozen_package(root / "campaign", manifest)
            manifest.pop("model_profile")
            manifest.pop("model_source")
            (root / "campaign/model_source").rename(root / "retained-model-source")
            with self.assertRaisesRegex(ValueError, "require campaign/v2"):
                verify_frozen_package(root / "campaign", manifest)

    def test_profile_campaign_command_freezes_floor_and_factory_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_profile(root, min_action_decisions_before_give_up=50)
            verify_frozen_package(root / "campaign", manifest)
            self.assertEqual(manifest["policy_parameters"]["min_action_decisions_before_give_up"], 50)
            self.assertNotIn("min_action_decisions_before_give_up", manifest)
            self.assertIn("complete at least 50 non-stop action decisions", manifest["policy_prompt"])
            child = MagicMock()
            child.wait.return_value = 0
            with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                launch.return_value.__enter__.return_value = child
                run_case(root / "campaign", 0, 0)
                command = launch.call_args.args[0]
            self.assertNotIn("--policy", command)
            self.assertEqual(command[command.index("--model-profile") + 1], "anonymous_code_agent")
            self.assertNotIn("--min-action-decisions-before-give-up", command)
            self.assertEqual(json.loads(command[command.index("--policy-args") + 1])["min_action_decisions_before_give_up"], 50)
            self.assertEqual(set(json.loads(command[command.index("--policy-args") + 1])),
                             {"directory", "prompt", "timeout_s", "max_chunk_length", "min_action_decisions_before_give_up"})
            for value in (49, True, 0):
                changed = {**manifest, "policy_parameters": {"min_action_decisions_before_give_up": value}}
                with self.assertRaises(ValueError):
                    verify_frozen_package(root / "campaign", changed)

    def test_new_default_campaign_explicitly_binds_anonymous_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = prepare(root / "campaign", "libero", root / "mailboxes", "original prompt")
            self.assertEqual(manifest["schema_version"], "starvla-rsi.campaign/v3")
            self.assertEqual(manifest["model_profile"]["id"], "anonymous_code_agent")
            self.assertEqual(manifest["model_source"]["schema_version"], "starvla-rsi.model-source/v6")
            self.assertEqual(manifest["policy_parameters"], {"min_action_decisions_before_give_up": 0})
            self.assertNotIn("min_action_decisions_before_give_up", manifest)
            self.assertTrue((root / "campaign/frozen/benchkit/campaigns/workflow.py").is_file())
            self.assertFalse((root / "campaign/frozen/AgentPolicies/evaluation").exists())
            verify_frozen_package(root / "campaign", manifest)

    def test_standalone_bundle_binds_effective_prompt_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = create_policy("anonymous_code_agent", directory=root / "endpoint", prompt="custom effective prompt")
            run_dir = root / "run"
            run_dir.mkdir()
            snapshot = capture_policy_source(run_dir, policy)
            verify_policy_source(run_dir, policy.descriptor.to_dict(), snapshot)
            self.assertTrue((run_dir / "model_source/files/AgentPolicies/__init__.py").is_file())
            self.assertEqual((run_dir / "model_source/files/campaign_prompt.txt").read_text(), "custom effective prompt")
            changed = policy.descriptor.to_dict()
            changed["parameters"]["prompt_sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                verify_policy_source(run_dir, changed, snapshot)
            path = run_dir / "model_source/files/AgentPolicies/anonymous_code_agent/config.json"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(ValueError):
                verify_policy_source(run_dir, policy.descriptor.to_dict(), snapshot)

    def test_runner_captures_profile_before_episode_and_rejects_source_drift(self):
        from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
        from benchkit.diagnostics.smoke import ReachBenchmark

        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                policy = create_policy("anonymous_code_agent", directory=root / "endpoint")
                if changed:
                    policy.descriptor.parameters["model_profile"]["config_sha256"] = "0" * 64
                benchmark = ReachBenchmark()
                runner = EvaluationRunner()
                request = RunRequest(root, run_id="run", episode_limit=1)
                with patch.object(benchmark, "open_episode") as native, patch.object(
                        runner, "_run_episode", side_effect=RuntimeError("after source capture")) as episode:
                    with self.assertRaises(ValueError if changed else RuntimeError):
                        runner.run(benchmark, policy, request)
                    native.assert_not_called()
                    self.assertEqual(episode.call_count, 0 if changed else 1)
                if not changed:
                    manifest = json.loads((root / "run/manifest.json").read_text())
                    verify_policy_source(root / "run", manifest["policy"], manifest["model_source"])
                else:
                    self.assertTrue((root / "run/initialization_error.json").is_file())
                    self.assertFalse((root / "run/manifest.json").exists())

    def test_policy_persistence_may_exceed_the_shared_evaluation_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_profile(root, decisions=2, min_action_decisions_before_give_up=50)
            self.assertEqual(manifest["max_policy_calls"], 2)
            self.assertEqual(manifest["policy_parameters"]["min_action_decisions_before_give_up"], 50)
            verify_frozen_package(root / "campaign", manifest)

    def test_campaign_inherits_profile_stop_rule_unless_explicitly_overridden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "fixture-profile"
            real_load = load_profile
            for relative, payload in real_load("anonymous_code_agent")["payloads"].items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            config_path = source / "AgentPolicies/anonymous_code_agent/config.json"
            config = json.loads(config_path.read_text())
            config["min_action_decisions_before_give_up"] = 50
            config_path.write_text(json.dumps(config))

            def fixture_load(profile_id, **kwargs):
                kwargs["repository"] = source
                return real_load(profile_id, **kwargs)

            with patch("benchkit.model_profiles.load_profile", side_effect=fixture_load):
                inherited = prepare(root / "inherited", "libero", root / "endpoints", "prompt")
                disabled = prepare(root / "disabled", "libero", root / "endpoints", "prompt",
                                   min_action_decisions_before_give_up=0)
            self.assertEqual(inherited["policy_parameters"]["min_action_decisions_before_give_up"], 50)
            self.assertEqual(disabled["policy_parameters"]["min_action_decisions_before_give_up"], 0)
            verify_frozen_package(root / "inherited", inherited)
            verify_frozen_package(root / "disabled", disabled)

if __name__ == "__main__":
    unittest.main()
