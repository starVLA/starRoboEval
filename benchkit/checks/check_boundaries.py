"""Static ownership/import checks; no simulator, policy calls or runtime attestation.

This checks active Python source, not frozen campaigns, result documents, native
dependencies or arbitrary dynamic imports. It is a regression guard, not a sandbox.
"""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path


BENCHMARKS = ("SimplerEnv", "LIBERO", "SIMPLE", "Robocasa_365", "Robocasa_tabletop")
MIGRATED_BENCHMARKS = frozenset(BENCHMARKS)
# Standalone SIM services need not pretend to implement frozen campaigns.
SERVER_ONLY_BENCHMARKS = ("RoboDojo", "MetaWorld", "LIBERO-plus", "Robotwin", "VLA-Arena", "calvin")
NESTED_ADAPTERS = MIGRATED_BENCHMARKS | frozenset(SERVER_ONLY_BENCHMARKS)
HEAVY_NATIVE_ROOTS = frozenset({
    "torch", "tensorflow", "jax", "mujoco", "mujoco_py", "robosuite", "robocasa",
    "libero", "simpler_env", "sapien", "mani_skill2", "mani_skill", "isaacsim",
    "isaacgym", "omni", "pxr", "habitat", "habitat_sim", "pybullet", "metaworld", "mplib", "curobo",
    "calvin_env", "vla_arena",
})
# These assemble/validate declared extensions or read supported historical bundles.
# They may import extensions, but their presence here is not a task-semantics audit.
ASSEMBLY_MODULES = frozenset({
    "benchkit/registry.py", "benchkit/campaigns/benchmark_plans.py", "benchkit/campaigns/workflow.py",
    "benchkit/reports/campaign_coverage.py", "benchkit/model_profiles.py",
})
SKIP = frozenset({"__pycache__", "checks", "artifact_checks", "artifacts", "results", "legacy", "rollouts", "_local"})
# Explicit trusted model-owned experiment entrypoint.
# Policy/actor modules still cannot import the administrative service client.
MODEL_DRIVERS = frozenset({"AgentPolicies/gpt6_astra/run.py"})


def _sources(directory: Path):
    # Prune output trees before traversal, not after enumerating frozen rollouts.
    for current, directories, files in os.walk(directory, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in SKIP and not name.startswith("."))
        for name in sorted(files):
            if name.endswith(".py") and name not in SKIP and not name.startswith("."):
                yield Path(current) / name


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                yield node, name.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node, node.module


def check(repository: Path) -> tuple[list[str], int]:
    """Return bounded static violations and the number of source files checked."""
    root = repository.resolve()
    errors: list[str] = []
    for obsolete in ("starVLA", "AgentPolicies/evaluation", "AgentPolicies/model_profiles.py",
                     "AgentPolicies/checks", "AgentPolicies/diagnostics", "benchkit/runner.py",
                     "benchkit/campaign.py", "benchkit/benchmark_plans.py", "benchkit/campaign_coverage.py",
                     "benchkit/result_index.py", "benchkit/smoke.py", "benchkit/catalog.py",
                     "benchkit/benchmark_catalog.json"):
        target = root / obsolete
        live = target.is_file() or (target.is_dir() and any(
            p.is_file() and p.suffix in {".py", ".json"} and "__pycache__" not in p.parts
            for p in target.rglob("*")))
        if live:
            errors.append(f"{obsolete}: removed namespace or evaluator source that belongs outside AgentPolicies/")
    for name in BENCHMARKS + SERVER_ONLY_BENCHMARKS:
        base = root / "benchmarks/simBenchmarks" / name
        adapter_path = "bench_server/adapter.py" if name in NESTED_ADAPTERS else "adapter.py"
        required_files = (adapter_path, "server.py", "EVALUATION_PROTOCOL.md")
        if name in BENCHMARKS:
            required_files += (("bench_server/protocol/plan.py" if name in MIGRATED_BENCHMARKS
                                else "evaluation/plan.py"),)
        if name in NESTED_ADAPTERS:
            for obsolete in ("adapter.py", "evaluation/__init__.py", "evaluation/plan.py"):
                if (base / obsolete).is_file():
                    errors.append(f"{base.relative_to(root)}/{obsolete}: removed compatibility entrypoint")
        for required in required_files:
            if not (base / required).is_file():
                errors.append(f"{base.relative_to(root)}/{required}: missing benchmark-owned component")

    paths = list(_sources(root / "benchkit")) + list(_sources(root / "AgentPolicies"))
    obsolete_service = root / "benchmarks/simBenchmarks/service"
    if any(_sources(obsolete_service)):
        errors.append("benchmarks/simBenchmarks/service: shared transport belongs in benchkit/sim_server")
    for name in BENCHMARKS + SERVER_ONLY_BENCHMARKS:
        base = root / "benchmarks/simBenchmarks" / name
        adapter_path = "bench_server/adapter.py" if name in NESTED_ADAPTERS else "adapter.py"
        paths += [base / adapter_path, base / "server.py"]
        paths += list(_sources(base / "bench_server"))
        paths += list(_sources(base / "protocol"))
        paths += list(_sources(base / "evaluation"))
        # Native workers/helpers, not asset-preparation/diagnostic launcher scripts.
        for filename in ("native_eef_worker.py", "worker_runtime.py", "asset_reference.py", "render_lifecycle.py"):
            candidate = base / "environment" / filename
            if candidate.is_file():
                paths.append(candidate)
        if name in SERVER_ONLY_BENCHMARKS:
            # Active root helpers (for example LIBERO-Plus catalog routing) are
            # benchmark code too, even without an evaluation/plan package.
            paths += list(base.glob("*.py"))
            paths += list(_sources(base / "environment"))
    checked = 0
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        label = relative.as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=label)
        except (SyntaxError, UnicodeError) as exc:
            errors.append(f"{label}: cannot inspect Python source: {exc}")
            continue
        checked += 1
        layer = relative.parts[0]
        lazy_imports = {id(node) for function in ast.walk(tree)
                        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                        for node in ast.walk(function)
                        if isinstance(node, (ast.Import, ast.ImportFrom))}
        for node, module in _imports(tree):
            module_root = module.split(".", 1)[0]
            reason = None
            if module_root == "starVLA":
                reason = "active import refers to the removed starVLA namespace"
            elif module == "AgentPolicies.evaluation" or module.startswith("AgentPolicies.evaluation."):
                reason = "active import refers to the removed evaluator namespace"
            elif module == "AgentPolicies.diagnostics" or module.startswith("AgentPolicies.diagnostics."):
                reason = "active import refers to the removed diagnostic namespace"
            elif module == "benchmarks.simBenchmarks.service" or module.startswith("benchmarks.simBenchmarks.service."):
                reason = "active import refers to the removed shared service namespace"
            elif layer == "benchkit":
                optional_media = (label == "benchkit/audits/mailbox_artifacts.py"
                                  and module_root in {"PIL", "numpy"} and id(node) in lazy_imports)
                optional_media = optional_media or (label == "benchkit/sim_server/wire.py"
                                  and module_root == "numpy" and id(node) in lazy_imports)
                optional_media = optional_media or (label == "benchkit/diagnostics/simpler_mailbox.py"
                                  and module_root == "PIL" and id(node) in lazy_imports)
                if (module_root in HEAVY_NATIVE_ROOTS or module_root in {"openai", "anthropic", "PIL", "numpy"}) and not optional_media:
                    reason = "shared engine imports a native/model/provider dependency"
                elif (label in {"benchkit/cli.py", "benchkit/diagnostics/robot_state_hold.py"}
                      and module == "AgentPolicies.policy_support.runner"):
                    pass  # Explicit driver/diagnostic callers use the real agent-owned loop.
                elif module_root in {"benchmarks", "AgentPolicies"} and label not in ASSEMBLY_MODULES:
                    reason = "extension imports belong in explicit assembly/validation entrypoints"
            elif layer == "AgentPolicies":
                if label in MODEL_DRIVERS and module == "benchkit.sim_server.client":
                    pass  # trusted driver only; never a capability passed to Policy
                elif module_root == "benchmarks" or module_root in HEAVY_NATIVE_ROOTS - {"torch", "tensorflow", "jax"}:
                    reason = "policy imports a benchmark or native simulator implementation"
                elif (module in {"benchkit.campaigns", "benchkit.sim_server"}
                      or module.startswith("benchkit.campaigns.")
                      or module.startswith("benchkit.sim_server.")):
                    reason = "policy imports evaluator execution/plan machinery"
                elif module == "benchkit.registry":
                    if not isinstance(node, ast.ImportFrom) or any(n.name != "register_policy" for n in node.names):
                        reason = "policy may register itself, not access benchmark construction"
            elif layer == "benchmarks" and module_root == "AgentPolicies":
                reason = "native benchmark/plan depends on a model implementation"
            if reason:
                errors.append(f"{label}:{node.lineno}: {reason}: {module}")
    return errors, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    errors, checked = check(args.repository)
    for error in errors:
        print(error)
    print(f"Ownership/import boundary check: {checked} active files, {len(errors)} violations")
    print("Scope: static imports and directory ownership only; not native parity or runtime isolation.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
