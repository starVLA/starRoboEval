"""Synthetic closed RGB evidence only: no native environments or model calls."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.Robocasa_365.environment import audit_rgb

try:
    import numpy as np
    from PIL import Image
except ImportError:
    np = Image = None


@unittest.skipIf(np is None or Image is None, "RGB checks require NumPy/Pillow")
class RGBChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "closed"
        self.root.mkdir()
        self.rows = []

    def fixture(self, alternating=False, count=5):
        gradient = np.repeat(np.arange(256, dtype=np.uint8)[:, None, None], 256, axis=1)
        gradient = np.repeat(gradient, 3, axis=2)
        for step in range(count):
            for index, camera in enumerate(audit_rgb.CAMERAS):
                if alternating:
                    image = gradient if (step + index) % 2 == 0 else gradient[::-1]
                else:
                    image = np.full((256, 256, 3), 40 + 70 * index, dtype=np.uint8)
                path = self.root / f"{camera}-{step:06d}.png"
                Image.fromarray(image).save(path)
                self.rows.append({"camera": camera, "step": step, "path": path.name,
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "instruction": "Move"})
        self.write_manifest()
        (self.root / "sim_server_session.json").write_text(json.dumps({
            "protocol": "starvla-rsi.sim-server/v1", "state": "closed",
            "acknowledged_controls": count - 1, "error_code": None, "cleanup_error": None}))

    def write_manifest(self):
        (self.root / "frames.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows))

    def test_healthy_stationary_distinct_cameras_do_not_warn(self):
        self.fixture()
        result = audit_rgb.audit(self.root)
        self.assertEqual(result["status"], "no_warnings")
        self.assertEqual(result["frame_count"], 15)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["schema_version"], "starvla-rsi.robocasa365.rgb-audit/v2")
        self.assertEqual(result["frame_completeness"]["status"], "matches_clean_server_receipt")
        self.assertEqual(result["frame_completeness"]["expected_steps"], 5)
        self.assertEqual(result["metrics"][1]["consecutive_frames"][audit_rgb.CAMERAS[0]]["direct_mae"], 0)

    def test_alternating_camera_clones_warn_with_explicit_thresholds(self):
        self.fixture(alternating=True)
        result = audit_rgb.audit(self.root)
        self.assertEqual(result["status"], "warnings")
        kinds = [warning["kind"] for warning in result["warnings"]]
        self.assertEqual(kinds.count("multicamera_collapse"), 1)
        self.assertEqual(kinds.count("alternating_vertical_orientation"), 3)
        self.assertEqual(result["warnings"][0]["detected_step"], 2)
        self.assertEqual(result["thresholds"]["similarity_mae"], 1.0)
        self.assertNotIn("success", result)
        self.assertNotIn("score", result)
        temporal = next(w for w in result["warnings"] if w["kind"] == "alternating_vertical_orientation")
        self.assertEqual(temporal["first_step"], 1)
        self.assertEqual(temporal["detected_step"], 3)
        self.assertIn("destination step", result["warning_step_semantics"])

    def test_short_anomaly_does_not_meet_run_threshold(self):
        self.fixture(alternating=True, count=2)
        self.assertEqual(audit_rgb.audit(self.root)["warnings"], [])

    def test_thresholds_are_configurable_and_validated(self):
        self.fixture(alternating=True)
        self.assertEqual(audit_rgb.audit(self.root, min_run=10)["warnings"], [])
        for kwargs in ({"similarity_mae": -1}, {"similarity_mae": True}, {"similarity_mae": float("nan")},
                       {"orientation_difference_mae": 0.5}, {"orientation_difference_mae": 256},
                       {"min_run": True}, {"min_run": 1}, {"min_run": 3.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                audit_rgb.audit(self.root, **kwargs)

    def test_manifest_cannot_select_unsafe_paths(self):
        self.fixture(count=1)
        original = self.rows[0]["path"]
        for path in ("../outside.png", "/etc/passwd", "a//b.png", "./frame.png", "a\\b.png", ""):
            self.rows[0]["path"] = path
            self.write_manifest()
            with self.subTest(path=path), self.assertRaises(ValueError):
                audit_rgb.audit(self.root)
        self.rows[0]["path"] = original

    def test_symlink_file_or_parent_is_not_followed(self):
        self.fixture(count=1)
        original = self.root / self.rows[0]["path"]
        outside = self.base / "outside.png"
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(outside)
        with self.assertRaises(OSError):
            audit_rgb.audit(self.root)
        original.unlink()
        (self.root / "linked").symlink_to(self.base, target_is_directory=True)
        self.rows[0]["path"] = "linked/outside.png"
        self.write_manifest()
        with self.assertRaises(OSError):
            audit_rgb.audit(self.root)

    def test_bad_digest_missing_frame_duplicate_and_noncontiguous_rejected(self):
        self.fixture(count=1)
        original = [dict(row) for row in self.rows]
        candidates = [original[:-1], original + [original[0]],
                      [{**row, "step": 1} for row in original],
                      [{**original[0], "sha256": "0" * 64}, *original[1:]]]
        for rows in candidates:
            self.rows = rows
            self.write_manifest()
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                audit_rgb.audit(self.root)

    def test_duplicate_json_keys_rejected(self):
        self.fixture(count=1)
        path = self.root / "frames.jsonl"
        data = path.read_text().replace('"step": 0', '"step": 0, "step": 0', 1)
        path.write_text(data)
        with self.assertRaises(ValueError):
            audit_rgb.audit(self.root)

    def test_open_session_is_not_a_closed_audit(self):
        self.fixture(count=1)
        (self.root / "sim_server_session.json").write_text('{"state":"running"}')
        with self.assertRaises(ValueError):
            audit_rgb.audit(self.root)

    def test_receipt_and_auditor_hashes_are_bound(self):
        self.fixture(count=1)
        result = audit_rgb.audit(self.root)
        self.assertEqual(result["server_receipt_sha256"], hashlib.sha256(
            (self.root / "sim_server_session.json").read_bytes()).hexdigest())
        self.assertEqual(result["auditor"]["source_sha256"], hashlib.sha256(
            Path(audit_rgb.__file__).read_bytes()).hexdigest())
        self.assertEqual(result["auditor"]["dependencies"]["numpy"], np.__version__)
        self.assertTrue(result["auditor"]["dependencies"]["pillow"])

    def test_clean_receipt_rejects_truncated_or_excess_frame_coverage(self):
        self.fixture(count=3)
        receipt_path = self.root / "sim_server_session.json"
        receipt = json.loads(receipt_path.read_text())
        for controls in (0, 10, True, -1, 2.0):
            receipt_path.write_text(json.dumps({**receipt, "acknowledged_controls": controls}))
            with self.subTest(controls=controls), self.assertRaises(ValueError):
                audit_rgb.audit(self.root)

    def test_absent_legacy_and_faulted_receipts_leave_completeness_unknown(self):
        self.fixture(count=1)
        receipt_path = self.root / "sim_server_session.json"
        clean = json.loads(receipt_path.read_text())
        for receipt in (None, {"state": "closed"},
                        {**clean, "protocol": "future"},
                        {**clean, "error_code": "native_or_observation_failed", "acknowledged_controls": 10},
                        {**clean, "cleanup_error": "native_close_failed"}):
            if receipt is None:
                receipt_path.unlink()
            else:
                receipt_path.write_text(json.dumps(receipt))
            with self.subTest(receipt=receipt):
                result = audit_rgb.audit(self.root)
                self.assertEqual(result["frame_completeness"]["status"], "unknown")
                self.assertIsNone(result["frame_completeness"]["expected_steps"])
                self.assertEqual(result["server_receipt_sha256"] is None, receipt is None)

    def test_receipt_recheck_detects_changed_added_or_deleted_receipt(self):
        self.fixture(count=1)
        original_read = audit_rgb._receipt_bytes
        receipt = original_read(self.root)
        for sequence in ((receipt, b'{"state":"running"}'), (None, receipt), (receipt, None)):
            with self.subTest(sequence=sequence), patch.object(audit_rgb, "_receipt_bytes", side_effect=sequence):
                with self.assertRaisesRegex(ValueError, "closure receipt changed"):
                    audit_rgb.audit(self.root)

    def test_auditor_source_recheck_detects_change_without_editing_source(self):
        self.fixture(count=1)
        original_read = audit_rgb._read
        source_name = Path(audit_rgb.__file__).name
        reads = 0

        def changing(root, relative, limit):
            nonlocal reads
            payload = original_read(root, relative, limit)
            if relative == source_name:
                reads += 1
                if reads == 2:
                    return payload + b"# synthetic concurrent change\n"
            return payload

        with patch.object(audit_rgb, "_read", side_effect=changing):
            with self.assertRaisesRegex(ValueError, "source file changed"):
                audit_rgb.audit(self.root)

    def test_image_dimensions_and_mode_rejected_before_decode(self):
        self.fixture(count=1)
        image = self.root / self.rows[0]["path"]
        Image.new("RGB", (32, 32)).save(image)
        self.rows[0]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaises(ValueError):
            audit_rgb.audit(self.root)

    def test_animated_png_rejected(self):
        self.fixture(count=1)
        image = self.root / self.rows[0]["path"]
        Image.new("RGB", (256, 256), (11, 22, 33)).save(image, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (256, 256), (44, 55, 66))])
        self.rows[0]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "single-frame"):
            audit_rgb.audit(self.root)

    def test_png_idat_crc_verified_even_when_pixels_decode(self):
        self.fixture(count=1)
        image = self.root / self.rows[0]["path"]
        payload = bytearray(image.read_bytes())
        offset = 8
        while offset < len(payload):
            size = struct.unpack(">I", payload[offset:offset + 4])[0]
            if payload[offset + 4:offset + 8] == b"IDAT":
                payload[offset + 8 + size] ^= 1
                break
            offset += size + 12
        else:
            self.fail("fixture missing IDAT")
        image.write_bytes(payload)
        self.rows[0]["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "PNG integrity"):
            audit_rgb.audit(self.root)

    def test_manifest_and_png_byte_bounds(self):
        self.fixture(count=1)
        for name in ("MAX_MANIFEST_BYTES", "MAX_PNG_BYTES", "MAX_TOTAL_PNG_BYTES", "MAX_FRAMES"):
            with self.subTest(name=name), patch.object(audit_rgb, name, 1), self.assertRaises(ValueError):
                audit_rgb.audit(self.root)

    def test_output_is_new_external_file_and_inputs_unchanged(self):
        self.fixture()
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        output = self.base / "audit.json"
        self.assertEqual(audit_rgb.main([str(self.root), "--output", str(output)]), 0)
        self.assertTrue(output.is_file())
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})
        for path in (output, self.root / "audit.json"):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                audit_rgb.main([str(self.root), "--output", str(path)])


if __name__ == "__main__":
    unittest.main()
