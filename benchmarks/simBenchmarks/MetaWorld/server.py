"""Benchmark-owned MetaWorld server; no simulator is created before reset."""
from benchmarks.simBenchmarks.MetaWorld.bench_server.adapter import make_metaworld
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = tuple("benchmarks/simBenchmarks/MetaWorld/" + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "bench_server/protocol/__init__.py", "bench_server/protocol/task_catalog.json",
    "environment/__init__.py", "environment/runtime.py", "environment/package_pin.json",
))


def main(argv=None) -> int:
    return launch(make_metaworld, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)

if __name__ == "__main__":
    raise SystemExit(main())
