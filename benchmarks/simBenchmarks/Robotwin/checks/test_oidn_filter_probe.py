"""Public setup-tool failure paths; these tests do not load native libraries."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.Robotwin.environment import oidn_filter_probe as probe


class OIDNFilterProbeChecks(unittest.TestCase):
    def test_invalid_pinned_libraries_fail_before_cuda_work(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(probe, "run") as run, \
                patch.object(probe.oidn_compat, "reject_preloaded_runtime"), redirect_stdout(io.StringIO()):
            root = Path(temporary)
            report = root / "report.json"
            self.assertEqual(probe.main(["--library-directory", temporary, "--output", str(report)]), 1)
            saved = json.loads(report.read_text())
            self.assertFalse(saved["passed"])
            self.assertEqual(saved["native_scenes"], 0)
            self.assertEqual(saved["model_calls"], 0)
            run.assert_not_called()

    def test_existing_output_is_not_replaced_or_reexecuted(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(probe, "run") as run:
            report = Path(temporary) / "report.json"
            report.write_text("original")
            with self.assertRaises(FileExistsError):
                probe.main(["--library-directory", temporary, "--output", str(report)])
            self.assertEqual(report.read_text(), "original")
            run.assert_not_called()

    def test_filter_or_cleanup_error_cannot_retain_pass_true(self):
        def fail_after_filter(directory, report):
            report["passed"] = True
            raise RuntimeError("synthetic cleanup failure")

        with tempfile.TemporaryDirectory() as temporary, patch.object(probe, "run", side_effect=fail_after_filter), \
                patch.object(probe, "verify_libraries", return_value={}), \
                patch.object(probe.oidn_compat, "reject_preloaded_runtime"), redirect_stdout(io.StringIO()):
            report = Path(temporary) / "report.json"
            self.assertEqual(probe.main(["--library-directory", temporary, "--output", str(report)]), 1)
            saved = json.loads(report.read_text())
            self.assertFalse(saved["passed"])
            self.assertEqual(saved["error"]["message"], "synthetic cleanup failure")

    def test_wrong_loaded_library_paths_fail_closed(self):
        def foreign_library(directory, report):
            report.update(passed=True, loaded_oidn_maps=["/foreign/libOpenImageDenoise.so.2.3.3"])

        with tempfile.TemporaryDirectory() as temporary, patch.object(probe, "run", side_effect=foreign_library), \
                patch.object(probe, "verify_libraries", return_value={}), \
                patch.object(probe.oidn_compat, "reject_preloaded_runtime"), redirect_stdout(io.StringIO()):
            report = Path(temporary) / "report.json"
            self.assertEqual(probe.main(["--library-directory", temporary, "--output", str(report)]), 1)
            saved = json.loads(report.read_text())
            self.assertFalse(saved["passed"])
            self.assertIn("mapped OIDN", saved["error"]["message"])


if __name__ == "__main__":
    unittest.main()
