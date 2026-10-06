from pathlib import Path
import unittest

from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.task_catalog import CATALOG_PATH, load_catalog, task_spec


class RoboDojoTaskCatalogChecks(unittest.TestCase):
    def test_public_catalog_has_one_accepted_task_not_one_protocol_per_task(self):
        catalog = load_catalog()
        self.assertEqual(set(catalog["tasks"]), {"classify_objects"})
        task = task_spec("classify_objects")
        self.assertEqual(task["panels"]["fast"]["layout_ids"], list(range(5)))
        self.assertEqual(task["panels"]["full"]["layout_ids"], list(range(50)))
        self.assertEqual(task["native_horizon"], 1100)
        self.assertEqual(task["panels"]["fast"]["attempts_per_layout"], 1)
        self.assertEqual(task["panels"]["full"]["attempts_per_layout"], 1)
        self.assertNotIn("protocol", task)
        self.assertNotIn("protocol_version", task)

    def test_catalog_binds_the_frozen_layout_snapshot(self):
        task = task_spec("classify_objects")
        import hashlib
        path = CATALOG_PATH.parents[2] / "environment/reference_eef_snapshot.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         task["layout_binding"]["snapshot_sha256"])

    def test_unknown_task_is_not_a_fallback(self):
        with self.assertRaises(ValueError):
            task_spec("arrange_largest_number")


if __name__ == "__main__":
    unittest.main()
