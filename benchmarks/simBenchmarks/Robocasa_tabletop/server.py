"""Robocasa_tabletop SIM server; native semantics remain in this benchmark's adapter."""
from benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter import make_tabletop
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = (
    "benchmarks/simBenchmarks/Robocasa_tabletop/__init__.py",
    "benchmarks/simBenchmarks/Robocasa_tabletop/server.py",
    "benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/__init__.py",
    "benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/adapter.py",
    "benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/protocol/__init__.py",
    "benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/protocol/robocasa_tabletop_contract.json",
)


def main(argv=None) -> int:
    """Serve the pinned Tabletop adapter without importing native packages."""
    return launch(make_tabletop, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
