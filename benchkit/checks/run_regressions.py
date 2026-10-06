"""Run isolated CPU regression groups, never native capability evaluations.

Uses the selected Python environment (NumPy, Pillow and PyAV are needed for the
media fixtures). A new output directory retains every group's stdout/stderr and
one machine-readable summary. No installed environment or old result is changed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

GROUPS = {
    "benchkit": "benchkit/checks",
    "benchmark_service": "benchkit/sim_server/checks",
    "media": "benchkit/artifact_checks",
    "anonymous_policy": "AgentPolicies/anonymous_code_agent/checks",
    "gpt6_astra_policy": "AgentPolicies/gpt6_astra/checks",
    **{name: f"benchmarks/simBenchmarks/{name}/checks" for name in (
        "SimplerEnv", "LIBERO", "SIMPLE", "Robocasa_365", "Robocasa_tabletop", "RoboDojo",
        "MetaWorld", "LIBERO-plus", "Robotwin", "DOMINO", "Behavior", "VLA-Arena", "calvin")},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new, unused report directory")
    parser.add_argument("--group", action="append", choices=tuple(GROUPS))
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 8 or not 0 < args.timeout <= 3600:
        parser.error("jobs must be 1..8; timeout must be positive and at most 3600 seconds")
    root = Path(__file__).resolve().parents[2]
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root)}

    def run(name: str) -> dict:
        command = [sys.executable, "-m", "unittest", "discover", "-s", GROUPS[name], "-q"]
        started = time.monotonic()
        timed_out = False
        try:
            process = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=args.timeout)
            stdout, stderr, returncode = process.stdout, process.stderr, process.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, returncode = exc.stdout or b"", exc.stderr or b"", None
            timed_out = True
        (output / f"{name}.stdout.log").write_bytes(stdout)
        (output / f"{name}.stderr.log").write_bytes(stderr)
        text = stderr.decode("utf-8", errors="replace")
        count = re.search(r"Ran (\d+) tests? in", text)
        skips = re.search(r"skipped=(\d+)", text)
        row = {"group": name, "command": command, "returncode": returncode,
               "timed_out": timed_out, "tests": int(count[1]) if count else None,
               "skipped": int(skips[1]) if skips else 0,
               "seconds": round(time.monotonic() - started, 3)}
        print(json.dumps(row), flush=True)
        return row

    selected = list(dict.fromkeys(args.group or GROUPS))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = [future.result() for future in as_completed([pool.submit(run, name) for name in selected])]
    rows.sort(key=lambda row: selected.index(row["group"]))
    passed = all(row["returncode"] == 0 and row["tests"] is not None for row in rows)
    summary = {"schema_version": "starvla-rsi.cpu-regressions/v1", "python": sys.executable,
               "source_root": str(root), "native_evaluations": 0, "passed": passed,
               "tests": sum(row["tests"] or 0 for row in rows),
               "skipped": sum(row["skipped"] for row in rows), "groups": rows}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(str(output / "summary.json"), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
