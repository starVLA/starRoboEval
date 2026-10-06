"""Native-free GR1 Tabletop service wiring; not asset or renderer validation."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from benchmarks.simBenchmarks.Robocasa_tabletop import server
from benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter import (
    CAMERA, PILOT_SEED, TabletopBenchmarkAdapter, TabletopEpisode,
)
from benchkit.source_snapshot import SERVICE_SOURCE_FILES

DIRECTORY = Path(__file__).resolve().parents[1]


def example():
    return json.loads((DIRECTORY / "server.example.json").read_text())


class TabletopServerChecks(unittest.TestCase):
    def test_example_selects_one_pinned_29_joint_task_and_explicit_paths(self):
        parameters = example()
        adapter = server.make_tabletop(parameters)
        episode, = adapter.episodes(PILOT_SEED)
        self.assertEqual(adapter.descriptor.name, "robocasa_tabletop")
        self.assertEqual(adapter.descriptor.source_revision, "4840e671596f93ca03651524b9f72ffb1aadfeff")
        self.assertEqual(episode.task, "gr1_unified/PnPCupToDrawerClose_GR1ArmsAndWaistFourierHands_Env")
        self.assertEqual(episode.metadata["attempt"], 1)
        self.assertEqual(episode.metadata["candidate_layout_ids"], [4])
        self.assertEqual(episode.metadata["candidate_style_ids"], list(range(12)))
        self.assertEqual(adapter.observation_spec.cameras, ("ego_view_bg_crop_pad_res256_freq20",))
        self.assertEqual(len(adapter.observation_spec.state_names), 29)
        self.assertEqual(adapter.action_spec.size, 29)
        self.assertEqual((adapter.budget_mode, adapter.max_policy_calls, adapter.replan_interval),
                         ("horizon", None, None))
        self.assertEqual(adapter.descriptor.protocol_version,
                         "gr1-tabletop-pilot-0-19/rgb256-qpos29/control-1000/v2")
        self.assertEqual(adapter.environment_step_cap, 1000)
        self.assertEqual(adapter.sources["robocasa"], Path(parameters["casa_source"]).resolve())
        self.assertEqual(adapter.sources["robosuite"], Path(parameters["suite_source"]).resolve())
        self.assertEqual(adapter.object_inventory, Path(parameters["object_inventory"]))

    def test_factory_rejects_unknown_tasks_and_incompatible_limits(self):
        for update in ({"task_ids": [0, 0]}, {"task_ids": [1]}, {"task_scope": "full"},
                       {"budget_mode": "decisions"}, {"max_policy_calls": 201},
                       {"replan_interval": True}, {"render_gpu_device_id": -1},
                       {"policy": "hidden-policy"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                server.make_tabletop({**example(), **update})
        adapter = server.make_tabletop(example())
        with self.assertRaises(ValueError):
            adapter.episodes(PILOT_SEED, 2)
        with self.assertRaises(ValueError):
            adapter.episodes(0)

    def test_entrypoint_uses_only_its_benchmark_factory(self):
        with patch.object(server, "launch", return_value=0) as launch:
            self.assertEqual(server.main(["--help"]), 0)
        launch.assert_called_once_with(server.make_tabletop, supplemental_sources=server.SUPPLEMENTAL_FILES, argv=["--help"])

    def test_launcher_captures_contract_without_native_reset_or_gpu_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "server"
            http = Mock(server_port=8768)
            seen = []

            def connect(service, **kwargs):
                seen.append(service.dispatch("describe", {}))
                self.assertEqual(service.claims, set())
                self.assertEqual(service.sessions, {})
                self.assertEqual(service.excluded, ())
                return http

            with (patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": "s" * 48}),
                  patch("benchkit.sim_server.launch.make_http_server", side_effect=connect),
                  patch.object(TabletopBenchmarkAdapter, "open_episode", side_effect=AssertionError("native open")),
                  redirect_stdout(io.StringIO()) as stdout):
                result = server.main(["--parameters", str(DIRECTORY / "server.example.json"),
                                      "--seed", str(PILOT_SEED), "--episodes", "1",
                                      "--output-dir", str(output), "--port", "8768"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue())["native_resets"], 0)
            http.serve_forever.assert_called_once_with(poll_interval=0.25)
            http.server_close.assert_called_once()
            self.assertEqual(seen[0]["descriptor"]["name"], "robocasa_tabletop")
            self.assertEqual(seen[0]["budget"]["environment_step_cap"], 1000)
            self.assertEqual(seen[0]["budget"], {"budget_mode": "horizon", "max_policy_calls": None,
                                               "replan_interval": None, "environment_step_cap": 1000})
            self.assertEqual({row["path"] for row in seen[0]["source"]["supplemental_files"]},
                             set(server.SUPPLEMENTAL_FILES))
            index = json.loads((output / "harness_source/index.json").read_text())
            shared = {row["path"]: row for row in index["files"]}
            self.assertEqual(set(shared), set(SERVICE_SOURCE_FILES))
            supplemental = {row["path"]: row for row in seen[0]["source"]["supplemental_files"]}
            self.assertFalse(set(shared) & set(supplemental))
            for captured_root, inventory in (("harness_source/files", shared), ("service_source", supplemental)):
                for relative, row in inventory.items():
                    original = (DIRECTORY.parents[2] / relative).read_bytes()
                    captured = (output / captured_root / relative).read_bytes()
                    self.assertEqual(captured, original)
                    self.assertEqual(row["size_bytes"], len(captured))
                    self.assertEqual(row["sha256"], hashlib.sha256(captured).hexdigest())

    def test_example_factory_does_not_import_native_packages_or_model(self):
        code = """
import json, sys
from benchmarks.simBenchmarks.Robocasa_tabletop.server import make_tabletop
with open('benchmarks/simBenchmarks/Robocasa_tabletop/server.example.json') as stream:
    adapter = make_tabletop(json.load(stream))
assert len(adapter.episodes(20260907)) == 1
for name in ('numpy', 'robocasa', 'robosuite', 'mujoco', 'gymnasium', 'AgentPolicies'):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name
"""
        completed = subprocess.run([sys.executable, "-B", "-S", "-c", code],
                                   cwd=DIRECTORY.parents[2], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


class TabletopControlBudgetChecks(unittest.TestCase):
    def test_legacy_default_and_explicit_decision_identities_are_unchanged(self):
        for scope, selection, version in (("pilot", "pilot-0-19", "0.1.0"),
                ("tabletop-next-pair-v1", "next-pair-1-2", "0.2.0")):
            with self.subTest(scope=scope):
                default = TabletopBenchmarkAdapter(task_scope=scope)
                explicit = TabletopBenchmarkAdapter(task_scope=scope, budget_mode="decisions",
                                                     max_policy_calls=200, replan_interval=5)
                self.assertEqual(default.descriptor, explicit.descriptor)
                self.assertEqual(default.descriptor.version, version)
                self.assertEqual(default.descriptor.protocol_version,
                                 f"gr1-tabletop-{selection}/rgb256-qpos29/decision-200-prefix-5/v1")
                self.assertEqual(default.budget_metadata(), explicit.budget_metadata())
                self.assertEqual(default.budget_metadata(), {
                    "budget_mode": "decisions", "max_policy_calls": 200, "replan_interval": 5,
                    "environment_step_cap": 1000,
                    "budget_status": "provisional_development_not_final_public_budget",
                    "native_engine_horizon": 1000, "native_ignore_done": True, "native_control_hz": 20})
        for arguments in ({"max_policy_calls": None}, {"replan_interval": None},
                          {"max_policy_calls": 201}, {"replan_interval": 6}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                TabletopBenchmarkAdapter(**arguments)

    def test_independent_control_cap_preserves_native_contract_and_selection(self):
        legacy = TabletopBenchmarkAdapter()
        for cap in (1, 7, 1000):
            with self.subTest(cap=cap):
                adapter = TabletopBenchmarkAdapter(budget_mode="horizon", control_step_cap=cap)
                self.assertEqual(adapter.environment_step_cap, cap)
                self.assertIsNone(adapter.max_policy_calls)
                self.assertIsNone(adapter.replan_interval)
                self.assertTrue(adapter.descriptor.protocol_version.endswith(f"/control-{cap}/v2"))
                self.assertEqual(adapter.action_spec, legacy.action_spec)
                self.assertEqual(adapter.observation_spec, legacy.observation_spec)
                self.assertEqual(adapter.task_ids, legacy.task_ids)
                for old, new in zip(legacy.episodes(PILOT_SEED), adapter.episodes(PILOT_SEED)):
                    self.assertEqual((old.id, old.task, old.seed, old.instruction),
                                     (new.id, new.task, new.seed, new.instruction))
                    expected = {**old.metadata, "budget_mode": "horizon", "max_policy_calls": None,
                                "replan_interval": None, "environment_step_cap": cap}
                    self.assertEqual(new.metadata, expected)
        self.assertEqual(TabletopBenchmarkAdapter(budget_mode="horizon").environment_step_cap, 1000)

    def test_invalid_and_mixed_budget_parameters_fail_before_native_open(self):
        bad = [{"budget_mode": "horizon", "control_step_cap": value}
               for value in (None, True, 0, -1, 1001, 1.0, "1000")]
        bad += [{"budget_mode": "horizon", key: value}
                for key in ("max_policy_calls", "replan_interval") for value in (None, 1, 5, 200)]
        bad += [{"control_step_cap": value} for value in (None, 1, 1000)]
        bad += [{"budget_mode": "unknown"}]
        with patch.object(TabletopBenchmarkAdapter, "open_episode") as opened:
            for arguments in bad:
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    server.make_tabletop(arguments)
            opened.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec("numpy") is not None, "NumPy is needed for wire RGB fixtures")
    def test_service_client_runner_uses_policy_prefix_without_changing_total_cap(self):
        import numpy as np
        from benchkit.contracts import ActionChunk, Observation, PolicyDecision, PolicyDescriptor
        from benchkit.sim_server.client import SimServerBenchmarkAdapter
        from benchkit.sim_server.server import BenchmarkService
        from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest

        # Only reset/observation/native I/O are fixtures. The real adapter step,
        # scorer flag handling, cap, shared wire and runner remain under test.
        class Session(TabletopEpisode):
            def reset(self):
                self.reset_started = True
                self.started_at = time.monotonic()
                def native_step(_):
                    ending = self.step_count + 1 == 3
                    success = ending and native_end == "success"
                    return ({}, float(success), ending and native_end == "done",
                            ending and native_end == "truncated", {"success": success})
                self.env = SimpleNamespace(step=native_step, close=lambda: None)
                return self._observe({})

            def _observe(self, raw):
                return Observation(self.step_count, "Fixture task.",
                    images={CAMERA: np.zeros((256, 256, 3), dtype=np.uint8)}, state=(0.,) * 29)

        class Policy:
            descriptor = PolicyDescriptor("tabletop-prefix-fixture", "scripted", version="1")
            def compatibility_errors(self, *_): return []
            def start_episode(self, context): self.context = context
            def end_episode(self): pass
            def act(self, observation):
                return PolicyDecision(action=ActionChunk.from_steps([[0.] * 29] * 7))

        cases = ((None, 4, None, 10), (6, 4, None, 10), (2, 8, None, 10), (None, 1, None, 7),
                 (None, 4, "success", 3), (None, 4, "done", 3), (None, 4, "truncated", 3))
        for prefix, call_cap, native_end, expected_steps in cases:
            with self.subTest(prefix=prefix, call_cap=call_cap, native_end=native_end), \
                    tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = TabletopBenchmarkAdapter(task_ids=[0], budget_mode="horizon", control_step_cap=10)
                with patch.object(adapter, "open_episode", side_effect=lambda ep: Session(adapter, ep)):
                    service = BenchmarkService(adapter, root=root / "server", seed=PILOT_SEED, limit=1)
                    with patch.object(SimServerBenchmarkAdapter, "_rpc", side_effect=service.dispatch), \
                         patch("benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter.action_dictionary",
                               return_value={}):
                        remote = SimServerBenchmarkAdapter("http://127.0.0.1:8768", "s" * 48)
                        policy = Policy()
                        output = EvaluationRunner().run(remote, policy, RunRequest(
                            root / "client", seed=PILOT_SEED, episode_limit=1, max_steps=10,
                            max_policy_calls=call_cap, replan_interval=prefix, budget_mode="horizon"))
                result = json.loads((output / "episodes.jsonl").read_text().splitlines()[0])
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["environment_steps"], expected_steps)
                self.assertEqual(result["success"], native_end == "success")
                if native_end:
                    self.assertEqual(result["policy_calls"], 1)
                    self.assertEqual(result["action_decisions"], 1)
                    expected_end = "truncated" if native_end == "truncated" else "terminated"
                    self.assertEqual(result["termination_reason"], f"environment:{expected_end}")
                self.assertEqual(policy.context.replan_interval, prefix)
                self.assertEqual(policy.context.max_policy_calls, call_cap)
                self.assertEqual(service.description["budget"], {
                    "budget_mode": "horizon", "max_policy_calls": None,
                    "replan_interval": None, "environment_step_cap": 10})
                self.assertEqual(len(service.claims), 1)
                record, = service.sessions.values()
                self.assertEqual(record["controls"], expected_steps)
                self.assertEqual(record["state"], "closed")
                self.assertIsNone(record["cleanup_error"])


if __name__ == "__main__":
    unittest.main()
