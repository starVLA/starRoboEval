"""Inventory existing object assets; compare every relative path, size and SHA256."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def inventory(root: Path) -> dict:
    files = {}
    for registry in ("objaverse", "sketchfab", "lightwheel"):
        base = root / registry
        if not base.is_dir():
            raise RuntimeError(f"missing registry: {base}")
        for directory, subdirectories, names in os.walk(base, followlinks=False):
            subdirectories.sort()
            for name in sorted(names + [name for name in subdirectories if (Path(directory) / name).is_symlink()]):
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    target = os.readlink(path)
                    data = target.encode()
                    files[relative] = {"kind": "symlink", "target": target, "size": len(data),
                                       "sha256": hashlib.sha256(data).hexdigest()}
                else:
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        while chunk := stream.read(4 * 1024 * 1024):
                            digest.update(chunk)
                    files[relative] = {"kind": "file", "size": path.stat().st_size, "sha256": digest.hexdigest()}
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"root": str(root.resolve()), "file_count": len(files),
            "total_regular_bytes": sum(value["size"] for value in files.values() if value["kind"] == "file"),
            "inventory_sha256": hashlib.sha256(canonical).hexdigest(), "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inventory(args.root)
    if args.reference:
        expected = json.loads(args.reference.read_text())
        keys = set(result["files"]) | set(expected["files"])
        differences = sorted(key for key in keys if result["files"].get(key) != expected["files"].get(key))
        result["comparison"] = {"reference": str(args.reference.resolve()), "matches": not differences,
                                "difference_count": len(differences), "first_differences": differences[:50]}
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output:
        args.output.write_text(encoded)
        print(json.dumps({key: value for key, value in result.items() if key != "files"}, indent=2))
    else:
        print(encoded, end="")
    if result.get("comparison", {}).get("matches") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
