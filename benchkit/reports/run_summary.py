"""Summarize recorded outcomes without loading a policy or simulator."""
from benchkit.contracts import ensure_jsonable


def summarize_run(run_id, benchmark_name, policy_name, results):
    """Keep completed-case SR and attempted-case coverage distinct.

    This preserves the existing result schema. A comparison with a predeclared
    panel must also report its unattempted cases and cannot discard errors.
    """
    completed = [result for result in results if result["status"] == "completed"]
    successes = [result for result in completed if result["success"] is True]
    usage = {}
    for key in ("calls", "input_tokens", "output_tokens", "cached_input_tokens",
                "estimated_cost_usd", "latency_s"):
        values = [result["usage"][key] for result in results]
        usage[key] = None if any(value is None for value in values) else sum(values)
    # Totals are not final while any episode's own usage report was
    # incomplete or contradicted its measured calls.
    usage_incomplete = sum(result["usage_reported_complete"] is False
                           or bool(result["usage_inconsistent_fields"]) for result in results)
    by_task = {}
    for task in sorted({str(result["episode"]["task"]) for result in results}):
        rows = [result for result in results if str(result["episode"]["task"]) == task]
        done = [result for result in rows if result["status"] == "completed"]
        won = sum(result["success"] is True for result in done)
        by_task[task] = {"attempted": len(rows), "completed": len(done),
            "errors": len(rows) - len(done), "successes": won,
            "policy_calls": sum(int(result["policy_calls"]) for result in rows),
            "rejected_actions": sum(int(result["rejected_actions"]) for result in rows),
            "success_rate": won / len(done) if done else None,
            "attempt_success_rate": won / len(rows) if rows else None}
    return ensure_jsonable({"schema_version": "starvla-rsi.eval/v1", "run_id": run_id,
        "benchmark": benchmark_name, "policy": policy_name,
        "attempted": len(results), "completed": len(completed),
        "errors": len(results) - len(completed), "successes": len(successes),
        "policy_calls": sum(int(result["policy_calls"]) for result in results),
        "rejected_actions": sum(int(result["rejected_actions"]) for result in results),
        "completion_rate": len(completed) / len(results) if results else 0.0,
        "success_rate": len(successes) / len(completed) if completed else None,
        "attempt_success_rate": len(successes) / len(results) if results else None,
        "usage": usage, "usage_incomplete_episodes": usage_incomplete, "by_task": by_task})
