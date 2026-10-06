"""Public BEHAVIOR DefaultWrapper debugging server; no native startup on import."""
from benchmarks.simBenchmarks.Behavior.bench_server.adapter import make_behavior
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = tuple("benchmarks/simBenchmarks/Behavior/" + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "bench_server/native_worker_client.py", "bench_server/protocol/__init__.py",
    "environment/__init__.py", "environment/deployment.py", "environment/native_bridge.py",
    "environment/native_worker.py", "environment/crash_handler.py",
))


def main(argv=None):
    return launch(make_behavior, supplemental_sources=SUPPLEMENTAL_FILES,
                  excluded_artifact_directories=("cache",), argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
