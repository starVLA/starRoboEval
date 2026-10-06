"""Direct-profile assembly and frozen-data checks; no provider or native calls."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchkit.artifacts import atomic_write_json
from benchkit.campaigns.workflow import digest, main, prepare, run_case, verify_frozen_package
from benchkit.model_profiles import create_policy, load_profile, validate_configuration


class ConfigurationSchemaChecks(unittest.TestCase):
    def setUp(self):
        self.config = {"transport": "direct-fixture", "max_output_tokens": 4096,
                       "timeout_s": 120, "enabled": True}
        self.schema = {"schema_version": "starvla-rsi.configuration-schema/v1", "profile_id": "fixture",
                       "execution": "direct", "factory_parameters": ["prompt", "timeout_s"], "fields": {
                           "transport": {"type": "string", "const": "direct-fixture"},
                           "max_output_tokens": {"type": "integer", "minimum": 1, "maximum": 8192},
                           "timeout_s": {"type": "number", "minimum": 1, "maximum": 900},
                           "enabled": {"type": "boolean", "enum": [True]},
                       }}

    def test_declaration_accepts_scalar_bounds_and_output_token_field(self):
        self.assertEqual(validate_configuration("fixture", self.config, self.schema),
                         {"execution": "direct", "factory_parameters": ("prompt", "timeout_s")})

    def test_unknown_missing_untyped_nonfinite_and_out_of_range_fields_are_rejected(self):
        for change in ({"extra": "value"}, {"max_output_tokens": True}, {"max_output_tokens": 4096.0},
                       {"max_output_tokens": 0}, {"max_output_tokens": 8193}, {"timeout_s": float("inf")},
                       {"enabled": False}, {"transport": "other"}, {"transport": ["direct-fixture"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_configuration("fixture", {**self.config, **change}, self.schema)
        missing = dict(self.config)
        missing.pop("enabled")
        with self.assertRaises(ValueError):
            validate_configuration("fixture", missing, self.schema)

    def test_schema_cannot_allow_credentials_or_execute_validators(self):
        for credential in ("api_key", "authorization", "credentials", "client_secret", "password", "access_token",
                           "openai_api_key", "provider_token"):
            with self.subTest(credential=credential):
                schema = deepcopy(self.schema)
                schema["fields"][credential] = {"type": "string"}
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    validate_configuration("fixture", {**self.config, credential: "synthetic"}, schema)
        for change in ({"validator": "arbitrary.module:execute"}, {"factory_parameters": ["directory"]},
                       {"execution": "arbitrary"}, {"execution": []}, {"profile_id": "other"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_configuration("fixture", self.config, {**self.schema, **change})


class DirectProfileChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prepare_direct(self):
        return prepare(self.root / "campaign", "libero", prompt="Use only the declared observations.",
                       model_profile="gpt6_astra")

    def test_declared_profile_and_pinned_cli_dependency_are_explicit(self):
        data = load_profile("gpt6_astra")
        self.assertEqual(data["execution"], "direct")
        self.assertTrue(data["profile"]["configured"])
        self.assertEqual(data["profile"]["policy"]["model"], "gpt-6-astra")
        self.assertEqual(data["profile"]["policy"]["provider"], "openai")
        self.assertNotIn("directory", data["factory_parameters"])
        dependencies = json.loads(data["payloads"]["AgentPolicies/gpt6_astra/dependencies.json"])
        self.assertEqual(dependencies["provider_sdk"], {"name": "codex-cli", "version": "0.154.0"})
        self.assertTrue({"AgentPolicies/gpt6_astra/transports/codex_cli.py", "AgentPolicies/gpt6_astra/configuration.schema.json"}
                        <= set(dependencies["files"]))

    def test_direct_directory_override_is_rejected_before_factory_import(self):
        with patch("benchkit.model_profiles.importlib.import_module") as factory:
            with self.assertRaisesRegex(ValueError, "unsupported profile policy parameters"):
                create_policy("gpt6_astra", directory=self.root / "must-not-exist")
            factory.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_direct_override_bounds_are_checked_before_factory_import_or_preparation(self):
        for parameters in ({"max_chunk_length": 33}, {"timeout_s": 3601}, {"max_chunk_length": True}):
            with self.subTest(parameters=parameters), patch("benchkit.model_profiles.importlib.import_module") as factory:
                with self.assertRaises(ValueError):
                    create_policy("gpt6_astra", **parameters)
                factory.assert_not_called()
        for parameters in ({"prefix": 33}, {"response_timeout_s": 3601}):
            with self.subTest(parameters=parameters), self.assertRaisesRegex(ValueError, "declared bounds"):
                prepare(self.root / "campaign", "libero", prompt="prompt", model_profile="gpt6_astra", **parameters)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_constructs_direct_profile_without_mailbox_or_provider_calls(self):
        from benchkit.cli import _run, build_parser

        args = build_parser().parse_args(["run", "--benchmark", "smoke-reach", "--model-profile", "gpt6_astra",
                                         "--output-dir", str(self.root / "output")])
        with patch("benchkit.cli.EvaluationRunner") as runner, patch("benchkit.cli.create_benchmark") as benchmark, \
                patch("benchkit.model_profiles.preflight_policy") as preflight:
            runner.return_value.run.return_value = self.root / "unused-run"
            self.assertEqual(_run(args), self.root / "unused-run")
            policy = runner.return_value.run.call_args.args[1]
            self.assertEqual(policy.descriptor.model, "gpt-6-astra")
            self.assertNotIn("directory", policy.descriptor.parameters)
            benchmark.assert_called_once()
            preflight.assert_called_once_with(policy)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_prepare_cli_omits_mailbox_and_retains_existing_envelopes(self):
        prompt = self.root / "prompt.txt"
        prompt.write_text("Use only the declared observations.")
        with patch.object(sys, "argv", ["campaign", "prepare", "--benchmark", "libero",
                "--output-dir", str(self.root / "campaign"), "--prompt-file", str(prompt),
                "--model-profile", "gpt6_astra"]):
            self.assertEqual(main(), 0)
        manifest = json.loads((self.root / "campaign/campaign.json").read_text())
        self.assertEqual(manifest["schema_version"], "starvla-rsi.campaign/v3")
        self.assertEqual(manifest["model_source"]["schema_version"], "starvla-rsi.model-source/v6")
        self.assertEqual(manifest["policy_execution"], "direct")
        self.assertEqual(manifest["response_timeout_s"], load_profile("gpt6_astra")["config"]["timeout_s"])
        self.assertTrue(all("policy_endpoint" not in case for case in manifest["cases"]))
        verify_frozen_package(self.root / "campaign", manifest)

    def test_documented_prepare_command_uses_profile_defaults_without_inference(self):
        repository = Path(__file__).resolve().parents[2]
        output = self.root / "campaign"
        environment = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
        result = subprocess.run([sys.executable, "-B", "-m", "benchkit.campaigns", "prepare",
            "--benchmark", "simpler_env", "--model-profile", "gpt6_astra", "--output-dir", str(output)],
            cwd=repository, env={**environment, "PYTHONPATH": str(repository), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((output / "campaign.json").read_text())
        profile = load_profile("gpt6_astra")
        self.assertEqual(manifest["policy_prompt"], profile["prompt"])
        self.assertEqual((output / "model_source/files/campaign_prompt.txt").read_bytes(),
                         profile["prompt"].encode("utf-8"))
        self.assertEqual(manifest["response_timeout_s"], 300)
        self.assertEqual(manifest["planned_cases"], 15)
        self.assertTrue(all("policy_endpoint" not in case for case in manifest["cases"]))
        self.assertFalse(any((output / case["case_id"]).exists() for case in manifest["cases"]))
        verify_frozen_package(output, manifest)

    def test_mailbox_prompt_remains_required_and_default_timeout_is_900(self):
        for prompt in ("", "   "):
            with self.subTest(prompt=prompt), self.assertRaisesRegex(ValueError, "nonempty frozen policy prompt"):
                prepare(self.root / "campaign", "libero", self.root / "endpoints", prompt)
            self.assertEqual(list(self.root.iterdir()), [])
        prompt_file = self.root / "prompt.txt"
        prompt_file.write_text("Synthetic mailbox prompt.")
        with patch.object(sys, "argv", ["campaign", "prepare", "--benchmark", "libero",
                "--output-dir", str(self.root / "campaign"), "--mailbox-root", str(self.root / "endpoints"),
                "--prompt-file", str(prompt_file)]):
            self.assertEqual(main(), 0)
        manifest = json.loads((self.root / "campaign/campaign.json").read_text())
        self.assertEqual(manifest["response_timeout_s"], 900)

    def test_prepare_cli_allows_explicit_response_timeout(self):
        with patch.object(sys, "argv", ["campaign", "prepare", "--benchmark", "libero",
                "--output-dir", str(self.root / "campaign"), "--model-profile", "gpt6_astra",
                "--response-timeout", "60"]):
            self.assertEqual(main(), 0)
        manifest = json.loads((self.root / "campaign/campaign.json").read_text())
        self.assertEqual(manifest["response_timeout_s"], 60)

    def test_mailbox_root_selection_stays_transport_specific(self):
        for profile, mailbox in (("gpt6_astra", self.root / "endpoint"), ("anonymous_code_agent", None)):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, "mailbox root"):
                prepare(self.root / "campaign", "libero", mailbox, "prompt", model_profile=profile)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_direct_coverage_cannot_carry_forward_mailbox_attempts(self):
        with self.assertRaisesRegex(ValueError, "fresh coverage"):
            prepare(self.root / "campaign", "robocasa365", prompt="prompt", model_profile="gpt6_astra",
                    task_scope="target50", carry_forward_campaign=self.root / "old-mailbox-campaign")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_direct_launch_command_contains_no_endpoint_or_dummy_directory(self):
        self.prepare_direct()
        with patch("benchkit.campaigns.workflow._preflight_case_policy", return_value=True), \
                patch("benchkit.campaigns.workflow.subprocess.Popen", side_effect=OSError("fixture: no launch")) as launch:
            with self.assertRaisesRegex(OSError, "fixture: no launch"):
                run_case(self.root / "campaign", 0, 0)
        command = launch.call_args.args[0]
        self.assertEqual(command[command.index("-m") + 1], "benchkit")
        self.assertEqual(command[command.index("--model-profile") + 1], "gpt6_astra")
        parameters = json.loads(command[command.index("--policy-args") + 1])
        self.assertEqual(set(parameters), {"prompt", "timeout_s", "max_chunk_length", "min_action_decisions_before_give_up"})
        self.assertFalse((self.root / "campaign/case-000/policy_endpoint.json").exists())
        outcome = json.loads((self.root / "campaign/case-000/outcome.json").read_text())
        self.assertEqual(outcome["status"], "infrastructure_or_policy_error")
        with self.assertRaises(FileExistsError):
            run_case(self.root / "campaign", 0, 0)

    def test_rewritten_direct_transport_or_endpoints_fail_before_attempt_claim(self):
        original = self.prepare_direct()
        campaign = self.root / "campaign"
        changes = (lambda doc: doc.pop("policy_execution"),
                   lambda doc: doc.update(policy_execution="mailbox"),
                   lambda doc: doc["cases"][0].update(policy_endpoint=str(self.root / "dummy")))
        for change in changes:
            manifest = deepcopy(original)
            change(manifest)
            atomic_write_json(campaign / "campaign.json", manifest)
            atomic_write_json(campaign / "campaign_digest.json", {"sha256": digest(campaign / "campaign.json")})
            with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                with self.assertRaisesRegex(ValueError, "execution|mailbox endpoints"):
                    run_case(campaign, 0, 0)
                launch.assert_not_called()
            self.assertFalse((campaign / "case-000").exists())

    def test_rewritten_direct_override_bounds_fail_before_attempt_claim(self):
        manifest = self.prepare_direct()
        campaign = self.root / "campaign"
        manifest["response_timeout_s"] = 3601
        atomic_write_json(campaign / "campaign.json", manifest)
        atomic_write_json(campaign / "campaign_digest.json", {"sha256": digest(campaign / "campaign.json")})
        with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
            with self.assertRaisesRegex(ValueError, "declared bounds"):
                run_case(campaign, 0, 0)
            launch.assert_not_called()
        self.assertFalse((campaign / "case-000").exists())

    def test_frozen_direct_factory_imports_without_anonymous_model_or_sdk(self):
        self.prepare_direct()
        frozen = self.root / "campaign/frozen"
        code = """
import json, sys
from pathlib import Path
import benchkit.campaigns.workflow
from benchkit.model_profiles import create_policy
policy = create_policy('gpt6_astra')
assert policy.descriptor.model == 'gpt-6-astra'
assert not any(name.startswith('AgentPolicies.anonymous_code_agent') for name in sys.modules)
assert 'openai' not in sys.modules
factory = sys.modules[type(policy).__module__]
assert Path(factory.__file__).resolve().is_relative_to(Path.cwd())
print(json.dumps(policy.descriptor.to_dict()))
"""
        environment = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=frozen,
            env={**environment, "PYTHONPATH": str(frozen), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_captured_direct_schema_and_transport_bytes_reject_tampering(self):
        self.prepare_direct()
        campaign = self.root / "campaign"
        for prefix in ("frozen", "model_source/files"):
            for name in ("transports/codex_cli.py", "configuration.schema.json"):
                with self.subTest(prefix=prefix, name=name):
                    source = campaign / prefix / "AgentPolicies/gpt6_astra" / name
                    original = source.read_bytes()
                    source.write_bytes(original + b"\nchanged")
                    try:
                        with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                            with self.assertRaisesRegex(ValueError, "source changed"):
                                run_case(campaign, 0, 0)
                            launch.assert_not_called()
                        self.assertFalse((campaign / "case-000").exists())
                    finally:
                        source.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
