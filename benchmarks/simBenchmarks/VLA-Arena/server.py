"""Independent benchmark-owned SIM service; no native creation before reset."""
from .bench_server.adapter import make_vla_arena
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = tuple("benchmarks/simBenchmarks/VLA-Arena/" + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "bench_server/protocol/__init__.py", "bench_server/protocol/task_catalog.json",
    "environment/__init__.py", "environment/runtime.py", "environment/configure.py",
    "environment/native_source_pin.json", "environment/robosuite_pin.json",
))


def main(argv=None):
    return launch(make_vla_arena, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)

if __name__ == "__main__":
    raise SystemExit(main())
