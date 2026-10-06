"""Model-owned driver checks; no real model, socket, reset or native imports."""
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from benchkit.errors import PolicyPreflightError
from AgentPolicies.gpt6_astra import run as subject


class ModelDriverChecks(unittest.TestCase):
    def arguments(self, root):
        return subject.build_parser().parse_args([
            "--control-method", "codex-native/v1",
            "--benchmark", "robodojo",
            "--sim-server", "http://127.0.0.1:8765", "--seed", "20260907",
            "--episodes", "5", "--max-steps", "1100", "--replan-interval", "5",
            "--output-dir", str(root), "--run-id", "classify_objects-category-sorting-panel5"])

    def test_new_default_is_generic_direct_with_explicit_benchmark(self):
        self.assertEqual(subject.build_parser().get_default("control_method"), "codex-direct/v3")
        self.assertIsNone(subject.build_parser().get_default("benchmark"))
        self.assertNotIn("--action-guard", subject.build_parser().format_help())
        self.assertNotIn("--protocol-preset", subject.build_parser().format_help())

    def test_direct_stop_flag_default_and_explicit_opt_in_are_effective(self):
        with patch("AgentPolicies.gpt6_astra.methods.codex_direct.CodexDirectPolicy.preflight_runtime", return_value=None):
            self.assertFalse(subject.checked_policy("codex-direct/v3").config["safety_stop"])
            self.assertTrue(subject.checked_policy("codex-direct/v3", safety_stop=True).config["safety_stop"])
        parser = subject.build_parser()
        self.assertIsNone(parser.get_default("safety_stop"))
        self.assertIn("--no-safety-stop", parser.format_help())

    def test_planned_stop_flag_default_and_explicit_opt_in_are_effective(self):
        with patch("AgentPolicies.gpt6_astra.methods.codex_planned.CodexPlannedPolicy.preflight_runtime", return_value=None):
            self.assertFalse(subject.checked_policy("codex-planned/v1").config["safety_stop"])
            self.assertTrue(subject.checked_policy("codex-planned/v1", safety_stop=True).config["safety_stop"])
            self.assertFalse(subject.checked_policy("codex-planned/v1", safety_stop=False).config["safety_stop"])

    def test_driver_rejects_stop_override_for_other_methods_before_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.safety_stop = False
            with patch.object(subject, "checked_policy") as factory, patch.object(subject, "SimServerBenchmarkAdapter") as client:
                with self.assertRaisesRegex(ValueError, "requires Direct v3"):
                    subject.run(args)
                factory.assert_not_called()
                client.assert_not_called()

    def test_method_stop_declaration_cannot_mislabel_effective_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.control_method = "codex-direct/v3"
            args.method_file = Path(temporary) / "method.json"
            args.method_file.write_text(json.dumps({"schema_version": "starvla-rsi.method/v1",
                "id": "fixture", "models": [{"id": "primary", "role": "policy", "model": "fixture"}],
                "configuration": {"safety_stop": True}}))
            policy = SimpleNamespace(descriptor=SimpleNamespace(parameters={"safety_stop": False}))
            with patch.object(subject, "checked_policy", return_value=policy), \
                    patch.object(subject, "SimServerBenchmarkAdapter") as client:
                for method in ("codex-direct/v3", "codex-planned/v1"):
                    args.control_method = method
                    with self.subTest(method=method), self.assertRaisesRegex(ValueError, "safety_stop differs"):
                        subject.run(args)
                client.assert_not_called()

    def test_planned_method_uses_generic_service_and_policy_owned_chunk(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.control_method, args.benchmark = "codex-planned/v1", "generic-robot"
            args.max_policy_calls, args.replan_interval, args.image_max_edge = 300, 7, 320
            args.safety_stop = False
            benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="generic-robot"),
                parameters={}, environment_step_cap=1100)
            with patch.object(subject, "checked_policy", return_value=object()) as factory, \
                    patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                    patch.object(subject, "EvaluationRunner") as loop:
                subject.run(args)
                factory.assert_called_once_with("codex-planned/v1",
                                                 image_max_edge=320, max_chunk_length=7, safety_stop=False)
                request = loop.return_value.run.call_args.args[2]
                self.assertEqual(request.replan_interval, 7)
                self.assertEqual(request.invalid_action_handling, "feedback")

    def test_planned_method_cannot_silently_change_service_horizon(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.control_method, args.max_policy_calls = "codex-planned/v1", 300
            for horizon in (None, 0, True, 1200):
                benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="robodojo"),
                    parameters={}, environment_step_cap=horizon)
                with self.subTest(horizon=horizon), patch.object(subject, "checked_policy", return_value=object()), \
                        patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                        patch.object(subject, "EvaluationRunner") as loop:
                    with self.assertRaisesRegex(ValueError, "control horizon"):
                        subject.run(args)
                    loop.assert_not_called()

    def test_planned_method_requires_feedback_before_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.control_method, args.invalid_action_handling = "codex-planned/v1", "terminate"
            with patch.object(subject, "checked_policy") as factory, \
                    patch.object(subject, "SimServerBenchmarkAdapter") as client:
                with self.assertRaisesRegex(ValueError, "planned control requires"):
                    subject.run(args)
                factory.assert_not_called()
                client.assert_not_called()

    def test_preview_option_is_persistent_only_before_preflight_or_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.image_max_edge = 480
            for method in ("codex-native/v1",):
                args.control_method = method
                with self.subTest(method=method), patch.object(subject, "checked_policy") as factory, \
                        patch.object(subject, "SimServerBenchmarkAdapter") as client:
                    with self.assertRaisesRegex(ValueError, "image-max-edge requires codex-direct/v3"):
                        subject.run(args)
                    factory.assert_not_called()
                    client.assert_not_called()

    def test_direct_v3_has_no_benchmark_protocol_or_raw_feedback_dependency(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch("AgentPolicies.gpt6_astra.methods.codex_direct.CodexDirectPolicy.preflight_runtime", return_value=None):
            policy = subject.checked_policy("codex-direct/v3", image_max_edge=240)
            self.assertEqual(policy.descriptor.parameters["image_max_edge"], 240)
            args = self.arguments(Path(temporary))
            args.control_method, args.image_max_edge = "codex-direct/v3", 240
            args.benchmark, args.replan_interval = "unseen-robot", 7
            args.max_policy_calls = 220
            for schema in (None, "unknown/v1"):
                benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="unseen-robot",
                    protocol_version="independent-contract/v7"), parameters={}, max_policy_calls=None,
                    environment_step_cap=1100,
                    observation_spec=SimpleNamespace(control_feedback_schema=schema))
                with self.subTest(schema=schema), patch.object(subject, "checked_policy", return_value=policy) as factory, \
                        patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                        patch.object(subject, "EvaluationRunner") as loop:
                    subject.run(args)
                    loop.return_value.run.assert_called_once()
                    factory.assert_called_once_with("codex-direct/v3", image_max_edge=240,
                                                     max_chunk_length=7)
                    self.assertEqual(loop.return_value.run.call_args.args[2].replan_interval, 7)

    def test_direct_requires_matching_advertised_horizon_before_claim(self):
        for horizon in (None, 0, True, 1200, 1100):
            with self.subTest(horizon=horizon), tempfile.TemporaryDirectory() as temporary:
                args = self.arguments(Path(temporary))
                args.control_method = "codex-direct/v3"
                args.max_policy_calls = 220
                benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="robodojo"),
                    parameters={}, max_policy_calls=None, environment_step_cap=horizon)
                with patch.object(subject, "checked_policy", return_value=object()), \
                        patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                        patch.object(subject, "EvaluationRunner") as loop:
                    if horizon == 1100:
                        subject.run(args)
                        self.assertEqual(loop.return_value.run.call_args.args[2].invalid_action_handling, "feedback")
                    else:
                        with self.assertRaisesRegex(ValueError, "control horizon"):
                            subject.run(args)
                        loop.assert_not_called()

    def test_server_is_required_no_implicit_local_native_fallback(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            subject.build_parser().parse_args(["--seed", "0", "--episodes", "1", "--max-steps", "1",
                "--output-dir", "/unused", "--run-id", "fixture"])

    def test_runner_has_only_the_agent_side_entrypoint(self):
        import benchkit
        import importlib.util
        from AgentPolicies.policy_support import runner
        self.assertIs(subject.EvaluationRunner, runner.EvaluationRunner)
        self.assertFalse(hasattr(benchkit, "EvaluationRunner"))
        self.assertFalse(hasattr(benchkit, "RunRequest"))
        self.assertIsNone(importlib.util.find_spec("benchkit.runner"))

    def test_model_factory_is_local_preflight_only_and_keeps_frozen_identity(self):
        with patch("AgentPolicies.gpt6_astra.methods.codex_native.CodexNativePolicy.preflight_runtime") as check:
            check.return_value = None
            policy = subject.checked_policy("codex-native/v1")
        check.assert_called_once_with()
        self.assertEqual(policy.descriptor.parameters["model_profile"]["id"], "gpt6_astra")
        self.assertEqual(policy.descriptor.version, "codex-native/v1")
        self.assertIsNone(policy.context)

    def test_preflight_failure_does_not_connect_or_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "unused"
            with patch.object(subject, "checked_policy", side_effect=PolicyPreflightError("credentials_missing")), \
                    patch.object(subject, "SimServerBenchmarkAdapter") as client:
                with self.assertRaises(PolicyPreflightError):
                    subject.run(self.arguments(root))
            client.assert_not_called()
            self.assertFalse(root.exists())

    def test_mixed_factory_and_capture_origins_fail_before_preflight(self):
        for module in (subject.policy_module, subject.profile_records, subject.driver_module,
                       subject.service_client_module):
            with self.subTest(module=module.__name__), patch.object(module, "__file__", "/other-root/module.py"), \
                    patch("AgentPolicies.gpt6_astra.methods.codex_native.CodexNativePolicy.preflight_runtime") as check:
                with self.assertRaisesRegex(ValueError, "same selected package"):
                    subject.checked_policy("codex-native/v1")
            check.assert_not_called()

    def test_wrong_service_and_diagnostic_cannot_start_capability_loop(self):
        for name, parameters in (("libero", {}), ("robodojo", {"diagnostic": True})):
            with self.subTest(name=name, parameters=parameters), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "unused"
                benchmark = SimpleNamespace(descriptor=SimpleNamespace(name=name), parameters=parameters)
                with patch.object(subject, "checked_policy"), \
                        patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                        patch.object(subject, "EvaluationRunner") as loop:
                    with self.assertRaises(ValueError):
                        subject.run(self.arguments(root))
                loop.assert_not_called()
                self.assertFalse(root.exists())

    def test_driver_does_not_add_a_200_decision_cap_or_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "unused"
            policy = object()
            benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="robodojo"),
                                        parameters={"diagnostic": False}, max_policy_calls=1100)
            with patch.object(subject, "checked_policy", return_value=policy), \
                    patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark) as client, \
                    patch.object(subject, "EvaluationRunner") as loop:
                loop.return_value.run.return_value = root
                self.assertEqual(subject.run(self.arguments(root)), root)
            client.assert_called_once()
            loop.return_value.run.assert_called_once()
            used_benchmark, used_policy, request = loop.return_value.run.call_args.args
            self.assertIs(used_benchmark, benchmark)
            self.assertIs(used_policy, policy)
            self.assertEqual((request.episode_limit, request.max_steps, request.replan_interval), (5, 1100, 5))
            self.assertEqual(request.max_policy_calls, 1100)
            self.assertEqual(request.invalid_action_handling, "feedback")
            self.assertFalse(root.exists())

    def test_client_recording_preferences_do_not_change_control_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.recording_mode = "minimal"
            args.record_model_io = True
            benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="robodojo"),
                                        parameters={}, max_policy_calls=1100)
            with patch.object(subject, "checked_policy"), \
                    patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                    patch.object(subject, "EvaluationRunner") as loop:
                subject.run(args)
            request = loop.return_value.run.call_args.args[2]
            self.assertEqual(request.recording.mode, "minimal")
            self.assertTrue(request.recording.model_io)
            self.assertFalse(request.recording.images)
            self.assertFalse(request.recording.videos)
            self.assertEqual((request.max_steps, request.replan_interval, request.max_policy_calls),
                             (1100, 5, 1100))

    def test_invalid_method_declaration_fails_before_preflight_or_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            args.method_file = Path(temporary) / "method.json"
            args.method_file.write_text(json.dumps({"schema_version": "unknown"}))
            with patch.object(subject, "checked_policy") as policy, \
                    patch.object(subject, "SimServerBenchmarkAdapter") as client:
                with self.assertRaises(ValueError):
                    subject.run(args)
            policy.assert_not_called()
            client.assert_not_called()

    def test_native_explicit_terminate_mode_does_not_invent_a_call_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.arguments(root)
            args.control_method = "codex-native/v1"
            args.invalid_action_handling = "terminate"
            benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="robodojo"), parameters={})
            with patch.object(subject, "checked_policy"), \
                    patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                    patch.object(subject, "EvaluationRunner") as loop:
                subject.run(args)
            request = loop.return_value.run.call_args.args[2]
            self.assertIsNone(request.max_policy_calls)
            self.assertEqual(request.invalid_action_handling, "terminate")

    def test_feedback_without_any_declared_call_budget_never_opens_an_episode(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.arguments(Path(temporary))
            benchmark = SimpleNamespace(descriptor=SimpleNamespace(name="robodojo"), parameters={})
            with patch.object(subject, "checked_policy"), \
                    patch.object(subject, "SimServerBenchmarkAdapter", return_value=benchmark), \
                    patch.object(subject, "EvaluationRunner") as loop:
                with self.assertRaisesRegex(ValueError, "policy-calls"):
                    subject.run(args)
                loop.assert_not_called()

    def test_legacy_methods_cannot_opt_into_unsupported_feedback_before_claim(self):
        for method in ("codex-eef/v1", "codex-eef/v2", "codex-direct/v1", "codex-direct/v2", "responses-native/v1"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temporary:
                args = self.arguments(Path(temporary))
                args.control_method = method
                args.invalid_action_handling = "feedback"
                with patch.object(subject, "checked_policy") as policy, \
                        patch.object(subject, "SimServerBenchmarkAdapter") as client:
                    with self.assertRaisesRegex(ValueError, "retired"):
                        subject.run(args)
                policy.assert_not_called()
                client.assert_not_called()

    def test_direct_policy_owns_chunk_without_robot_specific_guard(self):
        with patch("AgentPolicies.gpt6_astra.methods.codex_direct.CodexDirectPolicy.preflight_runtime", return_value=None):
            for chunk in (1, 7, 32):
                with self.subTest(chunk=chunk):
                    policy = subject.checked_policy("codex-direct/v3", max_chunk_length=chunk)
                    self.assertEqual(policy.config["max_chunk_length"], chunk)
                    self.assertNotIn("enforce_action_guard", policy.config)
                    self.assertNotIn("required_protocol", policy.config)
                    self.assertEqual(policy.descriptor.version, "codex-direct/v3")

    def test_cli_reports_errors_or_incomplete_panel_as_nonzero_not_task_failure(self):
        for attempted, errors, expected in ((5, 0, 0), (5, 1, 1), (4, 0, 1)):
            with self.subTest(attempted=attempted, errors=errors), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "summary.json").write_text(json.dumps({"attempted": attempted,
                    "completed": attempted-errors, "errors": errors, "successes": 0}))
                arguments = self.arguments(root)
                with patch.object(subject, "run", return_value=root), \
                        patch.object(subject, "build_parser") as parser, contextlib.redirect_stdout(io.StringIO()):
                    parser.return_value.parse_args.return_value = arguments
                    self.assertEqual(subject.main([]), expected)


if __name__ == "__main__":
    unittest.main()
