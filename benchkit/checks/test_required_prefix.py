"""Optional public action-prefix contract; synthetic worlds, no native SIM."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.contracts import ActionChunk, Observation, PolicyDecision, Transition
from benchkit.errors import InfrastructureError, ProtocolError
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.sim_server.client import SimServerBenchmarkAdapter
from benchkit.sim_server.server import BenchmarkService
from benchkit.diagnostics.smoke import ReachBenchmark, ScriptedReachPolicy


class RequiredPrefixChecks(unittest.TestCase):
    def describe(self, requirement=1):
        benchmark = ReachBenchmark()
        if requirement is not None:
            benchmark.required_replan_interval = requirement
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(benchmark, root=Path(directory) / "server", seed=0, limit=1)
            return service.dispatch("describe", {})

    def client(self, description):
        with patch.object(SimServerBenchmarkAdapter, "_rpc", return_value=deepcopy(description)):
            return SimServerBenchmarkAdapter("http://127.0.0.1:1", "synthetic-credential")

    def test_requirement_survives_service_client_boundary_without_native_open(self):
        with patch.object(ReachBenchmark, "open_episode", side_effect=AssertionError("no native open")):
            description = self.describe()
            client = self.client(description)
        self.assertEqual(description["budget"]["required_replan_interval"], 1)
        self.assertEqual(client.required_replan_interval, 1)
        self.assertIsNone(client.max_policy_calls)

    def test_old_description_retains_existing_budget_shape(self):
        description = self.describe(None)
        self.assertNotIn("required_replan_interval", description["budget"])
        self.assertIsNone(getattr(self.client(description), "required_replan_interval", None))

    def test_invalid_native_requirement_rejected_without_creating_service_directory(self):
        for value in (True, 0, -1, 1.0, "1"):
            benchmark = ReachBenchmark()
            benchmark.required_replan_interval = value
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "server"
                with self.assertRaises(ValueError):
                    BenchmarkService(benchmark, root=root, seed=0, limit=1)
                self.assertFalse(root.exists())

    def test_invalid_remote_requirement_rejected(self):
        description = self.describe()
        for value in (None, True, 0, -1, 1.0, "1"):
            with self.subTest(value=value):
                description["budget"]["required_replan_interval"] = value
                with self.assertRaises(InfrastructureError):
                    self.client(description)

    def test_wrong_prefix_rejected_before_policy_schedule_or_output(self):
        benchmark = ReachBenchmark()
        benchmark.required_replan_interval = 1
        for prefix in (None, 2, True, 1.0):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "results"
                with patch.object(benchmark, "episodes", side_effect=AssertionError("no schedule")):
                    with self.assertRaises(ProtocolError):
                        EvaluationRunner().run(benchmark, object(), RunRequest(
                            output_dir=root, replan_interval=prefix))
                self.assertFalse(root.exists())

    def test_invalid_local_requirement_rejected_before_policy(self):
        for value in (True, 0, -1, 1.0, "1"):
            benchmark = ReachBenchmark()
            benchmark.required_replan_interval = value
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ProtocolError):
                    EvaluationRunner().run(benchmark, object(), RunRequest(
                        output_dir=Path(directory), replan_interval=1))

    def test_small_call_budget_is_allowed_and_requirement_recorded(self):
        benchmark = ReachBenchmark()
        benchmark.required_replan_interval = 1
        with tempfile.TemporaryDirectory() as directory:
            run = EvaluationRunner().run(benchmark, ScriptedReachPolicy(), RunRequest(
                output_dir=Path(directory), episode_limit=1, max_steps=1,
                max_policy_calls=1, replan_interval=1, run_id="synthetic-prefix"))
            manifest = json.loads((run / "manifest.json").read_text())
            self.assertEqual(manifest["protocol"]["required_replan_interval"], 1)
            self.assertEqual(manifest["protocol"]["max_policy_calls"], 1)
            self.assertEqual(json.loads((run / "summary.json").read_text())["errors"], 0)


class ChangingInstructionEpisode:
    def __init__(self):
        self.actions = []

    def reset(self):
        return Observation(step=0, instruction="first", state=(0.0,))

    def step(self, action):
        self.actions.append(action)
        return Transition(observation=Observation(step=len(self.actions),
            instruction=f"after-{len(self.actions)}", state=(0.0,)), reward=0.0)

    def metrics(self):
        return {"success": False, "synthetic_controls": len(self.actions)}

    def artifacts(self):
        return {}

    def close(self):
        pass


class ActualChunkPrefixChecks(unittest.TestCase):
    def check_chunk_boundary(self, remote):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = ChangingInstructionEpisode()
            benchmark = ReachBenchmark()
            benchmark.required_replan_interval = 1
            benchmark.open_episode = lambda _: native
            policy = ScriptedReachPolicy()
            observed = []

            def act(observation):
                observed.append(observation.instruction)
                return PolicyDecision(action=ActionChunk.from_steps(((-0.5,), (0.5,))))

            policy.act = act
            request = RunRequest(output_dir=root / "result", episode_limit=1,
                                 max_steps=2, max_policy_calls=2, replan_interval=1)
            if remote:
                service = BenchmarkService(benchmark, root=root / "server", seed=0, limit=1)
                with patch.object(SimServerBenchmarkAdapter, "_rpc",
                                  side_effect=lambda op, params: service.dispatch(op, params)):
                    client = SimServerBenchmarkAdapter("http://127.0.0.1:1", "synthetic-review")
                    run = EvaluationRunner().run(client, policy, request)
            else:
                run = EvaluationRunner().run(benchmark, policy, request)
            self.assertEqual(native.actions, [(-0.5,), (-0.5,)])
            self.assertEqual(observed, ["first", "after-1"])
            self.assertEqual(json.loads((run / "summary.json").read_text())["errors"], 0)
            episode, = [json.loads(line) for line in (run / "episodes.jsonl").read_text().splitlines()]
            self.assertEqual(episode["policy_calls"], 2)
            self.assertEqual(episode["environment_steps"], 2)

    def test_long_chunk_cannot_cross_unseen_instruction_locally(self):
        self.check_chunk_boundary(remote=False)

    def test_long_chunk_cannot_cross_unseen_instruction_through_service(self):
        self.check_chunk_boundary(remote=True)


if __name__ == "__main__":
    unittest.main()
