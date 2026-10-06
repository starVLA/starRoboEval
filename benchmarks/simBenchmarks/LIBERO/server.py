"""LIBERO SIM server; native semantics remain in this benchmark's adapter."""
from benchmarks.simBenchmarks.LIBERO.bench_server.adapter import make_libero
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = (
    "benchmarks/simBenchmarks/LIBERO/__init__.py",
    "benchmarks/simBenchmarks/LIBERO/server.py",
    "benchmarks/simBenchmarks/LIBERO/bench_server/__init__.py",
    "benchmarks/simBenchmarks/LIBERO/bench_server/adapter.py",
    "benchmarks/simBenchmarks/LIBERO/bench_server/protocol/__init__.py",
    "benchmarks/simBenchmarks/LIBERO/bench_server/protocol/libero_catalog.json",
)


def main(argv=None) -> int:
    """Declare the fixed LIBERO service; native construction stays lazy."""
    return launch(make_libero, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
