"""Benchmark-owned RoboTwin service; native construction starts only on reset."""
from benchmarks.simBenchmarks.Robotwin.bench_server.adapter import make_robotwin
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = tuple("benchmarks/simBenchmarks/Robotwin/" + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "environment/__init__.py", "environment/runtime.py", "environment/deployment.py",
    "environment/oidn_compat.py", "environment/native_snapshot.json",
    "environment/runtime_snapshot.json", "environment/oidn_2_3_3_snapshot.json",
))


def main(argv=None):
    return launch(make_robotwin, excluded_artifact_directories=("cache",),
                  supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
