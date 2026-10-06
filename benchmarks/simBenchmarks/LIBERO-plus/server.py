"""LIBERO-Plus native SIM server, using the neutral evaluator-private transport."""
from .bench_server.adapter import make_libero_plus
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = tuple("benchmarks/simBenchmarks/LIBERO-plus/" + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "bench_server/protocol/__init__.py", "bench_server/protocol/catalog.py",
    "bench_server/protocol/catalogs/libero_spatial.json",
    "bench_server/protocol/catalogs/libero_object.json",
    "bench_server/protocol/catalogs/libero_goal.json",
    "bench_server/protocol/catalogs/libero_10.json",
    "environment/__init__.py", "environment/native_source_manifest.json",
))


def main(argv=None) -> int:
    return launch(make_libero_plus, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
