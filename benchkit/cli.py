"""Command-line entry point for catalog inspection and evaluation runs."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import secrets
import select
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator, Sequence

from benchkit.catalog import load_catalog, validate_repository_catalog
from benchkit.errors import InfrastructureError
from benchkit.registry import create_policy, policy_names
from AgentPolicies.gpt6_astra.tools.runner import EvaluationRunner, RunRequest

SMOKE_BENCHMARK = "smoke-reach"  # descriptor.name of the synthetic service


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

    list_parser = subparsers.add_parser(
        "list", help="list the diagnostic policies for run --policy; rsi-bench list shows benchmark services")
    list_parser.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser(
        "preflight-policy", help="check model-owned local runtime readiness without inference or a benchmark")
    preflight_parser.add_argument("--model-profile", required=True)
    preflight_parser.add_argument("--policy-args", type=_json_object, default={})

    run_parser = subparsers.add_parser(
        "run", help="run one diagnostic policy against a running benchmark service (rsi-bench serve)")
    run_parser.add_argument("--sim-server", required=True, help="evaluator-only http://127.0.0.1:port SIM endpoint")
    run_parser.add_argument("--benchmark", required=True, help="must equal the service's descriptor.name")
    run_parser.add_argument("--policy", required=True, help="diagnostic policy name; see list")
    run_parser.add_argument("--sim-server-token-env", default="RSI_SIM_SERVER_TOKEN")
    run_parser.add_argument("--sim-server-timeout", type=float, default=1200.0)
    run_parser.add_argument("--policy-args", type=_json_object, default={})
    run_parser.add_argument("--output-dir", type=Path, default=Path("results/rsi"))
    run_parser.add_argument("--seed", type=int, default=0)
    run_parser.add_argument("--episodes", type=int)
    run_parser.add_argument("--max-steps", type=int, default=500)
    run_parser.add_argument("--max-policy-calls", type=int)
    run_parser.add_argument("--replan-interval", type=int)
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--fail-fast", action="store_true")

    probe_parser = subparsers.add_parser(
        "probe", help="connect-level readiness: describe, claim one episode, reset and close; no policy or step")
    probe_parser.add_argument("--sim-server", required=True, help="evaluator-only http://127.0.0.1:port SIM endpoint")
    probe_parser.add_argument("--benchmark", required=True, help="must equal the service's descriptor.name")
    probe_parser.add_argument("--sim-server-token-env", default="RSI_SIM_SERVER_TOKEN")
    probe_parser.add_argument("--sim-server-timeout", type=float, default=1200.0)
    probe_parser.add_argument("--episode-id", help="default: the first served episode; the claim is permanent")
    probe_parser.add_argument("--output-dir", type=Path, default=Path("results/rsi-probe"))
    probe_parser.add_argument("--expect-source-sha256", help="pin for the describe source; omitted means unpinned")

    smoke_parser = subparsers.add_parser(
        "smoke", help="serve the synthetic world locally and run the dependency-free self-check through it")
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


def _run(args: argparse.Namespace, endpoint: str, token: str) -> Path:
    """Connect to the benchmark service, then run the selected policy through the runner."""
    from benchkit.sim_server.client import SimServerBenchmarkAdapter

    request = RunRequest(
        output_dir=args.output_dir,
        seed=args.seed,
        episode_limit=args.episodes,
        max_steps=args.max_steps,
        max_policy_calls=args.max_policy_calls,
        replan_interval=args.replan_interval,
        run_id=args.run_id,
        fail_fast=args.fail_fast,
        repository=_repository_root(),
    )
    policy = create_policy(args.policy, dict(args.policy_args))
    benchmark = SimServerBenchmarkAdapter(endpoint, token=token, timeout=args.sim_server_timeout)
    if benchmark.descriptor.name != args.benchmark:
        raise ValueError("--benchmark must equal the connected server's descriptor.name")
    return EvaluationRunner().run(benchmark, policy, request)


@contextmanager
def _smoke_service(output_dir: Path, seed: int, episodes: int) -> Iterator[tuple[str, str]]:
    """Start the synthetic service (python -m benchkit.sim_server) on an ephemeral
    loopback port and yield its endpoint and token; stop it with SIGTERM afterwards."""
    token = secrets.token_urlsafe(32)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = output_dir.absolute() / f"service-{stamp}-{secrets.token_hex(3)}"  # server/ and server.log
    root.mkdir(parents=True)
    paths = [str(_repository_root()), *filter(None, [os.environ.get("PYTHONPATH")])]
    env = {**os.environ, "RSI_SIM_SERVER_TOKEN": token, "PYTHONPATH": os.pathsep.join(paths)}
    command = [sys.executable, "-B", "-m", "benchkit.sim_server", "--seed", str(seed),
               "--episodes", str(episodes), "--output-dir", str(root / "server"), "--port", "0"]
    with (root / "server.log").open("x") as log:
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=log)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 60.0)
        try:  # the service prints one "listening" line once it accepts requests
            status = json.loads(process.stdout.readline()) if ready else {}
            endpoint = status["endpoint"] if status.get("status") == "listening" else None
        except (ValueError, AttributeError, KeyError):
            endpoint = None
        if not isinstance(endpoint, str):
            raise InfrastructureError(f"smoke service did not start; see {root / 'server.log'}")
        yield endpoint, token
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        try:
            code = process.wait(timeout=30.0)
        except subprocess.TimeoutExpired:
            process.kill()
            code = process.wait()
        process.stdout.close()
    if code != 0:
        raise InfrastructureError(f"smoke service did not stop cleanly; see {root / 'server.log'}")


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
        if args.command == "probe":
            from benchkit.diagnostics.probe import probe
            summary = probe(args.sim_server, os.environ.get(args.sim_server_token_env, ""), args.benchmark,
                            output_dir=args.output_dir, timeout=args.sim_server_timeout,
                            episode_id=args.episode_id, expect_source_sha256=args.expect_source_sha256)
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0 if summary["status"] == "passed" else 1
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
            if args.json:
                print(json.dumps({"policies": policy_names()}, indent=2))
            else:
                print(f"policies: {', '.join(policy_names())}")
                print("benchmarks run as services: see rsi-bench list and starvla-eval catalog")
            return 0
        if args.command == "smoke":
            args.benchmark = SMOKE_BENCHMARK
            args.policy = "scripted"
            args.policy_args = {}
            args.sim_server_timeout = 60.0
            args.max_steps = 10
            args.max_policy_calls = 10
            args.replan_interval = 1
            args.run_id = None
            args.fail_fast = True
            with _smoke_service(args.output_dir, args.seed, args.episodes) as (endpoint, token):
                run_dir = _run(args, endpoint, token)
        elif args.command == "run":
            run_dir = _run(args, args.sim_server, os.environ.get(args.sim_server_token_env, ""))
        else:
            parser.error(f"unsupported command: {args.command}")
            return 2
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return 1 if summary["errors"] else 0
