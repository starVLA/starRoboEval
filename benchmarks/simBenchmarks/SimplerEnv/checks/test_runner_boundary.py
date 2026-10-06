"""Dependency-free checks for the policy/evaluator boundary used by SimplerEnv.

Run from the repository root:
    python3 -m unittest discover -s benchmarks/simBenchmarks/SimplerEnv/checks

These fixtures exercise harness behavior, not simulator success or model skill.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchkit.contracts import (
    ActionChunk,
    ActionSpec,
    BenchmarkDescriptor,
    EpisodeSpec,
    Observation,
    ObservationSpec,
    PolicyDecision,
    PolicyDescriptor,
    Transition,
    Usage,
)
from benchkit.errors import ProtocolError
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest
from benchkit.diagnostics.smoke import ReachBenchmark, ScriptedReachPolicy


class FixtureSession:
    def __init__(self):
        self.native_steps = 0
        self.artifact_dir = None
        self.closed = False

    def bind_artifact_dir(self, path):
        assert path.is_dir()
        self.artifact_dir = path

    def reset(self):
        assert self.artifact_dir is not None, "artifacts must bind before reset"
        return self.observation()

    def observation(self):
        return Observation(
            step=self.native_steps,
            instruction="Move the robot using the visible camera.",
            images={"rgb": b"fixture RGB bytes"},
            state=(0.0,),
        )

    def step(self, action):
        self.native_steps += 1
        return Transition(
            observation=self.observation(),
            reward=123.0,
            info={"success": True, "object_pose": [0.25, 0.5, 0.75]},
        )

    def metrics(self):
        return {"success": self.native_steps > 0}

    def artifacts(self):
        path = self.artifact_dir / "native.json"
        path.write_text('{"native_only": true}\n', encoding="utf-8")
        return {"native": str(path)}

    def close(self):
        self.closed = True


class FixtureBenchmark:
    descriptor = BenchmarkDescriptor("boundary-fixture", "1", "fixture/v1", "fixture")
    observation_spec = ObservationSpec(
        cameras=("rgb",), state_names=("joint",), modalities=("language", "rgb", "state")
    )
    action_spec = ActionSpec("joint_position", 1, low=(-1.0,), high=(1.0,))

    def __init__(self, episode_ids=None):
        self.episode_ids = episode_ids or ["object-x-0.25-seed-99"]
        self.sessions = []

    def episodes(self, seed, limit=None):
        return [
            EpisodeSpec(
                id=episode_id,
                task="public-task",
                seed=99,
                instruction="Configured task placeholder.",
                metadata={"object_pose": [0.25, 0.5, 0.75], "reset_options": {"id": 17}},
            )
            for episode_id in self.episode_ids[:limit]
        ]

    def open_episode(self, episode):
        session = FixtureSession()
        self.sessions.append(session)
        return session


class FixturePolicy:
    descriptor = PolicyDescriptor("boundary-policy", "scripted", version="1")

    def __init__(self, callback=None):
        self.callback = callback or (lambda: PolicyDecision(action=ActionChunk.from_steps([[0.1]])))
        self.contexts = []
        self.observations = []
        self.ended = 0

    def compatibility_errors(self, observation_spec, action_spec):
        return []

    def start_episode(self, context):
        self.contexts.append(context)

    def act(self, observation):
        self.observations.append(observation)
        return self.callback()

    def end_episode(self):
        self.ended += 1


class RunnerBoundaryChecks(unittest.TestCase):
    def run_fixture(self, policy=None, benchmark=None, **options):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        benchmark = benchmark or FixtureBenchmark()
        policy = policy or FixturePolicy()
        run_dir = EvaluationRunner().run(
            benchmark,
            policy,
            RunRequest(output_dir=Path(temporary.name), max_steps=options.pop("max_steps", 2), **options),
        )
        result = json.loads((run_dir / "episodes.jsonl").read_text().splitlines()[0])
        events_path = next((run_dir / "episodes").glob("*/events.jsonl"))
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        return benchmark, policy, run_dir, result, events

    def test_private_reset_context_and_native_info_never_reach_policy(self):
        benchmark, policy, run_dir, result, events = self.run_fixture()
        context = policy.contexts[0]
        self.assertEqual(context.episode.id, "episode-000000")
        self.assertEqual(context.episode.task, "public-task")
        self.assertEqual(context.episode.instruction, policy.observations[0].instruction)
        self.assertFalse(hasattr(context.episode, "seed"))
        self.assertFalse(hasattr(context.episode, "metadata"))
        for observation in policy.observations:
            self.assertEqual(set(observation.images), {"rgb"})
            self.assertEqual(observation.metadata, {})
            self.assertFalse(hasattr(observation, "reward"))
            self.assertFalse(hasattr(observation, "info"))
        self.assertEqual(result["episode"]["seed"], 99)
        self.assertIn("object_pose", result["episode"]["metadata"])
        self.assertTrue(any(event.get("info", {}).get("object_pose") for event in events))
        artifact = Path(result["artifacts"]["native"])
        self.assertTrue(artifact.is_file())
        self.assertIn(run_dir, artifact.parents)
        self.assertTrue(benchmark.sessions[0].closed)

    def test_failed_policy_act_still_counts_attempt(self):
        def malformed():
            return PolicyDecision(action=ActionChunk.from_steps([[True]]))

        benchmark, policy, _, result, events = self.run_fixture(FixturePolicy(malformed))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["category"], "policy")
        self.assertEqual(result["policy_calls"], 1)
        self.assertIsNone(result["usage"]["calls"])
        self.assertIsNone(result["usage"]["input_tokens"])
        self.assertEqual(result["environment_steps"], 0)
        self.assertEqual(benchmark.sessions[0].native_steps, 0)
        self.assertEqual(policy.ended, 1)
        self.assertEqual(sum(event["event"] == "policy_call_start" for event in events), 1)
        self.assertTrue(Path(result["artifacts"]["native"]).is_file())

    def test_artifact_failure_is_visible_without_hiding_primary_policy_error(self):
        class BrokenArtifactSession(FixtureSession):
            def artifacts(self):
                raise OSError("video encoder unavailable")

        class BrokenArtifactBenchmark(FixtureBenchmark):
            def open_episode(self, episode):
                session = BrokenArtifactSession()
                self.sessions.append(session)
                return session

        for malformed in (False, True):
            with self.subTest(malformed=malformed):
                policy = FixturePolicy(lambda: None) if malformed else FixturePolicy()
                benchmark, _, _, result, events = self.run_fixture(policy, BrokenArtifactBenchmark())
                expected_category = "policy" if malformed else "infrastructure"
                self.assertEqual(result["error"]["category"], expected_category)
                error = result["error"]["artifact_error"] if malformed else result["error"]
                self.assertIn("video encoder unavailable", error["message"])
                self.assertTrue(any(event["event"] == "artifact_error" for event in events))
                self.assertTrue(benchmark.sessions[0].closed)

    def test_multi_inference_method_executes_with_separate_provider_and_policy_counts(self):
        policy = FixturePolicy(
            lambda: PolicyDecision(
                action=ActionChunk.from_steps([[0.1]]),
                usage=Usage(calls=2, input_tokens=40, output_tokens=12, estimated_cost_usd=0.01),
            )
        )
        benchmark, _, run_dir, result, events = self.run_fixture(policy)
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["error"])
        self.assertEqual(result["usage"]["calls"], 4)
        self.assertEqual(result["usage"]["input_tokens"], 80)
        self.assertEqual(result["usage"]["estimated_cost_usd"], 0.02)
        self.assertEqual(result["policy_calls"], 2)
        self.assertEqual(result["environment_steps"], 2)
        self.assertEqual(benchmark.sessions[0].native_steps, 2)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        self.assertEqual(manifest["protocol"]["usage_accounting_version"],
                         "starvla-rsi.method-usage/v1")
        decisions = [event for event in events if event["event"] == "policy_decision"]
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(event["usage"]["calls"] == 2 for event in decisions))

    def test_all_chunk_actions_validate_before_prefix_execution(self):
        for invalid in (2.0, float("nan"), "0.5", True):
            with self.subTest(invalid=invalid):
                policy = FixturePolicy(lambda: PolicyDecision(action=ActionChunk(((0.1,), (invalid,)))))
                benchmark, _, _, result, _ = self.run_fixture(policy, replan_interval=1)
                self.assertEqual(result["error"]["category"], "policy")
                self.assertEqual(result["policy_calls"], 1)
                self.assertEqual(benchmark.sessions[0].native_steps, 0)

    def test_accepted_full_chunk_is_logged_even_when_only_prefix_executes(self):
        policy = FixturePolicy(lambda: PolicyDecision(action=ActionChunk.from_steps([[0.1], [0.2]])))
        _, _, _, result, events = self.run_fixture(policy, max_steps=1, replan_interval=1)
        self.assertEqual(result["environment_steps"], 1)
        chunks = [event for event in events if event["event"] == "action_chunk"]
        self.assertEqual(chunks[0]["actions"], [[0.1], [0.2]])
        self.assertEqual(chunks[0]["maximum_executed_prefix"], 1)

    def test_policy_call_limit_stops_before_an_extra_request(self):
        _, policy, _, result, _ = self.run_fixture(max_steps=10, max_policy_calls=2)
        self.assertEqual(result["policy_calls"], 2)
        self.assertEqual(len(policy.observations), 2)
        self.assertEqual(result["termination_reason"], "runner:policy_call_limit")

    def test_episode_path_collisions_rejected_before_run_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            with self.assertRaisesRegex(ProtocolError, "collide"):
                EvaluationRunner().run(
                    FixtureBenchmark(["pose/a", "pose_a"]),
                    FixturePolicy(),
                    RunRequest(output_dir=output_dir),
                )
            self.assertEqual(list(output_dir.iterdir()), [])

    def test_usage_cannot_underreport_with_fractional_or_boolean_counters(self):
        for calls in (0.5, True):
            with self.subTest(calls=calls), self.assertRaises(TypeError):
                Usage(calls=calls)

    def test_unavailable_usage_is_not_zero_and_keeps_observed_policy_calls(self):
        reported = iter([Usage(calls=1, input_tokens=42, latency_s=0.5), Usage.unavailable(latency_s=0.7)])
        policy = FixturePolicy(lambda: PolicyDecision(
            action=ActionChunk.from_steps([[0.1]]), usage=next(reported)
        ))
        _, _, run_dir, result, _ = self.run_fixture(policy, max_steps=2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["policy_calls"], 2)
        self.assertIsNone(result["usage"]["calls"])
        self.assertIsNone(result["usage"]["input_tokens"])
        self.assertAlmostEqual(result["usage"]["latency_s"], 1.2)
        summary = json.loads((run_dir / "summary.json").read_text())
        self.assertEqual(summary["policy_calls"], 2)
        self.assertIsNone(summary["usage"]["calls"])
        self.assertIsNone(summary["usage"]["estimated_cost_usd"])
        self.assertEqual(summary["by_task"]["public-task"]["policy_calls"], 2)

    def test_usage_null_propagates_in_both_addition_orders(self):
        unknown = Usage.unavailable()
        known = Usage(calls=1, input_tokens=10)
        self.assertEqual((known + unknown).to_dict(), unknown.to_dict())
        self.assertEqual((unknown + known).to_dict(), unknown.to_dict())

    def test_sessions_without_artifact_binding_remain_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = EvaluationRunner().run(
                ReachBenchmark(), ScriptedReachPolicy(), RunRequest(output_dir=Path(temporary))
            )
            summary = json.loads((run_dir / "summary.json").read_text())
            self.assertEqual(summary["successes"], 3)


if __name__ == "__main__":
    unittest.main()
