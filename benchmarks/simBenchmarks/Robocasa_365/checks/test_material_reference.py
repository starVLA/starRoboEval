"""Fixture independence, without constructing any native simulator/context."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from benchmarks.simBenchmarks.Robocasa_365.environment.material_diagnose import CANDIDATE, REFERENCE, main


class MaterialReferenceChecks(unittest.TestCase):
    def test_independent_xmls_differ_only_in_declared_material_boundaries(self):
        candidate, reference = map(ElementTree.fromstring, (CANDIDATE, REFERENCE))
        candidate_materials, reference_materials = candidate.findall("asset/material"), reference.findall("asset/material")
        self.assertEqual([float(m.attrib["shininess"]) for m in candidate_materials], [-1., .5, 2.])
        self.assertEqual([float(m.attrib["shininess"]) for m in reference_materials], [0., .5, 1.])
        for material in candidate_materials + reference_materials:
            del material.attrib["shininess"]
        self.assertEqual(ElementTree.tostring(candidate), ElementTree.tostring(reference))
        self.assertEqual([c.attrib["name"] for c in candidate.findall("worldbody/camera")], ["front", "side", "top"])
        self.assertFalse(candidate.findall("worldbody/body"))
        self.assertFalse(candidate.findall("actuator"))

    def test_relative_output_preflight_failure_is_preserved_without_native_import(self):
        caller_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                with patch("benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter.verify_sources",
                           side_effect=RuntimeError("injected read-only preflight failure")), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--gpu", "0", "--condition", "candidate", "--output", "new-result"]), 1)
                self.assertEqual(Path.cwd(), Path(temporary).resolve())
                report = json.loads(Path("new-result/report.json").read_text())
                self.assertEqual(report["status"], "failed")
                self.assertIn("preflight failure", report["errors"][0]["message"])
                self.assertEqual(report["frames"], [])
                self.assertNotIn("guard_final", report)
                self.assertEqual(Path("new-result/scene.xml").read_text(), CANDIDATE)
            finally:
                os.chdir(caller_directory)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            sentinel = Path(temporary) / "sentinel"
            sentinel.write_text("preserve")
            with self.assertRaises(FileExistsError):
                main(["--gpu", "0", "--condition", "legal-reference", "--output", temporary])
            self.assertEqual(sentinel.read_text(), "preserve")

    def test_negative_gpu_fails_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main(["--gpu", "-1", "--condition", "legal-reference", "--output", str(output)])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
