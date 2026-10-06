"""Frozen campaign workflow; resume unattempted cases, never rerun a claimed case.

The coordinator is evaluator-private. Give an actor only its opaque mailbox
endpoint, never this manifest or the result/source directories. A mailbox is
not an OS sandbox or a provider meter, and these campaigns are development runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchkit.artifacts import atomic_write_json, git_provenance
from benchkit.campaigns.benchmark_plans import FIRST_PASS_SEED, PLAN_MODULES, get_plan
from benchkit.source_snapshot import capture_harness_source, installed_source_root

BENCHMARKS = tuple(PLAN_MODULES)
CAMPAIGN_SCHEMA = "starvla-rsi.campaign/v3"


def runtime_namespace(manifest: dict[str, Any]) -> str:
    """Select the captured executable namespace, never an import alias.

    Unmarked v3 campaigns predate the benchkit rename. Their frozen harness
    bytes remain authoritative; newly prepared campaigns declare benchkit.
    """
    schema = manifest.get("schema_version")
    if schema == CAMPAIGN_SCHEMA:
        namespace = manifest.get("runtime_namespace", "harness")
        if namespace not in ("harness", "benchkit"):
            raise ValueError("unsupported campaign runtime namespace")
        return namespace
    if schema in ("starvla-rsi.campaign/v1", "starvla-rsi.campaign/v2"):
        if "runtime_namespace" in manifest:
            raise ValueError("legacy campaign cannot override runtime namespace")
        return "starVLA.evaluation"
    raise ValueError("unsupported campaign schema")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_case_budget(manifest: dict, case: dict) -> None:
    """Reject runner/adapter mismatches before creating a permanent claim."""
    mode = manifest.get("budget_mode")
    args = case["benchmark_args"]
    if mode not in ("horizon", "decisions") or args.get("budget_mode", "horizon") != mode:
        raise ValueError("campaign runner and benchmark budget_mode must match before claim")
    for name in ("max_policy_calls", "replan_interval"):
        if name in args and (type(args[name]) is not int or args[name] != manifest[name]):
            raise ValueError(f"campaign/benchmark budget differs before claim: {name}")
    if mode == "decisions" and manifest["max_steps"] != manifest["max_policy_calls"] * manifest["replan_interval"]:
        raise ValueError("campaign decision cap differs from decisions times prefix")
    if "min_action_decisions_before_give_up" in manifest:
        from AgentPolicies.policy_support.stop_rules import validate_minimum
        minimum = validate_minimum(manifest["min_action_decisions_before_give_up"])
        if minimum and minimum >= manifest["max_policy_calls"]:
            raise ValueError("campaign voluntary-stop floor must leave a decision for the stop response")


def cases_for(benchmark: str, decisions: int, prefix: int, *,
              task_scope: str | None = None) -> list[dict[str, Any]]:
    plan = get_plan(benchmark)
    if task_scope not in plan.TASK_SCOPES:
        raise ValueError("unsupported benchmark task_scope")
    if any(type(value) is not int or value <= 0 for value in (decisions, prefix)):
        raise ValueError("decision and executed-prefix limits must be positive integers")
    common = {"budget_mode": "decisions", "max_policy_calls": decisions, "replan_interval": prefix}
    cases = plan.cases(common, FIRST_PASS_SEED, task_scope, None)
    for index, case in enumerate(cases):
        case.update(index=index, case_id=f"case-{index:03d}", attempts=1)
    return cases


def prepare(output: Path, benchmark: str, mailbox_root: Path | None = None, prompt: str = "", *,
            decisions: int = 200, prefix: int = 5, response_timeout_s: int | float | None = None,
            task_timeout_s: int = 14400, task_scope: str | None = None,
            carry_forward_campaign: Path | None = None,
            model_profile: str | None = None,
            min_action_decisions_before_give_up: int | None = None) -> dict[str, Any]:
    if not isinstance(prompt, str) or len(prompt) > 32768:
        raise ValueError("a nonempty frozen policy prompt of at most 32768 characters is required")
    from AgentPolicies.policy_support.stop_rules import validate_minimum, with_stop_rule_prompt
    from benchkit.model_profiles import load_profile, validate_policy_parameters
    # New-layout campaigns always freeze a real profile, never an implicit mailbox.
    model_profile = model_profile or "anonymous_code_agent"
    profile = load_profile(model_profile)
    direct = profile["execution"] == "direct"
    if not prompt.strip() and (not direct or prompt):
        raise ValueError("a nonempty frozen policy prompt of at most 32768 characters is required")
    if direct:
        if mailbox_root is not None:
            raise ValueError("direct policy campaigns do not use a mailbox root")
        if carry_forward_campaign is not None:
            raise ValueError("direct policy campaigns require fresh coverage; mailbox carry-forward is unsupported")
    elif not isinstance(mailbox_root, Path) or not mailbox_root.is_absolute():
        raise ValueError("mailbox root must be absolute and independent of task, seed and date")
    if response_timeout_s is None:
        response_timeout_s = profile["config"].get("timeout_s", 900)
    if (type(task_timeout_s) is not int or task_timeout_s <= 0
            or type(response_timeout_s) not in ((int, float) if direct else (int,))
            or (type(response_timeout_s) is float and not math.isfinite(response_timeout_s))
            or response_timeout_s <= 0):
        raise ValueError("timeouts must be positive finite numbers")
    if min_action_decisions_before_give_up is None:
        min_action_decisions_before_give_up = profile["config"]["min_action_decisions_before_give_up"]
    validate_minimum(min_action_decisions_before_give_up)
    if direct:
        validate_policy_parameters(profile, {"timeout_s": response_timeout_s, "max_chunk_length": prefix,
            "min_action_decisions_before_give_up": min_action_decisions_before_give_up})
    prompt = profile["prompt"].rstrip() + "\n\n" + prompt if prompt else profile["prompt"]
    # A policy may intend to persist longer than the shared budget permits.
    # Native end/hard caps still terminate it; this is not a benchmark constraint.
    plan = get_plan(benchmark)
    cases = cases_for(benchmark, decisions, prefix, task_scope=task_scope)
    runner_budget_mode = getattr(plan, "BUDGET_MODE", "decisions")
    budget = {"budget_mode": runner_budget_mode, "max_policy_calls": decisions,
              "replan_interval": prefix, "max_steps": decisions * prefix}
    for case in cases:
        verify_case_budget(budget, case)
    coverage_scope = task_scope in ("target50", "released-12")
    if carry_forward_campaign is not None and not coverage_scope:
        raise ValueError("carry-forward requires an explicit coverage expansion task_scope")
    ledger = None
    if coverage_scope:
        from benchkit.reports.campaign_coverage import build_coverage
        cases, ledger = build_coverage(benchmark, task_scope, cases,
            cases_for(benchmark, decisions, prefix), carry_forward_campaign)
        if carry_forward_campaign is not None and output.resolve().is_relative_to(carry_forward_campaign.resolve()):
            raise ValueError("expansion output must be outside the original campaign")
    repository = installed_source_root().parent
    supplemental_paths = getattr(plan, "SUPPLEMENTAL_FILES", ())
    # Shared offline auditors are already captured under benchkit/ in layout/v2.
    for relative in supplemental_paths:
        source = repository / relative
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(repository.resolve()):
            raise ValueError(f"missing or unsafe evaluator runtime file: {relative}")
        if source.name == "POLICY_GUIDE.md":
            prompt += "\n\n" + source.read_text(encoding="utf-8")
    prompt = with_stop_rule_prompt(prompt, min_action_decisions_before_give_up)
    if len(prompt) > 32768:
        raise ValueError("combined policy prompt exceeds the mailbox limit")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    snapshot = capture_harness_source(output)
    # v3 snapshots already carry their repository-relative executable layout.
    shutil.copytree(output / "harness_source" / "files", output / "frozen")
    package = output / "frozen" / "benchkit"
    supplemental = []
    for relative in supplemental_paths:
        source, target = repository / relative, output / "frozen" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        supplemental.append({"path": relative, "size_bytes": target.stat().st_size, "sha256": digest(target)})
    if not direct:
        from AgentPolicies.anonymous_code_agent.mailbox import new_mailbox_directory
        for case in cases:
            case["policy_endpoint"] = str(new_mailbox_directory(mailbox_root))
    manifest = {
        "schema_version": CAMPAIGN_SCHEMA, "source_layout": "repository-relative/v2", "benchmark": benchmark,
        "evaluation_mode": "fast", "runtime_namespace": "benchkit",
        "purpose": "development_task_coverage" if coverage_scope else getattr(plan, "PURPOSE", "development_pilot"),
        "created_at": datetime.now(timezone.utc).isoformat(), "seed": FIRST_PASS_SEED,
        "attempts_per_task": 1, "planned_cases": len(cases), "cases": cases,
        "budget_mode": runner_budget_mode, "max_policy_calls": decisions, "replan_interval": prefix,
        "max_steps": decisions * prefix, "response_timeout_s": response_timeout_s,
        "task_timeout_s": task_timeout_s, "policy_prompt": prompt,
        "policy_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "policy": {"name": "code-agent-development", "kind": "external-code-agent", "model": None, "provider": None},
        "provider_accounting": "unknown; mailbox is not a verified provider meter",
        "actor_isolation": "fresh task context; opaque mailbox only; OS isolation not enforced by this tool",
        "harness_source": snapshot, "package_initializer_sha256": digest(package / "__init__.py"),
        "supplemental_runtime_files": supplemental,
        "runtime_environment": dict(getattr(plan, "RUNTIME_ENVIRONMENT", {})),
        "preparation_git": git_provenance(installed_source_root().parent),
        "execution_provenance": "copied package verified against snapshot; run Git metadata is not a substitute for source hashes",
    }
    if profile is not None:
        from benchkit.model_profiles import capture_model_source
        identity, model_source = capture_model_source(output, model_profile, prompt)
        if identity != profile["identity"]:
            raise ValueError("model profile changed during campaign preparation")
        manifest.update(model_profile=identity,
                        model_source=model_source, policy=profile["profile"]["policy"])
    from AgentPolicies.policy_support.stop_rules import stop_constraint
    manifest["policy_parameters"] = {"min_action_decisions_before_give_up": min_action_decisions_before_give_up}
    manifest["policy_stop_rule"] = stop_constraint(min_action_decisions_before_give_up)
    if direct:
        manifest.update(policy_execution="direct",
            provider_accounting="reported by selected policy; not independent provider metering attestation",
            actor_isolation="declared observations only; OS process isolation is not enforced by this tool")
    if ledger is not None:
        manifest.update(task_scope=task_scope, coverage_ledger=ledger,
            selected_total=len(ledger["entries"]), carried_attempts=ledger["carried_attempts"],
            planned_new_cases=len(cases),
            coverage_reporting="coordinator counts executable cases only; full-ledger score aggregation is not implemented")
    elif task_scope is not None:
        manifest["task_scope"] = task_scope
    atomic_write_json(output / "campaign.json", manifest, overwrite=False)
    atomic_write_json(output / "campaign_digest.json", {"sha256": digest(output / "campaign.json")}, overwrite=False)
    return manifest


def terminate_child(process: subprocess.Popen) -> None:
    """Close only this coordinator's newly created process group."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def load_campaign(output: Path) -> dict[str, Any]:
    output = _campaign_root(output)
    manifest_path = _campaign_path(output, "campaign.json")
    expected = json.loads(_campaign_path(output, "campaign_digest.json").read_text())["sha256"]
    if digest(manifest_path) != expected:
        raise ValueError("campaign manifest changed after preparation")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") not in ("starvla-rsi.campaign/v1", "starvla-rsi.campaign/v2", CAMPAIGN_SCHEMA):
        raise ValueError("unsupported campaign schema")
    runtime_namespace(manifest)
    return manifest


def _campaign_root(output: Path) -> Path:
    # Preserve caller-location aliases outside the campaign (e.g. macOS /var),
    # but do not resolve away a replacement of the campaign root itself.
    output = Path(output).absolute()
    if output.is_symlink() or not output.is_dir():
        raise ValueError("campaign root must be a real directory, not a symlink")
    return output.resolve()


def _campaign_path(output: Path, relative: str, *, directory: bool = False) -> Path:
    """Reject symlinks in every campaign-owned ancestor before reading a file."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe campaign source path")
    target = output
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError(f"symlink in campaign source path: {relative}")
    if not (target.is_dir() if directory else target.is_file()):
        raise ValueError(f"missing or invalid campaign source path: {relative}")
    return target


def verify_frozen_package(output: Path, manifest: dict[str, Any]) -> None:
    runtime_namespace(manifest)
    if manifest.get("schema_version") == CAMPAIGN_SCHEMA:
        return verify_repository_package(output, manifest)
    if manifest.get("source_layout") is not None or "policy_execution" in manifest:
        raise ValueError("repository-relative source requires campaign/v3; legacy profiles require campaign/v2")
    output = _campaign_root(output)
    index_path = _campaign_path(output, "harness_source/index.json")
    frozen = _campaign_path(output, "frozen", directory=True)
    package = _campaign_path(output, "frozen/starVLA", directory=True)
    evaluation = _campaign_path(output, "frozen/starVLA/evaluation", directory=True)
    initializer = _campaign_path(output, "frozen/starVLA/__init__.py")
    if digest(index_path) != manifest["harness_source"]["index_sha256"]:
        raise ValueError("source snapshot index changed")
    if digest(initializer) != manifest["package_initializer_sha256"]:
        raise ValueError("frozen package initializer changed")
    rows = json.loads(index_path.read_text())["files"]
    expected = {row["path"] for row in rows}
    actual = {path.relative_to(evaluation).as_posix()
              for path in evaluation.rglob("*") if path.is_file() and path.suffix in (".py", ".json")}
    if actual != expected or any(path.is_symlink() for path in package.rglob("*")):
        raise ValueError("frozen source inventory changed or contains symlinks")
    for row in rows:
        path = _campaign_path(output, "frozen/starVLA/evaluation/" + row["path"])
        if path.stat().st_size != row["size_bytes"] or digest(path) != row["sha256"]:
            raise ValueError(f"frozen source changed: {row['path']}")
    supplemental = manifest.get("supplemental_runtime_files", [])
    expected_extra = {row["path"] for row in supplemental}
    actual_extra = {path.relative_to(frozen).as_posix()
                    for path in frozen.rglob("*")
                    if path.is_file() and not path.is_relative_to(package)}
    if actual_extra != expected_extra or any(path.is_symlink() for path in frozen.rglob("*")):
        raise ValueError("frozen supplemental runtime inventory changed or contains symlinks")
    for row in supplemental:
        path = _campaign_path(output, "frozen/" + row["path"])
        if path.stat().st_size != row["size_bytes"] or digest(path) != row["sha256"]:
            raise ValueError(f"frozen supplemental runtime changed: {row['path']}")
    has_model_siblings = any(path.name not in ("evaluation", "__init__.py", "__pycache__") for path in package.iterdir())
    if (manifest.get("schema_version") == "starvla-rsi.campaign/v2" or (output / "model_source").exists()
            or has_model_siblings
            or any(key in manifest for key in ("model_profile", "model_source", "min_action_decisions_before_give_up",
                                              "stop_constraint_version", "early_policy_stop_exception"))):
        if manifest.get("schema_version") != "starvla-rsi.campaign/v2":
            raise ValueError("model profile/source/stop extensions require campaign/v2")
        from benchkit.model_profiles import verify_model_source
        from AgentPolicies.policy_support.stop_rules import legacy_stop_constraint as stop_constraint, legacy_stop_constraint_prompt as stop_constraint_prompt, validate_minimum
        verify_model_source(output, manifest)
        minimum = validate_minimum(manifest.get("min_action_decisions_before_give_up", 0))
        expected_constraint = stop_constraint(minimum)
        actual_constraint = {key: manifest[key] for key in (
            "min_action_decisions_before_give_up", "stop_constraint_version", "early_policy_stop_exception")
            if key in manifest}
        if (actual_constraint != expected_constraint
                or (minimum and not manifest["policy_prompt"].endswith(stop_constraint_prompt(minimum)))):
            raise ValueError("campaign voluntary-stop constraint changed")


def verify_repository_package(output: Path, manifest: dict[str, Any]) -> None:
    """Verify v3 source and model inventories independently before any claim."""
    from benchkit.model_profiles import verify_model_source, validate_policy_parameters
    from benchkit.source_snapshot import inventory_digest
    from AgentPolicies.policy_support.stop_rules import stop_constraint, with_stop_rule_prompt, validate_minimum

    output = _campaign_root(output)
    namespace = runtime_namespace(manifest)
    if manifest.get("source_layout") != "repository-relative/v2" or manifest.get("evaluation_mode") != "fast":
        raise ValueError("unsupported campaign source layout or evaluation mode")
    index_path = _campaign_path(output, "harness_source/index.json")
    reference = manifest["harness_source"]
    if digest(index_path) != reference["index_sha256"]:
        raise ValueError("source snapshot index changed")
    index = json.loads(index_path.read_text())
    rows = index["files"]
    if (index.get("schema_version") != "starvla-rsi.harness-source/v2"
            or index.get("package") != namespace
            or f"{namespace}/__init__.py" not in {row["path"] for row in rows}
            or len({row["path"] for row in rows}) != len(rows)
            or index["inventory_sha256"] != inventory_digest(rows)
            or reference["inventory_sha256"] != index["inventory_sha256"]):
        raise ValueError("repository source inventory metadata changed")
    for key, value in (("file_count", len(rows)), ("total_bytes", sum(row["size_bytes"] for row in rows))):
        if (type(index.get(key)) is not int or type(reference.get(key)) is not int
                or index[key] != value or reference[key] != value):
            raise ValueError("repository source inventory counters changed")
    copied = _campaign_path(output, "harness_source/files", directory=True)
    copied_files = set()
    for path in copied.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlink in copied source inventory")
        if path.is_file():
            copied_files.add(path.relative_to(copied).as_posix())
        elif not path.is_dir():
            raise ValueError("non-regular copied source inventory entry")
    if copied_files != {row["path"] for row in rows}:
        raise ValueError("copied source inventory changed")
    for row in rows:
        for prefix in ("harness_source/files/", "frozen/"):
            path = _campaign_path(output, prefix + row["path"])
            if path.stat().st_size != row["size_bytes"] or digest(path) != row["sha256"]:
                raise ValueError(f"frozen source changed: {row['path']}")
    if digest(_campaign_path(output, f"frozen/{namespace}/__init__.py")) != manifest["package_initializer_sha256"]:
        raise ValueError("frozen package initializer changed")
    expected = {row["path"] for row in rows}
    for row in manifest.get("supplemental_runtime_files", []):
        if row["path"] in expected:
            raise ValueError("supplemental source overlaps harness source")
        path = _campaign_path(output, "frozen/" + row["path"])
        if path.stat().st_size != row["size_bytes"] or digest(path) != row["sha256"]:
            raise ValueError(f"frozen supplemental runtime changed: {row['path']}")
        expected.add(row["path"])
    profile = verify_model_source(output, manifest)
    execution = manifest.get("policy_execution", "mailbox")
    if execution not in ("mailbox", "direct") or execution != profile["execution"]:
        raise ValueError("campaign policy execution differs from captured profile")
    if execution == "direct":
        if any("policy_endpoint" in case for case in manifest["cases"]):
            raise ValueError("direct policy campaign must not declare mailbox endpoints")
    elif any(not isinstance(case.get("policy_endpoint"), str)
             or not Path(case["policy_endpoint"]).is_absolute() for case in manifest["cases"]):
        raise ValueError("mailbox campaign requires absolute policy endpoints")
    model_index = json.loads(_campaign_path(output, "model_source/index.json").read_text())
    expected.update(row["path"] for row in model_index["files"] if row["path"] != "campaign_prompt.txt")
    frozen = _campaign_path(output, "frozen", directory=True)
    actual = set()
    directories = set()
    for path in frozen.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlink in frozen source inventory")
        if path.is_file():
            actual.add(path.relative_to(frozen).as_posix())
        elif path.is_dir():
            directories.add(path.relative_to(frozen).as_posix())
        else:
            raise ValueError("non-regular frozen source")
    if actual != expected:
        raise ValueError("frozen supplemental runtime inventory changed")
    expected_dirs = {parent.as_posix() for relative in expected for parent in Path(relative).parents
                     if parent != Path(".")}
    if directories != expected_dirs:
        raise ValueError("unexpected directory in frozen source inventory")
    minimum = validate_minimum(manifest.get("policy_parameters", {}).get("min_action_decisions_before_give_up"))
    if (manifest.get("policy_parameters") != {"min_action_decisions_before_give_up": minimum}
            or manifest.get("policy_stop_rule") != stop_constraint(minimum)
            or manifest["policy_prompt"] != with_stop_rule_prompt(manifest["policy_prompt"], minimum)
            or any(key in manifest for key in ("min_action_decisions_before_give_up", "stop_constraint_version",
                                               "early_policy_stop_exception"))):
        raise ValueError("campaign policy stopping rule changed")
    if execution == "direct":
        validate_policy_parameters(profile, {"timeout_s": manifest["response_timeout_s"],
            "max_chunk_length": manifest["replan_interval"],
            "min_action_decisions_before_give_up": minimum})
def verify_tabletop_next_pair(manifest: dict) -> None:
    """Compatibility entrypoint; benchmark-owned validation lives with its plan."""
    return get_plan("robocasa_tabletop").verify_next_pair(manifest)

def _preflight_case_policy(output: Path, manifest: dict, policy_args: dict, env: dict) -> bool:
    """Run only a captured, declared local-readiness hook before the claim.

    Historical packages without the declaration keep their frozen behavior.
    Outputs are discarded, not copied into result logs: even a dependency's
    import/constructor error may contain credentials. This is not a sandbox.
    """
    if manifest.get("schema_version") != CAMPAIGN_SCHEMA or "model_profile" not in manifest:
        return False
    from benchkit.model_profiles import verify_model_source

    profile_id = manifest["model_profile"]["id"]
    # Read the captured schema/layout as verified data; the current live profile
    # loader may use a newer directory organization than this frozen campaign.
    profile = verify_model_source(output, manifest)
    if not profile.get("runtime_preflight"):
        return False
    command = [sys.executable, "-B", "-m", runtime_namespace(manifest), "preflight-policy",
               "--model-profile", profile_id, "--policy-args", json.dumps(policy_args)]
    failed = False
    try:
        with subprocess.Popen(command, cwd=output / "frozen", env=env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True) as process:
            try:
                failed = process.wait(timeout=60) != 0
            except BaseException:
                terminate_child(process)
                raise
    except (OSError, subprocess.SubprocessError):
        failed = True
    if failed:
        raise RuntimeError("Policy runtime preflight failed; case remains unattempted. "
                           "Use the captured runtime's preflight-policy command for local diagnostics.") from None
    return True


def run_case(output: Path, case_index: int, device_index: int) -> dict[str, Any]:
    output = _campaign_root(output)
    manifest = load_campaign(output)
    if type(case_index) is not int or not 0 <= case_index < manifest["planned_cases"]:
        raise ValueError("case index is outside the frozen campaign")
    if type(device_index) is not int or device_index < 0:
        raise ValueError("device index must be a nonnegative integer")
    verify_case_budget(manifest, manifest["cases"][case_index])
    verify_frozen_package(output, manifest)
    plan = get_plan(manifest["benchmark"])
    selection_verified = getattr(plan, "verify_selection", lambda _: False)(manifest)
    if (not selection_verified and (any(key in manifest for key in ("task_scope", "coverage_ledger", "selected_total",
                                       "carried_attempts", "planned_new_cases", "coverage_reporting"))
            or (manifest["benchmark"] in ("robocasa365", "simple_humanoid")
                and manifest.get("purpose") == "development_task_coverage")
            or any(case["benchmark_args"].get("task_scope") in ("target50", "released-12")
                   for case in manifest["cases"]))):
        if (manifest.get("task_scope") not in ("target50", "released-12")
                or not isinstance(manifest.get("coverage_ledger"), dict)):
            raise ValueError("expansion markers require an explicit task scope and coverage ledger")
        from benchkit.reports.campaign_coverage import verify_coverage
        verify_coverage(output, manifest)
    case = manifest["cases"][case_index]
    directory = output / case["case_id"]
    if directory.exists() or directory.is_symlink():
        raise FileExistsError("case has already been claimed")
    args = dict(case["benchmark_args"])
    plan = get_plan(manifest["benchmark"])
    device_key = getattr(plan, "DEVICE_KEY", "render_gpu_device_id")
    args[device_key] = f"cuda:{device_index}" if getattr(plan, "DEVICE_CUDA_STRING", False) else device_index
    direct = manifest.get("policy_execution") == "direct"
    policy_args = {"prompt": manifest["policy_prompt"], "timeout_s": manifest["response_timeout_s"],
                   "max_chunk_length": manifest["replan_interval"]}
    policy_selection = ["--policy", "mailbox"]
    if not direct:
        policy_args["directory"] = case["policy_endpoint"]
    if "model_profile" in manifest:
        policy_selection = ["--model-profile", manifest["model_profile"]["id"]]
    else:
        policy_args.update(manifest["policy"])
    if manifest.get("schema_version") == CAMPAIGN_SCHEMA:
        policy_args.update(manifest["policy_parameters"])
    entrypoint = runtime_namespace(manifest)
    command = [sys.executable, "-m", entrypoint, "run", "--benchmark", manifest["benchmark"],
               "--benchmark-args", json.dumps(args), *policy_selection, "--policy-args", json.dumps(policy_args),
               "--seed", str(manifest["seed"]), "--episodes", "1", "--budget-mode", manifest["budget_mode"],
               "--max-policy-calls", str(manifest["max_policy_calls"]), "--replan-interval", str(manifest["replan_interval"]),
               "--max-steps", str(manifest["max_steps"]), "--output-dir", str(directory), "--run-id", "run"]
    if manifest.get("min_action_decisions_before_give_up", 0):
        command += ["--min-action-decisions-before-give-up", str(manifest["min_action_decisions_before_give_up"])]
    env = {**os.environ, **manifest.get("runtime_environment", {}), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(output / "frozen") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    campaign_sha256 = digest(output / "campaign.json")
    if _preflight_case_policy(output, manifest, policy_args, env):
        if load_campaign(output) != manifest or digest(output / "campaign.json") != campaign_sha256:
            raise ValueError("campaign changed during policy runtime preflight")
        verify_frozen_package(output, manifest)
    # This mkdir, not preflight, atomically claims the only allowed attempt.
    # Concurrent successful checks can race here; only one may launch a case.
    directory.mkdir(exist_ok=False)
    atomic_write_json(directory / "attempt.json", {"case_index": case_index, "attempt": 1,
        "started_at": datetime.now(timezone.utc).isoformat(), "device_index": device_index,
        "campaign_sha256": campaign_sha256}, overwrite=False)
    atomic_write_json(directory / "command.json", command, overwrite=False)
    if not direct:
        atomic_write_json(directory / "policy_endpoint.json", {"directory": case["policy_endpoint"]}, overwrite=False)
    result: dict[str, Any] = {"case_index": case_index, "status": "infrastructure_or_policy_error",
                              "returncode": None, "timed_out": False, "summary": None}
    if not direct:
        print(f"policy endpoint: {case['policy_endpoint']}", flush=True)
    try:
        with (directory / "console.log").open("x") as log:
            with subprocess.Popen(command, cwd=output / "frozen", env=env,
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as process:
                try:
                    result["returncode"] = process.wait(timeout=manifest["task_timeout_s"])
                except subprocess.TimeoutExpired:
                    result["timed_out"] = True
                    terminate_child(process)
                    result["returncode"] = process.returncode
                except BaseException:
                    terminate_child(process)
                    raise
        summary = directory / "run" / "summary.json"
        if summary.is_file():
            result["summary"] = json.loads(summary.read_text())
        if (result["returncode"] == 0 and result["summary"] is not None
                and result["summary"].get("errors") == 0 and not result["timed_out"]):
            result["status"] = "completed"
    except BaseException as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        atomic_write_json(directory / "outcome.json", result, overwrite=False)
    return result


def summarize(output: Path) -> dict[str, Any]:
    manifest = load_campaign(output)
    outcomes = []
    for case in manifest["cases"]:
        directory = output / case["case_id"]
        path = directory / "outcome.json"
        outcome = json.loads(path.read_text()) if path.is_file() else {
            "status": "claimed_without_terminal_outcome" if directory.exists() else "unattempted"}
        outcomes.append({"case_index": case["index"], "task": case["episode"]["task"], **outcome})
    # Count every declared lifecycle state, including errors, without interpreting
    # it as a native score or reading active episode contents. The offline
    # coverage reporter performs the stronger closed-evidence validation.
    counts = {status: sum(x["status"] == status for x in outcomes) for status in (
        "unattempted", "claimed_without_terminal_outcome", "completed", "infrastructure_or_policy_error")}
    report = {"planned": len(outcomes), **counts,
              "other_status": len(outcomes) - sum(counts.values()), "outcomes": outcomes}
    if "coverage_ledger" in manifest:
        report.update(selected_total=manifest["selected_total"], carried_attempts=manifest["carried_attempts"],
                      planned_new_cases=manifest["planned_new_cases"], coverage_reporting=manifest["coverage_reporting"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare")
    create.add_argument("--benchmark", choices=BENCHMARKS, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--mailbox-root", type=Path, help="required for mailbox profiles; omitted for direct policies")
    create.add_argument("--prompt-file", type=Path,
                        help="required mailbox prompt; optional direct-profile supplemental prompt")
    create.add_argument("--response-timeout", type=int, default=None, dest="response_timeout_s",
                        help="response timeout in seconds; omitted inherits profile config or 900")
    create.add_argument("--max-policy-calls", type=int, default=200)
    create.add_argument("--replan-interval", type=int, default=5)
    create.add_argument("--task-scope", choices=("target50", "released-12", "tabletop-next-pair-v1"))
    create.add_argument("--carry-forward-campaign", type=Path)
    create.add_argument("--model-profile", help="configured model profile; defaults to explicit anonymous_code_agent")
    create.add_argument("--policy-min-action-decisions-before-give-up", type=int, default=None,
                        dest="min_action_decisions_before_give_up",
                        help="model policy override; omitted inherits profile config; zero explicitly disables")
    run = sub.add_parser("run-case")
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--case-index", type=int, required=True)
    run.add_argument("--device-index", type=int, required=True)
    report = sub.add_parser("summarize")
    report.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        manifest = prepare(args.output_dir, args.benchmark, args.mailbox_root,
                           args.prompt_file.read_text() if args.prompt_file is not None else "",
                           decisions=args.max_policy_calls, prefix=args.replan_interval,
                           response_timeout_s=args.response_timeout_s,
                           task_scope=args.task_scope, carry_forward_campaign=args.carry_forward_campaign,
                           model_profile=args.model_profile,
                           min_action_decisions_before_give_up=args.min_action_decisions_before_give_up)
        result = {"output_dir": str(args.output_dir.resolve()), "planned_cases": manifest["planned_cases"]}
        if "coverage_ledger" in manifest:
            result.update({key: manifest[key] for key in (
                "selected_total", "carried_attempts", "planned_new_cases", "coverage_reporting")})
    elif args.command == "run-case":
        result = run_case(args.output_dir, args.case_index, args.device_index)
    else:
        result = summarize(args.output_dir.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(args.command == "run-case" and result["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
