"""Environment-only diagnostic; no evaluated model and no benchmark score."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchkit.artifacts import atomic_write_json
from benchmarks.simBenchmarks.LIBERO.bench_server.adapter import FIRST_PASS_SEED, LiberoBenchmarkAdapter, task_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", type=int, default=0)
    parser.add_argument("--suite", choices=tuple(task_catalog()), default="libero_10")
    parser.add_argument("--scope", choices=("development", "task_coverage"), default="development")
    parser.add_argument("--render-gpu-device-id", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "kind": "environment_diagnostic_not_model_evaluation",
        "task_id": args.task_id, "suite": args.suite, "scope": args.scope,
        "policy_calls": 0, "diagnostic_steps": 0,
        "native_success_after_diagnostic_step": None,
        "artifacts": {}, "status": "initializing", "error": None,
    }
    atomic_write_json(output / "diagnostic_status.json", {"status": "initializing"})
    session = None
    try:
        adapter = LiberoBenchmarkAdapter(task_ids=[args.task_id], suite=args.suite, scope=args.scope,
                                        render_gpu_device_id=args.render_gpu_device_id)
        episode = adapter.episodes(FIRST_PASS_SEED)[0]
        session = adapter.open_episode(episode)
        session.bind_artifact_dir(output)
        observation = session.reset()
        transition = session.step((0.0,) * 6 + (-1.0,))
        result["diagnostic_steps"] = 1
        result["native_success_after_diagnostic_step"] = session.metrics()["success"]
        if observation.metadata or transition.observation.metadata or observation.state is not None:
            raise AssertionError("default RGB diagnostic leaked undeclared metadata/state")
        result["camera_shapes"] = {key: list(value.shape) for key, value in observation.images.items()}
        result["status"] = "completed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        try:
            if session is not None:
                try:
                    result["artifacts"] = session.artifacts()
                finally:
                    session.close()
        except Exception as exc:
            result["status"] = "failed"
            result["cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            atomic_write_json(output / "diagnostic_result.json", result)
            atomic_write_json(output / "diagnostic_status.json", {"status": result["status"]})
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
