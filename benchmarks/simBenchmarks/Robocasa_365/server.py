"""Robocasa_365 SIM server; native semantics remain in this benchmark's adapter."""
from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import make_robocasa365
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = (
    "benchmarks/simBenchmarks/Robocasa_365/__init__.py",
    "benchmarks/simBenchmarks/Robocasa_365/server.py",
    "benchmarks/simBenchmarks/Robocasa_365/bench_server/__init__.py",
    "benchmarks/simBenchmarks/Robocasa_365/bench_server/adapter.py",
    "benchmarks/simBenchmarks/Robocasa_365/bench_server/protocol/__init__.py",
    "benchmarks/simBenchmarks/Robocasa_365/bench_server/protocol/robocasa365_target50.json",
    "benchmarks/simBenchmarks/Robocasa_365/bench_server/protocol/task_inventory.json",
    "benchmarks/simBenchmarks/Robocasa_365/environment/render_lifecycle.py",
)


def main(argv=None) -> int:
    """Serve the pinned RoboCasa365 contract without starting native control."""
    return launch(make_robocasa365, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)

if __name__ == "__main__":
    raise SystemExit(main())
