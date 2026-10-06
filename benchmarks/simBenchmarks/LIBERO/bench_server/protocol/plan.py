"""Benchmark-owned predeclared fast selection; no native runtime is launched here."""

from benchmarks.simBenchmarks.LIBERO.bench_server.adapter import LiberoBenchmarkAdapter, task_catalog
TASK_SCOPES = (None,)
def cases(common, seed, task_scope=None, asset_reference=None):
    result = []
    for suite, row in task_catalog().items():
        for task_id in range(row["task_count"]):
            args = {**common, "suite": suite, "scope": "task_coverage", "task_ids": [task_id]}
            adapter = LiberoBenchmarkAdapter(**args)
            result.append({"benchmark_args": args, "episode": adapter.episodes(seed)[0].to_dict(),
                           "descriptor": adapter.descriptor.to_dict()})
    return result

PURPOSE = "development_task_coverage"
