"""Create an isolated native utility config, without importing or running a SIM."""
import argparse
import json
from pathlib import Path


def create_config(native_root: Path, config_directory: Path) -> Path:
    root = native_root.resolve(strict=True) / "vla_arena/vla_arena"
    if not all((root / name).is_dir() for name in ("assets", "bddl_files", "init_files")):
        raise ValueError("native root lacks the pinned resource directory layout")
    if config_directory.exists() or config_directory.is_symlink():
        raise ValueError("choose a new private native config directory; existing paths are never overwritten")
    config_directory.mkdir(mode=0o700, parents=False)
    path = config_directory / "config.yaml"
    # JSON is valid YAML and needs no YAML dependency for this setup command.
    with path.open("x", encoding="utf-8") as stream:
        json.dump({"benchmark_root": str(root), "bddl_files": str(root / "bddl_files"),
                   "init_states": str(root / "init_files"), "datasets": str(root.parent / "datasets")}, stream, indent=2)
        stream.write("\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-root", required=True, type=Path)
    parser.add_argument("--config-directory", required=True, type=Path)
    args = parser.parse_args(argv)
    print(create_config(args.native_root, args.config_directory))


if __name__ == "__main__":
    main()
