"""Service-owned source inputs; independent of legacy campaign selection."""

# Legacy campaign snapshots already capture the Python package and catalog.
# Their supplement must contain only inputs outside that common source bundle.
CAMPAIGN_SUPPLEMENTAL_FILES = (
    "benchmarks/simBenchmarks/SIMPLE/environment/native_worker.py",
    "benchmarks/simBenchmarks/SIMPLE/environment/upstream.json",
    "benchmarks/simBenchmarks/SIMPLE/bench_server/protocol/POLICY_GUIDE.md",
)

SUPPLEMENTAL_FILES = CAMPAIGN_SUPPLEMENTAL_FILES + (
    "benchmarks/simBenchmarks/SIMPLE/__init__.py",
    "benchmarks/simBenchmarks/SIMPLE/server.py",
    "benchmarks/simBenchmarks/SIMPLE/bench_server/__init__.py",
    "benchmarks/simBenchmarks/SIMPLE/bench_server/adapter.py",
    "benchmarks/simBenchmarks/SIMPLE/bench_server/native_worker_client.py",
    "benchmarks/simBenchmarks/SIMPLE/bench_server/source_inventory.py",
    "benchmarks/simBenchmarks/SIMPLE/bench_server/protocol/__init__.py",
    "benchmarks/simBenchmarks/SIMPLE/bench_server/protocol/simple_released_tasks.json",
)
