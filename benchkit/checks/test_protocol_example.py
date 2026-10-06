"""Educational driver checks through the real client and a fake loopback service.

Synthetic actions below test infrastructure only; they are not model results.
"""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from AgentPolicies.protocol_example import driver
from benchkit.checks.test_sim_server_client import fixture, observation
from benchkit.contracts import EpisodeSpec, ObservationSpec
from benchkit.recording import RecordingOptions
from benchkit.reports.basic_result import build_result, export_result
from benchkit.sim_server.client import RemoteEpisode, SimServerBenchmarkAdapter


METHOD = {"schema_version": "starvla-rsi.method/v1", "id": "educational-fixture",
          "version": "1", "models": [], "configuration": {"purpose": "offline test only"}}


def configured(state, endpoint, **budget):
    state.description["budget"].update(budget_mode="horizon", max_policy_calls=None)
    state.description["budget"].update(budget)
    state.files = []
    return SimServerBenchmarkAdapter(endpoint, "private-credential")


def closed(root):
    return json.loads((root / "episodes.jsonl").read_text())


def operations(state):
    return [call["op"] for call in state.calls]


class ProtocolExampleTests(unittest.TestCase):
    def run_example(self, client, directory, decide, **kwargs):
        return driver.run_one(client, decide, seed=0, method=METHOD,
                              output_dir=Path(directory).resolve() / "run", run_id="fixture-case", **kwargs)

    def test_import_does_not_connect_or_load_a_native_model_backend(self):
        with patch("http.client.HTTPConnection", side_effect=AssertionError("no connection")):
            importlib.reload(driver)
        source = Path(driver.__file__).read_text()
        for module in ("AgentPolicies.policy_support", "benchkit.model_profiles", "benchkit.sim_server.client"):
            self.assertNotIn("from " + module, source)
        self.assertLessEqual(len(source.splitlines()), 250)

    def test_full_horizon_closed_report_without_source_or_event_requirement(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            seen = []
            def decide(data):
                seen.append(deepcopy(data))
                return {"action": [0.25]}
            root = self.run_example(client, directory, decide)
            result = closed(root)
            self.assertEqual((result["policy_calls"], result["action_decisions"], result["environment_steps"]), (2, 2, 2))
            self.assertEqual(result["termination_reason"], "driver:control_limit")
            self.assertIs(result["success"], False)
            self.assertIsNone(result["usage"]["calls"])
            self.assertEqual([row["counters"]["environment_steps"] for row in seen], [0, 1])
            self.assertEqual(operations(state), ["describe", "open", "reset", "step", "step", "metrics", "finish"])
            report = build_result(root)
            self.assertEqual(report["outcome"]["completed"], 1)
            self.assertEqual(report["outcome"]["errors"], 0)
            self.assertFalse((root / "source").exists())
            export_result(root, Path(directory).resolve() / "report")
            self.assertTrue((Path(directory) / "report" / "result.json").exists())

    def test_projection_hides_administration_and_native_scoring(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            state.description["observation_spec"] = ObservationSpec(
                state_names=("robot_joint",), modalities=("language", "state")).to_dict()
            state.description["episodes"][0]["metadata"] = {"oracle": "PRIVATE_TASK"}
            original = state.result
            def response(request):
                value = original(request)
                if request["op"] in ("reset", "step"):
                    obs = value["observation"] if request["op"] == "reset" else value["transition"]["observation"]
                    obs.update(state=[0.5], metadata={"oracle": "PRIVATE_OBSERVATION"})
                if request["op"] == "step":
                    value["transition"].update(reward=999, info={"score": "PRIVATE_TRANSITION"})
                return value
            state.result = response
            client = configured(state, endpoint)
            seen = []
            def decide(data):
                seen.append(deepcopy(data))
                data["state"][0] = 999
                data["action_spec"]["size"] = 400
                return {"action": [0]}
            root = self.run_example(client, directory, decide)
            self.assertEqual(len(seen), 2)
            for row in seen:
                self.assertEqual(set(row), {"episode", "instruction", "images", "state", "control_feedback",
                                           "observation_spec", "action_spec", "counters"})
                self.assertEqual(row["state"], [0.5])
                self.assertEqual(row["episode"], "episode-000000")
                self.assertEqual(row["action_spec"]["size"], 1)
            public = json.dumps(seen)
            for hidden in ("PRIVATE_", "private-credential", "synthetic-server", "session-0", "task-0", "reward", "seed"):
                self.assertNotIn(hidden, public)
            self.assertNotIn("PRIVATE_", json.dumps(build_result(root)))

    def test_native_terminal_stops_before_another_callback(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            state.terminal = True
            state.override["metrics"] = {"metrics": {"success": True}}
            result = closed(self.run_example(client, directory, lambda _: {"action": [0]}))
            self.assertEqual(result["policy_calls"], 1)
            self.assertTrue(result["success"])
            self.assertEqual(result["termination_reason"], "environment:terminated")

    def test_stop_counts_decision_without_robot_control(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            root = self.run_example(client, directory, lambda _: {"stop": True, "reason": "give_up"})
            result = closed(root)
            self.assertEqual((result["policy_calls"], result["environment_steps"]), (1, 0))
            self.assertEqual(result["termination_reason"], "policy:give_up")
            self.assertNotIn("step", operations(state))
            self.assertEqual(build_result(root)["outcome"]["completed"], 1)

    def test_declared_optional_call_cap_is_preserved(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint, max_policy_calls=1, environment_step_cap=5)
            result = closed(self.run_example(client, directory, lambda _: {"action": [0]}))
            self.assertEqual(result["environment_steps"], 1)
            self.assertEqual(result["termination_reason"], "driver:declared_call_limit")

    def test_standard_and_minimal_have_same_actor_inputs_actions_and_outcomes(self):
        runs = []
        with tempfile.TemporaryDirectory() as directory:
            for mode in ("standard", "minimal"):
                with fixture() as (state, _, endpoint):
                    client = configured(state, endpoint)
                    seen = []
                    def decide(data):
                        seen.append(deepcopy(data))
                        return {"action": [0.25]}
                    root = self.run_example(client, Path(directory) / mode, decide, recording=RecordingOptions(mode))
                    result = closed(root)
                    runs.append((seen, [r["params"]["action"] for r in state.calls if r["op"] == "step"],
                                 result["success"], result["environment_steps"]))
                    self.assertEqual(bool(list(root.rglob("callback_events.jsonl"))), mode == "standard")
                    self.assertEqual(bool(list(root.rglob("robot_events.jsonl"))), mode == "standard")
                    self.assertEqual(build_result(root)["outcome"]["completed"], 1)
            self.assertEqual(runs[0], runs[1])

    def test_unsupported_budgets_or_schedule_refused_before_claim(self):
        mutations = [lambda d: d["budget"].update(budget_mode="decisions", max_policy_calls=2),
                     lambda d: d["budget"].update(environment_step_cap=None),
                     lambda d: d["budget"].update(replan_interval=2),
                     lambda d: d["budget"].update(required_replan_interval=2),
                     lambda d: d["episodes"].append(EpisodeSpec("task-1", "task", 1, "Do task").to_dict()),
                     lambda d: d["observation_spec"].update(modalities=["depth"])]
        for mutate in mutations:
            with self.subTest(mutation=mutate), fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
                state.description["budget"].update(budget_mode="horizon", max_policy_calls=None)
                mutate(state.description)
                client = SimServerBenchmarkAdapter(endpoint, "private-credential")
                with self.assertRaises(ValueError):
                    self.run_example(client, directory, lambda _: {"action": [0]})
                self.assertEqual(operations(state), ["describe"])
                self.assertFalse((Path(directory) / "run").exists())

    def test_output_collision_refused_before_claim(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            (Path(directory) / "run").mkdir()
            with self.assertRaises(FileExistsError):
                self.run_example(client, directory, lambda _: {"action": [0]})
            self.assertEqual(operations(state), ["describe"])

    def test_invalid_action_has_no_rpc_execution_or_retry(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            root = self.run_example(client, directory, lambda _: {"action": [99]})
            result = closed(root)
            self.assertEqual((result["policy_calls"], result["rejected_actions"], result["environment_steps"]), (1, 1, 0))
            self.assertEqual(result["error"]["category"], "protocol")
            self.assertFalse(result["error"]["execution_uncertain"])
            self.assertNotIn("step", operations(state))
            self.assertEqual(operations(state).count("reset"), 1)
            self.assertEqual(build_result(root)["outcome"]["errors"], 1)

    def test_invalid_second_ack_preserves_last_count_and_never_replays(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint, environment_step_cap=4)
            original = state.result
            def response(request):
                value = original(request)
                if request["op"] == "step" and request["params"]["sequence"] == 2:
                    value["transition"]["observation"]["step"] = 100
                return value
            state.result = response
            root = self.run_example(client, directory, lambda _: {"action": [0]})
            result = closed(root)
            self.assertEqual((result["policy_calls"], result["environment_steps"]), (2, 1))
            self.assertTrue(result["error"]["execution_uncertain"])
            self.assertIsNone(result["success"])
            self.assertEqual(operations(state).count("step"), 2)
            self.assertEqual(operations(state).count("finish"), 1)
            self.assertNotIn("metrics", operations(state))
            self.assertEqual(build_result(root)["outcome"]["errors"], 1)

    def test_callback_exception_is_policy_error_unknown_usage_not_task_failure(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            def decide(_):
                raise RuntimeError("private-credential")
            root = self.run_example(client, directory, decide)
            result = closed(root)
            self.assertEqual(result["error"]["category"], "policy")
            self.assertEqual((result["policy_calls"], result["environment_steps"]), (1, 0))
            self.assertIsNone(result["usage"]["calls"])
            self.assertIsNone(result["success"])
            self.assertNotIn("private-credential", json.dumps(result))
            self.assertEqual(build_result(root)["outcome"]["errors"], 1)

    def test_malformed_reply_keeps_reported_usage_or_unknown(self):
        for reply, expected in (([], None), ({"action": [0], "stop": True, "usage": {"calls": 3}}, 3)):
            with self.subTest(reply=reply), fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
                client = configured(state, endpoint)
                root = self.run_example(client, directory, lambda _: reply)
                result = closed(root)
                self.assertEqual(result["usage"]["calls"], expected)
                self.assertEqual(result["error"]["category"], "protocol")
                self.assertNotIn("step", operations(state))
                self.assertEqual(build_result(root)["outcome"]["errors"], 1)

    def test_malformed_optional_usage_warns_without_blocking_controls(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            result = closed(self.run_example(client, directory, lambda _: {"action": [0], "usage": {"calls": -1}}))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["environment_steps"], 2)
            self.assertIsNone(result["usage"]["calls"])
            self.assertIn("invalid_usage_unavailable", result["recording"]["warnings"])

    def test_component_usage_is_reported_not_invented_from_aggregate(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            method = {**METHOD, "models": [{"id": "planner", "role": "planning"}, {"id": "actor", "role": "control"}]}
            root = driver.run_one(client, lambda _: {"action": [0], "usage": {"calls": 3},
                "component_usage": {"actor": {"calls": 2}}}, seed=0, method=method,
                output_dir=Path(directory).resolve() / "run", run_id="fixture-case")
            result = closed(root)
            self.assertEqual(result["usage"]["calls"], 6)
            self.assertEqual(result["component_usage"]["actor"]["calls"], 4)
            self.assertIsNone(result["component_usage"]["planner"]["calls"])
            self.assertEqual(build_result(root)["component_usage"], result["component_usage"])

    def test_invalid_native_metrics_is_infrastructure_error(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            state.override["metrics"] = {"metrics": {"success": 1}}
            result = closed(self.run_example(client, directory, lambda _: {"action": [0]}))
            self.assertEqual(result["error"]["category"], "infrastructure")
            self.assertEqual(result["environment_steps"], 2)
            self.assertIsNone(result["success"])

    def test_finish_failure_still_closes_without_a_second_finish_request(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            original = state.result
            def response(request):
                if request["op"] == "finish":
                    state.response_mode = "mismatch"
                return original(request)
            state.result = response
            with patch.object(RemoteEpisode, "close", autospec=True, side_effect=RemoteEpisode.close) as close:
                root = self.run_example(client, directory, lambda _: {"action": [0]})
            result = closed(root)
            self.assertEqual(close.call_count, 1)
            self.assertEqual(operations(state).count("finish"), 1)
            self.assertEqual(result["error"]["operation"], "artifacts")
            self.assertEqual(result["error"]["cleanup_errors"][0]["operation"], "close")
            self.assertIsNone(result["success"])
            self.assertEqual(build_result(root)["outcome"]["errors"], 1)

    def test_optional_recording_write_failure_cannot_change_execution(self):
        with fixture() as (state, _, endpoint), tempfile.TemporaryDirectory() as directory:
            client = configured(state, endpoint)
            with patch("benchkit.recording.append_jsonl", side_effect=OSError("unavailable")):
                root = self.run_example(client, directory, lambda _: {"action": [0]})
            result = closed(root)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["environment_steps"], 2)
            self.assertIn("interaction_recording_failed", result["recording"]["warnings"])
            self.assertEqual(build_result(root)["outcome"]["completed"], 1)


if __name__ == "__main__":
    unittest.main()
