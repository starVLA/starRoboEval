"""Read-only pinned source/reset/BDDL checks, with optional import preflight.

No native environment is constructed and no pickle, reset, step or model is
executed. Complete asset rendering still requires a separate native diagnostic.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

adapter = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.bench_server.adapter")
catalog = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.bench_server.protocol.catalog")


def verify_inputs(upstream: Path, suites=None) -> dict:
    root = upstream.resolve()
    source = adapter.verify_native_source(root)
    suites = tuple(catalog.COUNTS) if suites is None else tuple(suites)
    if not suites or len(set(suites)) != len(suites) or any(name not in catalog.COUNTS for name in suites):
        raise ValueError("suites must be a nonempty unique subset of the four frozen suites")
    cache = {}
    count = 0
    for suite in suites:
        for row in catalog.task_catalog(suite)["tasks"]:
            names = catalog.native_files(suite, row["native_name"])
            for prefix, name, expected in (("bddl_files", names["bddl"], row["bddl_sha256"]),
                                            ("init_files", names["initial_file"], row["initial_file_sha256"])):
                path = (root / "libero/libero" / prefix / name).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("native catalog input resolves outside the source checkout")
                if path not in cache:
                    cache[path] = catalog.file_sha256(path)
                if cache[path] != expected:
                    raise ValueError(f"native {prefix} differs from frozen catalog: {name}")
            count += 1
    assets = root / "libero/libero/assets"
    required = ("articulated_objects", "new_objects", "scenes", "stable_hope_objects",
                "stable_scanned_objects", "textures", "turbosquid_objects")
    missing = [name for name in required if not (assets / name).is_dir()]
    if missing:
        raise ValueError(f"native asset folders are missing: {missing}")
    return {"schema_version": "starvla-rsi.libero_plus.readiness/v1", "upstream_revision": catalog.REVISION,
            "native_source_files": len(source["files"]), "source_manifest_sha256": source["manifest_sha256"],
            "catalog_variants_checked": count, "unique_bddl_reset_files_checked": len(cache),
            "suites": list(suites), "asset_folder_check": "present; not complete archive/content validation",
            "native_environments_constructed": 0, "native_resets": 0, "native_controls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--suite", choices=tuple(catalog.COUNTS), action="append")
    parser.add_argument("--check-imports", action="store_true",
                        help="also import native dependencies with configured EGL; never construct an environment")
    args = parser.parse_args()
    result = verify_inputs(args.upstream, args.suite)
    if args.check_imports:
        adapter.prepare_native_import(args.upstream.resolve())
        importlib.import_module("libero.libero.envs")
        importlib.import_module("OpenGL.EGL")
        result["image_magick"] = adapter.image_magick_receipt()
        result["native_imports"] = "passed; not render/reset validation"
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
