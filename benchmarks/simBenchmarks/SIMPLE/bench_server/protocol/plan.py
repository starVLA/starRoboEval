"""Benchmark-owned predeclared fast selection; no native runtime is launched here."""

from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import SimpleHumanoidBenchmarkAdapter, TASKS, FULL_TASKS
from benchmarks.simBenchmarks.SIMPLE.bench_server.source_inventory import CAMPAIGN_SUPPLEMENTAL_FILES as SUPPLEMENTAL_FILES
TASK_SCOPES = (None, "released-12")
def cases(common, seed, task_scope=None, asset_reference=None):
    result = []
    for task in (FULL_TASKS if task_scope else TASKS):
        args = {**common, "task_names": [task], "proprioception": True}
        if task_scope:
            args["task_scope"] = task_scope
        adapter = SimpleHumanoidBenchmarkAdapter(**args)
        result.append({"benchmark_args": args, "episode": adapter.episodes(seed)[0].to_dict(),
                       "descriptor": adapter.descriptor.to_dict()})
    return result

DEVICE_KEY = "gpu_id"
