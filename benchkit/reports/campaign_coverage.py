"""Private campaign continuation ledgers; read records, never native or actor paths.

Only the two original pilot formats are accepted as continuation sources. An
unsupported, incomplete or changed claim blocks continuation rather than being
treated as permission to try that task again. Future independent campaigns may
select the complete scope without a carry-forward source.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

AUDIT_FILES = ("benchkit/audits/closed_run.py",
               "benchkit/reports/progress.py")
HISTORICAL_AUDIT_FILES = (
    ("harness/audits/closed_run.py", "harness/reports/progress.py"),
)
SCHEMA = "starvla-rsi.campaign-coverage/v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def audit_tools(repository: Path | None = None):
    repository = repository or Path(__file__).resolve().parents[2]
    layouts = (AUDIT_FILES,) + HISTORICAL_AUDIT_FILES
    present = {relative for layout in layouts for relative in layout
               if (repository / relative).exists() or (repository / relative).is_symlink()}
    selected = [layout for layout in layouts if set(layout) == present]
    require(len(selected) == 1, "missing/mixed frozen carry-forward auditor layout")
    modules = []
    for index, relative in enumerate(selected[0]):
        path = repository / relative
        require(path.is_file() and not any((repository / parent).is_symlink()
                                          for parent in (Path(relative), *Path(relative).parents)),
                "missing/unsafe frozen carry-forward auditor")
        spec = importlib.util.spec_from_file_location(f"campaign_carry_auditor_{index}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return tuple(modules)


def artifact_hashes(files, relative: str) -> dict[str, str]:
    """Bind the retained artifact directory, including image/video bytes.

    Never follow paths inside native provenance, mailbox references or asset
    manifests. These are retained evidence, not renewed native-asset checks.
    """
    directory = files.root / relative
    require(directory.is_dir() and not directory.is_symlink(), "missing/unsafe prior artifact directory")
    result = {}
    total = 0
    entries = sorted(directory.rglob("*"))
    require(len(entries) <= 16384, "prior artifact inventory exceeds entry limit")
    for path in entries:
        require(not path.is_symlink(), "symlink in prior artifact inventory")
        if path.is_dir():
            continue
        key = path.relative_to(files.root).as_posix()
        path = files.path(key)
        before = path.stat()
        total += before.st_size
        require(total <= 4 * 1024**3, "prior artifact inventory exceeds 4 GiB")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while payload := source.read(1024 * 1024):
                digest.update(payload)
        after = path.stat()
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "prior artifact changed while hashing")
        result[key] = digest.hexdigest()
    require(entries == sorted(directory.rglob("*")), "prior artifact inventory changed during audit")
    return result


def verify_native_reset(files, artifact_dir: str, benchmark: str, selected: dict, original: dict) -> dict:
    provenance = files.json(artifact_dir + "/native_provenance.json")
    episode = original["episode"]
    require(provenance["task"] == episode["task"] and provenance["seed"] == episode["seed"],
            "prior native task/seed mismatch")
    if benchmark == "simple_humanoid":
        metadata = selected["episode"]["metadata"]
        require(provenance["dr_level"] == metadata["dr_level"] == 0
                and provenance["episode_index"] == metadata["episode_index"] == 0
                and provenance["reset_metadata"]["sha256"] == metadata["reset_metadata_sha256"]
                and provenance["track"] == original["descriptor"]["protocol_version"]
                and provenance["git_revision"] == original["descriptor"]["source_revision"]
                and provenance["diagnostic_only"] is False, "prior SIMPLE reset/track mismatch")
        reset = files.json(artifact_dir + "/private_reset.json")
        require(files.hashes[artifact_dir + "/private_reset.json"] == provenance["selected_reset"]["sha256"],
                "prior SIMPLE selected reset changed")
        require(reset["uid"] == metadata["native_task_uid"], "prior SIMPLE selected reset task UID mismatch")
        return {"dr_level": 0, "episode_index": 0,
                "reset_metadata_sha256": provenance["reset_metadata"]["sha256"],
                "selected_reset_sha256": provenance["selected_reset"]["sha256"]}
    require(provenance["split"] == selected["episode"]["metadata"]["split"] == "target"
            and provenance["native_horizon"] == selected["episode"]["metadata"]["native_horizon"]
            and provenance["sources"]["robocasa"]["revision"] == original["descriptor"]["source_revision"],
            "prior RoboCasa split/horizon mismatch")
    files.raw(artifact_dir + "/initial_scene.xml")
    require(files.hashes[artifact_dir + "/initial_scene.xml"] == provenance["initial_model_xml_sha256"],
            "prior RoboCasa scene changed")
    files.raw(artifact_dir + "/initial_state.npy")
    return {key: provenance[key] for key in ("split", "layout_id", "style_id",
            "initial_model_xml_sha256", "initial_state_sha256", "used_assets_inventory_sha256")}


def read_prior(source: Path, benchmark: str, selected: list[dict], pilots: list[dict],
               *, auditor_repository: Path | None = None) -> dict:
    from benchkit.campaigns.workflow import verify_frozen_package

    audit, progress = audit_tools(auditor_repository)
    require(not source.is_symlink(), "carry-forward campaign must not be a symlink")
    files = audit.ClosedFiles(source)
    manifest = files.json("campaign.json")
    campaign_hash = files.hashes["campaign.json"]
    require(files.json("campaign_digest.json")["sha256"] == campaign_hash, "prior campaign digest mismatch")
    require(manifest["schema_version"] in ("starvla-rsi.campaign/v1", "starvla-rsi.campaign/v3")
            and manifest["benchmark"] == benchmark, "prior campaign benchmark/schema mismatch")
    require(manifest.get("purpose") == "development_pilot" and "coverage_ledger" not in manifest,
            "only original pilot carry-forward is supported; no claim may be discarded")
    require(isinstance(manifest["policy_prompt"], str)
            and hashlib.sha256(manifest["policy_prompt"].encode("utf-8")).hexdigest()
            == manifest["policy_prompt_sha256"], "prior policy prompt digest mismatch")
    require(manifest["planned_cases"] == len(manifest["cases"]) == len(pilots) == 2
            and manifest["attempts_per_task"] == 1, "prior campaign selection/attempt count mismatch")
    expected_budget = {"seed": selected[0]["episode"]["seed"], "budget_mode": "decisions",
                       "max_policy_calls": selected[0]["benchmark_args"]["max_policy_calls"],
                       "replan_interval": selected[0]["benchmark_args"]["replan_interval"]}
    expected_budget["max_steps"] = expected_budget["max_policy_calls"] * expected_budget["replan_interval"]
    require(all(type(manifest[key]) is type(value) and manifest[key] == value
                for key, value in expected_budget.items()), "prior campaign seed/budget mismatch")
    require({p.name for p in files.root.glob("case-*")} == {c["case_id"] for c in pilots},
            "missing or additional prior claim; continuation must not retry it")
    audit.audit_source(files, manifest)
    verify_frozen_package(files.root, manifest)
    # Bind the actual frozen executable source and supplementals as well as its
    # independently copied runner inventory; no old package is imported.
    index = files.json("harness_source/index.json")
    for row in index["files"]:
        prefix = "frozen/" if manifest["schema_version"] == "starvla-rsi.campaign/v3" else "frozen/starVLA/evaluation/"
        files.raw(prefix + row["path"])
    model_schema = (manifest.get("model_source") or {}).get("schema_version")
    from benchkit.model_profiles import _source_namespace
    namespace = "starVLA" if model_schema is None else _source_namespace(model_schema)
    files.raw(f"frozen/{namespace}/__init__.py")
    for row in manifest.get("supplemental_runtime_files", []):
        files.raw("frozen/" + row["path"])
    selected_by_task = {c["episode"]["task"]: c for c in selected}
    carried = []
    evidence = {}
    for case, expected in zip(manifest["cases"], pilots):
        require({key: case[key] for key in expected} == expected,
                "prior case episode/descriptor/protocol differs from supported frozen pilot")
        task = case["episode"]["task"]
        require(task in selected_by_task, "prior task is outside selected scope")
        directory = case["case_id"]
        attempt = files.json(directory + "/attempt.json")
        require(attempt["case_index"] == case["index"] and attempt["attempt"] == 1
                and attempt["campaign_sha256"] == campaign_hash, "prior permanent attempt mismatch")
        outcome = files.json(directory + "/outcome.json")
        require(outcome["case_index"] == case["index"]
                and outcome["status"] in ("completed", "infrastructure_or_policy_error"),
                "unsupported prior outcome; attempt remains non-retryable")
        run_relative = directory + "/run"
        # Read lifecycle before invoking either auditor; active/incomplete runs
        # are unsupported carry-forward evidence, not unattempted tasks.
        status = files.json(run_relative + "/status.json")
        require(status["status"] in ("completed", "completed_with_errors"),
                "prior claim has no closed run; continuation must not retry it")
        checked = audit.audit_run(files.root / run_relative)
        for relative, expected_hash in checked["read_file_sha256"].items():
            key = run_relative + "/" + relative
            files.raw(key)
            require(files.hashes[key] == expected_hash, "prior closed evidence changed after audit")
        records = files.jsonl(run_relative + "/episodes.jsonl")
        require(len(records) == 1 and records[0]["episode"] == case["episode"], "prior run/episode mismatch")
        run_manifest = files.json(run_relative + "/manifest.json")
        require(run_manifest["benchmark"] == case["descriptor"], "prior run/descriptor mismatch")
        if benchmark == "simple_humanoid":
            from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import SimpleHumanoidBenchmarkAdapter
            adapter = SimpleHumanoidBenchmarkAdapter(**case["benchmark_args"])
        else:
            from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import RoboCasa365BenchmarkAdapter
            adapter = RoboCasa365BenchmarkAdapter(**case["benchmark_args"])
        require(run_manifest["action_spec"] == adapter.action_spec.to_dict()
                and run_manifest["observation_spec"] == adapter.observation_spec.to_dict(),
                "prior run observation/action contract mismatch")
        require(all(run_manifest["policy"].get(key) == value for key, value in manifest["policy"].items()),
                "prior run/campaign policy identity mismatch")
        # Bind the actual transport contract, not just its display identity.
        # Do not open the actor endpoint or instantiate MailboxPolicy here.
        expected_parameters = {
            "directory": case["policy_endpoint"],
            "timeout_s": float(manifest["response_timeout_s"]),
            "prompt_sha256": manifest["policy_prompt_sha256"],
            "max_response_bytes": 65536,
            "max_chunk_length": manifest["replan_interval"],
            "history": "current_observation_only",
            "usage_source": "client_reported_or_unavailable",
            "evaluation_status": "experimental",
            "provider_call_limit_verified": False,
            "public_path_base": "mailbox_root",
            "absolute_paths_exported": False,
            "endpoint_blinding": "operator_must_supply_seed_independent_root_and_opaque_endpoint",
        }
        parameters = run_manifest["policy"].get("parameters")
        expected_version = "starvla-rsi.mailbox/v2"
        if manifest["schema_version"] == "starvla-rsi.campaign/v3":
            expected_version = "starvla-rsi.mailbox/v3"
            expected_parameters.update(model_profile=manifest["model_profile"],
                                       policy_stop_rule=manifest["policy_stop_rule"])
        require(run_manifest["policy"].get("version") == expected_version
                and isinstance(parameters, dict) and parameters.keys() == expected_parameters.keys()
                and all(type(parameters[key]) is type(value) and parameters[key] == value
                        for key, value in expected_parameters.items()),
                "prior mailbox policy parameters/version mismatch")
        require(all(type(run_manifest["protocol"][key]) is type(value)
                    and run_manifest["protocol"][key] == value for key, value in expected_budget.items()),
                "prior run protocol budget mismatch")
        require(run_manifest["harness_source"]["inventory_sha256"] == manifest["harness_source"]["inventory_sha256"],
                "prior campaign/run source inventory mismatch")
        summary = files.json(run_relative + "/summary.json")
        require(outcome["summary"] == summary, "prior outcome/summary mismatch")
        completed = outcome["returncode"] == 0 and not outcome["timed_out"] and summary["errors"] == 0
        require((outcome["status"] == "completed") == completed, "prior outcome lifecycle mismatch")
        timing = progress.summarize_progress(files.root / run_relative)
        require(len(timing["episodes"]) == 1 and timing["episodes"][0]["episode"] == case["episode"],
                "prior progress episode mismatch")
        require(files.json(directory + "/progress.json") == timing, "prior stored/derived progress mismatch")
        result_path = next(p for p in checked["read_file_sha256"] if p.startswith("episodes/") and p.endswith("/result.json"))
        artifacts = run_relative + "/" + str(Path(result_path).parent / "artifacts")
        native_reset = verify_native_reset(files, artifacts, benchmark, selected_by_task[task], case)
        bound_artifacts = artifact_hashes(files, artifacts)
        for reference in records[0]["artifacts"].values():
            path = Path(reference)
            if path.is_absolute():
                require(path.is_relative_to(files.root / artifacts), "prior artifact reference escapes its private directory")
                relative = path.relative_to(files.root).as_posix()
            else:
                require(".." not in path.parts, "unsafe prior artifact reference")
                relative = str(Path(artifacts) / path)
            require(relative in bound_artifacts, "referenced prior artifact missing")
        evidence.update(bound_artifacts)
        carried.append({"task": task, "source_case_id": directory, "source_case_index": case["index"],
            "source_run": str(files.root / run_relative), "original_episode": case["episode"],
            "original_descriptor": case["descriptor"], "original_protocol": run_manifest["protocol"],
            "attempt_status": outcome["status"], "episode_status": records[0]["status"],
            "native_final_success": records[0]["success"], "original_error": records[0]["error"],
            "record_consistency": checked["record_consistency"], "native_reset": native_reset,
            "progress": timing["episodes"][0], "progress_sha256": files.hashes[directory + "/progress.json"],
            "record_auditor_sha256": checked["auditor"]["sha256"]})
    files.verify_unchanged()
    evidence.update(files.hashes)
    return {"campaign": str(files.root), "campaign_sha256": campaign_hash,
        "source_policy": manifest["policy"], "source_policy_prompt_sha256": manifest["policy_prompt_sha256"],
        "source_actor_isolation": manifest["actor_isolation"], "source_provider_accounting": manifest["provider_accounting"],
        "source_harness_inventory_sha256": manifest["harness_source"]["inventory_sha256"],
        "attempts": carried, "file_sha256": dict(sorted(evidence.items())),
        "evidence_scope": "campaign/claim/outcome/closed runner records/source inventories/progress and retained private artifact bytes; no mailbox or external native-asset paths followed",
        "caveats": ["Original pilot protocol, policy context and outcome remain unchanged; no homogeneous new score is asserted.",
                    "Record consistency and retained-byte binding are not native parity or execution attestation.",
                    "Reset artifacts are byte-bound; RoboCasa serialized NPY payload and SIMPLE reserialized environment configuration are not independently decoded/rehashed by this helper.",
                    "Provider identity/usage and actor isolation are not independently attested here."]}


def build_coverage(benchmark: str, task_scope: str, selected: list[dict], pilots: list[dict],
                   carry_forward_campaign: Path | None, *, auditor_repository: Path | None = None) -> tuple[list[dict], dict]:
    require((benchmark, task_scope) in (("robocasa365", "target50"), ("simple_humanoid", "released-12")),
            "unsupported expansion scope")
    expected_count = 50 if benchmark == "robocasa365" else 12
    require(len(selected) == len({c["episode"]["task"] for c in selected}) == expected_count,
            "selected scope must retain its complete distinct denominator")
    try:
        prior = None if carry_forward_campaign is None else read_prior(
            Path(carry_forward_campaign), benchmark, selected, pilots, auditor_repository=auditor_repository)
    except (KeyError, TypeError, OSError, StopIteration) as exc:
        raise ValueError(f"unsupported or missing carry-forward evidence; no retry is authorized: {exc}") from exc
    carried = {} if prior is None else {row["task"]: row for row in prior["attempts"]}
    cases, entries = [], []
    for selection_index, selected_case in enumerate(selected):
        task = selected_case["episode"]["task"]
        entry = {"selection_index": selection_index, "task": task,
                 "selected_episode": selected_case["episode"], "selected_descriptor": selected_case["descriptor"]}
        if task in carried:
            entry.update(disposition="carried_attempt", source_case_id=carried[task]["source_case_id"])
        else:
            case = copy.deepcopy(selected_case)
            case.update(index=len(cases), case_id=f"case-{len(cases):03d}")
            cases.append(case)
            entry.update(disposition="new_case", case_id=case["case_id"])
        entries.append(entry)
    return cases, {"schema_version": SCHEMA, "benchmark": benchmark, "task_scope": task_scope,
                   "selected_total": len(entries), "carried_attempts": len(carried),
                   "planned_new_cases": len(cases), "entries": entries, "carry_forward": prior,
                   "score_aggregation": "not_implemented; preserve original protocols and outcomes separately"}


def verify_coverage(output: Path, manifest: dict) -> None:
    """Rebuild and revalidate before creating a permanent new attempt claim."""
    from benchkit.campaigns.workflow import cases_for

    ledger = manifest["coverage_ledger"]
    prior = ledger["carry_forward"]
    selected = cases_for(manifest["benchmark"], manifest["max_policy_calls"],
                         manifest["replan_interval"], task_scope=manifest["task_scope"])
    pilots = cases_for(manifest["benchmark"], manifest["max_policy_calls"], manifest["replan_interval"])
    cases, expected = build_coverage(manifest["benchmark"], manifest["task_scope"], selected, pilots,
        None if prior is None else Path(prior["campaign"]), auditor_repository=output / "frozen")
    require(ledger == expected, "coverage ledger or bound prior evidence changed")
    actual = [{key: value for key, value in case.items() if key != "policy_endpoint"} for case in manifest["cases"]]
    require(actual == cases and manifest["planned_cases"] == len(cases),
            "executable selection changed or includes a carried task")
    require(all(manifest[key] == expected[key] for key in ("selected_total", "carried_attempts", "planned_new_cases")),
            "coverage denominator counters changed")
    require(manifest["seed"] == selected[0]["episode"]["seed"] and manifest["budget_mode"] == "decisions"
            and manifest["max_steps"] == manifest["max_policy_calls"] * manifest["replan_interval"],
            "expansion seed/budget changed")
