"""Prospective selection/claim guards; no simulator or policy calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter import (
    ACTION_SPEC, NEXT_TASKS, PILOT_SEED, PILOT_TASKS, TASK_LAYOUTS, TabletopBenchmarkAdapter,
    make_tabletop,
)
from benchkit.campaigns.workflow import (
    cases_for, prepare, run_case, summarize, verify_frozen_package, verify_tabletop_next_pair,
)
from benchkit.errors import ProtocolError

SCOPE = "tabletop-next-pair-v1"


class NextPairChecks(unittest.TestCase):
    def test_explicit_scope_does_not_change_pilot_defaults(self):
        pilot = TabletopBenchmarkAdapter()
        new = make_tabletop({"task_scope": SCOPE})
        self.assertEqual([e.task for e in pilot.episodes(PILOT_SEED)], list(PILOT_TASKS.values()))
        self.assertEqual([e.task for e in new.episodes(PILOT_SEED)], list(NEXT_TASKS.values()))
        self.assertEqual(new.task_ids, (1, 2))
        self.assertEqual(new.action_spec, ACTION_SPEC)
        self.assertEqual(new.observation_spec, pilot.observation_spec)
        self.assertNotEqual(new.descriptor.protocol_version, pilot.descriptor.protocol_version)
        self.assertEqual(new.budget_metadata(), pilot.budget_metadata())
        self.assertEqual(TASK_LAYOUTS, {0: 4, 19: 0, 1: 2, 2: 2})
        for episode in new.episodes(PILOT_SEED):
            self.assertEqual(episode.metadata["candidate_layout_ids"], [2])
            self.assertEqual(episode.metadata["candidate_style_ids"], list(range(12)))
            with self.assertRaises(ProtocolError):
                pilot.open_episode(episode)

    def test_new_scope_rejects_pilot_other_duplicate_and_mistyped_ids(self):
        for ids in ([0], [19], [1, 19], [3], [], [2, 1], [1, 1], [True], [1.0]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                TabletopBenchmarkAdapter(task_scope=SCOPE, task_ids=ids)
        with self.assertRaises(ValueError):
            TabletopBenchmarkAdapter(task_ids=[1])
        with self.assertRaises(ValueError):
            TabletopBenchmarkAdapter(task_scope="all24")

    def test_campaign_freezes_exact_two_new_tasks_and_public_guide(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            m = prepare(root / "pair", "robocasa_tabletop", root / "public", "Use declared sensors.", task_scope=SCOPE)
            verify_tabletop_next_pair(m)
            verify_frozen_package(root / "pair", m)
            self.assertEqual([c["benchmark_args"]["task_ids"] for c in m["cases"]], [[1], [2]])
            self.assertEqual(m["runtime_environment"], {"PYTHONHASHSEED": "0"})
            self.assertEqual(m["purpose"], "development_pilot")
            self.assertNotIn("coverage_ledger", m)
            self.assertEqual(summarize(root / "pair")["unattempted"], 2)
            self.assertEqual(len(m["supplemental_runtime_files"]), 1)
            guide = root / "pair/frozen/benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/protocol/POLICY_GUIDE.md"
            self.assertTrue(m["policy_prompt"].endswith(guide.read_text()))

    def manifest(self):
        return {"benchmark": "robocasa_tabletop", "task_scope": SCOPE, "purpose": "development_pilot",
                "seed": PILOT_SEED, "planned_cases": 2, "attempts_per_task": 1,
                "budget_mode": "decisions", "max_policy_calls": 200, "replan_interval": 5,
                "max_steps": 1000, "runtime_environment": {"PYTHONHASHSEED": "0"},
                "cases": cases_for("robocasa_tabletop", 200, 5, task_scope=SCOPE)}

    def test_typed_identity_budgets_hashseed_and_scope_are_bound(self):
        valid = self.manifest()
        verify_tabletop_next_pair(valid)
        for key, value in (("benchmark", "robodojo"), ("task_scope", "next-pair-v1"),
                           ("purpose", "development_task_coverage"), ("seed", 20260907.0),
                           ("planned_cases", 2.0), ("attempts_per_task", True),
                           ("max_policy_calls", 200.0), ("max_steps", 999),
                           ("runtime_environment", {}), ("budget_mode", "horizon"),
                           ("coverage_ledger", {})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_tabletop_next_pair({**valid, key: value})
        for key, value in (("candidate_layout_ids", [0]), ("native_task_index", True),
                           ("attempt", True), ("candidate_style_ids", [0])):
            changed = copy.deepcopy(valid)
            changed["cases"][0]["episode"]["metadata"][key] = value
            with self.subTest(metadata=key), self.assertRaises(ValueError):
                verify_tabletop_next_pair(changed)
        changed = copy.deepcopy(valid)
        changed["cases"] = cases_for("robocasa_tabletop", 200, 5)
        with self.assertRaises(ValueError):
            verify_tabletop_next_pair(changed)

    def test_removed_scope_is_rejected_before_claim_by_new_task_identity(self):
        m = self.manifest()
        del m["task_scope"]
        for case in m["cases"]:
            del case["benchmark_args"]["task_scope"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("benchkit.campaigns.workflow.load_campaign", return_value=m), \
                    patch("benchkit.campaigns.workflow.verify_frozen_package"), \
                    patch("benchkit.campaigns.workflow.subprocess.Popen") as launch:
                with self.assertRaises(ValueError):
                    run_case(root, 0, 2)
                launch.assert_not_called()
            self.assertFalse((root / "case-000").exists())

    def test_failed_launch_claim_is_permanent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "pair"
            prepare(output, "robocasa_tabletop", root / "public", "Use declared sensors.", task_scope=SCOPE)
            with patch("benchkit.campaigns.workflow.subprocess.Popen", side_effect=OSError("fixture launch failure")):
                with self.assertRaises(OSError):
                    run_case(output, 0, 2)
            result = json.loads((output / "case-000/outcome.json").read_text())
            self.assertEqual(result["status"], "infrastructure_or_policy_error")
            with self.assertRaises(FileExistsError):
                run_case(output, 0, 2)
            self.assertFalse((output / "case-001").exists())


if __name__ == "__main__":
    unittest.main()
