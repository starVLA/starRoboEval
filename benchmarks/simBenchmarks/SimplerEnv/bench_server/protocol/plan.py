"""Benchmark-owned predeclared fast selection; no native runtime is launched here."""

from benchmarks.simBenchmarks.SimplerEnv.bench_server.adapter import SimplerEnvBenchmarkAdapter, TASK_HORIZONS
TASK_SCOPES = (None,)
def cases(common, seed, task_scope=None, asset_reference=None):
    result = []
    for task in TASK_HORIZONS:
        args = {**common, "task": task}
        adapter = SimplerEnvBenchmarkAdapter(**args)
        result.append({"benchmark_args": args, "episode": adapter.episodes(seed, 1)[0].to_dict(),
                       "descriptor": adapter.descriptor.to_dict()})
    return result

PURPOSE = "development_task_coverage"
DEVICE_KEY = "device"
DEVICE_CUDA_STRING = True
