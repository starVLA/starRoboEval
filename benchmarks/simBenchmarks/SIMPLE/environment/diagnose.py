"""No-model reset/warmup/render/one-hold-tick diagnostic, NOT a capability score."""
from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import SimpleHumanoidBenchmarkAdapter, TASKS, SEED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=TASKS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=4)
    parser.add_argument("--rgb-only", action="store_true")
    parser.add_argument("--budget-mode", choices=("decisions", "horizon"), default="decisions")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    adapter = SimpleHumanoidBenchmarkAdapter(task_names=(args.task,), gpu_id=args.gpu, diagnostic=True,
        proprioception=not args.rgb_only, budget_mode=args.budget_mode)
    session = adapter.open_episode(adapter.episodes(SEED)[0])
    session.bind_artifact_dir(args.output)
    report = {"task": args.task, "diagnostic_only": True, "policy_calls": 0, "passed": False,
        "protocol": adapter.descriptor.to_dict(), "action_spec": adapter.action_spec.to_dict(),
        "observation_spec": adapter.observation_spec.to_dict()}
    try:
        first = session.reset()
        transition = session.diagnostic_hold()
        report.update({"passed": True, "reset_rgb_shape": list(first.images["head_stereo_left"].shape),
            "post_hold_rgb_shape": list(transition.observation.images["head_stereo_left"].shape),
            "reset_state_size": len(first.state) if first.state is not None else 0,
            "post_hold_state_size": len(transition.observation.state) if transition.observation.state is not None else 0,
            "instruction": first.instruction, "metrics": session.metrics(), "artifacts": session.artifacts()})
    except BaseException as exc:
        report.update({"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
        raise
    finally:
        (args.output / "diagnostic_result.json").write_text(json.dumps(report, indent=2) + "\n")
        session.close()


if __name__ == "__main__":
    main()
