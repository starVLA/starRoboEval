"""Synthetic continuation records only: no simulator or capability attempt."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchkit.artifacts import atomic_write_json
from benchkit.campaigns.workflow import cases_for, digest, prepare, run_case, summarize, verify_frozen_package
from benchkit.reports.campaign_coverage import AUDIT_FILES, audit_tools, build_coverage, verify_coverage
from benchkit.contracts import EpisodeSpec, Observation, PolicyDecision, PolicyDescriptor
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.diagnostics.smoke import ScriptedReachPolicy


class FixturePolicy(ScriptedReachPolicy):
    def __init__(self, case, manifest):
        from benchkit.model_profiles import create_policy
        declared = create_policy("anonymous_code_agent", directory=case["policy_endpoint"],
            prompt=manifest["policy_prompt"], timeout_s=float(manifest["response_timeout_s"]),
            max_chunk_length=manifest["replan_interval"], **manifest["policy_parameters"])
        self.descriptor = declared.descriptor
        self.prompt = declared.prompt

    def compatibility_errors(self, observation_spec, action_spec):
        return []

    def act(self, observation):
        return PolicyDecision(stop=True, stop_reason="synthetic_fixture")


class ErrorFixturePolicy(FixturePolicy):
    def act(self, observation):
        raise RuntimeError("synthetic error must remain an error")


class FixtureSession:
    def __init__(self, case):
        self.case = case

    def bind_artifact_dir(self, path):
        self.artifact_dir = path

    def reset(self):
        case = self.case
        ep = case["episode"]
        provenance = {"task": ep["task"], "seed": ep["seed"]}
        if case["descriptor"]["name"] == "simple_humanoid":
            from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import TASK_CONFIGS
            config = TASK_CONFIGS[ep["task"]]
            atomic_write_json(self.artifact_dir / "private_reset.json", {"uid": config["task_uid"]})
            provenance.update(dr_level=0, episode_index=0, diagnostic_only=False,
                track=case["descriptor"]["protocol_version"],
                git_revision=case["descriptor"]["source_revision"],
                reset_metadata={"sha256": config["reset_metadata_sha256"]},
                selected_reset={"sha256": digest(self.artifact_dir / "private_reset.json")})
        else:
            (self.artifact_dir / "initial_scene.xml").write_text("<mujoco/>")
            (self.artifact_dir / "initial_state.npy").write_bytes(b"synthetic bytes; never loaded")
            provenance.update(split="target", native_horizon=ep["metadata"]["native_horizon"],
                sources={"robocasa": {"revision": case["descriptor"]["source_revision"]}},
                layout_id=1, style_id=1, initial_model_xml_sha256=digest(self.artifact_dir / "initial_scene.xml"),
                initial_state_sha256="0" * 64, used_assets_inventory_sha256="1" * 64)
        atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
        (self.artifact_dir / "synthetic-video.mp4").write_bytes(b"retained synthetic artifact; no video decoding")
        return Observation(step=0, instruction=ep["instruction"])

    def step(self, action):
        raise AssertionError("synthetic stop/error fixture cannot execute controls")

    def metrics(self):
        return {"success": False}

    def artifacts(self):
        return {"native_provenance": "native_provenance.json", "video": "synthetic-video.mp4"}

    def close(self):
        pass


class FixtureAdapter:
    budget_mode, max_policy_calls, replan_interval, environment_step_cap = "decisions", 200, 5, 1000

    def __init__(self, case):
        self.case = case
        if case["descriptor"]["name"] == "simple_humanoid":
            from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import SimpleHumanoidBenchmarkAdapter
            real = SimpleHumanoidBenchmarkAdapter(**case["benchmark_args"])
        else:
            from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import RoboCasa365BenchmarkAdapter
            real = RoboCasa365BenchmarkAdapter(**case["benchmark_args"])
        self.descriptor, self.action_spec, self.observation_spec = real.descriptor, real.action_spec, real.observation_spec

    def episodes(self, seed, limit=None):
        return [EpisodeSpec(**self.case["episode"])]

    def open_episode(self, episode):
        return FixtureSession(self.case)


class CampaignExpansionChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / "public"

    def prior(self, benchmark="robocasa365", *, error=False):
        source = self.root / (benchmark + "-synthetic-pilot")
        manifest = prepare(source, benchmark, self.public, "Synthetic test prompt.")
        _, progress = audit_tools()
        for case in manifest["cases"]:
            directory = source / case["case_id"]
            directory.mkdir()
            atomic_write_json(directory / "attempt.json", {"case_index": case["index"], "attempt": 1,
                "campaign_sha256": digest(source / "campaign.json"), "device_index": 0})
            policy = (ErrorFixturePolicy if error else FixturePolicy)(case, manifest)
            run = EvaluationRunner().run(FixtureAdapter(case), policy,
                RunRequest(output_dir=directory, run_id="run", seed=manifest["seed"], episode_limit=1,
                    budget_mode="decisions", max_policy_calls=200, replan_interval=5, max_steps=1000))
            summary = json.loads((run / "summary.json").read_text())
            atomic_write_json(directory / "outcome.json", {"case_index": case["index"],
                "status": "infrastructure_or_policy_error" if error else "completed",
                "returncode": 1 if error else 0, "timed_out": False, "summary": summary})
            atomic_write_json(directory / "progress.json", progress.summarize_progress(run))
        return source

    def expand(self, source, benchmark="robocasa365", **kwargs):
        return prepare(self.root / "expanded", benchmark, self.public, "Synthetic new prompt.",
            task_scope="target50" if benchmark == "robocasa365" else "released-12",
            carry_forward_campaign=source, **kwargs)

    def mutate(self, path, change):
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def rewrite_campaign_digest(self, source):
        atomic_write_json(source / "campaign_digest.json", {"sha256": digest(source / "campaign.json")})

    def test_complete_denominators_exact_execution_and_original_files_unchanged(self):
        for benchmark, scope, total, new_count in (("robocasa365", "target50", 50, 48),
                                                  ("simple_humanoid", "released-12", 12, 10)):
            with self.subTest(benchmark=benchmark):
                source = self.prior(benchmark)
                before = {p.relative_to(source).as_posix(): digest(p) for p in source.rglob("*") if p.is_file()}
                output = self.root / (benchmark + "-expanded")
                manifest = prepare(output, benchmark, self.public, "Synthetic prompt.",
                    task_scope=scope, carry_forward_campaign=source)
                verify_frozen_package(output, manifest)
                verify_coverage(output, manifest)
                self.assertEqual(manifest["purpose"], "development_task_coverage")
                self.assertEqual((manifest["selected_total"], manifest["carried_attempts"], manifest["planned_cases"]),
                                 (total, 2, new_count))
                self.assertEqual(manifest["planned_new_cases"], new_count)
                ledger = manifest["coverage_ledger"]
                self.assertEqual([r["task"] for r in ledger["entries"]],
                                 [c["episode"]["task"] for c in cases_for(benchmark, 200, 5, task_scope=scope)])
                carried = ledger["carry_forward"]
                self.assertTrue(set(c["task"] for c in carried["attempts"]).isdisjoint(
                    c["episode"]["task"] for c in manifest["cases"]))
                for prior in carried["attempts"]:
                    self.assertNotIn(scope, prior["original_descriptor"]["protocol_version"])
                    self.assertFalse(prior["native_final_success"])
                self.assertFalse(any(output.glob("case-*")))
                self.assertTrue(all(relative in {r["path"] for r in json.loads((output / "harness_source/index.json").read_text())["files"]}
                                    for relative in AUDIT_FILES))
                self.assertEqual(before, {p.relative_to(source).as_posix(): digest(p) for p in source.rglob("*") if p.is_file()})
                report = summarize(output)
                self.assertEqual((report["selected_total"], report["carried_attempts"], report["unattempted"]),
                                 (total, 2, new_count))
                self.assertIn("not implemented", report["coverage_reporting"])
                self.assertTrue(any("events.jsonl" in p for p in carried["file_sha256"]))
                self.assertTrue(any("synthetic-video.mp4" in p for p in carried["file_sha256"]))

    def test_full_fresh_scope_remains_available_without_global_task_bans(self):
        for benchmark, scope, count in (("robocasa365", "target50", 50), ("simple_humanoid", "released-12", 12)):
            output = self.root / benchmark
            manifest = prepare(output, benchmark, self.public, "Future independent campaign.", task_scope=scope)
            self.assertEqual((manifest["planned_cases"], manifest["selected_total"], manifest["carried_attempts"]), (count, count, 0))
            verify_coverage(output, manifest)

    def test_bad_scope_and_carry_without_scope_create_no_output(self):
        for benchmark, scope in (("libero", "target50"), ("robocasa365", "released-12"),
                                 ("simple_humanoid", "target50"), ("robocasa365", "all"), ("robocasa365", True)):
            with self.subTest(benchmark=benchmark, scope=scope), self.assertRaises(ValueError):
                prepare(self.root / "invalid", benchmark, self.public, "prompt", task_scope=scope)
            self.assertFalse((self.root / "invalid").exists())
        with self.assertRaises(ValueError):
            prepare(self.root / "invalid", "robocasa365", self.public, "prompt", carry_forward_campaign=self.root / "absent")
        self.assertFalse((self.root / "invalid").exists())
        self.assertFalse(self.public.exists())

    def test_cross_benchmark_seed_budget_protocol_and_duplicate_selection_rejected(self):
        source = self.prior()
        original = (source / "campaign.json").read_bytes()
        mutations = (
            lambda doc: doc.update(benchmark="simple_humanoid"),
            lambda doc: doc.update(seed=1),
            lambda doc: doc.update(max_policy_calls=199),
            lambda doc: doc["cases"][0]["descriptor"].update(protocol_version="different"),
            lambda doc: doc["cases"][0]["episode"]["metadata"].update(split="pretrain"),
            lambda doc: doc["cases"].__setitem__(1, copy.deepcopy(doc["cases"][0])),
        )
        for mutation in mutations:
            (source / "campaign.json").write_bytes(original)
            self.mutate(source / "campaign.json", mutation)
            self.rewrite_campaign_digest(source)
            with self.assertRaises(ValueError):
                self.expand(source)
            self.assertFalse((self.root / "expanded").exists())
        (source / "campaign.json").write_bytes(original)
        self.rewrite_campaign_digest(source)
        with self.assertRaises(ValueError):
            self.expand(source, decisions=199)
        self.assertFalse((self.root / "expanded").exists())

    def test_changed_source_or_digest_and_missing_closed_evidence_block_preparation(self):
        source = self.prior()
        paths = [source / "campaign.json", source / "harness_source/files/benchkit/campaigns/workflow.py",
                 source / "case-000/progress.json", source / "case-000/attempt.json",
                 source / "case-000/run/status.json"]
        for path in paths:
            original = path.read_bytes()
            path.write_bytes(original + b" changed")
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.expand(source)
            path.write_bytes(original)
            self.assertFalse((self.root / "expanded").exists())
        (source / "case-000/outcome.json").unlink()
        with self.assertRaises(ValueError):
            self.expand(source)
        self.assertFalse((self.root / "expanded").exists())

    def test_unresolved_and_additional_claims_are_not_reclassified_as_unattempted(self):
        source = self.prior()
        status = source / "case-000/run/status.json"
        original = status.read_bytes()
        self.mutate(status, lambda doc: doc.update(status="running"))
        with self.assertRaisesRegex(ValueError, "no closed run"):
            self.expand(source)
        self.assertFalse((self.root / "expanded").exists())
        status.write_bytes(original)
        (source / "case-999").mkdir()
        with self.assertRaisesRegex(ValueError, "additional prior claim"):
            self.expand(source)
        self.assertFalse((self.root / "expanded").exists())

    def test_prior_run_protocol_sensor_contract_and_reset_mismatches_rejected(self):
        source = self.prior()
        run_manifest = source / "case-000/run/manifest.json"
        original = run_manifest.read_bytes()
        for change in (
                lambda doc: doc["protocol"].update(max_steps=999),
                lambda doc: doc["action_spec"].update(mode="wrong"),
                lambda doc: doc["harness_source"].update(inventory_sha256="0" * 64)):
            self.mutate(run_manifest, change)
            with self.assertRaises(ValueError):
                self.expand(source)
            run_manifest.write_bytes(original)
            self.assertFalse((self.root / "expanded").exists())
        provenance = next(source.glob("case-000/run/episodes/*/artifacts/native_provenance.json"))
        original = provenance.read_bytes()
        for change in (lambda doc: doc.update(seed=7), lambda doc: doc.update(split="pretrain"),
                       lambda doc: doc["sources"]["robocasa"].update(revision="wrong")):
            self.mutate(provenance, change)
            with self.assertRaises(ValueError):
                self.expand(source)
            provenance.write_bytes(original)
            self.assertFalse((self.root / "expanded").exists())
        simple = self.prior("simple_humanoid")
        provenance = next(simple.glob("case-000/run/episodes/*/artifacts/native_provenance.json"))
        self.mutate(provenance, lambda doc: doc["reset_metadata"].update(sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "SIMPLE reset/track"):
            self.expand(simple, "simple_humanoid")
        self.assertFalse((self.root / "expanded").exists())

    def test_consistent_closed_errors_remain_errors_and_are_excluded(self):
        source = self.prior(error=True)
        manifest = self.expand(source)
        self.assertEqual(manifest["planned_cases"], 48)
        for row in manifest["coverage_ledger"]["carry_forward"]["attempts"]:
            self.assertEqual(row["attempt_status"], "infrastructure_or_policy_error")
            self.assertEqual(row["episode_status"], "error")
            self.assertIsNone(row["native_final_success"])
            self.assertIsInstance(row["original_error"], dict)

    def test_prior_mailbox_contract_and_prompt_tampering_rejected(self):
        source = self.prior()
        path = source / "case-000/run/manifest.json"
        original = path.read_bytes()
        changes = {"directory": "/wrong/endpoint", "timeout_s": 17.0,
                   "prompt_sha256": "0" * 64, "max_response_bytes": 123,
                   "max_chunk_length": 99, "history": "all_observations",
                   "usage_source": "other", "evaluation_status": "verified",
                   "provider_call_limit_verified": 0, "public_path_base": "other",
                   "absolute_paths_exported": 0, "endpoint_blinding": "none"}
        for key, value in changes.items():
            with self.subTest(key=key):
                self.mutate(path, lambda doc: doc["policy"]["parameters"].update({key: value}))
                with self.assertRaisesRegex(ValueError, "mailbox policy|effective model prompt|incomplete model source identity"):
                    self.expand(source)
                path.write_bytes(original)
                self.assertFalse((self.root / "expanded").exists())
        for change in (lambda doc: doc["policy"].update(version="starvla-rsi.mailbox/v1"),
                       lambda doc: doc["policy"].pop("parameters"),
                       lambda doc: doc["policy"]["parameters"].update(unexpected=True)):
            self.mutate(path, change)
            with self.assertRaisesRegex(ValueError, "mailbox policy|effective model prompt|incomplete model source identity"):
                self.expand(source)
            path.write_bytes(original)
        campaign = source / "campaign.json"
        self.mutate(campaign, lambda doc: doc.update(policy_prompt="Changed without matching digest."))
        self.rewrite_campaign_digest(source)
        with self.assertRaisesRegex(ValueError, "policy prompt digest"):
            self.expand(source)
        self.assertFalse((self.root / "expanded").exists())

    def test_changed_missing_or_symlinked_prior_artifact_blocks_new_claim(self):
        source = self.prior()
        self.expand(source)
        artifact = next(source.glob("case-000/run/episodes/*/artifacts/synthetic-video.mp4"))
        original = artifact.read_bytes()
        artifact.write_bytes(b"changed bytes")
        output = self.root / "expanded"
        with patch("benchkit.campaigns.workflow.subprocess.Popen", side_effect=AssertionError("no launch")) as launch:
            with self.assertRaisesRegex(ValueError, "bound prior evidence changed"):
                run_case(output, 0, 0)
            artifact.unlink()
            with self.assertRaises(ValueError):
                run_case(output, 0, 0)
            outside = self.root / "outside"
            outside.write_bytes(original)
            artifact.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                run_case(output, 0, 0)
            launch.assert_not_called()
        self.assertFalse((output / "case-000").exists())

    def test_reintroduced_pilot_duplicate_case_and_changed_denominator_rejected_before_claim(self):
        source = self.prior()
        manifest = self.expand(source)
        output = self.root / "expanded"
        for change in (
                lambda m: m["cases"].__setitem__(0, {**cases_for("robocasa365", 200, 5)[0], "policy_endpoint": "/unused"}),
                lambda m: m["cases"].__setitem__(1, copy.deepcopy(m["cases"][0])),
                lambda m: m.update(selected_total=48),
                lambda m: m["coverage_ledger"]["entries"][4].update(disposition="new_case")):
            changed = copy.deepcopy(manifest)
            change(changed)
            with patch("benchkit.campaigns.workflow.load_campaign", return_value=changed), self.assertRaises(ValueError):
                run_case(output, 0, 0)
            self.assertFalse((output / "case-000").exists())

    def test_claimed_launch_failure_never_retried_and_frozen_auditors_verified(self):
        source = self.prior()
        self.expand(source)
        output = self.root / "expanded"
        with patch("benchkit.campaigns.workflow.subprocess.Popen", side_effect=OSError("synthetic launch failure")):
            with self.assertRaises(OSError):
                run_case(output, 0, 0)
            with self.assertRaises(FileExistsError):
                run_case(output, 0, 0)
        self.assertEqual(summarize(output)["infrastructure_or_policy_error"], 1)
        auditor = output / "frozen" / AUDIT_FILES[0]
        auditor.write_text(auditor.read_text() + "\n# changed\n")
        with self.assertRaisesRegex(ValueError, "frozen source changed"):
            run_case(output, 1, 0)
        self.assertFalse((output / "case-001").exists())

    def test_cli_scope_is_explicit_and_no_native_imports(self):
        completed = subprocess.run([sys.executable, "-m", "benchkit.campaigns.workflow", "prepare", "--help"],
                                   check=True, capture_output=True, text=True)
        self.assertIn("--task-scope", completed.stdout)
        self.assertIn("--carry-forward-campaign", completed.stdout)
        self.assertFalse(any(name in sys.modules for name in ("robocasa", "robosuite", "mujoco", "torch", "isaacsim")))


if __name__ == "__main__":
    unittest.main()
