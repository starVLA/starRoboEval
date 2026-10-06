"""CPU-only checks for the asset inventory used by runtime preparation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.simBenchmarks.RoboDojo.environment import asset_reference as assets


class AssetReferenceTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name).resolve()
        self.reference, self.runtime = self.root / "reference", self.root / "runtime"
        names = ["Robots/x5/X5A.urdf", "Robots/x5/curobo.yml",
                 "Eval_Layout/RoboDojo/arx_x5/0/stack_bowls_0.json",
                 "Eval_Layout/RoboDojo/arx_x5/0/push_T_0.json"]
        self.rows = []
        for name in sorted(names):
            payload = name.encode()
            for root in (self.reference, self.runtime):
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(payload)
            self.rows.append({"path": name, "bytes": len(payload),
                              "sha256": hashlib.sha256(payload).hexdigest()})
        self.document = {"schema_version": assets.SCHEMA, "reference_root": str(self.reference),
            "ready_for_user_reference_track": True, "files": self.rows,
            "reference_files": deepcopy(self.rows), "reference_absent": [],
            "crlf_equivalent_paths": [], "allowed_unresolved": list(assets.KNOWN_UNRESOLVED)}
        self.path = self.root / "reference.json"
        self.write(self.document)

    def write(self, document):
        self.path.write_text(json.dumps(document))
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_exact_reference_inventory(self):
        self.assertEqual(assets.verify_reference(self.path, self.digest, self.runtime), self.document)
        with self.assertRaises(ValueError):
            assets.accept_unresolved(assets.KNOWN_UNRESOLVED, None)

    def test_only_known_inherited_unresolved_permitted(self):
        assets.accept_unresolved(assets.KNOWN_UNRESOLVED, self.document)
        with self.assertRaises(ValueError):
            assets.accept_unresolved(["other.usd"], self.document)

    def test_relocated_reference_keeps_manifest_bytes_and_detects_drift(self):
        original_manifest = self.path.read_bytes()
        relocated = self.root / "relocated-assets"
        self.reference.rename(relocated)
        self.assertEqual(assets.verify_reference(self.path, self.digest, self.runtime,
            reference_assets=relocated), self.document)
        self.assertEqual(self.path.read_bytes(), original_manifest)
        with self.assertRaises(ValueError):
            assets.verify_reference(self.path, self.digest, self.runtime)
        file = relocated / self.rows[0]["path"]
        file.write_bytes(b"x" * file.stat().st_size)
        with self.assertRaises(ValueError):
            assets.verify_reference(self.path, self.digest, self.runtime, reference_assets=relocated)

    def test_reference_override_rejects_missing_directory_and_symlink(self):
        link = self.root / "linked-reference"
        link.symlink_to(self.reference, target_is_directory=True)
        for reference in (self.root / "absent", link):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                assets.verify_reference(self.path, self.digest, self.runtime, reference_assets=reference)

    def test_reference_provenance_is_absolute_but_need_not_exist(self):
        document = deepcopy(self.document)
        document["reference_root"] = "/archived/original/Assets"
        self.write(document)
        self.assertEqual(assets.load_reference(self.path, self.digest), document)
        assets.verify_reference(self.path, self.digest, self.runtime, reference_assets=self.reference)
        for root in (None, 1, "", "relative/assets", "/assets/../other", "/assets//other", "/bad\x00"):
            document["reference_root"] = root
            self.write(document)
            with self.subTest(root=root), self.assertRaises(ValueError):
                assets.load_reference(self.path, self.digest)

    def test_digest_schema_and_paths_fail_closed(self):
        with self.assertRaises(ValueError):
            assets.load_reference(self.path, "0" * 64)
        for transform in (
                lambda value: value.update(ready_for_user_reference_track=False),
                lambda value: value.update(allowed_unresolved=[*assets.KNOWN_UNRESOLVED, "other"]),
                lambda value: value["files"][0].update(path="../escape"),
                lambda value: value.update(files=value["files"][:-1])):
            document = deepcopy(self.document)
            transform(document)
            self.write(document)
            with self.subTest(transform=transform), self.assertRaises(ValueError):
                assets.load_reference(self.path, self.digest)

    def test_reference_runtime_drift_and_symlink_fail(self):
        file = self.runtime / self.rows[0]["path"]
        original = file.read_bytes()
        file.write_bytes(b"x" * len(original))
        with self.assertRaises(ValueError):
            assets.verify_reference(self.path, self.digest, self.runtime)
        file.write_bytes(original)
        extra = self.runtime / "extra"
        extra.symlink_to(file)
        with self.assertRaises(ValueError):
            assets.verify_reference(self.path, self.digest, self.runtime)

    def test_only_declared_urdf_crlf_equivalence(self):
        name = "Robots/x5/X5A.urdf"
        for root, payload, rows in ((self.runtime, b"<robot>\r\n</robot>", self.document["files"]),
                (self.reference, b"<robot>\n</robot>", self.document["reference_files"])):
            (root / name).write_bytes(payload)
            row = next(row for row in rows if row["path"] == name)
            row.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        self.document["crlf_equivalent_paths"] = [name]
        self.write(self.document)
        assets.verify_reference(self.path, self.digest, self.runtime)


if __name__ == "__main__":
    unittest.main()
