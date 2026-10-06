"""Start only the dependency-free synthetic service, never a native robot task."""
from benchkit.sim_server.launch import main as launch
from benchkit.diagnostics.smoke import make_smoke_benchmark

SUPPLEMENTAL_FILES = (
    "benchkit/sim_server/__main__.py",
    "benchkit/diagnostics/__init__.py",
    "benchkit/diagnostics/smoke.py",
)


def main(argv=None):
    return launch(make_smoke_benchmark, supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
