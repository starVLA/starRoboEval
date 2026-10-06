"""CPU-only checks for the one published RoboDojo Direct v2 contract."""
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchkit.errors import ActionRejected, ProtocolError
from benchmarks.simBenchmarks.RoboDojo.bench_server import adapter


def target(opening=1.0):
    return [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, opening] * 2


def tick(n, *, success=False, ended=False, horizon=adapter.HORIZON):
    truncated = ended and not success and n >= horizon
    terminated = ended and not truncated
    return {"terminated": terminated, "truncated": truncated,
        "metrics": {"success": success, "native_end_flag": ended,
            "native_alive_flag": success or not ended,
            "native_reward": 1.0 if success else 0.0,
            "control_targets": n, "native_take_action_count": n,
            "native_reward_evaluations": n, "physics_ticks": n * 10}}


class DirectContractChecks(unittest.TestCase):
    def benchmark(self, **updates):
        values = {"runtime_manifest": "/deployment/runtime.json",
            "runtime_manifest_sha256": "a" * 64, "panel": "fast"}
        values.update(updates)
        with patch.object(adapter, "load_runtime", return_value={"python": "/native/bin/python"}):
            return adapter.make_reference_eef(values)

    def test_single_factory_has_no_protocol_selector_or_policy_budget(self):
        value = self.benchmark()
        self.assertIs(type(value), adapter.DirectEEFBenchmarkAdapter)
        self.assertEqual(value.descriptor.protocol_version, adapter.INTERFACE_PROTOCOL)
        self.assertEqual([row.metadata["layout_id"] for row in value.episodes()], list(range(5)))
        self.assertIsNone(value.max_policy_calls)
        self.assertIsNone(value.replan_interval)
        for forbidden in ({"protocol_track": "reference-eef-v2"},
                          {"robot_feedback": "robodojo.robot-control-feedback/v1"},
                          {"layout_ids": [0, 3]}, {"panel": "unknown"},
                          {"max_policy_calls": 200}, {"replan_interval": 5}):
            with self.subTest(forbidden=forbidden), self.assertRaises((TypeError, ValueError)):
                self.benchmark(**forbidden)

    def test_action_is_absolute_dual_eef_and_only_validity_is_benchmark_owned(self):
        self.assertEqual(adapter.validate_action(target()), tuple(target()))
        self.assertEqual(adapter.DirectEEFBenchmarkAdapter.validate_action_input(target()), tuple(target()))
        moved = target()
        moved[0], moved[8] = 100.0, -100.0
        self.assertEqual(adapter.DirectEEFBenchmarkAdapter.validate_action_input(moved), tuple(moved))
        for bad in (target()[:-1], target(float("nan")), target(-0.1)):
            with self.subTest(bad=bad), self.assertRaises((ActionRejected, ProtocolError, ValueError)):
                adapter.DirectEEFBenchmarkAdapter.validate_action_input(bad)
        bad = target()
        bad[3:7] = [2.0, 0.0, 0.0, 0.0]
        with self.assertRaises(ActionRejected):
            adapter.DirectEEFBenchmarkAdapter.validate_action_input(bad)

    def test_reset_launches_sibling_environment_with_importable_repository(self):
        benchmark = self.benchmark()
        benchmark.python = Path(sys.executable)
        session = benchmark.open_episode(benchmark.episodes()[0])
        benchmark_root = Path(__file__).resolve().parents[1]
        repository = benchmark_root.parents[2]
        with tempfile.TemporaryDirectory() as directory:
            session.bind_artifact_dir(Path(directory))
            try:
                with (patch.dict(os.environ, {"OMNI_KIT_ACCEPT_EULA": "yes",
                                             "RSI_SIM_SERVER_TOKEN": "test-secret"}),
                      patch.object(benchmark, "runtime_document", return_value={"recording_support": "/recording"}),
                      patch.object(adapter.subprocess, "Popen") as popen,
                      patch.object(session, "_rpc", return_value={}) as rpc,
                      patch.object(session, "_observation", return_value="public-observation")):
                    self.assertEqual(session.reset(), "public-observation")
                command = popen.call_args.args[0]
                self.assertEqual(Path(command[2]), benchmark_root / "environment/native_eef_worker.py")
                self.assertTrue(Path(command[2]).is_file())
                environment = popen.call_args.kwargs["env"]
                self.assertEqual(environment["PYTHONPATH"].split(os.pathsep)[0], str(repository))
                self.assertTrue((repository / "benchmarks/simBenchmarks/RoboDojo/server.py").is_file())
                self.assertNotIn("RSI_SIM_SERVER_TOKEN", environment)
                self.assertEqual(rpc.call_args.args[0]["layout_id"], 0)
            finally:
                if session.log is not None:
                    session.log.close()

    def test_native_tick_flags_distinguish_success_failure_and_timeout(self):
        self.assertEqual(adapter.validate_direct_tick_result(tick(4), 4), (False, False, False, 0.0))
        self.assertEqual(adapter.validate_direct_tick_result(tick(4, success=True, ended=True), 4),
                         (True, True, False, 1.0))
        self.assertEqual(adapter.validate_direct_tick_result(tick(adapter.HORIZON, ended=True), adapter.HORIZON),
                         (False, False, True, 0.0))
        with self.assertRaises(ProtocolError):
            adapter.validate_direct_tick_result(tick(adapter.HORIZON), adapter.HORIZON)

    def test_public_state_is_closed_robot_only_vector(self):
        state = [0.0] * 6 + [1.0] + [0.0] * 6 + [1.0]
        state += [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0] * 2
        self.assertEqual(adapter.public_state(state), tuple(state))
        for bad in (state[:-1], [*state[:17], 0.0, 0.0, 0.0, 0.0, *state[21:]],
                    [float("nan"), *state[1:]]):
            with self.subTest(), self.assertRaises(ProtocolError):
                adapter.public_state(bad)

    def test_frame_reader_rejects_escape_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frame.png").write_bytes(b"frame")
            with adapter.open_frame(root, "frame.png") as stream:
                self.assertEqual(stream.read(), b"frame")
            for name in ("../frame.png", "/frame.png", "a\\b"):
                with self.subTest(name=name), self.assertRaises(ProtocolError):
                    adapter.open_frame(root, name)
            (root / "link.png").symlink_to("frame.png")
            with self.assertRaises(OSError):
                adapter.open_frame(root, "link.png")


if __name__ == "__main__":
    unittest.main()
