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
from benchkit.errors import CompatibilityError, PolicyPreflightError, ProtocolError
from benchkit import model_profiles as profile_records
from benchkit.model_profiles import load_profile
from benchkit.source_snapshot import installed_source_root
from benchkit.recording import add_recording_arguments, recording_from_arguments
from AgentPolicies.gpt6_astra import codex_native as policy_module
from AgentPolicies.gpt6_astra.codex_native import create_policy
from AgentPolicies.gpt6_astra.tools import runner as driver_module
from AgentPolicies.gpt6_astra.tools.runner import EvaluationRunner, RunRequest


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-server", required=True, help="evaluator-only authenticated loopback endpoint")
    parser.add_argument("--token-env", default="RSI_SIM_SERVER_TOKEN")
    parser.add_argument("--sim-server-timeout", type=float, default=1200)
    parser.add_argument("--benchmark", required=True, help="must match the selected server identity")
    parser.add_argument("--stagnation-review", action=argparse.BooleanOptionalAction, default=None,
                        help="advisory repeated-command review, disabled by default; no automatic action or stop")
    parser.add_argument("--allow-task-completion", action=argparse.BooleanOptionalAction, default=None,
                        help="permit model-declared completion, enabled by default; native scoring is separate")
    parser.add_argument("--stagnation-window", type=int, default=None,
                        help="review every 2..32 repeated executed decisions, default 4; setting it enables the review")
    parser.add_argument("--safety-stop", action=argparse.BooleanOptionalAction, default=None,
                        help="permit policy-requested early safety stops, enabled by default")
    parser.add_argument("--image-max-edge", type=int, default=None,
                        help="attachment max edge 0..4096, default 480; 0 keeps originals")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--episodes", type=int, required=True)
    parser.add_argument("--max-steps", type=int, default=None,
                        help="control horizon, default the service's advertised horizon; recorded in the manifest")
    parser.add_argument("--max-policy-calls", type=int)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--method-file", type=Path,
                        help="optional declared method/model composition JSON; not provider attestation")
    add_recording_arguments(parser)
    return parser


def checked_policy(*, image_max_edge=None, safety_stop=None,
                   stagnation_review=None, stagnation_window=None, allow_task_completion=None):
    """Validate local configuration and construct a policy without runtime I/O.

    No service connection, child process, actor thread or model turn starts here.
    Runtime readiness is a separate phase after service compatibility checks.
    """
    root = Path(__file__).absolute().parents[2]
    origins = ((Path(profile_records.__file__).absolute(), root / "benchkit/model_profiles.py"),
               (Path(policy_module.__file__).absolute(), root / "AgentPolicies/gpt6_astra/codex_native.py"),
               (Path(driver_module.__file__).absolute(), root / "AgentPolicies/gpt6_astra/tools/runner.py"),
               (Path(service_client_module.__file__).absolute(), root / "benchkit/sim_server/client.py"),
               (installed_source_root().absolute(), root / "benchkit"))
    if any(actual != expected for actual, expected in origins):
        raise ValueError("driver, factory and harness must come from this checkout; "
                         "the run records its Git revision")
    data = load_profile("gpt6_astra")
    parameters = {"prompt": data["prompt"]}
    if image_max_edge is not None:
        parameters["image_max_edge"] = image_max_edge
    if safety_stop is not None:
        parameters["safety_stop"] = safety_stop
    for name, value in (("stagnation_review", stagnation_review), ("stagnation_window", stagnation_window),
                        ("allow_task_completion", allow_task_completion)):
        if value is not None:
            parameters[name] = value
    policy = create_policy(config=data["config"], identity=data["profile"]["policy"], **parameters)
    policy.descriptor = replace(policy.descriptor, parameters={
        **policy.descriptor.parameters, "model_profile": data["profile"]["id"]})
    return policy


def check_runtime(policy):
    """Probe local CLI/configuration readiness, never inference or case claims.

    The policy may create temporary files, child processes and an ephemeral
    configuration thread. This is not pure configuration validation.
    """
    try:
        if policy.preflight_runtime() is not None:
            raise PolicyPreflightError("initialization_failed")
    except PolicyPreflightError:
        raise
    except Exception:
        raise PolicyPreflightError("initialization_failed") from None


def run(args):
    # Pure local checks precede the first service connection. Runtime probes
    # happen only after describe/compatibility, always before a case claim.
    recording = recording_from_arguments(args)
    method = None
    if args.method_file is not None:
        from benchkit.methods import normalize_method
        method = normalize_method(json.loads(args.method_file.read_text(encoding="utf-8")))
    policy = checked_policy(image_max_edge=args.image_max_edge,
                            safety_stop=args.safety_stop,
                            allow_task_completion=args.allow_task_completion,
                            stagnation_review=args.stagnation_review, stagnation_window=args.stagnation_window)
    benchmark = SimServerBenchmarkAdapter(args.sim_server, os.environ.get(args.token_env, ""),
                                         timeout=args.sim_server_timeout)
    if benchmark.descriptor.name != args.benchmark:
        raise ValueError("benchmark name differs from the connected server")
    if benchmark.parameters.get("diagnostic") is True:
        raise ValueError("model capability evaluation cannot use a diagnostic-only service")
    if getattr(benchmark, "budget_mode", None) != "horizon":
        raise ValueError("codex_native requires a budget_mode=horizon service; "
                         "decision-coupled services need a compatible driver")
    # The service's horizon is the default; an override is recorded against it.
    max_steps = benchmark.environment_step_cap if args.max_steps is None else args.max_steps
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("codex_native needs --max-steps or a positive advertised service horizon")
    if (benchmark.descriptor.name == "simpler_env"
            and benchmark.parameters.get("action_rejection_feedback") is not True):
        raise ValueError("SimplerEnv feedback needs its explicitly versioned action_rejection_feedback track")
    call_cap = args.max_policy_calls
    if call_cap is None:
        call_cap = getattr(benchmark, "max_policy_calls", None)
    if type(call_cap) is not int or call_cap <= 0:
        raise ValueError("codex_native needs --max-policy-calls or a positive advertised service allowance")
    # The whole policy chunk executes unless the service declares a prefix.
    request = RunRequest(output_dir=args.output_dir, seed=args.seed, episode_limit=args.episodes,
        max_steps=max_steps, max_policy_calls=call_cap,
        replan_interval=getattr(benchmark, "required_replan_interval", None), run_id=args.run_id, budget_mode="horizon",
        # Invalid actions come back to the model as feedback, without execution.
        invalid_action_handling="feedback",
        recording=recording, method=method,
        repository=Path(__file__).absolute().parents[2])
    # These checks read only the cached description and local policy contract.
    # The reusable runner repeats them for its other entrypoints, before claims.
    errors = list(policy.compatibility_errors(benchmark.observation_spec, benchmark.action_spec))
    if errors:
        raise CompatibilityError("; ".join(errors))
    available = len(tuple(benchmark.episodes(request.seed, request.episode_limit)))
    if available != args.episodes:
        raise ProtocolError(f"benchmark offers {available} episodes for this seed, not --episodes {args.episodes}")
    check_runtime(policy)
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
