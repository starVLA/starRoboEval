"""Fake C API only: these regressions never load a native library or GPU."""
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from benchmarks.simBenchmarks.Robotwin.environment import renderer_readiness as readiness


class RendererReadinessChecks(unittest.TestCase):
    def api(self, handle=7, error=0):
        return SimpleNamespace(oidnGetNumPhysicalDevices=Mock(return_value=int(bool(handle))),
                               oidnNewDevice=Mock(return_value=handle),
                               oidnGetDeviceError=Mock(return_value=error),
                               oidnCommitDevice=Mock(), oidnReleaseDevice=Mock())

    def test_success_is_cuda_only_and_releases_device(self):
        api = self.api()
        self.assertTrue(readiness.check_cuda_device(api)["passed"])
        api.oidnNewDevice.assert_called_once_with(3)
        api.oidnCommitDevice.assert_called_once_with(7)
        api.oidnReleaseDevice.assert_called_once_with(7)

    def test_unsupported_cuda_does_not_commit_or_release_null(self):
        api = self.api(None, 5)
        report = readiness.check_cuda_device(api)
        self.assertFalse(report["passed"])
        self.assertEqual(report["error_code"], 5)
        api.oidnCommitDevice.assert_not_called()
        api.oidnReleaseDevice.assert_not_called()

    def test_commit_error_is_not_a_pass_and_releases(self):
        api = self.api(error=5)
        self.assertFalse(readiness.check_cuda_device(api)["passed"])
        api.oidnReleaseDevice.assert_called_once_with(7)

    def test_exception_still_releases_created_device(self):
        api = self.api()
        api.oidnCommitDevice.side_effect = RuntimeError("device failure")
        with self.assertRaises(RuntimeError):
            readiness.check_cuda_device(api)
        api.oidnReleaseDevice.assert_called_once_with(7)

    def test_missing_library_failure_is_saved_without_loading(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(readiness.ctypes, "CDLL") as loader:
            report_path = Path(directory) / "report.json"
            with redirect_stdout(io.StringIO()):
                result = readiness.main(["--library-directory", directory, "--output", str(report_path)])
            report = json.loads(report_path.read_text())
            self.assertEqual(result, 1)
            self.assertFalse(report["passed"])
            self.assertEqual(report["model_calls"], 0)
            self.assertEqual(report["error"]["type"], "ValueError")
            loader.assert_not_called()
            original = report_path.read_bytes()
            with self.assertRaises(FileExistsError):
                readiness.main(["--library-directory", directory, "--output", str(report_path)])
            self.assertEqual(report_path.read_bytes(), original)

    def test_library_mismatch_and_symlink_fail_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / readiness.LIBRARIES[0]
            path.write_bytes(b"not the pinned library")
            with self.assertRaisesRegex(ValueError, "differs"):
                readiness.verify_libraries(Path(directory))
            target = Path(directory) / "link.so"
            target.symlink_to(path)
            with patch.object(readiness, "LIBRARIES", ("link.so",)), patch.object(readiness.json, "loads", return_value={
                "packages": {"sapien": {"files": [{"path": "sapien/oidn_library/link.so"}]}}}):
                with self.assertRaisesRegex(ValueError, "symlinked"):
                    readiness.verify_libraries(Path(directory))

    def test_selected_three_libraries_are_pinned(self):
        snapshot = json.loads(Path(readiness.__file__).with_name("runtime_snapshot.json").read_text())
        rows = snapshot["packages"]["sapien"]["files"]
        selected = [row for row in rows if row["path"].startswith("sapien/oidn_library/")]
        self.assertEqual({Path(row["path"]).name for row in selected}, set(readiness.LIBRARIES))
        self.assertTrue(all(len(row["sha256"]) == hashlib.sha256().digest_size * 2 for row in selected))

    def test_changed_snapshot_is_rejected_before_native_library_inspection(self):
        with patch.object(readiness, "RUNTIME_SNAPSHOT_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "snapshot changed"):
                readiness.verify_libraries(Path("/unused"))

    def test_device_selection_receipt_excludes_unrelated_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(readiness.os.environ, {
            "CUDA_VISIBLE_DEVICES": "2", "OIDN_VERBOSE": "3", "UNRELATED_SECRET": "do-not-record"
        }), redirect_stdout(io.StringIO()):
            path = Path(directory) / "report.json"
            readiness.main(["--library-directory", directory, "--output", str(path)])
            report = json.loads(path.read_text())
            self.assertEqual(report["device_selection_environment"]["CUDA_VISIBLE_DEVICES"], "2")
            self.assertEqual(report["runtime_snapshot_sha256_expected"], readiness.RUNTIME_SNAPSHOT_SHA256)
            self.assertNotIn("do-not-record", path.read_text())


if __name__ == "__main__":
    unittest.main()
