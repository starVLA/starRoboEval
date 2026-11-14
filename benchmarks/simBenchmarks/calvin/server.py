"""Serve a predeclared CALVIN debug sequence, without constructing SIM at launch."""
from benchmarks.simBenchmarks.calvin.bench_server.adapter import make_calvin
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = tuple("benchmarks/simBenchmarks/calvin/" + name for name in (
    "__init__.py", "server.py", "bench_server/__init__.py", "bench_server/adapter.py",
    "bench_server/protocol/__init__.py", "bench_server/protocol/selected_sequence.json",
    "bench_server/protocol/eval_sequences.json", "environment/__init__.py",
    "environment/runtime.py", "environment/runtime_snapshot.json",
    "environment/requirements-rgb-setup.txt",
))


def main(argv=None):
    return launch(make_calvin, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
