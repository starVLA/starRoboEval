"""Model-owned, server-only evaluation entrypoint; never imports a native SIM.

This is a trusted experiment driver, separate from the Codex actor.
It holds administrative service access for fixed episode claims and result
collection. Only allowed observations and public counters reach the model.
Do not hand this driver or its credentials to an untrusted model process.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path

import benchkit.sim_server.client as service_client_module
from benchkit.sim_server.client import SimServerBenchmarkAdapter
from benchkit.errors import PolicyPreflightError
from benchkit import model_profiles as profile_records
from benchkit.model_profiles import load_profile, validate_policy_parameters
from benchkit.source_snapshot import installed_source_root
from benchkit.recording import add_recording_arguments, recording_from_arguments
from AgentPolicies.gpt6_astra.tools import factory as policy_module
from AgentPolicies.gpt6_astra.tools.factory import METHODS, create_policy
from AgentPolicies.policy_support import runner as driver_module
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-server", required=True, help="evaluator-only authenticated loopback endpoint")
    parser.add_argument("--token-env", default="RSI_SIM_SERVER_TOKEN")
    parser.add_argument("--sim-server-timeout", type=float, default=1200)
    parser.add_argument("--benchmark", required=True, help="must match the selected server identity")
    parser.add_argument("--control-method", choices=METHODS, default="codex-direct/v3")
    parser.add_argument("--safety-stop", action=argparse.BooleanOptionalAction, default=None,
                        help="Direct v3/Planned v1: permit policy-requested early safety stops; default disabled in SIM")
    parser.add_argument("--image-max-edge", type=int, default=None,
                        help="Direct v3/planned v1: attachment max edge 0..4096, default480; 0 keeps originals")
    parser.add_argument("--invalid-action-handling", choices=("feedback", "terminate"), default=None,
                        help="active methods default to feedback without execution")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--episodes", type=int, required=True)
    parser.add_argument("--max-steps", type=int, required=True)
    parser.add_argument("--max-policy-calls", type=int)
    parser.add_argument("--replan-interval", type=int, default=5)
    parser.add_argument("--budget-mode", choices=("horizon", "decisions"), default="horizon")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--method-file", type=Path,
                        help="optional declared method/model composition JSON; not provider attestation")
    add_recording_arguments(parser)
    return parser


def checked_policy(control_method, *, image_max_edge=None, max_chunk_length=None, safety_stop=None):
    """Use shared declarative validation, but construct/check this model here."""
    root = Path(__file__).absolute().parents[2]
    origins = ((Path(profile_records.__file__).absolute(), root / "benchkit/model_profiles.py"),
               (Path(policy_module.__file__).absolute(), root / "AgentPolicies/gpt6_astra/tools/factory.py"),
               (Path(driver_module.__file__).absolute(), root / "AgentPolicies/policy_support/runner.py"),
               (Path(service_client_module.__file__).absolute(), root / "benchkit/sim_server/client.py"),
               (installed_source_root().absolute(), root / "benchkit"))
    if any(actual != expected for actual, expected in origins):
        raise ValueError("driver, factory and captured source must come from the same selected package")
    data = load_profile("gpt6_astra")
    parameters = {"control_method": control_method, "prompt": data["prompt"]}
    if image_max_edge is not None:
        parameters["image_max_edge"] = image_max_edge
    if max_chunk_length is not None:
        parameters["max_chunk_length"] = max_chunk_length
    if safety_stop is not None:
        parameters["safety_stop"] = safety_stop
    validate_policy_parameters(data, parameters)
    policy = create_policy(config=data["config"], identity=data["profile"]["policy"], **parameters)
    policy.descriptor = replace(policy.descriptor, parameters={
        **policy.descriptor.parameters, "model_profile": data["identity"]})
    try:
        if policy.preflight_runtime() is not None:
            raise PolicyPreflightError("initialization_failed")
    except PolicyPreflightError:
        raise
    except Exception:
        raise PolicyPreflightError("initialization_failed") from None
    return policy


def run(args):
    if args.control_method not in METHODS:
        raise ValueError("unknown or retired model control method")
    # Preflight is local and makes no inference request; fail before claiming
    # any episode. This method never falls back to an in-process simulator.
    recording = recording_from_arguments(args)
    method = None
    if args.method_file is not None:
        from benchkit.methods import normalize_method
        method = normalize_method(json.loads(args.method_file.read_text(encoding="utf-8")))
    direct_methods = ("codex-direct/v3",)
    feedback_methods = ("codex-native/v1", "codex-planned/v1", *direct_methods)
    if args.invalid_action_handling == "feedback" and args.control_method not in feedback_methods:
        raise ValueError("action rejection feedback requires an active Codex method")
    if args.control_method in direct_methods and args.invalid_action_handling == "terminate":
        raise ValueError("Direct control requires recoverable invalid-input feedback")
    if args.control_method == "codex-planned/v1" and args.invalid_action_handling == "terminate":
        raise ValueError("planned control requires recoverable invalid-input feedback")
    if args.image_max_edge is not None and args.control_method not in ("codex-direct/v3", "codex-planned/v1"):
        raise ValueError("--image-max-edge requires codex-direct/v3 or codex-planned/v1")
    image_parameter = {"image_max_edge": args.image_max_edge} if args.image_max_edge is not None else {}
    if args.safety_stop is not None:
        if args.control_method not in ("codex-direct/v3", "codex-planned/v1"):
            raise ValueError("--safety-stop/--no-safety-stop requires Direct v3 or Planned v1")
        image_parameter["safety_stop"] = args.safety_stop
    if args.control_method in ("codex-direct/v3", "codex-planned/v1"):
        image_parameter["max_chunk_length"] = args.replan_interval
    policy = checked_policy(args.control_method, **image_parameter)
    if (args.control_method in ("codex-direct/v3", "codex-planned/v1") and method is not None
            and "safety_stop" in method["configuration"]
            and method["configuration"]["safety_stop"] is not policy.descriptor.parameters["safety_stop"]):
        raise ValueError("declared method safety_stop differs from the effective policy setting")
    benchmark = SimServerBenchmarkAdapter(args.sim_server, os.environ.get(args.token_env, ""),
                                         timeout=args.sim_server_timeout)
    if benchmark.descriptor.name != args.benchmark:
        raise ValueError("benchmark name differs from the connected server")
    if benchmark.parameters.get("diagnostic") is True:
        raise ValueError("model capability evaluation cannot use a diagnostic-only service")
    if args.control_method in ("codex-direct/v3", "codex-planned/v1"):
        horizon = benchmark.environment_step_cap
        if (type(horizon) is not int or horizon <= 0 or args.max_steps != horizon
                or args.budget_mode != "horizon"):
            raise ValueError("persistent control requires the advertised native/development control horizon")
    rejection_mode = args.invalid_action_handling or (
        "feedback" if args.control_method in feedback_methods else "terminate")
    if (rejection_mode == "feedback" and benchmark.descriptor.name == "simpler_env"
            and benchmark.parameters.get("action_rejection_feedback") is not True):
        raise ValueError("SimplerEnv feedback needs its explicitly versioned action_rejection_feedback track")
    call_cap = args.max_policy_calls
    if rejection_mode == "feedback" and call_cap is None:
        call_cap = getattr(benchmark, "max_policy_calls", None)
        if type(call_cap) is not int or call_cap <= 0:
            raise ValueError("feedback mode needs --max-policy-calls or a positive advertised service allowance")
    if args.control_method in direct_methods and (type(call_cap) is not int or call_cap <= 0):
        raise ValueError("Direct needs a positive model action-submission allowance")
    request = RunRequest(output_dir=args.output_dir, seed=args.seed, episode_limit=args.episodes,
        max_steps=args.max_steps, max_policy_calls=call_cap,
        replan_interval=args.replan_interval, run_id=args.run_id, budget_mode=args.budget_mode,
        invalid_action_handling=rejection_mode,
        recording=recording, method=method,
        repository=Path(__file__).absolute().parents[2])
    return EvaluationRunner().run(benchmark, policy, request)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        output = run(args)
    except PolicyPreflightError as exc:
        print(json.dumps({"status": "preflight_failed", "error_code": exc.code,
                          "native_attempts": 0, "model_requests": 0}))
        return 1
    summary = json.loads((output / "summary.json").read_text())
    print(json.dumps({"output": str(output), "attempted": summary["attempted"],
                      "completed": summary["completed"], "errors": summary["errors"],
                      "successes": summary["successes"]}))
    return 0 if summary["attempted"] == args.episodes and summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
