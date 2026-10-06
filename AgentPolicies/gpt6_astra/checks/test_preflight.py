"""Native CLI/PNG readiness fixtures: no live CLI, model, network or simulator."""
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchkit.errors import PolicyPreflightError
from AgentPolicies.gpt6_astra.tools import runtime_preflight
from AgentPolicies.gpt6_astra.tools.factory import create_policy, ROOT

IDENTITY = {"name": "fixture", "kind": "direct-model", "model": "gpt-6-astra", "provider": "openai"}
CONFIG = json.loads((ROOT / "configs/config.json").read_text())


class PolicyPreflightChecks(unittest.TestCase):
    def policy(self):
        return create_policy(config=CONFIG, identity=IDENTITY)

    def test_construction_is_lazy_without_image_dependencies(self):
        with patch.dict(sys.modules, {"numpy": None, "PIL": None}), \
                patch("AgentPolicies.gpt6_astra.transports.codex_cli.preflight_runtime") as check:
            policy = self.policy()
            self.assertIsNone(policy.context)
            check.assert_not_called()

    def test_real_png_roundtrip_calls_only_mocked_cli_preflight(self):
        policy = self.policy()
        before = json.dumps(policy.descriptor.to_dict(), sort_keys=True)
        with patch("AgentPolicies.gpt6_astra.transports.codex_cli.preflight_runtime", return_value={}) as check, \
                patch("AgentPolicies.gpt6_astra.transports.codex_cli.send") as send, patch.object(policy, "act") as act:
            self.assertIsNone(policy.preflight_runtime())
            check.assert_called_once_with()
            send.assert_not_called()
            act.assert_not_called()
        self.assertEqual(json.dumps(policy.descriptor.to_dict(), sort_keys=True), before)
        self.assertIsNone(policy.context)

    def test_cli_preflight_error_propagates_without_dispatch(self):
        with patch("AgentPolicies.gpt6_astra.transports.codex_cli.preflight_runtime",
                   side_effect=PolicyPreflightError("credentials_missing")), \
                patch("AgentPolicies.gpt6_astra.transports.codex_cli.send") as send:
            with self.assertRaises(PolicyPreflightError) as caught:
                self.policy().preflight_runtime()
            self.assertEqual(caught.exception.code, "credentials_missing")
            send.assert_not_called()

    def test_missing_image_dependency_is_sanitized(self):
        for module in ("numpy", "PIL"):
            with self.subTest(module=module), patch.dict(sys.modules, {module: None}), \
                    patch("AgentPolicies.gpt6_astra.transports.codex_cli.preflight_runtime", return_value={}):
                with self.assertRaises(PolicyPreflightError) as caught:
                    runtime_preflight.preflight_native_runtime()
                self.assertEqual(caught.exception.code, "dependency_unavailable")

    def test_codec_failure_hides_raw_exception(self):
        with patch("AgentPolicies.gpt6_astra.transports.codex_cli.preflight_runtime", return_value={}), \
                patch.dict(sys.modules, {"numpy": SimpleNamespace(
                    array=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("private-marker")),
                    uint8=object())}):
            with self.assertRaises(PolicyPreflightError) as caught:
                runtime_preflight.preflight_native_runtime()
            self.assertEqual(caught.exception.code, "initialization_failed")
            self.assertNotIn("private-marker", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
