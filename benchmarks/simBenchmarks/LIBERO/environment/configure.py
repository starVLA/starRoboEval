"""Create an isolated LIBERO config without an interactive import or home edits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.upstream.resolve() / "libero" / "libero"
    for suffix in ("assets", "bddl_files", "init_files"):
        if not (root / suffix).is_dir():
            parser.error(f"missing pinned upstream directory: {root / suffix}")
    directory = args.config_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    datasets = directory / "unused-datasets"
    datasets.mkdir(exist_ok=True)
    payload = {
        "benchmark_root": str(root), "bddl_files": str(root / "bddl_files"),
        "init_states": str(root / "init_files"), "assets": str(root / "assets"),
        "datasets": str(datasets),
    }
    destination = directory / "config.yaml"
    # JSON is a YAML subset accepted by the upstream YAML loader.
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if destination.exists():
        if destination.read_text() != encoded:
            parser.error(f"refusing to overwrite a different LIBERO config: {destination}")
    else:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(f"Set LIBERO_CONFIG_PATH={directory}")


if __name__ == "__main__":
    main()
