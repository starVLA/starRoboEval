"""Campaign plan registry: concrete task selections remain benchmark-owned.

These are fast, once-per-selected-task development plans. A full native matrix
must be verified and implemented in its benchmark plan; it is never inferred by
repeating failed cases.
"""
from importlib import import_module

FIRST_PASS_SEED = 20260907
PLAN_MODULES = {
    "libero": "benchmarks.simBenchmarks.LIBERO.bench_server.protocol.plan",
    "simpler_env": "benchmarks.simBenchmarks.SimplerEnv.bench_server.protocol.plan",
    "robocasa365": "benchmarks.simBenchmarks.Robocasa_365.bench_server.protocol.plan",
    "simple_humanoid": "benchmarks.simBenchmarks.SIMPLE.bench_server.protocol.plan",
    "robocasa_tabletop": "benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.protocol.plan",
}

# Declare actual implementation modules; source capture must not assume that
# every benchmark retains a root adapter or an evaluation/ directory.
ADAPTER_MODULES = {
    "libero": "benchmarks.simBenchmarks.LIBERO.bench_server.adapter",
    "simpler_env": "benchmarks.simBenchmarks.SimplerEnv.bench_server.adapter",
    "robocasa365": "benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter",
    "simple_humanoid": "benchmarks.simBenchmarks.SIMPLE.bench_server.adapter",
    "robocasa_tabletop": "benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter",
}

def get_plan(benchmark):
    try:
        module_name = PLAN_MODULES[benchmark]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"campaign benchmark must be one of {tuple(PLAN_MODULES)}") from exc
    return import_module(module_name)
