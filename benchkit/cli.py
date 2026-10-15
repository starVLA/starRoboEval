"""Command-line entry point for catalog inspection and evaluation runs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from benchkit.catalog import load_catalog, validate_repository_catalog
from benchkit.registry import create_benchmark, create_policy, registered
from AgentPolicies.gpt6_astra.tools.runner import EvaluationRunner, RunRequest


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return parsed


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser without importing simulator dependencies."""
    parser = argparse.ArgumentParser(prog="starvla-eval", description="StarVLA-RSI embodied-agent evaluation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog_parser = subparsers.add_parser("catalog", help="list benchmark integration targets and status")
    catalog_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    catalog_parser.add_argument("--check", action="store_true", help="validate directories and protocol files")

    list_parser = subparsers.add_parser("list", help="list runnable adapters installed in this environment")
    list_parser.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser(
        "preflight-policy", help="check model-owned local runtime readiness without inference or a benchmark")
    preflight_parser.add_argument("--model-profile", required=True)
    preflight_parser.add_argument("--policy-args", type=_json_object, default={})

    run_parser = subparsers.add_parser("run", help="run one benchmark-policy evaluation cell")
    run_parser.add_argument("--benchmark", required=True)
    policy_selection = run_parser.add_mutually_exclusive_group(required=True)
    policy_selection.add_argument("--policy")
    policy_selection.add_argument("--model-profile", help="select a frozen model-folder policy profile")
    run_parser.add_argument("--benchmark-args", type=_json_object, default={})
    run_parser.add_argument("--sim-server", help="evaluator-only http://127.0.0.1:port SIM endpoint")
    run_parser.add_argument("--sim-server-token-env", default="RSI_SIM_SERVER_TOKEN")
    run_parser.add_argument("--sim-server-timeout", type=float, default=1200.0)
    run_parser.add_argument("--policy-args", type=_json_object, default={})
    run_parser.add_argument("--output-dir", type=Path,
                            help="defaults to the selected model's results/<benchmark>/raw directory")
    run_parser.add_argument("--seed", type=int, default=0)
    run_parser.add_argument("--episodes", type=int)
    run_parser.add_argument("--max-steps", type=int, default=500)
    run_parser.add_argument("--max-policy-calls", type=int)
    run_parser.add_argument("--replan-interval", type=int)
    run_parser.add_argument("--budget-mode", choices=("horizon", "decisions"), default="horizon")
    run_parser.add_argument(
        "--policy-min-action-decisions-before-give-up", type=int,
        help="opt-in persistence preference of the selected policy, not a benchmark budget",
    )
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--fail-fast", action="store_true")

    smoke_parser = subparsers.add_parser("smoke", help="run the dependency-free end-to-end self-check")
    smoke_parser.add_argument("--output-dir", type=Path, default=Path("results/rsi-smoke"))
    smoke_parser.add_argument("--episodes", type=int, default=3)
    smoke_parser.add_argument("--seed", type=int, default=0)
    return parser


def _print_catalog(as_json: bool) -> None:
    entries = load_catalog()
    if as_json:
        print(json.dumps([entry.__dict__ | {"tags": list(entry.tags)} for entry in entries], indent=2))
        return
    print(f"{'ID':<20} {'STATUS':<18} {'PRIORITY':<10} NAME")
    for entry in entries:
        print(f"{entry.id:<20} {entry.migration_status:<18} {entry.priority:<10} {entry.display_name}")


def _run(args: argparse.Namespace) -> Path:
    profile = getattr(args, "model_profile", None)
    if profile is None and str(getattr(args, "policy", "")).strip().lower() == "mailbox":
        # Compatibility spelling, not a provenance bypass: the executable
        # anonymous policy still gets its own exact model-source bundle.
        profile = "anonymous_code_agent"
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = (_repository_root() / "AgentPolicies" / profile / "results" / args.benchmark / "raw"
                      if profile else Path("results/rsi"))
    request = RunRequest(
        output_dir=output_dir,
        seed=args.seed,
        episode_limit=args.episodes,
        max_steps=args.max_steps,
        max_policy_calls=args.max_policy_calls,
        replan_interval=args.replan_interval,
        run_id=args.run_id,
        fail_fast=args.fail_fast,
        repository=_repository_root(),
        budget_mode=args.budget_mode,
    )
    policy_args = dict(args.policy_args)
    minimum = getattr(args, "policy_min_action_decisions_before_give_up", None)
    if minimum is not None:
        key = "min_action_decisions_before_give_up"
        if key in policy_args:
            raise ValueError("policy persistence rule must be set once: use the flag or --policy-args")
        policy_args[key] = minimum
    if profile:
        from benchkit.model_profiles import create_policy as create_profile_policy, load_profile, preflight_profile

        if load_profile(profile).get("runtime_preflight"):
            policy = preflight_profile(profile, **policy_args)
        else:
            policy = create_profile_policy(profile, **policy_args)
    else:
        policy = create_policy(args.policy, policy_args)
    if getattr(args, "sim_server", None):
        from benchkit.sim_server.client import SimServerBenchmarkAdapter

        if args.benchmark_args:
            raise ValueError("server owns benchmark parameters; --benchmark-args must be omitted")
        benchmark = SimServerBenchmarkAdapter(args.sim_server,
            token=os.environ.get(args.sim_server_token_env, ""), timeout=args.sim_server_timeout)
        if benchmark.descriptor.name != args.benchmark:
            raise ValueError("--benchmark must equal the connected server's descriptor.name")
    else:
        benchmark = create_benchmark(args.benchmark, args.benchmark_args)
    return EvaluationRunner().run(benchmark, policy, request)


def _preflight(args: argparse.Namespace) -> int:
    """A model-only command: no run directory, benchmark import or request."""
    from benchkit.errors import PolicyPreflightError
    from benchkit.model_profiles import preflight_profile

    code = None
    try:
        preflight_profile(args.model_profile, **args.policy_args)
    except PolicyPreflightError as exc:
        code = exc.code if exc.code in PolicyPreflightError.CODES else "initialization_failed"
    except Exception:
        code = "initialization_failed"
    print(json.dumps({"status": "failed" if code else "passed", "scope": "local_runtime_only",
                      "error_code": code}))
    return 1 if code else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one CLI command and return a process status code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight-policy":
            return _preflight(args)
        if args.command == "catalog":
            _print_catalog(args.json)
            if args.check:
                errors = validate_repository_catalog(_repository_root())
                if errors:
                    for error in errors:
                        print(f"ERROR: {error}", file=sys.stderr)
                    return 1
                print("catalog layout: OK", file=sys.stderr)
            return 0
        if args.command == "list":
            entries = registered()
            if args.json:
                print(json.dumps(entries, indent=2, sort_keys=True))
            else:
                for kind, names in entries.items():
                    print(f"{kind}: {', '.join(names) or '(none)'}")
            return 0
        if args.command == "smoke":
            args.benchmark = "smoke"
            args.policy = "scripted"
            args.benchmark_args = {}
            args.policy_args = {}
            args.max_steps = 10
            args.max_policy_calls = 10
            args.replan_interval = 1
            args.budget_mode = "horizon"
            args.run_id = None
            args.fail_fast = True
            run_dir = _run(args)
        elif args.command == "run":
            run_dir = _run(args)
        else:
            parser.error(f"unsupported command: {args.command}")
            return 2
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return 1 if summary["errors"] else 0
