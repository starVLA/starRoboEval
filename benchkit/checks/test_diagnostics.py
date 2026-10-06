"""CPU fixtures: diagnostic ownership and self-contained source provenance."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchkit.campaigns.workflow import prepare, run_case, verify_frozen_package
from benchkit.contracts import Observation
from benchkit.registry import create_policy
from benchkit.source_snapshot import capture_harness_source


class DiagnosticChecks(unittest.TestCase):
    def test_constant_keeps_cli_behavior_and_diagnostic_identity(self):
        policy = create_policy("constant", {"action": [0.25, -0.5], "chunk_length": 3})
        self.assertEqual(type(policy).__module__, "benchkit.diagnostics.constant")
        self.assertEqual(policy.descriptor.parameters["purpose"], "infrastructure_validation_only")
        self.assertIsNone(policy.descriptor.model)
        self.assertIsNone(policy.descriptor.provider)
        decision = policy.act(Observation(step=0, instruction="synthetic diagnostic"))
        self.assertEqual(decision.action.steps, ((0.25, -0.5),) * 3)
        self.assertFalse(decision.stop)

    def test_constant_does_not_accept_model_or_strategy_parameters(self):
        for extra in ({"model": "example"}, {"min_action_decisions_before_give_up": 50}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "only action and chunk_length"):
                create_policy("constant", {"action": [0.0], **extra})

    def test_campaign_diagnostic_source_is_separate_and_tampering_blocks_claim(self):
        for prefix in ("frozen", "harness_source/files"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                campaign = root / "campaign"
                manifest = prepare(campaign, "libero", root / "mailboxes", "Use declared sensors.",
                                   model_profile="anonymous_code_agent")
                verify_frozen_package(campaign, manifest)
                index = json.loads((campaign / "model_source/index.json").read_text())
                self.assertFalse(any("diagnostics" in Path(row["path"]).parts for row in index["files"]))
                source = campaign / prefix / "benchkit/diagnostics/constant.py"
                source.write_bytes(source.read_bytes() + b"\n# altered diagnostic source\n")
                with patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                    with self.assertRaisesRegex(ValueError, "frozen source changed"):
                        run_case(campaign, 0, 0)
                    launch.assert_not_called()
                self.assertFalse((campaign / "case-000").exists())

    def test_harness_snapshot_contains_diagnostic_bytes_and_loads_without_models(self):
        with tempfile.TemporaryDirectory(prefix="diagnostic-source-check-") as temporary:
            run = Path(temporary)
            capture_harness_source(run)
            snapshot = run / "harness_source"
            index = json.loads((snapshot / "index.json").read_text())
            rows = {row["path"]: row for row in index["files"]}
            for relative in ("benchkit/diagnostics/__init__.py", "benchkit/diagnostics/constant.py"):
                self.assertIn(relative, rows)
                payload = (snapshot / "files" / relative).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), rows[relative]["sha256"])
            self.assertEqual({path for path in rows if path.startswith("AgentPolicies/")},
                {"AgentPolicies/policy_support/runner.py", "AgentPolicies/gpt6_astra/run.py"})
            frozen = snapshot / "files"
            command = """
import sys
from pathlib import Path
from benchkit.registry import create_policy
policy = create_policy('constant', {'action': [0.0], 'chunk_length': 1})
module = sys.modules[type(policy).__module__]
assert Path(module.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
assert policy.descriptor.parameters['purpose'] == 'infrastructure_validation_only'
assert not any(name == 'AgentPolicies' or name.startswith('AgentPolicies.') for name in sys.modules)
"""
            result = subprocess.run([sys.executable, "-B", "-c", command, str(frozen)],
                cwd=run, env={**os.environ, "PYTHONPATH": str(frozen), "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
