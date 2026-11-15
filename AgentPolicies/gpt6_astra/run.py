"""Evaluate the Native GPT-6-Astra Policy against a benchmark service.

The driver connects to the service, checks that the service and the policy are
compatible, and then runs the selected episodes. It holds the service token;
the model receives only public observations and counters.

Start reading at main(), reading step 1 below.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from benchkit.errors import CompatibilityError, PolicyPreflightError, ProtocolError
from benchkit.driver.methods import normalize_method
from benchkit.driver.model_profiles import create_policy, preflight_policy
from benchkit.driver.recording import add_recording_arguments, recording_from_arguments
from benchkit.sim_server.client import SimServerBenchmarkAdapter
from benchkit.driver.runner import EvaluationRunner, RunRequest

PROFILE = "gpt6_astra"  # benchkit loads AgentPolicies/gpt6_astra/configs/profile.json
REPOSITORY = Path(__file__).absolute().parents[2]  # repository root; the manifest records its git revision
# Command-line options forwarded to the policy factory as configuration overrides.
POLICY_OPTIONS = ("image_max_edge", "safety_stop", "allow_task_completion",
                  "stagnation_review", "stagnation_window")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)

    service = parser.add_argument_group("benchmark service")
    service.add_argument("--sim-server", required=True, help="service URL")
    service.add_argument("--token-env", default="RSI_SIM_SERVER_TOKEN",
                         help="environment variable that holds the service token")
    service.add_argument("--sim-server-timeout", type=float, default=1200,
                         help="service request timeout in seconds")
    service.add_argument("--benchmark", required=True, help="benchmark ID; must match the service")

    schedule = parser.add_argument_group("schedule and budget")
    schedule.add_argument("--seed", type=int, required=True)
    schedule.add_argument("--episodes", type=int, required=True)
    schedule.add_argument("--max-steps", type=int, default=None,
                          help="control horizon; default is the service's advertised horizon")
    schedule.add_argument("--max-policy-calls", type=int, default=None,
                          help="policy-call cap; default is the service's advertised allowance")

    policy = parser.add_argument_group("policy options (any change makes a different method)")
    policy.add_argument("--image-max-edge", type=int, default=None,
                        help="longest image side 0..4096, default 480; 0 keeps originals")
    policy.add_argument("--safety-stop", action=argparse.BooleanOptionalAction, default=None,
                        help="allow model-requested safety stops, enabled by default")
    policy.add_argument("--allow-task-completion", action=argparse.BooleanOptionalAction, default=None,
                        help="allow model-declared completion, enabled by default; the benchmark still scores")
    policy.add_argument("--stagnation-review", action=argparse.BooleanOptionalAction, default=None,
                        help="remind the model after repeated constant commands, disabled by default")
    policy.add_argument("--stagnation-window", type=int, default=None,
                        help="repeated decisions before a reminder, 2..32, default 4; enables the review")

    output = parser.add_argument_group("output")
    output.add_argument("--output-dir", type=Path, required=True)
    output.add_argument("--run-id", required=True)
    output.add_argument("--method-file", type=Path, help="optional method declaration JSON")
    add_recording_arguments(parser)
    return parser


# Reading step 2 of 6: build the policy, connect to the service, then hand over to
# EvaluationRunner.run in benchkit/driver/runner.py.
def run(args):
    recording = recording_from_arguments(args)  # which interactions, images and artifacts are kept
    method = _read_method(args.method_file)
    # Loads the profile's config, schema and prompt, then calls create_policy in codex_native.py.
    policy = create_policy(PROFILE, **_policy_overrides(args))
    benchmark = _connect(args)  # service client: specs, episode schedule, sessions; stays in this driver
    max_steps = _max_steps(args, benchmark)
    max_policy_calls = _max_policy_calls(args, benchmark)
    request = RunRequest(
        output_dir=args.output_dir, run_id=args.run_id,
        seed=args.seed, episode_limit=args.episodes,
        max_steps=max_steps, max_policy_calls=max_policy_calls,
        # Set only when the service fixes the controls per decision; None means no per-decision cap.
        replan_interval=getattr(benchmark, "required_replan_interval", None),
        invalid_action_handling="feedback",  # invalid replies go back to the model instead of ending the episode
        recording=recording, method=method, repository=REPOSITORY)
    # Both checks run before any output is written; preflight boots Codex once on a throwaway thread.
    _check_compatibility(policy, benchmark, request)
    preflight_policy(policy)
    return EvaluationRunner().run(benchmark, policy, request)  # returns the run directory


def _read_method(path):
    """The participant's method declaration; None lets the runner derive one from the policy descriptor."""
    if path is None:
        return None
    return normalize_method(json.loads(path.read_text(encoding="utf-8")))


def _policy_overrides(args):
    """Only the options given on the command line; the rest keep their configured values."""
    values = {name: getattr(args, name) for name in POLICY_OPTIONS}
    return {name: value for name, value in values.items() if value is not None}


def _connect(args):
    benchmark = SimServerBenchmarkAdapter(args.sim_server, os.environ.get(args.token_env, ""),
                                         timeout=args.sim_server_timeout)  # fetches the service description
    # Refuse the wrong benchmark or a diagnostic-only service.
    if benchmark.descriptor.name != args.benchmark:
        raise ValueError("benchmark name differs from the connected server")
    if benchmark.parameters.get("diagnostic") is True:
        raise ValueError("model capability evaluation cannot use a diagnostic-only service")
    return benchmark


def _max_steps(args, benchmark):
    """Control horizon per episode: --max-steps if given, else the service's advertised cap."""
    value = benchmark.environment_step_cap if args.max_steps is None else args.max_steps
    if type(value) is not int or value <= 0:
        raise ValueError("gpt6-astra-codex-native needs --max-steps or a positive advertised service horizon")
    return value


def _max_policy_calls(args, benchmark):
    """Model calls per episode, rejected replies included: --max-policy-calls, else the service's allowance."""
    value = args.max_policy_calls
    if value is None:
        value = getattr(benchmark, "max_policy_calls", None)
    if type(value) is not int or value <= 0:
        raise ValueError("gpt6-astra-codex-native needs --max-policy-calls or a positive advertised service allowance")
    return value


def _check_compatibility(policy, benchmark, request):
    """Fail before preflight and before any output: the specs must suit the policy, and the
    service must offer exactly the requested number of episodes for this seed."""
    errors = list(policy.compatibility_errors(benchmark.observation_spec, benchmark.action_spec))
    if errors:
        raise CompatibilityError("; ".join(errors))
    # The service's fixed schedule, cut to --episodes; fewer means the schedule is too short.
    available = len(tuple(benchmark.episodes(request.seed, request.episode_limit)))
    if available != request.episode_limit:
        raise ProtocolError(
            f"benchmark offers {available} episodes for this seed, not --episodes {request.episode_limit}")


# Reading step 1 of 6 (start here): the command-line entry. Next: run() above.
def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        output = run(args)
    except PolicyPreflightError as exc:  # Codex CLI, login or boot check failed; no episode ran
        print(json.dumps({"status": "preflight_failed", "error_code": exc.code,
                          "native_attempts": 0, "model_requests": 0}))
        return 1
    summary = json.loads((output / "summary.json").read_text())  # written by the runner after the last episode
    print(json.dumps({"output": str(output), "attempted": summary["attempted"],
                      "completed": summary["completed"], "errors": summary["errors"],
                      "successes": summary["successes"]}))
    # Exit 0 only when every requested episode ran without an error; successes do not affect it.
    return 0 if summary["attempted"] == args.episodes and summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
