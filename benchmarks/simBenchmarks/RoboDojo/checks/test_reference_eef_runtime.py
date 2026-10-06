"""CPU-only deployment guard tests; no simulator, network or shared-tree writes."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.RoboDojo.environment import reference_eef_runtime as runtime


class ReferenceDeploymentChecks(unittest.TestCase):
    def test_public_native_panel_pins_and_additional_asset_scope(self):
        p = runtime.pins()
        self.assertEqual(p["native_revision"], "ee67a1468510da7624a089164402359f2afc72c8")
        self.assertEqual(len(p["source_files"]), 169)
        self.assertEqual([r["layout_id"] for r in p["layouts"]], list(range(5)))
        self.assertEqual(p["native_horizon"], 1100)
        self.assertEqual(len(p["additional_asset_leaves"]), 19)
        self.assertEqual(p["asset_parent_sha256"], "bcee49283722d1b80c0d95a51a44267e0fb9bbc1d76dd52ea0d0e2416e0879dd")

    def test_relative_paths_reject_escape_and_links_are_not_files(self):
        for name in ("", ".", "../a", "/a", "a/../b", "a\\b", "a//b"):
            with self.subTest(name=name), self.assertRaises(Exception):
                runtime.safe_relative(name)
        self.assertEqual(str(runtime.safe_relative("Object/a/file.usd")), "Object/a/file.usd")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").write_bytes(b"original")
            (root / "link").symlink_to("data")
            with self.assertRaises(ValueError):
                runtime.inventory(root)

    def test_inventory_detects_changes_extras_and_removed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").write_bytes(b"A")
            rows = runtime.inventory(root)
            runtime.verify_rows(root, rows)
            (root / "b").write_bytes(b"B")
            with self.assertRaises(ValueError):
                runtime.verify_rows(root, rows)
            (root / "b").unlink()
            (root / "a").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                runtime.verify_rows(root, rows)
            (root / "a").unlink()
            with self.assertRaises(ValueError):
                runtime.verify_rows(root, rows)

    def test_manifest_requires_hash_and_fixed_qualifications(self):
        p = runtime.pins()
        document = {"schema": runtime.SCHEMA, "native_revision": p["native_revision"],
            "asset_parent_sha256": p["asset_parent_sha256"],
            "additional_asset_inventory_sha256": p["additional_asset_inventory_sha256"],
            "allowed_unresolved": list(runtime.KNOWN_UNRESOLVED), "versions": runtime.VERSIONS,
            "complete_assets": False}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text(json.dumps(document))
            self.assertEqual(runtime.load_runtime(path, runtime.sha(path)), document)
            with self.assertRaises(ValueError):
                runtime.load_runtime(path, "0" * 64)
            for key, value in (("complete_assets", True), ("native_revision", "wrong"),
                               ("allowed_unresolved", list(runtime.KNOWN_UNRESOLVED) + ["arbitrary_missing.png"]),
                               ("versions", {"isaacsim": "latest"})):
                path.write_text(json.dumps({**document, key: value}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    runtime.load_runtime(path, runtime.sha(path))

    def test_controller_dependency_is_explicit_and_missing_or_changed_version_fails(self):
        self.assertEqual(runtime.VERSIONS["scipy"], "1.15.3")
        p = runtime.pins()
        document = {"schema": runtime.SCHEMA, "native_revision": p["native_revision"],
            "asset_parent_sha256": p["asset_parent_sha256"],
            "additional_asset_inventory_sha256": p["additional_asset_inventory_sha256"],
            "allowed_unresolved": list(runtime.KNOWN_UNRESOLVED), "versions": runtime.VERSIONS,
            "complete_assets": False}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            for versions in ({key: value for key, value in runtime.VERSIONS.items() if key != "scipy"},
                             {**runtime.VERSIONS, "scipy": "1.15.2"}):
                path.write_text(json.dumps({**document, "versions": versions}))
                with self.subTest(versions=versions), self.assertRaises(ValueError):
                    runtime.load_runtime(path, runtime.sha(path))

    def test_layout_guard_keeps_all_candidates_but_selects_fixed_first5(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            layouts = source / "Assets/Eval_Layout/RoboDojo/arx_x5/0"
            layouts.mkdir(parents=True)
            for i in range(55):
                (layouts / f"classify_objects_{i}.json").write_text(json.dumps({"synthetic": i}))
            rows = [{"name": f"classify_objects_{i}.json",
                "bytes": (layouts / f"classify_objects_{i}.json").stat().st_size,
                "sha256": runtime.sha(layouts / f"classify_objects_{i}.json")} for i in range(55)]
            p = {"classify_layout_inventory_sha256": runtime.canonical_digest(rows),
                 "layouts": [{"layout_id": i, "sha256": rows[i]["sha256"]} for i in range(5)]}
            with patch.object(runtime, "pins", return_value=p):
                self.assertEqual(runtime.verify_layouts(source), rows)
                (layouts / "classify_objects_54.json").write_text("changed")
                with self.assertRaises(ValueError):
                    runtime.verify_layouts(source)

    def test_prepare_is_create_only_before_source_or_asset_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "occupied"
            destination.mkdir()
            with self.assertRaises(ValueError):
                runtime.prepare(native_repository=root / "absent", base_assets=root / "absent",
                    additional_assets=root / "absent", asset_parent_manifest=root / "absent",
                    runtime_root=destination, python=root / "absent", isaaclab_root=root / "absent",
                    curobo_root=root / "absent", recording_support=root / "absent", archive=root / "new.tar.gz")
            self.assertEqual(list(destination.iterdir()), [])

    def test_prepare_checks_explicit_counterpart_before_native_source_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base"
            base.mkdir()
            (base / "a").write_bytes(b"A")
            parent = {"files": runtime.inventory(base), "reference_root": "/historical/unavailable"}
            args = dict(native_repository=root / "source", base_assets=base,
                additional_assets=root / "additional", asset_parent_manifest=root / "parent.json",
                runtime_root=root / "new", python=root / "python", isaaclab_root=root / "isaac",
                curobo_root=root / "curobo", recording_support=root / "recording", archive=root / "new.tar.gz")
            with patch.object(runtime, "load_reference", return_value=parent), \
                 patch.object(runtime, "verify_reference_document", side_effect=ValueError("counterpart drift")) as verify, \
                 patch.object(runtime, "git") as git:
                with self.assertRaisesRegex(ValueError, "counterpart drift"):
                    runtime.prepare(**args, reference_assets=root / "relocated")
                verify.assert_called_once_with(parent, base, reference_assets=root / "relocated")
                git.assert_not_called()
                self.assertFalse(args["runtime_root"].exists())
            args["recording_support"].mkdir()
            expected = {**runtime.pins(), "additional_asset_leaves": [],
                "additional_asset_inventory_sha256": runtime.canonical_digest([])}
            with patch.object(runtime, "pins", return_value=expected), \
                 patch.object(runtime, "load_reference", return_value=parent), \
                 patch.object(runtime, "verify_reference_document") as verify, \
                 patch.object(runtime, "verify_dependencies", side_effect=ValueError("dependency gate")):
                with self.assertRaisesRegex(ValueError, "dependency gate"):
                    runtime.prepare(**args)
                verify.assert_not_called()
                self.assertFalse(args["runtime_root"].exists())

    def test_prepare_cli_passes_optional_reference_assets(self):
        required = ("native-repository", "base-assets", "additional-assets", "asset-parent-manifest",
            "runtime-root", "python", "isaaclab-root", "curobo-root", "recording-support", "archive")
        arguments = ["prepare"]
        for name in required:
            arguments.extend(("--" + name, "/deployment/" + name))
        for extra, expected in (([], None), (["--reference-assets", "/relocated/Assets"], Path("/relocated/Assets"))):
            with self.subTest(expected=expected), patch.object(runtime, "prepare", return_value={}) as prepare, \
                 patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(runtime.main(arguments + extra), 0)
                self.assertEqual(prepare.call_args.kwargs["reference_assets"], expected)


if __name__ == "__main__":
    unittest.main()
