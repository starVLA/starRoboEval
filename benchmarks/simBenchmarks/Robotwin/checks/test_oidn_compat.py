"""Content/loader/lifecycle tests only; no GPU, native library or simulator."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchkit.errors import CompatibilityError
from benchmarks.simBenchmarks.Robotwin.bench_server import adapter
from benchmarks.simBenchmarks.Robotwin.environment import oidn_compat as compat, renderer_readiness, runtime


class OIDNCompatibilityChecks(unittest.TestCase):
    def test_base_pin_and_default_track_stay_original(self):
        self.assertEqual(hashlib.sha256(runtime.RUNTIME_SNAPSHOT.read_bytes()).hexdigest(),
                         "b1b7ecba4723d9fecdcdf79e0323817ccd05cc58cb12cd7af56ad2e4fefd4d28")
        self.assertEqual(compat.snapshot()["base_runtime_snapshot_sha256"], runtime.RUNTIME_SNAPSHOT_SHA256)
        args = {"source_root": "/unused/native", "deployment_manifest_sha256": "0" * 64}
        old = adapter.make_robotwin(args)
        new = adapter.make_robotwin({**args, "renderer_runtime": compat.TRACK})
        self.assertEqual(old.renderer_runtime, runtime.BUNDLED_RENDERER)
        self.assertEqual(old.descriptor.protocol_version, adapter.PROTOCOL)
        self.assertEqual(new.descriptor.protocol_version, adapter.COMPAT_PROTOCOL)
        self.assertNotEqual(old.descriptor.protocol_version, new.descriptor.protocol_version)
        self.assertEqual(old.action_spec, new.action_spec)
        self.assertEqual(old.observation_spec, new.observation_spec)
        self.assertEqual(old.episodes(7), new.episodes(7))

    def test_only_oidn_loader_and_library_directory_change(self):
        original = compat._base_rows()
        kept = {row["path"]: row for row in original if row["path"] != "sapien/_oidn_tricks.py"
                and not row["path"].startswith("sapien/oidn_library/")}
        rows = {row["path"]: row for row in compat.package_rows(original)}
        self.assertTrue(kept)
        self.assertEqual({key: rows[key] for key in kept}, kept)
        self.assertEqual(set(rows) - set(kept), {"sapien/_oidn_tricks.py"} |
                         {row["path"] for row in compat.snapshot()["release_files"]})
        self.assertEqual(sum(row["path"].endswith(".so.2.3.3") for row in rows.values()), 3)
        self.assertNotIn("sapien/oidn_library/libOpenImageDenoise_device_cpu.so.2.3.3", rows)
        libraries = compat.snapshot()["unchanged_sapien_distribution_files"]
        self.assertEqual(sum(row["path"].startswith("sapien.libs/") for row in libraries), 3)

    def test_unreviewed_renderer_selection_rejected_lazily(self):
        for value in (None, True, [], "latest", "cpu", "none"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                adapter.make_robotwin({"source_root": "/unused/native", "deployment_manifest_sha256": "0" * 64,
                                       "renderer_runtime": value})

    def test_new_track_factory_does_not_import_native_packages(self):
        script = """
import sys
from benchmarks.simBenchmarks.Robotwin.bench_server.adapter import make_robotwin
b = make_robotwin({'source_root':'/unused/native','deployment_manifest_sha256':'0'*64,
                  'renderer_runtime':'oidn_2_3_3_cuda_v1'})
assert len(b.episodes(7)) == 1
for name in ('numpy','torch','sapien','mplib','curobo','envs','AgentPolicies'):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name
"""
        result = subprocess.run([sys.executable, "-B", "-S", "-c", script],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preimported_sapien_or_oidn_fails_before_constructor(self):
        with patch.dict(sys.modules, {"sapien": SimpleNamespace()}), self.assertRaisesRegex(CompatibilityError, "already imported"):
            compat.reject_preloaded_runtime()
        with patch.object(compat, "_loaded_native_paths", return_value={"/old/libOpenImageDenoise.so.2.0.1"}), \
                self.assertRaisesRegex(CompatibilityError, "already loaded"):
            compat.reject_preloaded_runtime()

    def test_loaded_native_paths_require_same_overlay_and_cuda_plugin(self):
        root = Path("/owned/overlay")
        prefix = root / "sapien/oidn_library"
        paths = {str(prefix / name) for name in renderer_readiness.library_names(compat.TRACK)}
        paths.update(str(root / row["path"]) for row in compat.snapshot()["unchanged_sapien_distribution_files"]
                     if row["path"].startswith("sapien.libs/"))
        with patch.dict(sys.modules, {"sapien": SimpleNamespace(__file__=str(root / "sapien/__init__.py"))}), \
                patch.object(compat, "_loaded_native_paths", return_value=paths):
            self.assertTrue(compat.verify_loaded(root, require_cuda_plugin=True)["cuda_plugin_loaded"])
            paths.remove(str(prefix / "libOpenImageDenoise_device_cuda.so.2.3.3"))
            self.assertFalse(compat.verify_loaded(root, require_cuda_plugin=False)["cuda_plugin_loaded"])
            with self.assertRaises(CompatibilityError):
                compat.verify_loaded(root, require_cuda_plugin=True)
            paths.add("/foreign/libOpenImageDenoise.so.2.3.3")
            with self.assertRaises(CompatibilityError):
                compat.verify_loaded(root, require_cuda_plugin=False)

    def test_readiness_default_and_compat_library_names_never_mix(self):
        self.assertEqual(renderer_readiness.library_names(runtime.BUNDLED_RENDERER), renderer_readiness.LIBRARIES)
        self.assertTrue(all(name.endswith("2.3.3") for name in renderer_readiness.library_names(compat.TRACK)))
        with self.assertRaises(ValueError):
            renderer_readiness.library_names("arbitrary")

    def test_wrong_release_or_existing_output_never_loads_or_modifies_native(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(runtime, "verify_runtime") as verify:
            root = Path(temporary).resolve()
            archive = root / "not-a-release.tar.gz"
            archive.write_bytes(b"invalid")
            for output in (root, root / "new-overlay"):
                with self.subTest(output=output), self.assertRaises((ValueError, CompatibilityError)):
                    compat.prepare(archive, output)
            verify.assert_not_called()
            self.assertFalse((root / "new-overlay").exists())

    def test_snapshot_changes_fail_closed(self):
        with patch.object(compat, "SNAPSHOT_SHA256", "0" * 64), self.assertRaises(CompatibilityError):
            compat.snapshot()

    def test_new_runtime_provenance_survives_native_import_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "native"
            source.mkdir()
            benchmark = adapter.make_robotwin({"source_root": str(source), "deployment_manifest_sha256": "0" * 64,
                                               "renderer_runtime": compat.TRACK})
            session = benchmark.open_episode(benchmark.episodes(7)[0])
            session.bind_artifact_dir(root / "artifacts")
            identity = {"runtime": {"renderer_compatibility": {"renderer_runtime": compat.TRACK,
                "compatibility_snapshot_sha256": compat.SNAPSHOT_SHA256}}}
            with patch.object(runtime, "readiness", return_value=identity), \
                    patch.object(runtime, "create_native", side_effect=RuntimeError("native import error")), \
                    self.assertRaisesRegex(RuntimeError, "native import error"):
                session.reset()
            receipt = json.loads((root / "artifacts/native_provenance.json").read_text())
            self.assertEqual(receipt["protocol_version"], adapter.COMPAT_PROTOCOL)
            self.assertEqual(receipt["runtime"]["renderer_compatibility"]["renderer_runtime"], compat.TRACK)
            self.assertFalse(session.native_reset_returned)
            self.assertTrue(session.closed)

    def _overlay(self, root):
        contents = {"sapien/__init__.py": b"# fake package\n", "sapien-3.0.0b1.dist-info/METADATA": b"Name: sapien\nVersion: 3.0.0b1\n"}
        rows = []
        for name, data in contents.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            rows.append({"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        (root / compat.RECORD).write_bytes(compat.record_bytes(rows))
        (root / compat.RECEIPT).write_text(json.dumps({"renderer_runtime": compat.TRACK,
            "compatibility_snapshot_sha256": compat.SNAPSHOT_SHA256,
            "release_sha256": compat.snapshot()["release_sha256"]}))
        distribution = importlib.metadata.PathDistribution(root / "sapien-3.0.0b1.dist-info")
        return rows, distribution

    def test_overlay_record_content_extra_files_and_import_shadow_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            rows, distribution = self._overlay(root)
            with patch.object(compat, "all_rows", return_value=rows), \
                    patch.object(compat.importlib.util, "find_spec", return_value=SimpleNamespace(origin=str(root / "sapien/__init__.py"))) as spec, \
                    patch.object(compat, "reject_preloaded_runtime"):
                self.assertEqual(compat.verify_overlay(distribution, []) ["selected_distribution_files"], 2)
                original_record = (root / compat.RECORD).read_bytes()
                (root / compat.RECORD).write_bytes(original_record.replace(b"sha256=", b"md5="))
                with self.assertRaisesRegex(CompatibilityError, "RECORD content"):
                    compat.verify_overlay(distribution, [])
                (root / compat.RECORD).write_bytes(original_record)
                spec.return_value.origin = "/foreign/sapien/__init__.py"
                with self.assertRaisesRegex(CompatibilityError, "import would not"):
                    compat.verify_overlay(distribution, [])
                (root / "extra.py").write_text("# unrecorded")
                with self.assertRaisesRegex(CompatibilityError, "file set"):
                    compat.verify_overlay(distribution, [])

    def test_overlay_symlinks_are_rejected_even_if_content_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            rows, distribution = self._overlay(root)
            (root / "alias.py").symlink_to(root / "sapien/__init__.py")
            with patch.object(compat, "all_rows", return_value=rows), self.assertRaisesRegex(CompatibilityError, "symlinks"):
                compat.verify_overlay(distribution, [])


if __name__ == "__main__":
    unittest.main()
