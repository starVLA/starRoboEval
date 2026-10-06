"""Source provenance checks using only temporary fixtures and the standard library."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchkit.artifacts import atomic_write_json, git_provenance
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.diagnostics.smoke import ReachBenchmark, ScriptedReachPolicy
from benchkit import source_snapshot
from benchkit.source_snapshot import (
    SourceSnapshotError, capture_harness_source, installed_source_root, inventory_digest,
)


class SourceSnapshotChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repository = self.root / "fixture-repository"
        self.source = self.repository / "benchkit"
        self.source.mkdir(parents=True)
        (self.source / "__init__.py").write_text('"""Fixture."""\n')
        (self.source / "runner.py").write_text("VALUE = 1\n")
        (self.source / "catalog.json").write_text('{"version": 1}\n')

    def capture(self, name, **limits):
        run = self.root / name
        run.mkdir()
        reference = capture_harness_source(run, source_root=self.source, **limits)
        index = json.loads((run / reference["path"]).read_text())
        return run, reference, index

    def git(self, *arguments):
        return subprocess.check_output(
            ["git", "-C", str(self.repository), *arguments], stderr=subprocess.PIPE
        )

    def test_copy_scope_hash_recomputation_and_deterministic_digest(self):
        (self.repository / ".env").write_text("FAKE_CREDENTIAL=outside-source\n")
        (self.repository / "credentials.json").write_text('{"fake": "outside-source"}')
        (self.source / "credentials.json").write_text('{"fake": "excluded-name"}')
        (self.source / ".env").write_text("FAKE_CREDENTIAL=excluded-hidden-path\n")
        (self.source / "weights.bin").write_bytes(b"ignored binary\0")
        cache = self.source / "__pycache__"
        cache.mkdir()
        (cache / "ignored.py").write_text("ignored even with a source suffix")
        run, reference, index = self.capture("first")
        self.assertEqual([row["path"] for row in index["files"]], ["__init__.py", "catalog.json", "runner.py"])
        for row in index["files"]:
            payload = (run / reference["files_root"] / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), row["sha256"])
            self.assertEqual(len(payload), row["size_bytes"])
        self.assertEqual(index["total_bytes"], sum(row["size_bytes"] for row in index["files"]))
        self.assertEqual(inventory_digest(index["files"]), reference["inventory_sha256"])
        canonical = json.dumps(index["files"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), reference["inventory_sha256"])
        self.assertEqual(hashlib.sha256((run / reference["path"]).read_bytes()).hexdigest(), reference["index_sha256"])
        _, repeated, _ = self.capture("repeated")
        self.assertEqual(reference["inventory_sha256"], repeated["inventory_sha256"])

    def test_clean_dirty_and_untracked_source_are_distinguishable(self):
        # All Git writes/commits in this check are confined to a disposable fixture.
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=JinhuiYE", "-c", "user.email=jinhuiyes@gmail.com",
                 "commit", "-qm", "temporary provenance fixture")
        clean = git_provenance(self.repository, evaluation_root=self.source)
        _, baseline, _ = self.capture("clean")
        self.assertFalse(clean["dirty"])
        self.assertEqual(clean["evaluation_package_diff"]["sha256"], hashlib.sha256(b"").hexdigest())
        (self.source / "runner.py").write_text("VALUE = 2\n")
        dirty = git_provenance(self.repository, evaluation_root=self.source)
        _, modified, _ = self.capture("dirty")
        self.assertTrue(dirty["dirty"])
        self.assertNotEqual(baseline["inventory_sha256"], modified["inventory_sha256"])
        expected = self.git("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--binary", "--", "benchkit")
        self.assertEqual(dirty["evaluation_package_diff"]["sha256"], hashlib.sha256(expected).hexdigest())
        (self.source / "new_adapter.py").write_text("UNTRACKED = True\n")
        untracked = git_provenance(self.repository, evaluation_root=self.source)
        _, added, index = self.capture("new-file")
        self.assertNotEqual(modified["inventory_sha256"], added["inventory_sha256"])
        self.assertIn("new_adapter.py", [row["path"] for row in index["files"]])
        # HEAD diff intentionally omits untracked files; the source copy includes them.
        self.assertEqual(dirty["evaluation_package_diff"]["sha256"], untracked["evaluation_package_diff"]["sha256"])
        self.assertFalse(untracked["evaluation_package_diff"]["includes_untracked_files"])
        (self.repository / "outside-package.py").write_text("DO_NOT_CAPTURE = True\n")
        _, outside_change, _ = self.capture("outside-change")
        self.assertEqual(added["inventory_sha256"], outside_change["inventory_sha256"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_source_file_directory_and_root_symlinks_are_rejected(self):
        outside = self.root / "outside.py"
        outside.write_text("DO_NOT_READ = True\n")
        link = self.source / "linked.py"
        link.symlink_to(outside)
        with self.assertRaisesRegex(SourceSnapshotError, "symlink"):
            self.capture("file-link")
        link.unlink()
        (self.source / "linked-directory").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(SourceSnapshotError, "symlink"):
            self.capture("directory-link")
        root_link = self.root / "root-link"
        root_link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(SourceSnapshotError, "symlink"):
            capture_harness_source(self.root, source_root=root_link)

    def test_oversized_file_total_and_file_count_are_rejected(self):
        for name, limits in (("file-limit", {"max_file_bytes": 1}),
                             ("total-limit", {"max_total_bytes": 1}),
                             ("count-limit", {"max_files": 1})):
            with self.subTest(name=name), self.assertRaises(SourceSnapshotError):
                self.capture(name, **limits)
            self.assertFalse((self.root / name / "harness_source" / "index.json").exists())

    def test_ignored_entries_cannot_bypass_the_bounded_tree_scan(self):
        for number in range(5):
            (self.source / f"ignored-{number}.bin").write_bytes(b"not source")
        with patch.object(source_snapshot, "MAX_TREE_ENTRIES", 4):
            with self.assertRaisesRegex(SourceSnapshotError, "entry scan limit"):
                self.capture("tree-limit")

    def test_source_added_during_capture_invalidates_the_snapshot(self):
        original_scan = source_snapshot._source_files
        scan_count = 0

        def add_after_first_inventory(root, max_files):
            nonlocal scan_count
            inventory = original_scan(root, max_files)
            scan_count += 1
            if scan_count == 1:
                (self.source / "late.py").write_text("ARRIVED_DURING_CAPTURE = True\n")
            return inventory

        with patch.object(source_snapshot, "_source_files", side_effect=add_after_first_inventory):
            with self.assertRaisesRegex(SourceSnapshotError, "tree changed"):
                self.capture("changed-tree")
        self.assertFalse((self.root / "changed-tree" / "harness_source" / "index.json").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_parent_directory_replaced_after_scan_cannot_escape_package(self):
        nested = self.source / "nested"
        nested.mkdir()
        (nested / "adapter.py").write_text("ORIGINAL_SOURCE = True\n")
        outside = self.root / "outside-package"
        outside.mkdir()
        (outside / "adapter.py").write_text("FAKE_EXTERNAL_CREDENTIAL = True\n")
        original_scan = source_snapshot._source_files

        def swap_parent_after_inventory(root, max_files):
            inventory = original_scan(root, max_files)
            nested.rename(self.root / "moved-original")
            nested.symlink_to(outside, target_is_directory=True)
            return inventory

        with patch.object(source_snapshot, "_source_files", side_effect=swap_parent_after_inventory):
            with self.assertRaises(SourceSnapshotError):
                self.capture("raced-symlink")
        snapshot = self.root / "raced-symlink" / "harness_source"
        self.assertFalse((snapshot / "index.json").exists())
        self.assertFalse((snapshot / "files" / "nested" / "adapter.py").exists())

    def test_existing_snapshot_and_atomic_json_are_not_overwritten(self):
        run, reference, _ = self.capture("existing")
        original = (run / reference["path"]).read_bytes()
        (self.source / "runner.py").write_text("CHANGED = True\n")
        with self.assertRaises(FileExistsError):
            capture_harness_source(run, source_root=self.source)
        self.assertEqual((run / reference["path"]).read_bytes(), original)
        path = self.root / "immutable.json"
        atomic_write_json(path, {"original": True}, overwrite=False)
        with self.assertRaises(FileExistsError):
            atomic_write_json(path, {"replacement": True}, overwrite=False)
        self.assertEqual(json.loads(path.read_text()), {"original": True})

    def test_snapshot_cannot_recurse_into_its_source(self):
        output = self.source / "bad-output"
        output.mkdir()
        with self.assertRaisesRegex(SourceSnapshotError, "outside"):
            capture_harness_source(output, source_root=self.source)


class RunnerInitializationChecks(unittest.TestCase):
    def test_snapshot_failure_is_terminal_before_open_or_policy_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = RunRequest(output_dir=Path(temporary), run_id="failed-source")
            benchmark = ReachBenchmark()
            policy = ScriptedReachPolicy()
            with patch("AgentPolicies.policy_support.runner.capture_harness_source", side_effect=SourceSnapshotError("oversized source")), \
                    patch.object(benchmark, "open_episode") as open_episode, \
                    patch.object(policy, "start_episode") as start_episode:
                with self.assertRaises(SourceSnapshotError):
                    EvaluationRunner().run(benchmark, policy, request)
            open_episode.assert_not_called()
            start_episode.assert_not_called()
            run = Path(temporary) / "failed-source"
            status = json.loads((run / "status.json").read_text())
            failure = json.loads((run / "initialization_error.json").read_text())
            self.assertEqual(status["status"], "initialization_failed")
            self.assertEqual(status["episodes_written"], 0)
            self.assertEqual(failure["phase"], "initialization")
            self.assertEqual(failure["error"]["category"], "infrastructure")
            self.assertFalse((run / "episodes.jsonl").exists())
            self.assertFalse((run / "manifest.json").exists())

    def test_manifest_failure_never_starts_simulator_or_leaves_running(self):
        original_writer = atomic_write_json

        def fail_manifest(path, payload, **options):
            if path.name == "manifest.json":
                raise OSError("injected manifest publication failure")
            return original_writer(path, payload, **options)

        with tempfile.TemporaryDirectory() as temporary:
            benchmark = ReachBenchmark()
            with patch("AgentPolicies.policy_support.runner.atomic_write_json", side_effect=fail_manifest), \
                    patch.object(benchmark, "open_episode") as open_episode:
                with self.assertRaisesRegex(OSError, "publication failure"):
                    EvaluationRunner().run(benchmark, ScriptedReachPolicy(),
                                           RunRequest(output_dir=Path(temporary), run_id="failed-manifest"))
            open_episode.assert_not_called()
            status = json.loads((Path(temporary) / "failed-manifest" / "status.json").read_text())
            self.assertEqual(status["status"], "initialization_failed")

    def test_installed_package_is_captured_before_reset_without_policy_exposure(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "private-source"
            benchmark = ReachBenchmark()
            policy = ScriptedReachPolicy()
            original_open = benchmark.open_episode
            contexts = []

            def open_after_capture(episode):
                manifest = json.loads((run / "manifest.json").read_text())
                self.assertTrue((run / manifest["harness_source"]["path"]).is_file())
                return original_open(episode)

            with patch.object(benchmark, "open_episode", side_effect=open_after_capture), \
                    patch.object(policy, "start_episode", side_effect=contexts.append):
                EvaluationRunner().run(benchmark, policy,
                                       RunRequest(output_dir=Path(temporary), run_id="private-source", episode_limit=1))
            manifest = json.loads((run / "manifest.json").read_text())
            reference = manifest["harness_source"]
            self.assertEqual(Path(reference["source_root"]), installed_source_root().parent)
            index = json.loads((run / reference["path"]).read_text())
            self.assertIn("benchkit/source_snapshot.py", [row["path"] for row in index["files"]])
            self.assertEqual(index["schema_version"], "starvla-rsi.harness-source/v2")
            names = {row["path"] for row in index["files"]}
            self.assertEqual(len(names), len(index["files"]), "source capture must not duplicate paths")
            for benchmark in ("LIBERO", "SimplerEnv", "SIMPLE"):
                base = f"benchmarks/simBenchmarks/{benchmark}/"
                self.assertIn(base + "bench_server/adapter.py", names)
                self.assertIn(base + "bench_server/protocol/plan.py", names)
                self.assertNotIn(base + "adapter.py", names)
                self.assertNotIn(base + "evaluation/plan.py", names)
            self.assertIn("benchkit/sim_server/server.py", names)
            self.assertIn("benchkit/sim_server/client.py", names)
            self.assertFalse(any(name.startswith("benchmarks/simBenchmarks/service/") for name in names))
            self.assertEqual({name for name in names if name.startswith("AgentPolicies/")},
                             {"AgentPolicies/policy_support/runner.py", "AgentPolicies/gpt6_astra/run.py"})
            self.assertFalse(any("/checks/" in name for name in names))
            self.assertNotIn("harness_source", repr(contexts[0]))
            self.assertNotIn(str(run), repr(contexts[0]))
            self.assertFalse(hasattr(contexts[0], "runtime"))
            self.assertFalse(hasattr(contexts[0].episode, "metadata"))


if __name__ == "__main__":
    unittest.main()
