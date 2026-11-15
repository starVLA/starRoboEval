"""SimplerEnv SIM server; native semantics remain in this benchmark's adapter."""
from benchmarks.simBenchmarks.SimplerEnv.bench_server.adapter import make_simpler_env
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = (
    "benchmarks/simBenchmarks/SimplerEnv/__init__.py",
    "benchmarks/simBenchmarks/SimplerEnv/server.py",
    "benchmarks/simBenchmarks/SimplerEnv/bench_server/__init__.py",
    "benchmarks/simBenchmarks/SimplerEnv/bench_server/adapter.py",
    "benchmarks/simBenchmarks/SimplerEnv/bench_server/protocol/__init__.py",
    "benchmarks/simBenchmarks/SimplerEnv/bench_server/protocol/max_matrix.py",
    "benchmarks/simBenchmarks/SimplerEnv/bench_server/protocol/task_catalog.json",
    "benchmarks/simBenchmarks/SimplerEnv/environment/__init__.py",
    "benchmarks/simBenchmarks/SimplerEnv/environment/render_device.py",
)


def main(argv=None) -> int:
    """Freeze service-owned sources without constructing a native environment."""
    return launch(make_simpler_env, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
