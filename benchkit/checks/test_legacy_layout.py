"""Synthetic old-layout data checks; no archived result or simulator is changed."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchkit.artifacts import atomic_write_json
from benchkit.campaigns.workflow import cases_for, digest, run_case, verify_frozen_package
from benchkit.model_profiles import _allowed_files, _profile_data, load_profile, verify_policy_source
from benchkit.source_snapshot import capture_harness_source, inventory_digest


class LegacyLayoutChecks(unittest.TestCase):
    def test_external_ledger_script_bootstraps_without_current_package_on_pythonpath(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(__file__).resolve().parents[1] / "reports/task_ledger.py"
            completed = subprocess.run([sys.executable, str(script), "--help"], cwd=temporary,
                env={**os.environ, "PYTHONPATH": temporary, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=30, check=True)
            self.assertIn("--campaign", completed.stdout)

    def test_v1_package_keeps_old_layout_and_old_execution_entrypoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_source, output = root / "old-source", root / "old-campaign"
            old_source.mkdir()
            output.mkdir()
            (old_source / "__init__.py").write_text('"""Synthetic legacy package."""\n')
            snapshot = capture_harness_source(output, source_root=old_source)
            package = output / "frozen/starVLA"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text('"""Synthetic old parent."""\n')
            shutil.copytree(output / "harness_source/files", package / "evaluation")
            case = cases_for("libero", 200, 5)[0]
            case["policy_endpoint"] = str(root / "opaque-endpoint")
            manifest = {"schema_version": "starvla-rsi.campaign/v1", "benchmark": "libero",
                "purpose": "development_task_coverage", "harness_source": snapshot,
                "package_initializer_sha256": digest(package / "__init__.py"),
                "supplemental_runtime_files": [], "cases": [case], "planned_cases": 1,
                "attempts_per_task": 1, "seed": 20260907, "budget_mode": "decisions",
                "max_policy_calls": 200, "replan_interval": 5, "max_steps": 1000,
                "response_timeout_s": 900, "task_timeout_s": 14400,
                "policy_prompt": "legacy prompt", "policy": {"name": "code-agent-development",
                    "kind": "external-code-agent", "model": None, "provider": None}}
            atomic_write_json(output / "campaign.json", manifest)
            atomic_write_json(output / "campaign_digest.json", {"sha256": digest(output / "campaign.json")})
            before = (output / "campaign.json").read_bytes()
            verify_frozen_package(output, manifest)
            with patch("benchkit.campaigns.workflow.subprocess.Popen", side_effect=OSError("fixture: no launch")) as launch:
                with self.assertRaisesRegex(OSError, "fixture: no launch"):
                    run_case(output, 0, 0)
                command = launch.call_args.args[0]
            self.assertEqual(command[command.index("-m") + 1], "starVLA.evaluation")
            self.assertNotIn("--model-profile", command)
            self.assertNotIn("--policy-min-action-decisions-before-give-up", command)
            self.assertEqual((output / "campaign.json").read_bytes(), before)
            self.assertTrue((output / "case-000/attempt.json").is_file())
            with self.assertRaises(FileExistsError):
                run_case(output, 0, 0)

    def test_v1_model_allowlist_is_checked_as_legacy_data_not_migrated(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            current = load_profile("anonymous_code_agent")
            payloads = {relative: current["payloads"].get(
                            relative.replace("starVLA/", "AgentPolicies/", 1), b"# synthetic old runtime bytes\n")
                        for relative in _allowed_files("anonymous_code_agent", legacy=True)}
            prefix = "starVLA/anonymous_code_agent/"
            profile = json.loads(payloads[prefix + "profile.json"])
            profile["factory"] = "starVLA.anonymous_code_agent.policy:create_policy"
            payloads[prefix + "profile.json"] = json.dumps(profile).encode()
            config = json.loads(payloads[prefix + "config.json"])
            config.pop("policy_stop_rule_version")
            config.pop("min_action_decisions_before_give_up")
            payloads[prefix + "config.json"] = json.dumps(config).encode()
            dependencies = json.loads(payloads[prefix + "dependencies.json"])
            dependencies["files"] = list(_allowed_files("anonymous_code_agent", legacy=True))
            payloads[prefix + "dependencies.json"] = json.dumps(dependencies).encode()
            data = _profile_data("anonymous_code_agent", payloads, require_configured=True, legacy=True)
            payloads["campaign_prompt.txt"] = b"legacy effective prompt"
            rows = []
            for relative, payload in sorted(payloads.items()):
                target = output / "model_source/files" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                rows.append({"path": relative, "size_bytes": len(payload),
                             "sha256": hashlib.sha256(payload).hexdigest()})
            index = {"schema_version": "starvla-rsi.model-source/v1", "profile": data["identity"],
                "files": rows, "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
                "inventory_sha256": inventory_digest(rows), "scope": "synthetic old explicit bundle"}
            atomic_write_json(output / "model_source/index.json", index)
            snapshot = {key: index[key] for key in ("schema_version", "inventory_sha256", "file_count", "total_bytes")}
            snapshot.update(path="model_source/index.json", index_sha256=digest(output / "model_source/index.json"))
            descriptor = {**data["profile"]["policy"], "parameters": {"model_profile": data["identity"],
                "prompt_sha256": hashlib.sha256(payloads["campaign_prompt.txt"]).hexdigest()}}
            verify_policy_source(output, descriptor, snapshot)
            old_file = output / "model_source/files/starVLA/model_profiles.py"
            old_file.write_bytes(old_file.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "model source changed"):
                verify_policy_source(output, descriptor, snapshot)


if __name__ == "__main__":
    unittest.main()
