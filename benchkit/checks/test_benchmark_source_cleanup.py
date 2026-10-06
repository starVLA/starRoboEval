"""Source-tree cleanup must not discard or relabel historical evidence."""

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def relocated_result(relative):
    """Resolve the root-directory rename without rewriting historical indexes."""
    for prefix, current in (("starVLA/", "AgentPolicies/"),
                            ("examples/", "benchmarks/"), ("harness/", "benchkit/")):
        if relative.startswith(prefix):
            return ROOT / (current + relative[len(prefix):])
    return ROOT / relative


class BenchmarkSourceCleanupTests(unittest.TestCase):
    def test_removed_copies_have_hash_identical_preserved_records(self):
        index = ROOT / "AgentPolicies/anonymous_code_agent/results/source_cleanup.json"
        document = json.loads(index.read_text())
        self.assertEqual(len(document["documents"]), 14)
        for item in document["documents"]:
            with self.subTest(path=item["removed_path"]):
                self.assertFalse((ROOT / item["removed_path"]).exists())
                preserved = relocated_result(item["preserved_path"])
                self.assertEqual(hashlib.sha256(preserved.read_bytes()).hexdigest(), item["sha256"])

    def test_canonical_service_and_catalog_still_exist(self):
        for benchmark, catalog in (("SimplerEnv", "task_catalog.json"),
                                   ("LIBERO", "libero_catalog.json"),
                                   ("SIMPLE", "simple_released_tasks.json")):
            base = ROOT / "benchmarks/simBenchmarks" / benchmark
            self.assertTrue((base / "server.py").is_file())
            self.assertTrue((base / "bench_server/adapter.py").is_file())
            self.assertTrue((base / "bench_server/protocol" / catalog).is_file())

    def test_historical_document_path_map_resolves(self):
        index = ROOT / "AgentPolicies/anonymous_code_agent/results/source_cleanup.json"
        for item in json.loads(index.read_text())["reference_path_relocations"]:
            with self.subTest(path=item["old_path"]):
                self.assertFalse((ROOT / item["old_path"]).exists())
                self.assertTrue(relocated_result(item["current_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
