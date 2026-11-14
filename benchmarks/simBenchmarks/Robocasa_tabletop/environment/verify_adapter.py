"""One native adapter reset/render/hold, without any policy object or capability score."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from benchkit.artifacts import atomic_write_json
from benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter import (
    PARTS, PILOT_SEED, TabletopBenchmarkAdapter,
)
from verify_environment import assert_gpu_idle, measured_hold_and_contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casa-source", type=Path, required=True)
    parser.add_argument("--suite-source", type=Path, required=True)
    parser.add_argument("--object-inventory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--native-task-index", type=int, choices=(0, 1, 2, 19), default=0)
    parser.add_argument("--task-scope", choices=("pilot", "tabletop-next-pair-v1"), default="pilot")
    parser.add_argument("--gpu", type=int, default=2)
    parser.add_argument("--reference-diagnostic", type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {"kind": "native_adapter_infrastructure_diagnostic_not_model_evaluation", "status": "initializing",
              "policy_calls": 0, "diagnostic_steps": 0, "errors": [],
              "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    session = None

    def persist():
        atomic_write_json(output / "diagnostic_result.json", result)
        atomic_write_json(output / "diagnostic_status.json", {"status": result["status"]})

    persist()
    try:
        adapter = TabletopBenchmarkAdapter(task_ids=[args.native_task_index], task_scope=args.task_scope,
                                          casa_source=args.casa_source, suite_source=args.suite_source,
                                          object_inventory=args.object_inventory, render_gpu_device_id=args.gpu)
        result["gpu"] = assert_gpu_idle(args.gpu)
        episode = adapter.episodes(PILOT_SEED)[0]
        result["episode"] = episode.to_dict()
        result["benchmark"] = adapter.descriptor.to_dict()
        result["action_contract"] = adapter.action_spec.to_dict()
        result["observation_contract"] = adapter.observation_spec.to_dict()
        session = adapter.open_episode(episode)
        session.bind_artifact_dir(output / "artifacts")
        observation = session.reset()
        result["reset_observation"] = observation.log_view()
        if args.reference_diagnostic:
            reference = json.loads(args.reference_diagnostic.read_text())
            if reference["task"] != episode.task or reference["seed"] != episode.seed:
                raise RuntimeError("reset signature reference must use this exact task/seed")
            result["repeat_reset_signature_match"] = (reference["initial_state_sha256"]
                                                       == session.provenance["initial_state_sha256"])
            if not result["repeat_reset_signature_match"]:
                raise RuntimeError("same fixed task/seed reset differs from retained infrastructure signature")
        # Evaluator-private diagnostic control only. This is not a policy and is
        # never called by a model evaluator to produce an action for a model.
        native_hold, _ = measured_hold_and_contract(session.env.unwrapped.env)
        hold = tuple(float(value) for public, _, _ in PARTS for value in native_hold["action." + public])
        atomic_write_json(output / "diagnostic_hold_action.json", {"action": hold, "origin": "measured_native_infrastructure_hold"})
        result["status"] = "executing_one_measured_hold"
        persist()
        transition = session.step(hold)
        result["diagnostic_steps"] = 1
        result["transition"] = {"reward": transition.reward, "terminated": transition.terminated,
                                "truncated": transition.truncated, "info": transition.info}
        result["final_observation"] = transition.observation.log_view()
        result["metrics"] = session.metrics()
        result["artifacts"] = session.artifacts()
        result["status"] = "completed"
    except Exception as error:
        result["status"] = "failed"
        result["errors"].append({"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
        if session is not None:
            result["metrics"] = session.metrics()
            result["diagnostic_steps"] = session.step_count
            try:
                result["artifacts"] = session.artifacts()
            except Exception as artifact_error:
                result["errors"].append({"phase": "artifacts", "type": type(artifact_error).__name__, "message": str(artifact_error)})
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as close_error:
                result["status"] = "failed"
                result["errors"].append({"phase": "close", "type": type(close_error).__name__, "message": str(close_error)})
        persist()
    print(json.dumps(result, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
