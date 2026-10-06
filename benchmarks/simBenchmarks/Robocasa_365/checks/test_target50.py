"""Target50 identity and compatibility checks; no simulator construction."""

import copy
import hashlib
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import (
    PILOT_SEED, PILOT_TASKS, RoboCasa365BenchmarkAdapter, make_robocasa365,
    target50_inventory, verify_target50_registry, verify_target50_sources,
)
from benchkit.errors import CompatibilityError, ProtocolError


class Target50Checks(unittest.TestCase):
    def setUp(self):
        self.inventory = target50_inventory()

    def adapter(self, ids):
        return RoboCasa365BenchmarkAdapter(task_ids=ids, task_scope="target50",
            budget_mode="decisions", max_policy_calls=200, replan_interval=5)

    def registries(self):
        groups = {group: [r["task"] for r in self.inventory["tasks"] if r["task_set"] == group]
                  for group in self.inventory["counts"]}
        atomic, composite = {}, {}
        for row in self.inventory["tasks"]:
            destination = atomic if row["task_set"] == "atomic_seen" else composite
            destination[row["task"]] = {"horizon": row["native_horizon"]}
        return groups, atomic, composite

    def test_exact_denominator_groups_and_order(self):
        rows = self.inventory["tasks"]
        self.assertEqual(len(rows), 50)
        self.assertEqual(Counter(r["task_set"] for r in rows), self.inventory["counts"])
        self.assertEqual([r["task"] for r in rows if r["index"] in (0, 17, 18, 33, 34, 49)],
            ["CloseBlenderLid", "TurnOnSinkFaucet", "DeliverStraw", "WashLettuce",
             "ArrangeBreadBasket", "WeighIngredients"])
        self.assertEqual(len({r["task"] for r in rows}), 50)
        self.assertNotIn("WipeTable", {r["task"] for r in rows})

    def test_all_fifty_episodes_have_distinct_scoped_ids(self):
        adapter = self.adapter(list(range(50)))
        episodes = adapter.episodes(PILOT_SEED)
        self.assertEqual([e.task for e in episodes], [r["task"] for r in self.inventory["tasks"]])
        self.assertEqual(len({e.id for e in episodes}), 50)
        for row, ep in zip(self.inventory["tasks"], episodes):
            self.assertEqual(ep.metadata["native_horizon"], row["native_horizon"])
            self.assertEqual(ep.metadata["task_set"], row["task_set"])
            self.assertEqual(ep.metadata["task_scope"], "target50")
            self.assertEqual(ep.metadata["environment_step_cap"], 1000)
            self.assertEqual(ep.metadata["split"], "target")
            self.assertEqual(ep.seed, PILOT_SEED)
            self.assertIsNotNone(adapter.open_episode(ep))  # No native import/reset.

    def test_native_horizons_are_not_replaced_by_the_common_cap(self):
        adapter = self.adapter([2, 5, 34])
        rows = adapter.episodes(PILOT_SEED)
        self.assertEqual([e.metadata["native_horizon"] for e in rows], [450, 1050, 4350])
        self.assertEqual([adapter.step_cap(e.task) for e in rows], [1000, 1000, 1000])
        native = RoboCasa365BenchmarkAdapter(task_ids=[34], task_scope="target50")
        self.assertEqual(native.step_cap("ArrangeBreadBasket"), 4350)
        self.assertNotEqual(native.descriptor.protocol_version, adapter.descriptor.protocol_version)

    def test_legacy_pilot_ids_protocol_metadata_and_default_are_unchanged(self):
        pilot = RoboCasa365BenchmarkAdapter()
        episodes = pilot.episodes(PILOT_SEED)
        self.assertEqual([e.task for e in episodes], list(PILOT_TASKS))
        self.assertEqual([e.id for e in episodes],
            ["robocasa365-task00-attempt01", "robocasa365-task01-attempt01"])
        self.assertEqual(pilot.descriptor.protocol_version,
                         "target-first2-development/rgb/native-horizons/v1")
        self.assertTrue(all("task_scope" not in e.metadata for e in episodes))
        expanded = self.adapter([4, 6]).episodes(PILOT_SEED)
        self.assertEqual([e.task for e in expanded], ["NavigateKitchen", "OpenDrawer"])
        self.assertFalse(set(e.id for e in expanded) & set(e.id for e in episodes))
        # Carry-forward/no-retry is campaign-specific, not a global ban on
        # evaluating these tasks with a different future policy.
        for ep in expanded:
            self.assertIsNotNone(self.adapter([ep.metadata["task_id"]]).open_episode(ep))

    def test_invalid_scope_selection_and_cross_scope_episode_fail(self):
        for scope in (None, "365", "all", "target", True):
            with self.assertRaises(ValueError):
                RoboCasa365BenchmarkAdapter(task_scope=scope)
        for ids in ([], [50], [-1], [True], [1, 0], [0, 0], [0.0]):
            with self.assertRaises(ValueError):
                self.adapter(ids)
        adapter = self.adapter([6])
        pilot = RoboCasa365BenchmarkAdapter(task_ids=[0]).episodes(PILOT_SEED)[0]
        with self.assertRaises(ProtocolError):
            adapter.open_episode(pilot)
        ep = adapter.episodes(PILOT_SEED)[0]
        with self.assertRaises(ProtocolError):
            adapter.open_episode(replace(ep, metadata={**ep.metadata, "native_horizon": 1000}))

    def test_native_registry_order_horizon_missing_and_wrong_group_fail(self):
        groups, atomic, composite = self.registries()
        verify_target50_registry(groups, atomic, composite)
        swapped = copy.deepcopy(groups)
        swapped["atomic_seen"][0:2] = reversed(swapped["atomic_seen"][0:2])
        with self.assertRaises(CompatibilityError):
            verify_target50_registry(swapped, atomic, composite)
        bad = copy.deepcopy(composite)
        bad["WeighIngredients"]["horizon"] = 1000
        with self.assertRaises(CompatibilityError):
            verify_target50_registry(groups, atomic, bad)
        del bad["WeighIngredients"]
        with self.assertRaises(CompatibilityError):
            verify_target50_registry(groups, atomic, bad)
        with self.assertRaises(CompatibilityError):
            verify_target50_registry(groups, composite, atomic)

    def test_file_only_source_binding_detects_changed_missing_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "native.py"
            source.write_bytes(b"native source")
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            inventory = {"source_files": {"native.py": sha}, "tasks": []}
            with patch("benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter.target50_inventory", return_value=inventory):
                report = verify_target50_sources(root)
                self.assertFalse(report["native_execution_verified"])
                source.write_bytes(b"changed source")
                with self.assertRaises(CompatibilityError):
                    verify_target50_sources(root)
                source.unlink()
                with self.assertRaises(CompatibilityError):
                    verify_target50_sources(root)
                actual = root / "actual.py"
                actual.write_bytes(b"native source")
                source.symlink_to(actual)
                with self.assertRaises(CompatibilityError):
                    verify_target50_sources(root)

    def test_cli_factory_exposes_scope_without_changing_pilot_default(self):
        self.assertEqual(make_robocasa365({}).task_scope, "pilot")
        adapter = make_robocasa365({"task_scope": "target50", "task_ids": [49]})
        self.assertEqual(adapter.episodes(PILOT_SEED)[0].task, "WeighIngredients")
        with self.assertRaises(ValueError):
            make_robocasa365({"scope": "target50"})


if __name__ == "__main__":
    unittest.main()
