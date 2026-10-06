"""Preparation/relocation checks; never start a simulator, actor or model call."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from benchkit.model_profiles import load_profile


REPO = Path(__file__).resolve().parents[3]


class PreparationToolChecks(unittest.TestCase):
    def test_module_allocator_returns_fresh_opaque_uncreated_endpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "policy-mailboxes"
            paths = []
            for _ in range(2):
                result = subprocess.run(
                    [sys.executable, "-m", "AgentPolicies.anonymous_code_agent.tools.new_mailbox",
                     "--root", str(root)], cwd=REPO, check=True, capture_output=True, text=True,
                )
                path = Path(result.stdout.strip())
                self.assertEqual(path.parent, root)
                self.assertRegex(path.name, r"^mbx-[0-9a-f]{32}$")
                self.assertFalse(path.exists())
                paths.append(path)
            self.assertNotEqual(*paths)

    def test_simpler_reference_is_source_bound_but_allocator_is_not_policy_runtime(self):
        files = {row["path"] for row in load_profile("anonymous_code_agent")["files"]}
        self.assertIn("AgentPolicies/anonymous_code_agent/prompts/simpler_development.txt", files)
        self.assertNotIn("AgentPolicies/anonymous_code_agent/tools/new_mailbox.py", files)

    def test_reference_prompt_is_bound_and_retired_launcher_is_not_public(self):
        expected = {"AgentPolicies/anonymous_code_agent/prompts/simpler_development.txt":
                    "38b826f38673402104f5012582e323639f1012294bf079c30d7f4b8648199ee6"}
        for relative, digest in expected.items():
            with self.subTest(relative=relative):
                self.assertEqual(hashlib.sha256((REPO / relative).read_bytes()).hexdigest(), digest)
        for old in ("run_development.py", "new_mailbox.py", "prompts/policy.txt"):
            self.assertFalse((REPO / "benchmarks/simBenchmarks/SimplerEnv" / old).exists())
        self.assertFalse((REPO / "benchmarks/simBenchmarks/SimplerEnv/legacy").exists())


if __name__ == "__main__":
    unittest.main()
