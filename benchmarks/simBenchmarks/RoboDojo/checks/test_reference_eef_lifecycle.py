"""CPU-only native path identity and failed-reset artifact regressions."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from benchmarks.simBenchmarks.RoboDojo.environment import native_eef_worker as worker_module
from benchmarks.simBenchmarks.RoboDojo.environment.native_eef_worker import (
    ReferenceEEFWorker, validate_native_layout_manager,
)


def native_seed_fixture(root: Path):
    """Reproduce native path spelling/cursor; files contain synthetic bytes."""
    fixture = json.loads((Path(__file__).with_name("fixtures") / "reference_eef_configuration.json").read_text())
    projection = dict(fixture["seed_manager_projection"])
    template = projection.pop("native_path_template")
    source = root / "RoboDojo"
    (source / "env").mkdir(parents=True)
    directory = source / "Assets/Eval_Layout/RoboDojo/arx_x5/0"
    directory.mkdir(parents=True)
    rows, seed_info = [], {}
    for i in range(55):
        path = directory / f"classify_objects_{i}.json"
        data = f"synthetic-{i}".encode()
        path.write_bytes(data)
        rows.append({"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        seed_info[i] = {"scene_layout": template.format(source_root=source, layout_id=i)}
    manager = SimpleNamespace(**projection, seed_list=list(range(55)), seed_info=seed_info)
    return source, manager, rows


class ReferenceEEFLifecycleChecks(unittest.TestCase):
    def test_native_parent_segment_paths_match_all55_hashes_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, manager, rows = native_seed_fixture(root)
            before = deepcopy(manager.__dict__)
            receipt = validate_native_layout_manager(manager, source, rows, root)
            self.assertTrue(receipt["validated"])
            self.assertEqual(len(receipt["entries"]), 55)
            self.assertTrue(all(row["canonical_path_matches"] and row["hash_matches"] for row in receipt["entries"]))
            self.assertEqual(manager.__dict__, before)
            self.assertIn("/env/../Assets/", manager.seed_info[0]["scene_layout"])
            text = (root / "native_layout_validation.json").read_text()
            self.assertNotIn("synthetic-", text)
            self.assertNotIn(str(source), text)
            self.assertFalse(receipt["layout_contents_exposed"])

    def test_same_path_with_changed_bytes_fails_and_records_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, manager, rows = native_seed_fixture(root)
            Path(manager.seed_info[3]["scene_layout"]).write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, r"layout3.hash_matches"):
                validate_native_layout_manager(manager, source, rows, root)
            receipt = json.loads((root / "native_layout_validation.json").read_text())
            self.assertTrue(receipt["entries"][3]["canonical_path_matches"])
            self.assertFalse(receipt["entries"][3]["hash_matches"])
            self.assertEqual(manager.idx, 0)

    def test_identical_bytes_at_different_path_are_not_read_or_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, manager, rows = native_seed_fixture(root)
            other = root / "other.json"
            other.write_bytes(Path(manager.seed_info[0]["scene_layout"]).read_bytes())
            manager.seed_info[0]["scene_layout"] = str(other)
            real_sha = worker_module.sha
            def only_expected(path):
                self.assertNotEqual(path, other)
                return real_sha(path)
            with patch.object(worker_module, "sha", side_effect=only_expected), self.assertRaisesRegex(RuntimeError, "canonical_path_matches"):
                validate_native_layout_manager(manager, source, rows, root)
            receipt = json.loads((root / "native_layout_validation.json").read_text())
            self.assertIsNone(receipt["entries"][0]["sha256"])

    def test_extra_mapping_fields_are_not_exposed_or_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, manager, rows = native_seed_fixture(root)
            manager.seed_info[0]["unrequested"] = {"do_not_expose_this_value": 99}
            with self.assertRaisesRegex(RuntimeError, "keys_match"):
                validate_native_layout_manager(manager, source, rows, root)
            text = (root / "native_layout_validation.json").read_text()
            self.assertNotIn("do_not_expose_this_value", text)

    def test_manager_cursor_and_inventory_drift_remain_errors(self):
        for field, value in (("idx", 1), ("_current_batch_seeds", [0]), ("ed_idx", 54),
                             ("seed_list", list(range(54))), ("eval_seed", 1)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, manager, rows = native_seed_fixture(root)
                setattr(manager, field, value)
                before = deepcopy(manager.__dict__)
                with self.assertRaisesRegex(RuntimeError, "manager."):
                    validate_native_layout_manager(manager, source, rows, root)
                receipt = json.loads((root / "native_layout_validation.json").read_text())
                self.assertFalse(receipt["validated"])
                self.assertEqual(manager.__dict__, before)

    def test_incomplete_reset_finalization_lists_only_existing_regular_evidence(self):
        class UninitializedNative:
            def __getattr__(self, name):
                raise AssertionError("failed reset must not query incomplete native state: " + name)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = ReferenceEEFWorker()
            worker.output, worker.env = root, UninitializedNative()
            (root / "native_error_reset.json").write_text('{"error":"preserved failure"}')
            (root / "native_config_validation.json").write_text('{"validated":false}')
            worker.event("reset_failed")
            result = worker.finalize()
            self.assertFalse(result["reset_completed"])
            self.assertFalse(result["metrics"]["success"])
            self.assertFalse(result["metrics"]["native_reset_completed"])
            self.assertIsNone(result["metrics"]["native_benchmark_score"])
            self.assertIn("native_error_reset", result["artifacts"])
            self.assertIn("native_config_validation", result["artifacts"])
            self.assertNotIn("frame_manifest", result["artifacts"])
            self.assertNotIn("asset_manifest", result["artifacts"])
            self.assertTrue(all((root / p).is_file() and not (root / p).is_symlink()
                for p in result["artifacts"].values()))
            self.assertEqual(worker.finalize(), result)

    def test_incomplete_reset_does_not_advertise_symlink_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = ReferenceEEFWorker()
            worker.output = root
            (root / "real.json").write_text("{}")
            (root / "frame_manifest.json").symlink_to("real.json")
            self.assertNotIn("frame_manifest", worker.finalize()["artifacts"])

    def test_completed_reset_keeps_strict_required_artifact_contract(self):
        worker = ReferenceEEFWorker()
        worker.reset_completed = True
        expected = {"metrics": {"success": False}, "artifacts": {
            "frame_manifest": "frame_manifest.json", "asset_manifest": "asset_manifest.json"}}
        with patch.object(worker_module.Worker, "finalize", return_value=expected) as original:
            self.assertIs(worker.finalize(), expected)
        original.assert_called_once()

    def test_video_finalization_errors_are_not_hidden_for_incomplete_reset(self):
        worker = ReferenceEEFWorker()
        with patch.object(worker_module.Worker, "finalize", side_effect=RuntimeError("recording failure")):
            with self.assertRaisesRegex(RuntimeError, "recording failure"):
                worker.finalize()

    def test_incomplete_reset_never_executes_target_or_reads_robot_state(self):
        worker = ReferenceEEFWorker()
        worker.env = object()
        worker.measured_robot = Mock(side_effect=AssertionError("state query after failed reset"))
        with self.assertRaisesRegex(RuntimeError, "completed sensor reset"):
            worker.step([0, 0, 0, 1, 0, 0, 0, 1] * 2)
        worker.measured_robot.assert_not_called()
        self.assertEqual(worker.targets, 0)
        self.assertEqual(worker.attempted_targets, 0)


if __name__ == "__main__":
    unittest.main()
