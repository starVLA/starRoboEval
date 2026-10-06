"""Persistent robot-tool fixtures: no Codex inference or native simulation."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from benchkit.contracts import ActionRejectionFeedback, BenchmarkDescriptor, Observation, ObservationSpec, ExecutionFeedback
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError
from benchkit.model_profiles import create_policy
from benchkit.recording import RecordingOptions
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.tools import persistent_runtime as subject
from AgentPolicies.gpt6_astra.checks.fixtures import context


class FakeTransport:
    def __init__(self, policy):
        self.policy = policy
        self.requests, self.replies, self.events = [], [], []
        self.closed = False
        self.serial = 0
        self.override = None
        self.thread_summary = None
        self.thread_read_events = []

    def request(self, method, params, timeout):
        self.requests.append((method, params))
        if method == "turn/start":
            return {"turn": {"id": "turn-" + str(len(self.requests))}}
        if method == "thread/read" and self.thread_summary is not None:
            self.events[0:0] = self.thread_read_events
            return {"thread": deepcopy(self.thread_summary)}
        raise AssertionError(method)

    def reply(self, identifier, result):
        self.replies.append((identifier, result))

    def next_message(self, timeout):
        if self.events:
            event = self.events.pop(0)
            if isinstance(event, BaseException):
                raise event
            return event
        self.serial += 1
        arguments = proposal(self.policy.packet)
        if self.override:
            self.override(arguments)
        return {"id": self.serial, "method": "item/tool/call", "params": {
            "threadId": self.policy.thread_id, "turnId": self.policy.turn_id,
            "callId": f"call-{self.serial}", "tool": "robot_act", "arguments": arguments}}

    def diagnostics(self):
        return {"closed": self.closed, "requests": len(self.requests)}

    def close(self):
        self.closed = True


def proposal(packet):
    return {"request_id": packet["request_id"], "actions": [[.25, -.5]] * 5,
            "reason": "Choose a bounded control from the public observation.", "stop_reason": None}


class DirectChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.policy = create_policy("gpt6_astra", control_method="codex-direct/v3",
                                    **getattr(self, "policy_parameters", {}))
        self.context = context(benchmark=BenchmarkDescriptor("generic-fixture", "v",
            "arbitrary-public-protocol", "private-source"),
            observation_spec=ObservationSpec(cameras=("view_a", "view_b", "view_c"),
                state_names=("measured_joint", "last_command", "other_sensor")),
            max_steps=1100, max_policy_calls=1100, replan_interval=5, invalid_action_handling="feedback")
        self.policy.bind_artifact_dir(Path(self.temp.name) / "artifacts")
        self.policy.start_episode(self.context)
        self.fake = FakeTransport(self.policy)
        def boot():
            self.policy.transport = self.fake
            self.policy.thread_id = "one-thread"
        self.boot = patch.object(self.policy, "_boot", side_effect=boot)
        self.boot.start()
        self.addCleanup(self.boot.stop)
        self.addCleanup(self.policy.end_episode)
        self.obs = Observation(0, "Move according to the public task instruction", {
            camera: np.array([[[1, 127, 255]]], dtype=np.uint8)
            for camera in self.context.observation_spec.cameras},
            [.1, .2, .3], metadata={"oracle-marker": "forbidden"})

    def next(self, n=5):
        self.policy.observe_execution(ExecutionFeedback(self.policy.issued, self.policy.decisions + 1,
                                                       self.policy.controls + n, n))
        self.obs = replace(self.obs, step=self.policy.controls)
        return self.policy.act(self.obs)

    def test_one_thread_one_turn_many_robot_actions(self):
        first = self.policy.act(self.obs)
        self.assertEqual(first.action.steps[0][-1], -.5)
        second = self.next()
        self.assertEqual(first.action, second.action)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(len(self.fake.replies), 1)
        self.assertIsNone(first.usage.calls)
        payload = self.fake.requests[0][1]
        encoded = json.dumps(payload)
        for value in ("oracle-marker", "private-source", "private-opaque-marker", "private-task-marker",
                      "RSI_SIM_SERVER_TOKEN", "layout_id"):
            self.assertNotIn(value, encoded)
        self.assertEqual(len(payload["input"]), 4)

    def test_hooks_do_not_reply_or_make_model_requests(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 2, 2))
        self.assertEqual(len(self.fake.requests), 1)
        self.assertFalse(self.fake.replies)
        self.assertEqual(self.policy.controls, 2)

    def test_rejection_returns_same_observation_without_reset_or_execution(self):
        self.fake.override = lambda args: args.update(actions=[[99, 0]])
        with self.assertRaises(ActionRejected) as caught:
            self.policy.act(self.obs)
        packet = self.policy.packet
        self.policy.observe_rejection(ActionRejectionFeedback(caught.exception.issue, 1, 0, 0, 0, 1, ()))
        self.assertEqual((self.policy.controls, len(self.fake.replies)), (0, 0))
        self.fake.override = None
        result = self.policy.act(self.obs)
        self.assertEqual(result.action.steps[0][0], .25)
        reply = self.fake.replies[0][1]
        self.assertFalse(reply["success"])
        body = json.loads(reply["contentItems"][0]["text"])
        self.assertEqual(body["request_id"], packet["request_id"])
        self.assertEqual(body["validation_issue"]["code"], "out_of_bounds")
        self.assertEqual(body["rejected_controls_executed"], 0)
        self.assertEqual(len(reply["contentItems"]), 1)
        self.assertEqual(len(self.fake.requests), 1)
        self.next()
        self.assertEqual(Path(self.policy.packet["next_call"]["observation_path"]).parent.name, "000002")

    def test_partial_ack_is_not_replayed_and_uses_new_observation(self):
        self.policy.act(self.obs)
        self.policy.observe_rejection(ActionRejectionFeedback(ValidationIssue("invalid_action"), 1, 1, 2, 2, 1))
        self.policy.act(replace(self.obs, step=2))
        body = json.loads(self.fake.replies[0][1]["contentItems"][0]["text"])
        self.assertEqual(body["step_id"], 2)
        self.assertEqual(body["executed_prefix_controls"], 2)
        self.assertFalse(body["no_execution"])

    def test_native_closure_cancels_without_paid_final_continuation(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 3, 3))
        audit = self.policy.audit
        self.policy.end_episode()
        self.assertTrue(self.fake.closed)
        self.assertFalse(self.fake.replies)
        self.assertEqual(len(self.fake.requests), 1)
        record = json.loads((audit / "closed.json").read_text())
        self.assertEqual(record["executed_controls"], 3)
        self.assertEqual(record["final_ack_delivery"], "withheld_on_close")
        self.assertFalse((audit / "public_observations/000000/camera-000.png").exists())
        self.assertTrue((audit / "public_observations/000000/observation.json").is_file())

    def test_invalid_or_stale_response_is_rejected_without_execution(self):
        self.policy.act(self.obs)
        for mutate in (
            lambda a: a.update(request_id="stale"), lambda a: a.update(output_dir="/private"),
            lambda a: a.update(actions=[]), lambda a: a.update(actions=[[True, 0]]),
            lambda a: a.update(actions=[[0]]), lambda a: a.update(actions=[[float("nan"), 0]]),
            lambda a: a.update(actions=[[10**400, 0]]), lambda a: a.update(actions=[[2, 0]]),
            lambda a: a.update(actions=[[0, 0]] * 6), lambda a: a.update(actions="bad"),
            lambda a: a.update(reason=""), lambda a: a.update(reason="x" * 1025),
            lambda a: a.update(stop_reason="give_up", actions=[]),
        ):
            args = proposal(self.policy.packet)
            mutate(args)
            with self.subTest(args=args), self.assertRaises(ActionRejected):
                self.policy._validate_action(args, self.policy.packet)
        self.assertEqual(self.policy.controls, 0)

    def test_native_vectors_are_exact_without_eef_guards_or_gripper_conversion(self):
        self.policy.act(self.obs)
        args = proposal(self.policy.packet)
        args["actions"] = [[.8, -.75], [-.6, .3]]
        _, vectors = self.policy._validate_action(args, self.policy.packet)
        self.assertEqual(vectors, [(.8, -.75), (-.6, .3)])
        self.assertNotIn("enforce_action_guard", self.policy.config)
        self.assertNotIn("required_protocol", self.policy.config)

    def test_invalid_reason_and_actions_are_typed_rejections_not_infrastructure(self):
        for field, value in (("reason", ""), ("reason", "x" * 1025), ("actions", "bad")):
            self.fake.override = lambda args, field=field, value=value: args.update({field: value})
            with self.subTest(field=field), self.assertRaises(ActionRejected) as caught:
                self.policy.act(self.obs)
            self.policy.observe_rejection(ActionRejectionFeedback(caught.exception.issue,
                self.policy.issued, 0, 0, 0, self.policy.rejected + 1))
        self.assertEqual(self.policy.controls, 0)

    def test_public_export_rejects_modified_bytes(self):
        self.policy.end_episode()
        self.policy.configure_recording(RecordingOptions(images=True))
        self.policy.bind_artifact_dir(Path(self.temp.name) / "image-export")
        self.policy.start_episode(self.context)
        self.policy.act(self.obs)
        path = self.policy.public / "000000/camera-000.png"
        original = path.read_bytes()
        try:
            path.write_bytes(b"x" * len(original))
            with self.assertRaises(PolicyError):
                self.policy._export_public()
        finally:
            path.write_bytes(original)
            # Preserve the failed standalone export probe separately.
            (self.policy.audit / "public_observations").rename(self.policy.audit / "failed-probe-export")

    def test_public_export_never_follows_actor_added_symlinks(self):
        self.policy.act(self.obs)
        link = self.policy.public / "outside"
        link.symlink_to(self.policy.audit, target_is_directory=True)
        try:
            with self.assertRaises(PolicyError):
                self.policy._export_public()
        finally:
            link.unlink()

    def test_token_notifications_are_cumulative_not_provider_calls(self):
        for total in (100, 180):
            self.fake.events.append({"method": "thread/tokenUsage/updated", "params": {
                "threadId": "one-thread", "tokenUsage": {"total": {
                    "inputTokens": total, "cachedInputTokens": 10, "outputTokens": total // 10}}}})
            result = self.policy.act(self.obs) if total == 100 else self.next()
            self.assertEqual(result.usage.input_tokens, 100 if total == 100 else 80)
            self.assertIsNone(result.usage.calls)
        with self.assertRaises(PolicyError):
            self.policy._token_update({"tokenUsage": {"total": {"inputTokens": 1, "cachedInputTokens": 0, "outputTokens": 0}}})

    def test_no_automatic_action_replay_on_uncertain_transport(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 5, 5))
        with patch.object(self.fake, "reply", side_effect=TimeoutError("private text")) as reply:
            with self.assertRaises(PolicyCallError) as caught:
                self.policy.act(replace(self.obs, step=5))
        self.assertEqual(reply.call_count, 1)
        self.assertIsNone(self.policy.pending_rpc)
        self.assertNotIn("private text", str(caught.exception))

    def test_zero_usage_notice_is_not_free_inference(self):
        self.fake.events.append({"method": "thread/tokenUsage/updated", "params": {
            "threadId": "one-thread", "tokenUsage": {"total": {
                "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0}}}})
        result = self.policy.act(self.obs)
        self.assertIsNone(result.usage.input_tokens)
        self.assertEqual(result.metadata["provider_receipt"]["zero_or_unavailable_notices"], 1)

    def test_model_reroute_invalidates_the_attempt(self):
        self.fake.events.append({"method": "model/rerouted", "params": {"threadId": "one-thread"}})
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual(self.policy.issued, 0)

    def test_only_verified_closed_network_turn_can_continue(self):
        self.fake.events = [{"method": "turn/completed", "params": {"threadId": "one-thread",
            "turn": {"id": "turn-1", "status": "failed", "error": {"message": "stream disconnected"}}}}]
        with patch.object(subject.time, "sleep"):
            self.policy.act(self.obs)
        self.assertEqual(self.policy.network_continuations, 1)
        self.assertEqual(len(self.fake.requests), 2)
        self.assertTrue(all(row[1]["threadId"] == "one-thread" for row in self.fake.requests))
        self.assertFalse(self.fake.replies)
        self.assertFalse(subject._network_error({"message": "quota connection reset"}))

    @staticmethod
    def overload_event(turn=1, *, notification=False, will_retry=False):
        error = {"codexErrorInfo": "serverOverloaded", "message": "PRIVATE_PROVIDER_TEXT"}
        if notification:
            return {"method": "error", "params": {"threadId": "one-thread",
                "turnId": f"turn-{turn}", "willRetry": will_retry, "error": error}}
        return {"method": "turn/completed", "params": {"threadId": "one-thread",
            "turn": {"id": f"turn-{turn}", "status": "failed", "error": error}}}

    def test_overload_recovers_same_thread_after_ack_without_replaying(self):
        self.policy.act(self.obs)
        self.fake.events = [self.overload_event(notification=True), self.overload_event()]
        with patch.object(subject.time, "sleep") as sleep:
            decision = self.next()
        sleep.assert_called_once_with(30)
        self.assertEqual((self.policy.issued, self.policy.controls), (2, 5))
        self.assertEqual(len(self.fake.replies), 1)  # Exactly one ACK, never resent.
        self.assertEqual([row[0] for row in self.fake.requests], ["turn/start", "turn/start"])
        self.assertTrue(all(row[1]["threadId"] == "one-thread" for row in self.fake.requests))
        receipt = decision.metadata["provider_receipt"]
        self.assertEqual(receipt["overload_continuations"], 1)
        self.assertEqual(receipt["last_overload_error_code"], "server_overloaded")
        self.assertNotIn("PRIVATE_PROVIDER_TEXT", json.dumps(receipt))
        self.assertEqual(self.policy.overload_consecutive, 0)
        # A later failure gets a fresh per-submission allowance.
        self.fake.events = [self.overload_event(2)]
        with patch.object(subject.time, "sleep"):
            self.next()
        self.assertEqual(self.policy.overload_continuations, 2)

    def test_overload_stops_after_ten_failed_attempts(self):
        self.fake.events = [self.overload_event(n) for n in range(1, 11)]
        with patch.object(subject.time, "sleep") as sleep, self.assertRaises(PolicyCallError) as caught:
            self.policy.act(self.obs)
        self.assertEqual(sleep.call_count, 9)
        self.assertEqual(len(self.fake.requests), 10)
        self.assertEqual(self.policy.overload_continuations, 9)
        self.assertEqual((self.policy.issued, self.policy.controls), (0, 0))
        self.assertEqual(caught.exception.metadata["failure_code"], "server_overloaded_attempts_exhausted")
        self.assertNotIn("PRIVATE_PROVIDER_TEXT", json.dumps(caught.exception.metadata))

    def test_overload_notification_alone_never_continues(self):
        self.fake.events = [self.overload_event(notification=True), TimeoutError()]
        with patch.object(subject.time, "sleep") as sleep, self.assertRaises(PolicyCallError) as caught:
            self.policy.act(self.obs)
        sleep.assert_not_called()
        self.assertEqual([row[0] for row in self.fake.requests], ["turn/start"])
        self.assertEqual(caught.exception.metadata["failure_code"], "server_overloaded_unconfirmed_closure")

    def test_overload_provider_retry_notification_does_not_add_turn(self):
        self.fake.events = [self.overload_event(notification=True, will_retry=True)]
        self.policy.act(self.obs)
        self.assertEqual(self.policy.overload_continuations, 0)
        self.assertEqual(len(self.fake.requests), 1)

    def test_overload_uses_latest_terminal_error_not_earlier_capacity(self):
        terminal = self.overload_event()
        terminal["params"]["turn"]["error"] = {"codexErrorInfo": "usageLimitExceeded"}
        self.fake.events = [self.overload_event(notification=True), terminal]
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual(len(self.fake.requests), 1)

    def test_overload_stale_turn_completion_is_not_closure(self):
        self.fake.events = [self.overload_event(notification=True), self.overload_event(0), TimeoutError()]
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual(len(self.fake.requests), 1)

    def test_overload_cannot_survive_a_new_quota_error_notification(self):
        quota = self.overload_event(notification=True, will_retry=True)
        quota["params"]["error"] = {"codexErrorInfo": "usageLimitExceeded"}
        terminal = self.overload_event()
        terminal["params"]["turn"]["error"] = None
        self.fake.events = [self.overload_event(notification=True), quota, terminal]
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual(len(self.fake.requests), 1)

    def test_overload_requires_exact_structured_wire_enum(self):
        self.assertTrue(subject._overload_error({"codexErrorInfo": "serverOverloaded"}))
        for info in ("usageLimitExceeded", "unauthorized", "rateLimitExceeded", "other", None,
                     "server_overloaded", {"serverOverloaded": {}}, {"httpConnectionFailed": {"httpStatusCode": 503}}):
            with self.subTest(info=info):
                self.assertFalse(subject._overload_error({"codexErrorInfo": info,
                    "message": "server_overloaded model at capacity", "code": "server_overloaded"}))

    def test_overload_does_not_turn_quota_or_auth_into_retry(self):
        self.fake.events = [{"method": "error", "params": {"threadId": "one-thread", "turnId": "turn-1",
            "willRetry": False, "error": {"codexErrorInfo": "unauthorized", "message": "model at capacity"}}}]
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual(len(self.fake.requests), 1)

    def test_overload_must_not_cross_pending_action(self):
        self.policy.act(self.obs)
        self.fake.events = [self.overload_event()]
        with self.assertRaises(PolicyError):
            self.policy._next_action()
        self.assertEqual(len(self.fake.requests), 1)

    def test_timed_out_network_turn_reads_only_idle_thread_summary(self):
        self.fake.thread_summary = {"id": "one-thread", "status": {"type": "idle"}}
        self.fake.thread_read_events = [TimeoutError("empty post-read queue")]
        self.fake.events = [{"method": "error", "params": {"threadId": "one-thread",
            "turnId": "turn-1", "willRetry": False,
            "error": {"message": "stream disconnected"}}}, TimeoutError("idle fixture")]
        with patch.object(subject.time, "sleep"):
            self.policy.act(self.obs)
        self.assertEqual(self.policy.network_continuations, 1)
        self.assertEqual([row[0] for row in self.fake.requests], ["turn/start", "thread/read", "turn/start"])
        self.assertEqual(self.fake.requests[1][1], {"threadId": "one-thread", "includeTurns": False})
        self.assertNotIn("turns", self.fake.requests[1][1])

    def test_timed_out_network_turn_must_be_idle_before_continuing(self):
        self.fake.thread_summary = {"id": "one-thread", "status": {"type": "active"}}
        self.fake.events = [{"method": "error", "params": {"threadId": "one-thread",
            "turnId": "turn-1", "willRetry": False,
            "error": {"message": "stream disconnected"}}}, TimeoutError("idle fixture")]
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual(self.policy.network_continuations, 0)
        self.assertEqual([row[0] for row in self.fake.requests], ["turn/start", "thread/read"])

    def test_retrying_error_is_not_summary_recovery_proof(self):
        self.fake.thread_summary = {"id": "one-thread", "status": {"type": "idle"}}
        self.fake.events = [{"method": "error", "params": {"threadId": "one-thread",
            "turnId": "turn-1", "willRetry": True,
            "error": {"message": "stream disconnected"}}}, TimeoutError("idle fixture")]
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual([row[0] for row in self.fake.requests], ["turn/start"])

    def test_thread_read_does_not_cross_any_queued_events(self):
        self.fake.thread_summary = {"id": "one-thread", "status": {"type": "idle"}}
        self.fake.thread_read_events = [
            {"method": "turn/completed", "params": {"threadId": "one-thread",
                "turn": {"id": "turn-1", "status": "failed",
                         "error": {"message": "stream disconnected"}}}},
            {"method": "error", "params": {"threadId": "one-thread",
                "turnId": "turn-1", "willRetry": False,
                "error": {"message": "UsageLimitExceeded after connection reset"}}}]
        self.fake.events = [{"method": "error", "params": {"threadId": "one-thread",
            "turnId": "turn-1", "willRetry": False,
            "error": {"message": "stream disconnected"}}}, TimeoutError("idle fixture")]
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual(self.policy.network_continuations, 0)
        self.assertEqual([row[0] for row in self.fake.requests], ["turn/start", "thread/read"])

    def test_structured_non_network_errors_override_network_words(self):
        for kind in ("rateLimitExceeded", "contextWindowExceeded", "sessionBudgetExceeded",
                     "usageLimitExceeded", "unauthorized"):
            with self.subTest(kind=kind):
                self.assertFalse(subject._network_error({"message": "stream disconnected", "codexErrorInfo": kind}))
        for kind in ("httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected"):
            with self.subTest(kind=kind):
                self.assertTrue(subject._network_error({"message": "provider request failed",
                    "codexErrorInfo": {kind: {"httpStatusCode": None}}}))
        self.assertFalse(subject._network_error({"message": "stream disconnected",
            "codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": 429}}}))
        for status in (402, 407, 429, True, "503", -1, 65536):
            with self.subTest(http_status=status):
                self.assertFalse(subject._network_error({"message": "stream disconnected",
                    "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": status}}}))
        self.assertTrue(subject._network_error({"message": "request timed out",
            "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 408}}}))

    def test_tools_are_local_and_no_secret_or_sim_authority_in_launch(self):
        config = subject.launch_settings(self.policy.actor, self.policy.public, self.policy.audit)
        self.assertEqual(config["shell_environment_policy.inherit"], "none")
        self.assertFalse(config["permissions.rsi_direct_actor.network.enabled"])
        self.assertTrue(config["features.shell_tool"])
        self.assertTrue(config["features.view_image"])
        roots = config["permissions.rsi_direct_actor.filesystem"]
        self.assertNotIn(str(self.policy.audit), roots)
        self.assertEqual(roots[str(self.policy.public)], "read")
        self.assertEqual(roots[str(self.policy.actor)], "write")
        self.assertNotIn("RSI_SIM_SERVER_TOKEN", json.dumps(config))
        for key in ("sqlite_home", "log_dir"):
            path = Path(config[key])
            self.assertFalse(path.is_relative_to(self.policy.audit))
            self.assertFalse(path.is_relative_to(self.policy.actor))
            self.assertFalse(path.is_relative_to(self.policy.public))

    def test_protocol_name_is_not_a_robot_specific_compatibility_gate(self):
        self.policy.end_episode()
        self.policy.bind_artifact_dir(Path(self.temp.name) / "another")
        self.policy.start_episode(replace(self.context,
            benchmark=replace(self.context.benchmark, protocol_version="another-public-contract")))
        self.assertIsNotNone(self.policy.context)


class BootstrapDeadlineChecks(unittest.TestCase):
    setUp = DirectChecks.setUp

    def bootstrap_transport(self, initialize_delay):
        from AgentPolicies.gpt6_astra.transports.codex_app_server import TransportTimeout
        self.boot.stop()
        config = {}
        for key, value in subject.launch_settings(self.policy.actor, self.policy.public, self.policy.audit).items():
            row = config
            parts = key.split(".")
            for part in parts[:-1]:
                row = row.setdefault(part, {})
            row[parts[-1]] = deepcopy(value)
        transport = Mock()
        transport.diagnostics.return_value = {}

        def request(method, params, timeout):
            if method == "initialize":
                if initialize_delay >= timeout:
                    raise TransportTimeout("request_timeout")
                return {}
            if method == "config/read":
                return {"config": config}
            if method == "thread/start":
                return {"model": "gpt-6-astra", "modelProvider": "openai", "reasoningEffort": "xhigh",
                        "activePermissionProfile": subject.PERMISSIONS, "approvalPolicy": "never",
                        "cwd": str(self.policy.actor), "thread": {"id": "fake-bootstrap-thread"}}
            raise AssertionError(method)

        transport.request.side_effect = request
        for target, options in (
            ("AgentPolicies.gpt6_astra.transports.codex_cli._inspect_runtime",
             {"return_value": (Path("/fake/pinned/codex"), {})}),
            ("AgentPolicies.gpt6_astra.transports.codex_app_server.StdioAppServer",
             {"return_value": transport}),
        ):
            patched = patch(target, **options)
            patched.start()
            self.addCleanup(patched.stop)
        return transport

    def test_slow_initialize_within_startup_deadline_keeps_other_limits_and_counts(self):
        transport = self.bootstrap_transport(initialize_delay=31)
        self.policy._boot()
        self.assertEqual([(call.args[0], call.args[2]) for call in transport.request.call_args_list],
                         [("initialize", 120), ("config/read", 30), ("thread/start", 30)])
        transport.notify.assert_called_once_with("initialized", {})
        self.assertEqual(self.policy.config["timeout_s"], 900)
        self.assertEqual((self.policy.issued, self.policy.controls, self.policy.network_continuations), (0, 0, 0))
        self.assertEqual(self.policy.thread_id, "fake-bootstrap-thread")

    def test_default_no_frame_export_still_retains_transport_diagnostics(self):
        transport = self.bootstrap_transport(initialize_delay=0)
        with patch("AgentPolicies.gpt6_astra.transports.codex_app_server.StdioAppServer",
                   return_value=transport) as constructor:
            self.policy._boot()
        self.assertFalse(self.policy.recording.images)
        self.assertEqual(constructor.call_args.args[1], self.policy.audit / "transport")

    def test_initialize_timeout_does_not_notify_start_thread_or_retry(self):
        transport = self.bootstrap_transport(initialize_delay=121)
        with self.assertRaises(PolicyCallError):
            self.policy.act(self.obs)
        self.assertEqual([call.args[0] for call in transport.request.call_args_list], ["initialize"])
        transport.notify.assert_not_called()
        self.assertIsNone(self.policy.thread_id)
        self.assertEqual((self.policy.issued, self.policy.controls, self.policy.network_continuations), (0, 0, 0))


class ConfigurationChecks(unittest.TestCase):
    def setUp(self):
        self.actor, self.public, self.audit = (Path("/owned") / name for name in ("actor", "public", "audit"))
        self.config = {}
        for key, value in subject.launch_settings(self.actor, self.public, self.audit).items():
            row = self.config
            parts = key.split(".")
            for part in parts[:-1]:
                row = row.setdefault(part, {})
            row[parts[-1]] = deepcopy(value)

    def verify(self):
        return subject.verify_configuration(self.config, self.actor, self.public, self.audit)

    def test_exact_configuration_accepts_null_defaults_and_disabled_mcp(self):
        p = self.config["permissions"][subject.PERMISSIONS]
        p.update(extends=None, workspace_roots=None)
        p["filesystem"]["glob_scan_max_depth"] = None
        p["network"]["domains"] = None
        self.config["mcp_servers"] = {"operator-server": {"enabled": False, "private": "never-record"}}
        receipt = self.verify()
        self.assertTrue(receipt["effective_configuration_checked"])
        self.assertNotIn("never-record", json.dumps(receipt))
        self.assertFalse(receipt["kernel_isolation_attested"])

    def test_inherited_mcp_cannot_silently_remain_enabled(self):
        for server in ({}, {"enabled": True}, {"enabled": 0}):
            self.config["mcp_servers"] = {"inherited": server}
            with self.subTest(server=server), self.assertRaises(PolicyError):
                self.verify()

    def test_extra_filesystem_or_network_authority_fails_closed(self):
        p = self.config["permissions"][subject.PERMISSIONS]
        original = deepcopy(p)
        changes = (lambda: p["filesystem"].update({"/private": "read"}),
                   lambda: p["network"].update(enabled=True),
                   lambda: p.update(extends="full-access"),
                   lambda: p.update(workspace_roots=["/private"]))
        for change in changes:
            p.clear()
            p.update(deepcopy(original))
            change()
            with self.assertRaises(PolicyError):
                self.verify()

    def test_inherited_shell_secret_is_not_allowed(self):
        self.config["shell_environment_policy"]["set"]["SECRET"] = "never-record"
        with self.assertRaises(PolicyError) as caught:
            self.verify()
        self.assertNotIn("never-record", str(caught.exception))

    def test_external_model_instructions_are_not_allowed(self):
        for key in ("model_instructions_file", "experimental_compact_prompt_file", "instructions", "compact_prompt"):
            self.config[key] = "private-unbound-instructions"
            with self.subTest(key=key), self.assertRaises(PolicyError) as caught:
                self.verify()
            self.assertNotIn("private-unbound-instructions", str(caught.exception))
            del self.config[key]


if __name__ == "__main__":
    unittest.main()
