#!/usr/bin/env python3
"""Record time-to-success from closed event logs, without querying a simulator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

NATIVE_SUCCESS_FIELDS = {
    "simpler_env": "success", "libero": "native_success",
    "robocasa365": "native_success", "simple_humanoid": "native_success",
    "robocasa_tabletop": "native_success", "robodojo": "native_success",
}


def summarize_progress(run: Path) -> dict:
    run = run.resolve(strict=True)
    lifecycle = json.loads((run / "status.json").read_text())
    if lifecycle.get("status") not in ("completed", "completed_with_errors"):
        raise ValueError("progress analysis requires a closed run")
    manifest = json.loads((run / "manifest.json").read_text())
    field = NATIVE_SUCCESS_FIELDS.get(manifest["benchmark"]["name"])
    rows = []
    for result_path in sorted((run / "episodes").glob("*/result.json")):
        if not result_path.resolve().is_relative_to(run):
            raise ValueError("episode result must remain inside the run")
        result = json.loads(result_path.read_text())
        events_path = result_path.parent / "events.jsonl"
        if not events_path.resolve().is_relative_to(run):
            raise ValueError("episode events must remain inside the run")
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line]
        steps = [event for event in events if event.get("event") == "environment_step"]
        scored = [event for event in steps if type(event.get("info", {}).get(field)) is bool] if field else []
        coverage = (
            bool(field) and len(scored) == result["environment_steps"]
            and [event["environment_step"] for event in scored] == list(range(1, result["environment_steps"] + 1))
        )
        successful = [event for event in scored if event["info"][field]]
        first = successful[0] if successful else None
        trailing = 0
        for event in reversed(scored):
            if not event["info"][field]:
                break
            trailing += 1
        rows.append({
            "episode": result["episode"], "status": result["status"],
            "native_success_field": field, "complete_step_coverage": coverage,
            "first_native_success_step": first["environment_step"] if first and coverage else None,
            "policy_call_at_first_native_success": first["policy_call"] if first and coverage else None,
            "first_native_success_timestamp": first["timestamp"] if first and coverage else None,
            "first_logged_success_step": first["environment_step"] if first else None,
            "last_native_success_step": successful[-1]["environment_step"] if successful else None,
            "successful_logged_steps": len(successful),
            "consecutive_success_steps_at_end": trailing if coverage else None,
            "final_environment_steps": result["environment_steps"],
            "final_policy_calls": result["policy_calls"], "final_success": result["success"],
            "termination_reason": result["termination_reason"], "error": result["error"],
            "source_events": str(events_path),
        })
    if len(rows) != lifecycle.get("episodes_written"):
        raise ValueError("closed status and available episode records disagree")
    return {
        "schema_version": "starvla-rsi.closed-run-progress/v1",
        "source_run": str(run), "benchmark": manifest["benchmark"], "protocol": manifest["protocol"],
        "method": "existing native step info only; no simulator or extra scorer call",
        "interpretation": "First success is diagnostic and does not replace final native scoring. Null is not an estimated step.",
        "episodes": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new derived report; never overwrite source results")
    args = parser.parse_args()
    report = summarize_progress(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
