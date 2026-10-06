"""Small synthetic archives and import trees; no downloaded/native assets needed."""
from contextlib import ExitStack
import hashlib
import importlib
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from benchkit.errors import CompatibilityError

adapter = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.bench_server.adapter")
assets = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.environment.extract_assets")


def entry(name, payload=b"ok", mode=stat.S_IFREG | 0o644):
    item = zipfile.ZipInfo(str(assets.ARCHIVE_PREFIX) + "/" + name)
    item.create_system = 3
    item.external_attr = mode << 16
    item.file_size = len(payload)
    return item


class ImportInventoryChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.package = self.root / "libero/libero"
        (self.package / "envs").mkdir(parents=True)
        for path in (self.package / "__init__.py", self.package / "envs/__init__.py"):
            path.write_text("# fixture\n")
        self.rows = [{"path": path.relative_to(self.root).as_posix()}
                     for path in self.package.rglob("*.py")]

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_code_inventory_excludes_declared_data_scopes(self):
        for scope in ("assets", "bddl_files", "init_files"):
            directory = self.package / scope
            directory.mkdir()
            (directory / "not_imported.py").write_text("# released data helper\n")
        adapter.verify_native_import_inventory(self.root, self.rows)

    def test_untracked_python_extension_and_bytecode_shadowing_rejected(self):
        for relative in ("override.py", "envs/native.cpython-310-x86_64-linux-gnu.so",
                         "envs/__pycache__/__init__.cpython-310.pyc", "envs/native.pyd"):
            with self.subTest(relative=relative):
                path = self.package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unexpected")
                with self.assertRaises(CompatibilityError):
                    adapter.verify_native_import_inventory(self.root, self.rows)
                path.unlink()

    def test_outer_namespace_source_and_extension_rejected(self):
        for name in ("__init__.py", "libero.so", "__init__.pyc"):
            path = self.root / "libero" / name
            path.write_bytes(b"unexpected")
            with self.assertRaises(CompatibilityError):
                adapter.verify_native_import_inventory(self.root, self.rows)
            path.unlink()

    def test_missing_source_and_code_symlink_rejected(self):
        (self.package / "envs/__init__.py").unlink()
        with self.assertRaises(CompatibilityError):
            adapter.verify_native_import_inventory(self.root, self.rows)
        (self.package / "envs/__init__.py").symlink_to(self.package / "__init__.py")
        with self.assertRaises(CompatibilityError):
            adapter.verify_native_import_inventory(self.root, self.rows)
        (self.package / "envs/__init__.py").unlink()
        (self.package / "envs/__init__.py").write_text("# fixture\n")
        (self.package / "extra").symlink_to(self.package / "envs", target_is_directory=True)
        with self.assertRaises(CompatibilityError):
            adapter.verify_native_import_inventory(self.root, self.rows)


class ArchiveInspectionChecks(unittest.TestCase):
    def test_strips_only_exact_native_prefix_and_keeps_paths(self):
        root = zipfile.ZipInfo(str(assets.ARCHIVE_PREFIX) + "/")
        result = assets.inspect_entries([root, entry("scenes/table.xml")])
        self.assertEqual([relative for _, relative in result], [Path("."), Path("scenes/table.xml")])

    def test_path_traversal_absolute_wrong_prefix_empty_segments_rejected(self):
        for name in ("../escape", "/absolute", "inspire/../escape", "C:/escape",
                     str(assets.ARCHIVE_PREFIX) + "/../escape", str(assets.ARCHIVE_PREFIX) + "//double",
                     str(assets.ARCHIVE_PREFIX) + "/back\\slash"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                assets.inspect_entries([zipfile.ZipInfo(name)])

    def test_symlink_device_duplicate_and_file_parent_rejected(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFCHR | 0o644):
            with self.assertRaises(ValueError):
                assets.inspect_entries([entry("object", mode=mode)])
        for entries in ([entry("same"), entry("same")], [entry("parent"), entry("parent/child")]):
            with self.assertRaises(ValueError):
                assets.inspect_entries(entries)

    def test_expansion_entry_file_and_encryption_bounds(self):
        normal = entry("ok")
        for name, bound in (("MAX_ENTRIES", 0), ("MAX_TOTAL_BYTES", 1), ("MAX_FILE_BYTES", 1)):
            with patch.object(assets, name, bound), self.assertRaises(ValueError):
                assets.inspect_entries([normal])
        normal.flag_bits |= 1
        with self.assertRaises(ValueError):
            assets.inspect_entries([normal])

    def test_verified_new_target_extraction_and_receipt_no_native_import(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory).resolve()
            archive, output, receipt = root / "assets.zip", root / "assets", root / "receipt.json"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr(entry("scenes/table.xml"), b"table-data")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            stack.enter_context(patch.object(assets, "ARCHIVE_SIZE", archive.stat().st_size))
            stack.enter_context(patch.object(assets, "ARCHIVE_SHA256", digest))
            report = assets.extract(archive, output, receipt)
            self.assertEqual((output / "scenes/table.xml").read_bytes(), b"table-data")
            self.assertEqual(report["archive_sha256"], digest)
            self.assertEqual(report["regular_files"], 1)
            self.assertEqual(report["native_resets"], 0)
            self.assertTrue(receipt.is_file())
            with self.assertRaises(ValueError):
                assets.extract(archive, output, root / "different-receipt.json")

    def test_bad_release_digest_and_existing_or_symlink_target_never_written(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory).resolve()
            archive = root / "assets.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr(entry("scenes/table.xml"), b"table")
            output, receipt = root / "assets", root / "receipt.json"
            stack.enter_context(patch.object(assets, "ARCHIVE_SIZE", archive.stat().st_size))
            with self.assertRaises(ValueError):
                assets.extract(archive, output, receipt)
            self.assertFalse(output.exists())
            self.assertFalse(receipt.exists())
            (root / "existing").mkdir()
            output.symlink_to(root / "existing", target_is_directory=True)
            with self.assertRaises(ValueError):
                assets.extract(archive, output, receipt)
            self.assertEqual(list((root / "existing").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
