"""Public DOMINO server factory; construction/describe do not initialize SIM."""
from benchmarks.simBenchmarks.DOMINO.bench_server.adapter import make_domino
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = tuple("benchmarks/simBenchmarks/DOMINO/" + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "bench_server/protocol/__init__.py", "environment/__init__.py",
    "environment/deployment.py", "environment/runtime.py", "environment/native_outcome.py",
))


def main(argv=None):
    return launch(make_domino, supplemental_sources=SUPPLEMENTAL_FILES,
                  excluded_artifact_directories=("cache",), argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
