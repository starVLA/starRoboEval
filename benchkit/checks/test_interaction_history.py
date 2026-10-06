"""Fixed synthetic records, with no simulator, policy or source-snapshot setup."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.audits.closed_run import AuditError, audit_run
from benchkit.reports.interaction_history import build_history, export_history, main, render_html


SECRET = "PRIVATE_ORACLE_AND_CREDENTIAL_SENTINEL"
KNOWN = {"calls": 1, "input_tokens": 3, "output_tokens": 1, "cached_input_tokens": 0,
         "estimated_cost_usd": None, "latency_s": 0.1}
ZERO = {key: 0 for key in KNOWN}
NOTE = '<script>alert("model output")</script> & measured motion'
STAMP = "2026-10-01T00:00:00.000Z"


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root, turns=None, *, dimensions=1, feedback_schema=None, missing_usage=False):
    """Build the frozen event shapes emitted by the runner, not an imitation runtime."""
    turns = turns or [{"actions": [[0.1] * dimensions, [0.2] * dimensions, [0.3] * dimensions],
                       "acks": 2, "terminated": True, "success": True, "structured": True}]
    root.mkdir()
    folder = root / "episodes" / "fixture-episode"
    folder.mkdir(parents=True)
    spec = {"id": "task/seed7", "task": "fixture-task", "seed": 7,
            "instruction": "Move the robot.", "metadata": {"oracle": SECRET}}
    protocol = {"episode_ids": [spec["id"]], "max_steps": 10, "max_policy_calls": 5,
                "replan_interval": 3, "budget_mode": "horizon", "fail_fast": False,
                "execution_feedback_version": "starvla-rsi.execution-feedback/v1",
                "invalid_action_handling": "feedback",
                "action_rejection_feedback_version": "starvla-rsi.action-rejection-feedback/v1"}
    obs_spec = {"cameras": ["head"], "state_names": ["joint"], "modalities": ["language", "state", "rgb"],
                "privileged": False}
    if feedback_schema:
        obs_spec["control_feedback_schema"] = feedback_schema
        protocol.update(control_feedback_schema=feedback_schema,
                        control_acknowledgement_version="starvla-rsi.control-acknowledgement/v1")
    manifest = {"schema_version": "starvla-rsi.eval/v1", "run_id": "fixed-records",
        "benchmark": {"name": "fixture-benchmark", "version": "v1", "protocol_version": "fixture/v1",
                      "source_revision": "recorded-upstream", "metadata": SECRET},
        "policy": {"name": "fixture-policy", "kind": "scripted-fixture", "version": "v1",
                   "provider": "declared-only", "model": "unknown", "parameters": {"token": SECRET}},
        "observation_spec": obs_spec,
        "action_spec": {"mode": "joint_position", "size": dimensions,
                        "names": [f"axis-{i}" for i in range(dimensions)], "control_hz": 10,
                        "frame": "robot", "rotation": None, "gripper": None, "low": None, "high": None},
        "protocol": protocol, "runtime": {"executable": "/private/" + SECRET},
        "harness_source": {"path": "absent-private-source-index"}}

    def observation(step):
        row = {"step": step, "instruction": "Move the robot.", "camera_names": ["head"],
               "state": [float(step)], "metadata": {"oracle": SECRET}}
        if feedback_schema and step:
            row["control_feedback"] = {"schema": feedback_schema, "control_target": step,
                                       "unknown_private_extension": SECRET}
        return row

    events = [{"event": "episode_start", "timestamp": STAMP, "episode": spec},
              {"event": "observation", "timestamp": STAMP, "observation": observation(0)}]
    controls = decisions = rejects = 0
    error = None
    success = False
    reason = "runner:policy_call_limit"
    usage = dict.fromkeys(KNOWN, None) if missing_usage else dict(KNOWN)
    for index, turn in enumerate(turns, 1):
        events.append({"event": "policy_call_start", "timestamp": STAMP, "policy_call": index})
        phase = turn.get("reject")
        action = turn.get("actions", [])
        stop = turn.get("stop", False)
        if phase != "policy_act" and not turn.get("call_error"):
            note = turn.get("note", NOTE)
            metadata = {"provider_receipt": {"secret": SECRET}, "arbitrary": SECRET}
            if turn.get("structured"):
                metadata["structured_output"] = {"stop": stop, "stop_reason": "give_up" if stop else None,
                                                 "actions": action, "note": note}
            events.append({"event": "policy_decision", "timestamp": STAMP, "policy_call": index,
                "note": note, "metadata": metadata, "usage": usage, "stop": stop,
                "stop_reason": "give_up" if stop else None, "chunk_length": len(action)})
        if action and phase not in ("policy_act", "action_spec") and not turn.get("call_error"):
            events.append({"event": "action_chunk", "timestamp": STAMP, "policy_call": index,
                           "actions": action, "maximum_executed_prefix": min(len(action), 3, 10 - controls)})
        played = turn.get("acks", 0)
        ack_rows = []
        for chunk_index in range(played):
            controls += 1
            decisions += int(chunk_index == 0)
            observed = observation(controls)
            terminated = turn.get("terminated", False) and chunk_index == played - 1
            events.append({"event": "environment_step", "timestamp": STAMP, "policy_call": index,
                "chunk_index": chunk_index, "environment_step": controls, "action": action[chunk_index],
                "reward": 0.0, "terminated": terminated, "truncated": False,
                "info": {"scorer": SECRET}, "observation": observed})
            if feedback_schema:
                ack_rows.append({"environment_step": controls, "observation_step": controls,
                                 "payload": observed["control_feedback"]})
        if phase:
            rejects += 1
            feedback = {"schema_version": "starvla-rsi.action-rejection-feedback/v1",
                        "policy_calls": index, "action_decisions": decisions, "environment_steps": controls,
                        "executed_steps": played, "rejected_actions": rejects,
                        "issue": {"code": "invalid_action", "field": "action", "actual": None,
                                  "limit": None, "action_index": None}}
            if feedback_schema:
                feedback["control_acks"] = ack_rows
            events.append({"event": "action_rejected", "timestamp": STAMP, "policy_call": index,
                "phase": phase, "feedback": feedback, "usage": usage if phase == "policy_act" else ZERO,
                "usage_recorded_in": "action_rejected" if phase == "policy_act" else "policy_decision",
                "metadata": {"private": SECRET}})
        if turn.get("call_error") or turn.get("error"):
            error = {"category": "infrastructure", "type": "InfrastructureError", "message": SECRET,
                     "traceback": "/private/" + SECRET}
            if turn.get("call_error"):
                error.update(policy_call=index, usage=usage, metadata={"provider_receipt": SECRET})
            events.append({"event": "error", "timestamp": STAMP, "error": error})
            reason = "error:infrastructure"
        elif stop:
            reason = "policy:give_up"
        elif turn.get("terminated"):
            reason = "environment:terminated"
            success = turn.get("success", False)
    total_usage = {key: None if value is None else value * len(turns) for key, value in usage.items()}
    result = {"schema_version": "starvla-rsi.eval/v1", "episode": spec,
              "status": "error" if error else "completed", "success": None if error else success,
              "termination_reason": reason, "policy_calls": len(turns), "environment_steps": controls,
              "action_decisions": decisions, "rejected_actions": rejects, "reward_sum": 0.0,
              "duration_s": 1.0, "usage": total_usage, "metrics": {"success": success, "oracle": SECRET},
              "artifacts": {"video": "/private/" + SECRET}, "error": error}
    events.append({"event": "episode_end", "timestamp": STAMP, "result": result})
    write_json(root / "manifest.json", manifest)
    write_json(root / "status.json", {"status": "completed_with_errors" if error else "completed", "episodes_written": 1})
    write_json(root / "summary.json", {"run_id": "fixed-records", "benchmark": "fixture-benchmark",
        "policy": "fixture-policy", "attempted": 1, "completed": int(not error), "errors": int(bool(error)),
        "successes": int(success and not error), "policy_calls": len(turns), "rejected_actions": rejects,
        "usage": total_usage})
    write_json(root / "episodes.jsonl", result)
    write_json(folder / "result.json", result)
    (folder / "events.jsonl").write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    return root


class InteractionHistoryChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def run_fixture(self, turns=None, **kwargs):
        return fixture(self.root / "run", turns, **kwargs)

    def rewrite_events(self, run, change):
        path = next((run / "episodes").glob("*/events.jsonl"))
        events = [json.loads(line) for line in path.read_text().splitlines()]
        change(events)
        path.write_text("".join(json.dumps(event) + "\n" for event in events))

    def test_projects_real_record_shapes_without_source_snapshot_or_private_fields(self):
        run = self.run_fixture(feedback_schema="fixture.robot-feedback/v1")
        with self.assertRaises((AuditError, FileNotFoundError)):
            audit_run(run)  # Missing source evidence still fails the independent full audit.
        history = build_history(run)
        self.assertEqual(history["outcome"]["scope"], "client_selected_schedule")
        episode = history["episodes"][0]
        call = episode["calls"][0]
        self.assertEqual(episode["seed"], 7)
        self.assertEqual(episode["counters"], {"policy_calls": 1, "action_decisions": 1, "controls": 2, "rejected_actions": 0})
        self.assertEqual(call["input_to_policy"]["origin"], "reset")
        self.assertEqual(call["decision"]["structured_output"]["content"]["note"], NOTE)
        self.assertEqual(call["unacknowledged_actions"], [{"chunk_index": 2, "status": "not_attempted"}])
        self.assertEqual(call["acknowledged_controls"][-1]["observation"]["robot_feedback"]["availability"],
                         "recorded_payload_not_projected")
        self.assertEqual(history["contracts"]["observation"]["state_names"], ["joint"])
        self.assertEqual(history["contracts"]["action"]["frame"], "robot")
        self.assertNotIn(SECRET, json.dumps(history))
        self.assertNotIn("provider_receipt", json.dumps(history))

    def test_rejection_reuses_reset_then_next_call_uses_latest_ack(self):
        run = self.run_fixture([{"reject": "policy_act"}, {"actions": [[0.1], [0.2]], "acks": 2}, {"stop": True}])
        calls = build_history(run)["episodes"][0]["calls"]
        self.assertEqual(calls[0]["input_to_policy"], calls[1]["input_to_policy"])
        self.assertEqual(calls[2]["input_to_policy"]["step"], 2)
        self.assertEqual(calls[2]["input_to_policy"]["origin"], "acknowledged_control")
        self.assertEqual(calls[0]["rejection"]["executed_controls"], 0)
        self.assertIsNone(calls[0]["decision"])
        self.assertTrue(calls[2]["decision"]["stop"])

    def test_action_spec_rejection_does_not_invent_missing_vectors(self):
        run = self.run_fixture([{"actions": [[2.0]], "reject": "action_spec"}, {"stop": True}])
        first = build_history(run)["episodes"][0]["calls"][0]
        self.assertEqual(first["decision"]["chunk_length"], 1)
        self.assertIsNone(first["submitted_actions"])
        self.assertEqual(first["actions_availability"], "not_recorded")

    def test_partial_prefix_rejection_preserves_ack_and_marks_only_rejected_vector(self):
        run = self.run_fixture([{"actions": [[0.1], [0.2], [0.3], [0.4]], "acks": 1, "reject": "session_step"}, {"stop": True}])
        first, second = build_history(run)["episodes"][0]["calls"]
        self.assertEqual(len(first["acknowledged_controls"]), 1)
        self.assertEqual([row["status"] for row in first["unacknowledged_actions"]],
                         ["rejected_without_execution", "not_attempted", "not_selected_for_execution"])
        self.assertEqual(second["input_to_policy"]["step"], 1)

    def test_partial_prefix_error_does_not_assert_an_attempt_or_zero_execution(self):
        run = self.run_fixture([{"actions": [[0.1], [0.2], [0.3], [0.4]], "acks": 1, "error": True}])
        first = build_history(run)["episodes"][0]["calls"][0]
        self.assertEqual([row["status"] for row in first["unacknowledged_actions"]],
                         ["execution_not_confirmed_attempt_not_recorded", "not_attempted", "not_selected_for_execution"])
        self.assertEqual(first["error"], {"category": "infrastructure", "details": "recorded_privately"})

    def test_call_failure_and_unknown_usage_have_no_fabricated_model_output(self):
        run = self.run_fixture([{"call_error": True}], missing_usage=True)
        first = build_history(run)["episodes"][0]["calls"][0]
        self.assertIsNone(first["decision"])
        self.assertIsNone(first["usage"]["calls"])
        self.assertEqual(first["acknowledged_controls"], [])

    def add_collection_failure(self, run, *, primary_policy_error=False, cleanup=False):
        folder = next((run / "episodes").iterdir())
        result = json.loads((folder / "result.json").read_text())
        events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
        artifact = {"category": "infrastructure", "type": "RuntimeError", "message": SECRET}
        if primary_policy_error:
            primary = next(event["error"] for event in events if event["event"] == "error")
            primary.update(category="policy", type="PolicyCallError")
            result["error"] = {**primary, "artifact_error": artifact}
        else:
            result["error"] = artifact
        if cleanup:
            result["error"]["cleanup_errors"] = ["session.close: " + SECRET]
        result.update(status="error", success=None, termination_reason="error:" + result["error"]["category"])
        events[-1]["result"] = result
        events.insert(-1, {"event": "artifact_error", "timestamp": STAMP, "error": artifact})
        write_json(folder / "result.json", result)
        write_json(run / "episodes.jsonl", result)
        (folder / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
        write_json(run / "status.json", {"status": "completed_with_errors", "episodes_written": 1})
        summary = json.loads((run / "summary.json").read_text())
        summary.update(completed=0, errors=1, successes=0)
        write_json(run / "summary.json", summary)

    def test_collection_and_cleanup_do_not_overwrite_primary_call_failure(self):
        run = self.run_fixture([{"call_error": True}])
        self.add_collection_failure(run, primary_policy_error=True, cleanup=True)
        episode = build_history(run)["episodes"][0]
        self.assertEqual(episode["calls"][0]["error"]["category"], "policy")
        self.assertEqual(episode["error"]["category"], "policy")
        self.assertEqual([item["stage"] for item in episode["aftermath_errors"]], ["artifact_collection", "cleanup"])
        self.assertNotIn(SECRET, json.dumps(episode))

    def test_collection_error_after_native_terminal_does_not_imply_model_or_action_failure(self):
        run = self.run_fixture()
        self.add_collection_failure(run)
        episode = build_history(run)["episodes"][0]
        call = episode["calls"][0]
        self.assertIsNone(call["error"])
        self.assertEqual(call["unacknowledged_actions"], [{"chunk_index": 2, "status": "not_attempted"}])
        self.assertEqual(episode["aftermath_errors"][0]["stage"], "artifact_collection")

    def test_error_after_completed_prefix_is_not_attributed_to_model_call(self):
        run = self.run_fixture([{"actions": [[0.1], [0.2], [0.3]], "acks": 3, "error": True}])
        episode = build_history(run)["episodes"][0]
        self.assertIsNone(episode["calls"][0]["error"])
        self.assertEqual(episode["aftermath_errors"][0]["stage"], "after_call")

    def test_two_dimensional_native_failure_has_same_generic_interface(self):
        run = self.run_fixture([{"actions": [[0.2, 0.3]], "acks": 1, "terminated": True}], dimensions=2)
        history = build_history(run)
        self.assertEqual(history["outcome"]["successes"], 0)
        self.assertFalse(history["episodes"][0]["success"])
        self.assertEqual(history["contracts"]["action"]["size"], 2)

    def test_recorded_observation_index_is_not_invented_from_control_count(self):
        run = self.run_fixture()
        def change(rows):
            for event in rows:
                if event["event"] == "environment_step":
                    event["observation"]["step"] = event["environment_step"] * 10
        self.rewrite_events(run, change)
        last = build_history(run)["episodes"][0]["calls"][0]["acknowledged_controls"][-1]["observation"]
        self.assertEqual(last["step"], 20)
        self.assertEqual(last["acknowledged_controls"], 2)

    def test_existing_mailbox_output_is_projected_without_endpoint_or_request_identity(self):
        run = self.run_fixture()
        def change(rows):
            event = next(row for row in rows if row["event"] == "policy_decision")
            output = event["metadata"].pop("structured_output")
            event["metadata"].update(request_id=SECRET, observation_path="/private/" + SECRET,
                response_path="/private/" + SECRET, structured_response={"request_id": SECRET,
                "usage": KNOWN, "actions": output["actions"], "note": output["note"]})
        self.rewrite_events(run, change)
        output = build_history(run)["episodes"][0]["calls"][0]["decision"]["structured_output"]
        self.assertEqual(output["availability"], "recorded_projection")
        self.assertEqual(output["content"]["actions"], [[0.1], [0.2], [0.3]])
        self.assertNotIn(SECRET, json.dumps(output))

    def test_existing_eef_output_is_bound_to_its_recorded_vector(self):
        vector = [0.0, 0.1, 0.2, 1.0, 0.0, 0.0, 0.0, 0.0] * 2
        run = self.run_fixture([{"actions": [vector], "acks": 1, "terminated": True}], dimensions=16)
        def change(rows):
            event = next(row for row in rows if row["event"] == "policy_decision")
            event["metadata"]["structured_output"] = {"request_id": SECRET, "mode": "eef", "steps": 1,
                "reason": event["note"], "target": {side: {"position": vector[:3], "quaternion_wxyz": vector[3:7],
                    "gripper_closed": True} for side in ("left", "right")}}
        self.rewrite_events(run, change)
        output = build_history(run)["episodes"][0]["calls"][0]["decision"]["structured_output"]
        self.assertEqual(output["content"]["target"]["left"]["position"], vector[:3])
        self.assertNotIn(SECRET, json.dumps(output))
        def corrupt(rows):
            event = next(row for row in rows if row["event"] == "policy_decision")
            event["metadata"]["structured_output"]["target"]["left"]["gripper_closed"] = False
        self.rewrite_events(run, corrupt)
        with self.assertRaisesRegex(AuditError, "EEF output/action"):
            build_history(run)

    def test_exports_escaped_standalone_html_without_mutating_source(self):
        run = self.run_fixture()
        before = {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob("*") if p.is_file()}
        target = self.root / "view"
        history = export_history(run, target)
        page = (target / "index.html").read_text()
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn(SECRET, page)
        self.assertEqual(json.loads((target / "history.json").read_text()), history)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["history.json", "index.html"])
        self.assertEqual(before, {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob("*") if p.is_file()})
        with self.assertRaisesRegex(AuditError, "new"):
            export_history(run, target)
        with self.assertRaisesRegex(AuditError, "outside"):
            export_history(run, run / "view")

    def test_refuses_symlink_input_and_output_and_does_not_follow_artifact_paths(self):
        run = self.run_fixture()
        alias = self.root / "alias"
        alias.symlink_to(run, target_is_directory=True)
        with self.assertRaisesRegex(AuditError, "symlink"):
            build_history(alias)
        with self.assertRaisesRegex(AuditError, "symlink"):
            export_history(run, alias / "view")
        events = next((run / "episodes").glob("*/events.jsonl"))
        external = self.root / "external.jsonl"
        events.rename(external)
        events.symlink_to(external)
        with self.assertRaisesRegex(AuditError, "symlink"):
            build_history(run)

    def test_rejects_malformed_or_inconsistent_events_before_creating_output(self):
        run = self.run_fixture()
        self.rewrite_events(run, lambda rows: next(r for r in rows if r["event"] == "environment_step").update(environment_step=9))
        with self.assertRaises(AuditError):
            export_history(run, self.root / "view")
        self.assertFalse((self.root / "view").exists())

    def test_malformed_decision_metadata_is_an_explicit_record_error(self):
        run = self.run_fixture()
        self.rewrite_events(run, lambda rows: next(r for r in rows if r["event"] == "policy_decision").update(metadata=[SECRET]))
        with self.assertRaisesRegex(AuditError, "decision metadata must be an object"):
            build_history(run)

    def test_malformed_nested_response_is_an_explicit_record_error(self):
        run = self.run_fixture()
        def change(rows):
            decision = next(r for r in rows if r["event"] == "policy_decision")
            decision["metadata"]["structured_response"] = [SECRET]
        self.rewrite_events(run, change)
        with self.assertRaisesRegex(AuditError, "recorded structured response must be an object"):
            build_history(run)

    def test_change_after_staged_writes_publishes_no_complete_looking_output(self):
        run = self.run_fixture()
        from benchkit.reports import interaction_history as module
        original = module._Files.verify_unchanged
        calls = 0
        def check(files):
            nonlocal calls
            calls += 1
            if calls == 3:
                (run / "summary.json").write_text("{}")
            return original(files)
        target = self.root / "view"
        with patch.object(module._Files, "verify_unchanged", new=check):
            with self.assertRaisesRegex(AuditError, "changed"):
                export_history(run, target)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".rsi-interaction-*")), [])

    def test_rejects_duplicate_json_nonfinite_privileged_and_source_change(self):
        run = self.run_fixture()
        path = run / "manifest.json"
        original = path.read_text()
        for contents in ('{"run_id":1,"run_id":2}', '{"value":NaN}'):
            path.write_text(contents)
            with self.assertRaises((AuditError, KeyError)):
                build_history(run)
        manifest = json.loads(original)
        manifest["observation_spec"]["privileged"] = True
        write_json(path, manifest)
        with self.assertRaisesRegex(AuditError, "non-privileged"):
            build_history(run)
        path.write_text(original)
        from benchkit.reports import interaction_history as module
        original_render = render_html

        def changed(history):
            (run / "summary.json").write_text("{}")
            return original_render(history)

        with patch.object(module, "render_html", side_effect=changed):
            with self.assertRaisesRegex(AuditError, "changed"):
                export_history(run, self.root / "view")
        self.assertFalse((self.root / "view").exists())

    def test_unknown_output_shape_is_not_dumped_and_cli_is_offline(self):
        run = self.run_fixture()
        def change(rows):
            event = next(row for row in rows if row["event"] == "policy_decision")
            event["metadata"]["structured_output"] = {"arbitrary_provider_body": SECRET}
        self.rewrite_events(run, change)
        history = build_history(run)
        self.assertEqual(history["episodes"][0]["calls"][0]["decision"]["structured_output"]["availability"],
                         "unsupported_record_shape")
        with patch("socket.socket", side_effect=AssertionError("no network")), \
             patch("subprocess.Popen", side_effect=AssertionError("no process execution")), \
             patch("builtins.print"):
            self.assertEqual(main(["--run-dir", str(run), "--output-dir", str(self.root / "view")]), 0)


if __name__ == "__main__":
    unittest.main()
