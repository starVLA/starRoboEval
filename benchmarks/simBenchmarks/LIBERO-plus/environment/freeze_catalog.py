"""Read the pinned native source/assets and print a deterministic catalog.

No simulator, torch pickle, model, reset or action is imported/executed.
Generated catalog data is reviewed and checked into this benchmark directory.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import importlib
import json
from pathlib import Path
import re
import subprocess

catalog = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.bench_server.protocol.catalog")


def generate(root: Path, suite: str) -> dict:
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    if revision != catalog.REVISION:
        raise ValueError("upstream revision differs")
    native = root / "libero/libero"
    source = native / "benchmark/libero_suite_task_map.py"
    nodes = ast.parse(source.read_text()).body
    assignments = [node for node in nodes if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "libero_task_map" for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError("ambiguous native task map")
    names = ast.literal_eval(assignments[0].value)[suite]
    classified = json.loads((native / "benchmark/task_classification.json").read_text())[suite]
    if len(names) != catalog.COUNTS[suite] or len(classified) != len(names):
        raise ValueError("native count differs")
    cache = {}

    def sha(path):
        if str(path) not in cache:
            cache[str(path)] = catalog.file_sha256(path)
        return cache[str(path)]

    rows = []
    for index, (name, classification) in enumerate(zip(names, classified)):
        if classification["name"] != name or classification["id"] != index + 1:
            raise ValueError("native classification identity/order differs")
        files = catalog.native_files(suite, name)
        bddl = native / "bddl_files" / files["bddl"]
        source_text = re.sub(r";.*$", "", bddl.read_text(), flags=re.MULTILINE).lower()
        matches = re.findall(r"\(:language\s+([^()]*)\)", source_text)
        if len(matches) != 1:
            raise ValueError("BDDL language must have one flat native token group")
        instruction = " ".join(matches[0].split())
        if "_language_" in name:
            native_instruction = instruction
        else:
            # Exact grab_language_from_filename behavior, including suffixes.
            full = name + ".bddl"
            if full[0].isupper():
                start = full.find("SCENE") + (8 if "SCENE10" in full else 7)
                native_instruction = " ".join(full[start:].split("_"))
            else:
                native_instruction = " ".join(full.split("_"))
            native_instruction = native_instruction[:native_instruction.find(".bddl")]
        rows.append([index, name, instruction, native_instruction, classification["category"], classification["difficulty_level"],
                     sha(bddl), files["initial_file"], sha(native / "init_files" / files["initial_file"])])
    return {"schema_version": "starvla-rsi.libero-plus-catalog/v1", "upstream_revision": revision,
            "suite": suite, "task_count": len(rows), "task_order_index": 0,
            "category_counts": dict(sorted(Counter(row[4] for row in rows).items())),
            "columns": list(catalog.COLUMNS), "tasks": rows}


def source_manifest(root: Path) -> dict:
    names = subprocess.run(["git", "-C", str(root), "ls-files", "libero/libero/*.py",
                            "libero/libero/benchmark/task_classification.json"],
                           capture_output=True, text=True, check=True, timeout=20).stdout.splitlines()
    rows = []
    for name in names:
        path = root / name
        expected = subprocess.run(["git", "-C", str(root), "show", f"{catalog.REVISION}:{name}"],
                                  capture_output=True, check=True, timeout=20).stdout
        actual = path.read_bytes()
        if actual != expected:
            raise ValueError(f"native tracked source differs from pinned revision: {name}")
        rows.append({"path": name, "size_bytes": len(actual), "sha256": catalog.file_sha256(path)})
    return {"schema_version": "starvla-rsi.libero-plus-native-source/v1", "upstream_revision": catalog.REVISION,
            "scope": "tracked Python under libero/libero and native task classification; not all assets",
            "files": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--suite", choices=tuple(catalog.COUNTS))
    parser.add_argument("--source-manifest", action="store_true")
    args = parser.parse_args()
    if args.source_manifest == (args.suite is not None):
        parser.error("select exactly one of --suite or --source-manifest")
    payload = source_manifest(args.upstream.resolve()) if args.source_manifest else generate(args.upstream.resolve(), args.suite)
    # One compact row per line keeps each suite below the harness's 2 MiB cap.
    if "tasks" in payload:
        rows = payload.pop("tasks")
        prefix = json.dumps(payload, sort_keys=True, indent=2)[:-2]
        print(prefix + ',\n  "tasks": [\n' + ',\n'.join('    ' + json.dumps(row, separators=(",", ":"), ensure_ascii=False)
                                                        for row in rows) + '\n  ]\n}')
    else:
        print(json.dumps(payload, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
