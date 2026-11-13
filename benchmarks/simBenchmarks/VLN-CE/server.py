"""VLN-CE service entrypoint; importing or describing does not start Habitat."""
from .bench_server.adapter import make_vlnce
from benchkit.sim_server.launch import main as launch

PREFIX = "benchmarks/simBenchmarks/VLN-CE/"
SUPPLEMENTAL_FILES = tuple(PREFIX + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "bench_server/native_worker_client.py", "environment/__init__.py",
    "environment/native_runtime.py", "environment/native_worker.py",
))


def main(argv=None):
    return launch(make_vlnce, supplemental_sources=SUPPLEMENTAL_FILES,
                  excluded_artifact_directories=("cache",), argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
