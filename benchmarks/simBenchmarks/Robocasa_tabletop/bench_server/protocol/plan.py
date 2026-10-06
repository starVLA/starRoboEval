"""Benchmark-owned predeclared fast selection; no native runtime is launched here."""

from benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter import TabletopBenchmarkAdapter, PILOT_TASKS, NEXT_TASKS
TASK_SCOPES = (None, "tabletop-next-pair-v1")
def cases(common, seed, task_scope=None, asset_reference=None):
    result = []
    for task_id in (NEXT_TASKS if task_scope else PILOT_TASKS):
        args = {**common, "task_ids": [task_id]}
        if task_scope:
            args["task_scope"] = task_scope
        adapter = TabletopBenchmarkAdapter(**args)
        result.append({"benchmark_args": args, "episode": adapter.episodes(seed)[0].to_dict(),
                       "descriptor": adapter.descriptor.to_dict()})
    return result

RUNTIME_ENVIRONMENT = {"PYTHONHASHSEED": "0"}
SUPPLEMENTAL_FILES = ("benchmarks/simBenchmarks/Robocasa_tabletop/bench_server/protocol/POLICY_GUIDE.md",)


def verify_selection(manifest):
    if manifest.get("task_scope") == "tabletop-next-pair-v1" or any(
            case["benchmark_args"].get("task_scope") == "tabletop-next-pair-v1"
            or case.get("episode", {}).get("task") in NEXT_TASKS.values() for case in manifest["cases"]):
        verify_next_pair(manifest)
        return True
    return False


def verify_next_pair(manifest: dict) -> None:
    """Bind the separately authorized pair without reopening old pilot identities."""
    import json
    from benchkit.campaigns.workflow import cases_for, CAMPAIGN_SCHEMA
    from benchkit.campaigns.benchmark_plans import FIRST_PASS_SEED
    if (manifest.get("benchmark") != "robocasa_tabletop"
        or manifest.get("task_scope") != "tabletop-next-pair-v1"
        or manifest.get("purpose") != "development_pilot" or manifest.get("budget_mode") != "decisions"
        or type(manifest.get("seed")) is not int or manifest["seed"] != FIRST_PASS_SEED
        or type(manifest.get("planned_cases")) is not int or manifest["planned_cases"] != 2
        or type(manifest.get("attempts_per_task")) is not int or manifest["attempts_per_task"] != 1
        or manifest.get("runtime_environment") != {"PYTHONHASHSEED": "0"}
        or any(key in manifest for key in ("coverage_ledger", "carried_attempts", "selected_total",
                                           "planned_new_cases", "coverage_reporting"))):
        raise ValueError("invalid explicit Tabletop next-pair pilot declaration")
    if (any(type(manifest.get(key)) is not int for key in ("max_steps", "max_policy_calls", "replan_interval"))
        or manifest["max_steps"] != manifest["max_policy_calls"] * manifest["replan_interval"]):
        raise ValueError("Tabletop next-pair runner control safety cap changed")
    cases = manifest["cases"]
    if not isinstance(cases, list) or len(cases) != 2:
        raise ValueError("Tabletop next-pair requires its exact two cases")
    expected = cases_for("robocasa_tabletop", manifest["max_policy_calls"], manifest["replan_interval"],
                         task_scope="tabletop-next-pair-v1")
    actual = [{key: value for key, value in case.items() if key != "policy_endpoint"} for case in cases]
    if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
        raise ValueError("Tabletop next-pair selection/metadata changed or includes a prior task")
