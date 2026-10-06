"""Local readiness must not consume a native attempt or dispatch a model call."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from benchkit.audits.closed_run import AuditError, audit_configuration
from benchkit.campaigns.workflow import _preflight_case_policy, digest, prepare, run_case, summarize
from benchkit.cli import _run, build_parser, main
from benchkit.errors import PolicyPreflightError
from benchkit.model_profiles import load_profile, preflight_policy, validate_configuration


class RuntimeCapabilityChecks(unittest.TestCase):
    def test_schema_marker_is_optional_exact_true_and_data_only(self):
        profile = load_profile("gpt6_astra")
        schema, config = profile["configuration"], profile["config"]
        self.assertIs(profile["runtime_preflight"], True)
        for declared in (True, "absent"):
            copy = deepcopy(schema)
            if declared == "absent":
                copy.pop("runtime_preflight")
            with patch("importlib.import_module", side_effect=AssertionError("no model import")):
                result = validate_configuration("gpt6_astra", config, copy)
                audit_configuration(config, copy, "gpt6_astra")
            self.assertEqual(result.get("runtime_preflight", False), declared is True)
        for invalid in (False, None, 1, "true", {}, []):
            with self.subTest(invalid=invalid):
                copy = {**schema, "runtime_preflight": invalid}
                with self.assertRaises(ValueError):
                    validate_configuration("gpt6_astra", config, copy)
                with self.assertRaises(AuditError):
                    audit_configuration(config, copy, "gpt6_astra")

    def test_success_requires_none_and_missing_capability_is_not_success(self):
        hook = MagicMock(return_value=None)
        preflight_policy(SimpleNamespace(preflight_runtime=hook))
        hook.assert_called_once_with()
        for policy, expected in ((object(), "unsupported"),
                                 (SimpleNamespace(preflight_runtime=lambda: True), "initialization_failed")):
            with self.assertRaises(PolicyPreflightError) as failure:
                preflight_policy(policy)
            self.assertEqual(failure.exception.code, expected)

    def test_dependency_exceptions_and_mutated_codes_are_sanitized_without_context(self):
        sentinel = "synthetic-secret-must-not-escape"
        corrupt = PolicyPreflightError("dependency_unavailable")
        corrupt.code = sentinel
        for error, code in ((RuntimeError(sentinel), "initialization_failed"),
                            (PolicyPreflightError("credentials_missing"), "credentials_missing"),
                            (corrupt, "initialization_failed")):
            with self.subTest(code=code):
                hook = MagicMock(side_effect=error)
                try:
                    preflight_policy(SimpleNamespace(preflight_runtime=hook))
                except PolicyPreflightError as failure:
                    self.assertEqual(failure.code, code)
                    self.assertNotIn(sentinel, str(failure))
                    self.assertIsNone(failure.__cause__)
                    self.assertIsNone(failure.__context__)
                else:
                    self.fail("failed readiness passed")

    def test_manual_command_has_only_closed_diagnostics_and_no_benchmark(self):
        for error, expected in ((None, None), (RuntimeError("synthetic-secret"), "initialization_failed"),
                                (PolicyPreflightError("dependency_unavailable"), "dependency_unavailable")):
            out, err = io.StringIO(), io.StringIO()
            with patch("benchkit.model_profiles.preflight_policy", side_effect=error), \
                    patch("benchkit.cli.create_benchmark") as benchmark, \
                    redirect_stdout(out), redirect_stderr(err):
                status = main(["preflight-policy", "--model-profile", "gpt6_astra"])
            self.assertEqual(status, int(expected is not None))
            self.assertEqual(json.loads(out.getvalue()), {"status": "failed" if expected else "passed",
                "scope": "local_runtime_only", "error_code": expected})
            self.assertEqual(err.getvalue(), "")
            benchmark.assert_not_called()

    def test_undeclared_manual_check_does_not_import_factory(self):
        with patch("benchkit.model_profiles.create_policy") as factory, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["preflight-policy", "--model-profile", "anonymous_code_agent"]), 1)
        self.assertEqual(json.loads(out.getvalue())["error_code"], "unsupported")
        factory.assert_not_called()

    def test_noisy_factory_and_hook_cannot_leak_python_or_native_fd_output(self):
        code = r'''
import json, os, sys
from unittest.mock import patch
from benchkit.cli import main
from benchkit.errors import PolicyPreflightError
from benchkit.model_profiles import create_policy

def noise():
    print('synthetic-secret-python-stdout')
    print('synthetic-secret-python-stderr', file=sys.stderr)
    os.write(1, b'synthetic-secret-native-stdout\n')
    os.write(2, b'synthetic-secret-native-stderr\n')

def factory(*args, **kwargs):
    noise()
    return create_policy(*args, **kwargs)

for failure in (False, True):
    def hook(*args):
        noise()
        if failure:
            raise PolicyPreflightError('dependency_unavailable')
    with patch('benchkit.model_profiles.create_policy', side_effect=factory), \
         patch('benchkit.model_profiles.preflight_policy', side_effect=hook):
        assert main(['preflight-policy', '--model-profile', 'gpt6_astra']) == int(failure)
print('restored-stdout')
print('restored-stderr', file=sys.stderr)
'''
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root,
            env={**os.environ, "OPENAI_API_KEY": "", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root)},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("synthetic-secret", result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual([json.loads(line)["status"] for line in lines[:2]], ["passed", "failed"])
        self.assertEqual(lines[2:], ["restored-stdout"])
        self.assertEqual(result.stderr, "restored-stderr\n")

    def test_bare_run_checks_before_benchmark_construction_or_runner(self):
        args = build_parser().parse_args(["run", "--benchmark", "unused", "--model-profile", "gpt6_astra"])
        with patch("benchkit.model_profiles.preflight_policy", side_effect=PolicyPreflightError("credentials_missing")), \
                patch("benchkit.cli.create_benchmark") as benchmark, patch("benchkit.cli.EvaluationRunner") as runner:
            with self.assertRaises(PolicyPreflightError):
                _run(args)
        benchmark.assert_not_called()
        runner.assert_not_called()


class CampaignRuntimeChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "campaign"
        self.manifest = prepare(self.output, "libero", model_profile="gpt6_astra")
        self.case = self.output / "case-000"

    def test_frozen_missing_cli_leaves_every_case_unattempted_without_new_files(self):
        before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        # The current Native default uses local CLI login, not an API key. An
        # empty search path proves failure before any real CLI can be invoked.
        with patch.dict(os.environ, {"PATH": ""}):
            with self.assertRaisesRegex(RuntimeError, "preflight failed; case remains unattempted"):
                run_case(self.output, 0, 0)
        self.assertEqual(before, {p.relative_to(self.output): p.read_bytes()
                                 for p in self.output.rglob("*") if p.is_file()})
        self.assertFalse(self.case.exists())
        report = summarize(self.output)
        self.assertEqual(report["unattempted"], self.manifest["planned_cases"])

    def test_frozen_manual_check_does_not_import_benchmark_or_provider_without_cli(self):
        code = """
import sys
from benchkit.cli import main
status = main(['preflight-policy', '--model-profile', 'gpt6_astra'])
assert status == 1
assert 'openai' not in sys.modules
assert not any(name.startswith('benchmarks.simBenchmarks.') for name in sys.modules)
"""
        frozen = self.output / "frozen"
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=frozen,
            env={**os.environ, "PATH": "", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(frozen)},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["error_code"], "dependency_unavailable")
        self.assertFalse(self.case.exists())

    def test_frozen_subprocess_uses_same_interpreter_env_args_and_discards_all_io(self):
        parameters, env = {"timeout_s": 120, "max_chunk_length": 5}, {"PUBLIC_FIXTURE": "1"}
        with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
            launch.return_value.__enter__.return_value.wait.return_value = 0
            self.assertTrue(_preflight_case_policy(self.output, self.manifest, parameters, env))
        command = launch.call_args.args[0]
        self.assertEqual(command[:5], [sys.executable, "-B", "-m", "benchkit", "preflight-policy"])
        self.assertEqual(json.loads(command[-1]), parameters)
        self.assertEqual(launch.call_args.kwargs, {"cwd": self.output / "frozen", "env": env,
            "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
            "start_new_session": True})
        launch.return_value.__enter__.return_value.wait.assert_called_once_with(timeout=60)
        self.assertFalse(self.case.exists())

    def test_failed_and_timed_out_preflight_have_no_claim_and_no_raw_errors(self):
        for failure in (OSError("synthetic-secret"), subprocess.TimeoutExpired("synthetic-secret", 60), None):
            with self.subTest(failure=type(failure).__name__), patch("benchkit.campaigns.workflow.subprocess.Popen") as launch, \
                    patch("benchkit.campaigns.workflow.terminate_child") as terminate:
                process = launch.return_value.__enter__.return_value
                if isinstance(failure, OSError):
                    launch.side_effect = failure
                elif failure is not None:
                    process.wait.side_effect = failure
                else:
                    process.wait.return_value = 1
                try:
                    run_case(self.output, 0, 0)
                except RuntimeError as error:
                    self.assertNotIn("synthetic-secret", str(error))
                    self.assertIsNone(error.__context__)
                else:
                    self.fail("failed check claimed a case")
                if isinstance(failure, subprocess.TimeoutExpired):
                    terminate.assert_called_once_with(process)
                self.assertFalse(self.case.exists())

    def test_already_claimed_case_does_not_even_start_preflight(self):
        self.case.mkdir()
        with patch("benchkit.campaigns.workflow._preflight_case_policy") as check, \
                patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
            with self.assertRaises(FileExistsError):
                run_case(self.output, 0, 0)
        check.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(list(self.case.iterdir()), [])

    def test_another_coordinator_can_win_atomic_claim_after_successful_preflight(self):
        def competing_claim(*args):
            self.case.mkdir()
            return True
        with patch("benchkit.campaigns.workflow._preflight_case_policy", side_effect=competing_claim), \
                patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
            with self.assertRaises(FileExistsError):
                run_case(self.output, 0, 0)
        launch.assert_not_called()
        self.assertEqual(list(self.case.iterdir()), [])

    def test_source_mutation_during_successful_preflight_fails_before_claim(self):
        def mutate(*args):
            path = self.output / "frozen/AgentPolicies/gpt6_astra/tools/factory.py"
            path.write_bytes(path.read_bytes() + b"\n# changed\n")
            return True
        with patch("benchkit.campaigns.workflow._preflight_case_policy", side_effect=mutate), \
                patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
            with self.assertRaisesRegex(ValueError, "source changed"):
                run_case(self.output, 0, 0)
        launch.assert_not_called()
        self.assertFalse(self.case.exists())

    def test_rehashed_campaign_mutation_during_preflight_fails_before_claim(self):
        def mutate(*args):
            path = self.output / "campaign.json"
            changed = {**self.manifest, "task_timeout_s": self.manifest["task_timeout_s"] + 1}
            path.write_text(json.dumps(changed))
            (self.output / "campaign_digest.json").write_text(json.dumps({"sha256": digest(path)}))
            return True
        with patch("benchkit.campaigns.workflow._preflight_case_policy", side_effect=mutate), \
                patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
            with self.assertRaisesRegex(ValueError, "campaign changed"):
                run_case(self.output, 0, 0)
        launch.assert_not_called()
        self.assertFalse(self.case.exists())

    def test_undeclared_historical_runtime_and_old_schema_do_not_gain_a_hook(self):
        with patch("benchkit.model_profiles.verify_model_source", return_value={"execution": "direct"}) as profile, \
                patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
            self.assertFalse(_preflight_case_policy(self.output, self.manifest, {}, {}))
            profile.assert_called_once_with(self.output, self.manifest)
            profile.reset_mock()
            self.assertFalse(_preflight_case_policy(self.output, {"schema_version": "starvla-rsi.campaign/v2"}, {}, {}))
            profile.assert_not_called()
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
