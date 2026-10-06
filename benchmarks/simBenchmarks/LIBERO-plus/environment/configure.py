"""Create a dedicated LIBERO-Plus path config; never modify a user's home config."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def configure(upstream: Path, config_dir: Path) -> Path:
    root = upstream.resolve() / "libero/libero"
    for suffix in ("assets", "bddl_files", "init_files"):
        if not (root / suffix).is_dir():
            raise ValueError(f"missing native directory: {root / suffix}")
    directory = config_dir.resolve()
    if directory.is_relative_to(upstream.resolve()):
        raise ValueError("keep runtime config outside the pinned native checkout")
    directory.mkdir(parents=True, exist_ok=True)
    datasets = directory / "unused-datasets"
    datasets.mkdir(exist_ok=True)
    payload = {"benchmark_root": str(root), "bddl_files": str(root / "bddl_files"),
               "init_states": str(root / "init_files"), "assets": str(root / "assets"),
               "datasets": str(datasets)}
    # JSON is a YAML subset understood by the native yaml loader.
    encoded = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    destination = directory / "config.yaml"
    if destination.exists():
        if destination.read_text() != encoded:
            raise ValueError("refusing to overwrite a different LIBERO config")
    else:
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        path = configure(args.upstream, args.config_dir)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Set LIBERO_CONFIG_PATH={path}")


if __name__ == "__main__":
    main()
