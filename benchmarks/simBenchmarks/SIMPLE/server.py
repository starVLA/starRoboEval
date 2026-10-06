"""SIMPLE SIM server; native semantics remain in this benchmark's adapter."""
from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import make_simple_humanoid
from benchmarks.simBenchmarks.SIMPLE.bench_server.source_inventory import SUPPLEMENTAL_FILES
from benchkit.sim_server.launch import main as launch


def main(argv=None) -> int:
    """Launch the declared SIMPLE service and capture its private worker sources."""
    return launch(make_simple_humanoid, excluded_artifact_directories=("cache",),
                  supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
