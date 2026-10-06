"""Benchmark-owned predeclared fast selection; no native runtime is launched here."""

from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import RoboCasa365BenchmarkAdapter, target50_inventory
TASK_SCOPES = (None, "target50")
def cases(common, seed, task_scope=None, asset_reference=None):
    result = []
    for task_id in (range(len(target50_inventory()["tasks"])) if task_scope else (0, 1)):
        args = {**common, "task_ids": [task_id]}
        if task_scope:
            args["task_scope"] = task_scope
        adapter = RoboCasa365BenchmarkAdapter(**args)
        result.append({"benchmark_args": args, "episode": adapter.episodes(seed)[0].to_dict(),
                       "descriptor": adapter.descriptor.to_dict()})
    return result
