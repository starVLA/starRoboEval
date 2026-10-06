"""Generic planned-policy boundary fixtures; no model, credentials or simulator."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from benchkit.contracts import (
    ActionRejectionFeedback, ActionSpec, BenchmarkDescriptor, ExecutionFeedback,
    Observation, ObservationSpec, PolicyEpisodeSpec,
)
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError
from benchkit.model_profiles import create_policy
from benchkit.recording import RecordingOptions
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.checks.fixtures import context
from AgentPolicies.gpt6_astra.tools.persistent_runtime import launch_settings, verify_configuration


def proposal(policy):
    step = policy.controls
    return {
        "request_id": policy.packet["request_id"],
        "plan": {"goal": "Reach the requested visual relation.", "subgoals": [
            {"id": "inspect", "description": "Test a bounded movement.",
             "expected_evidence": "A visible relative-position change."}], "active_subgoal": "inspect"},
        "assessment": {"observation_step": step,
                       "previous_expectation_status": "initial" if not policy.decisions else "uncertain",
                       "evidence": "The supplied current image is available; progress is uncertain."},
        "memory": [{"kind": "observed", "statement": "A colored region is visible.",
                    "observation_step": step},
                   {"kind": "hypothesis", "statement": "The region may be the target.",
                    "observation_step": step}],
        "expected_observation": "The relative image position may change.",
        "actions": [[0.25, -0.5], [0.4, 0.5]], "stop_reason": None,
        "reason": "Test the public control semantics with a short model-selected chunk.",
    }


class FakeTransport:
    def __init__(self, policy):
        self.policy = policy
        self.requests, self.replies, self.events = [], [], []
        self.closed = False
        self.serial = 0
        self.override = None

    def request(self, method, params, timeout):
        self.requests.append((method, params))
        if method == "turn/start":
            return {"turn": {"id": "turn-" + str(len(self.requests))}}
        raise AssertionError("Unexpected offline RPC: " + method)

    def reply(self, identifier, result):
        self.replies.append((identifier, result))

    def next_message(self, timeout):
        if self.events:
            event = self.events.pop(0)
            if isinstance(event, BaseException):
                raise event
            return event
        self.serial += 1
        arguments = proposal(self.policy)
        if self.override:
            self.override(arguments)
        return {"id": self.serial, "method": "item/tool/call", "params": {
            "threadId": self.policy.thread_id, "turnId": self.policy.turn_id,
            "callId": "call-" + str(self.serial), "tool": "planned_act", "arguments": arguments}}

    def diagnostics(self):
        return {"closed": self.closed, "requests": len(self.requests)}

    def close(self):
        self.closed = True


class PlannedPolicyChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = create_policy("gpt6_astra", control_method="codex-planned/v1")
        self.context = context(
            benchmark=BenchmarkDescriptor("private-benchmark-marker", "version", "arbitrary-public-protocol",
                                          "private-source-marker"),
            episode=PolicyEpisodeSpec("private-opaque-marker", "private-task-marker", "Move to the target"),
            observation_spec=ObservationSpec(cameras=("front_sensor",), state_names=("measured_axis",)),
            replan_interval=5, invalid_action_handling="feedback")
        self.policy.bind_artifact_dir(self.root / "audit")
        self.policy.start_episode(self.context)
        self.fake = FakeTransport(self.policy)
        def boot():
            self.policy.transport = self.fake
            self.policy.thread_id = "one-thread"
        mocked = patch.object(self.policy, "_boot", side_effect=boot)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.addCleanup(self.policy.end_episode)
        self.obs = Observation(0, "Move to the target", {"front_sensor": np.array([[[1, 127, 255]]], np.uint8)},
                               (0.2,), metadata={"private-metadata-marker": "never send"},
                               control_feedback={"private-undeclared-payload": "never send"})

    def advance(self, count=2):
        self.policy.observe_execution(ExecutionFeedback(self.policy.issued, self.policy.decisions + 1,
                                                       self.policy.controls + count, count))
        self.obs = replace(self.obs, step=self.policy.controls)
        return self.policy.act(self.obs)

    def test_generic_contract_and_private_context_never_enter_actor(self):
        result = self.policy.act(self.obs)
        self.assertEqual(result.action.steps, ((0.25, -0.5), (0.4, 0.5)))
        self.assertEqual(self.policy.packet["action_spec"], self.context.action_spec.to_dict())
        self.assertEqual(self.policy.packet["state_names"], ["measured_axis"])
        serialized = json.dumps(self.fake.requests) + "".join(path.read_text() for path in self.policy.public.rglob("*.json"))
        for marker in ("private-benchmark-marker", "private-source-marker", "private-opaque-marker",
                       "private-task-marker", "private-metadata-marker", "private-undeclared-payload",
                       "RSI_SIM_SERVER_TOKEN", "current_eef", "initial_eef"):
            self.assertNotIn(marker, serialized)
        self.assertNotIn("required_protocol", self.policy.config)
        self.assertIsNone(result.usage.calls)
        receipt = result.metadata["provider_receipt"]
        self.assertFalse(receipt["provider_identity_verified"])
        self.assertIsNone(receipt["provider_calls"])

    def test_one_episode_one_thread_and_ack_hooks_make_no_model_calls(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 1, 1))
        self.assertEqual(len(self.fake.requests), 1)
        self.assertFalse(self.fake.replies)
        second = self.policy.act(replace(self.obs, step=1))
        self.assertEqual(second.action.steps[0], (0.25, -0.5))
        self.assertEqual((len(self.fake.requests), len(self.fake.replies)), (1, 1))
        self.assertEqual(self.policy.thread_id, "one-thread")

    def test_next_action_requires_acknowledged_observation(self):
        self.policy.act(self.obs)
        with self.assertRaises(PolicyError):
            self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 1, 1))
        with self.assertRaises(PolicyCallError):
            self.policy.act(replace(self.obs, step=2))
        self.assertFalse(self.fake.replies)

    def test_shared_overload_recovery_preserves_planned_episode(self):
        self.policy.act(self.obs)
        self.fake.events = [{"method": "turn/completed", "params": {"threadId": "one-thread",
            "turn": {"id": "turn-1", "status": "failed",
                     "error": {"codexErrorInfo": "serverOverloaded"}}}}]
        with patch("AgentPolicies.gpt6_astra.tools.persistent_runtime.time.sleep") as sleep:
            decision = self.advance()
        sleep.assert_called_once_with(30)
        self.assertEqual(decision.metadata["provider_receipt"]["overload_continuations"], 1)
        self.assertEqual((self.policy.controls, self.policy.issued), (2, 2))
        self.assertEqual(len(self.fake.replies), 1)
        self.assertEqual([row[0] for row in self.fake.requests], ["turn/start", "turn/start"])
        self.assertTrue(all(row[1]["threadId"] == "one-thread" for row in self.fake.requests))

    def test_plan_and_memory_are_model_claims_not_sensor_or_success(self):
        result = self.policy.act(self.obs)
        submitted = result.metadata["structured_output"]
        self.assertEqual([item["kind"] for item in submitted["memory"]], ["observed", "hypothesis"])
        self.assertEqual(submitted["assessment"]["previous_expectation_status"], "initial")
        self.assertNotIn("success", submitted)
        self.advance(1)
        reply = json.loads(self.fake.replies[0][1]["contentItems"][0]["text"])
        self.assertNotIn("success", reply)
        self.assertNotIn("reward", reply)
        self.assertEqual(reply["recent_executions"][0]["actions"], [[0.25, -0.5]])
        self.assertEqual(reply["recent_executions"][0]["authority"], "acknowledged_execution_not_task_effect")
        self.assertEqual(reply["model_summary"]["authority"], "model_authored_unverified")

    def test_strict_actions_and_bounded_plans_are_rejected_without_execution(self):
        cases = (
            lambda value: value.update(request_id="stale"),
            lambda value: value.update(actions=[[True, 0]]),
            lambda value: value.update(actions=[[2, 0]]),
            lambda value: value.update(actions=[[0]]),
            lambda value: value.update(actions=[[0, 0]] * 6),
            lambda value: value.update(actions=[]),
            lambda value: value.update(actions=[[float("nan"), 0]]),
            lambda value: value.update(stop_reason="give_up", actions=[]),
            lambda value: value.update(stop_reason="success", actions=[]),
            lambda value: value["plan"].update(active_subgoal="not-listed"),
            lambda value: value["plan"]["subgoals"].append(deepcopy(value["plan"]["subgoals"][0])),
            lambda value: value.update(memory=value["memory"] * 7),
            lambda value: value["memory"][0].update(kind="confirmed_success"),
            lambda value: value["memory"][0].update(observation_step=1),
            lambda value: value["assessment"].update(observation_step=1),
            lambda value: value.update(reason="x" * 1025),
            lambda value: value.update(extra="not allowed"),
        )
        # Validation is isolated from the live submission loop and never dispatches.
        self.policy._observation(self.obs)
        self.policy._boot()
        self.policy._turn("Deliver the synthetic public observation for this offline validator fixture.")
        self.assertEqual(self.policy.observation_steps, {0})
        for mutate in cases:
            args = proposal(self.policy)
            mutate(args)
            with self.subTest(mutate=mutate), self.assertRaises(ActionRejected):
                self.policy._validate_action(args, self.policy.packet)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertFalse(self.fake.replies)
        self.assertEqual(self.policy.controls, 0)

    def test_rejected_input_reuses_observation_without_advancing_memory(self):
        self.fake.override = lambda value: value.update(actions=[[99, 0]])
        with self.assertRaises(ActionRejected) as caught:
            self.policy.act(self.obs)
        request_id = self.policy.packet["request_id"]
        self.policy.observe_rejection(ActionRejectionFeedback(caught.exception.issue, 1, 0, 0, 0, 1))
        self.fake.override = None
        decision = self.policy.act(self.obs)
        reply = json.loads(self.fake.replies[0][1]["contentItems"][0]["text"])
        self.assertEqual(reply["request_id"], request_id)
        self.assertTrue(reply["no_execution"])
        self.assertEqual(reply["rejected_controls_executed"], 0)
        self.assertEqual(decision.metadata["structured_output"]["assessment"]["previous_expectation_status"], "initial")

    def test_partial_rejection_has_new_observation_and_never_replays_prefix(self):
        self.policy.act(self.obs)
        self.policy.observe_rejection(ActionRejectionFeedback(ValidationIssue("invalid_action"), 1, 1, 1, 1, 1))
        self.policy.act(replace(self.obs, step=1))
        reply = json.loads(self.fake.replies[0][1]["contentItems"][0]["text"])
        self.assertFalse(reply["no_execution"])
        self.assertEqual(reply["executed_prefix_controls"], 1)
        self.assertEqual(reply["rejected_controls_executed"], 0)
        self.assertEqual((self.policy.controls, self.policy.decisions), (1, 1))

    def test_memory_cannot_cite_an_unobserved_middle_control(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 2, 2))
        self.fake.override = lambda value: value["memory"][0].update(observation_step=1)
        with self.assertRaises(ActionRejected):
            self.policy.act(replace(self.obs, step=2))
        self.assertEqual(self.policy.controls, 2)
        self.assertEqual(len(self.fake.replies), 1)

    def test_native_vector_dimension_and_frames_are_not_hardcoded(self):
        self.policy.end_episode()
        vector = [index / 20 - 0.7 for index in range(29)]
        native = ActionSpec("absolute-joint-test", 29,
                            names=tuple("joint_" + str(index) for index in range(29)),
                            low=(-2,) * 29, high=(2,) * 29, frame="declared joint frame",
                            rotation="joint radians", gripper="no gripper")
        self.policy.bind_artifact_dir(self.root / "other-contract")
        self.policy.start_episode(replace(self.context, action_spec=native,
            observation_spec=ObservationSpec(cameras=("side_sensor",)), replan_interval=None))
        self.fake.override = lambda value: value.update(actions=[vector])
        observation = Observation(0, "Follow the public instruction", {"side_sensor": self.obs.images["front_sensor"]})
        result = self.policy.act(observation)
        self.assertEqual(result.action.steps, (tuple(vector),))
        self.assertEqual(self.policy.packet["action_spec"], native.to_dict())
        self.assertIsNone(self.policy.packet["state"])
        self.assertFalse(self.policy.packet["state_names"])

    def test_original_pixels_are_preserved_separately_from_preview(self):
        pixels = np.arange(640 * 320 * 3, dtype=np.uint8).reshape((320, 640, 3))
        self.policy.act(replace(self.obs, images={"front_sensor": pixels}))
        descriptor = self.policy.packet["images"][0]
        original = Path(descriptor["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), descriptor["sha256"])
        with Image.open(io.BytesIO(original)) as decoded:
            self.assertTrue(np.array_equal(np.asarray(decoded), pixels))
        preview = Path(descriptor["codex_preview"]["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(preview).hexdigest(), descriptor["codex_preview"]["sha256"])
        with Image.open(io.BytesIO(preview)) as decoded:
            self.assertEqual(decoded.size, (480, 240))

    def test_no_progress_assessment_does_not_invoke_scripted_recovery(self):
        first = self.policy.act(self.obs)
        self.fake.override = lambda value: value["assessment"].update(previous_expectation_status="not_observed")
        second = self.advance(1)  # Deliberately unchanged RGB and measured state.
        self.assertEqual(first.action, second.action)
        self.assertEqual(second.metadata["structured_output"]["assessment"]["previous_expectation_status"], "not_observed")
        self.assertEqual((len(self.fake.requests), len(self.fake.replies)), (1, 1))

    def test_declared_runtime_bounds_and_preflight_clone(self):
        fresh = self.policy._preflight_policy()
        self.assertEqual(fresh.descriptor.version, "codex-planned/v1")
        self.assertEqual(fresh.config, self.policy.config)
        self.assertEqual(fresh.prompt, self.policy.prompt)
        self.assertEqual(fresh.descriptor.parameters["prompt_sha256"], self.policy.descriptor.parameters["prompt_sha256"])
        self.assertEqual(fresh._tool_spec()["name"], "planned_act")
        self.assertIsNone(fresh.transport)
        for overrides in ({"max_chunk_length": 0}, {"max_chunk_length": 33},
                          {"max_chunk_length": True}, {"timeout_s": 901}, {"timeout_s": True},
                          {"image_max_edge": -1}, {"image_max_edge": True},
                          {"min_action_decisions_before_give_up": 1}, {"safety_stop": 0},
                          {"safety_stop": 1}, {"safety_stop": "false"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                create_policy("gpt6_astra", control_method="codex-planned/v1", **overrides)

    def test_camera_identifier_cannot_escape_public_workspace(self):
        # The shared ObservationSpec deliberately does not validate path syntax.
        # The method must either reject the contract or use host-owned safe names.
        self.policy.end_episode()
        self.policy.bind_artifact_dir(self.root / "camera-contract")
        name = str(self.root / "camera-escape")
        try:
            self.policy.start_episode(replace(self.context,
                observation_spec=ObservationSpec(cameras=(name,))))
        except PolicyError:
            pass
        else:
            try:
                self.policy.act(Observation(0, "Observe the target", {name: self.obs.images["front_sensor"]}))
            except PolicyCallError:
                pass
        self.assertFalse((self.root / "camera-escape.png").exists())

    def test_no_cross_episode_memory_or_privileged_observations(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 2, 2))
        self.policy.end_episode()
        self.policy.bind_artifact_dir(self.root / "second-episode")
        self.policy.start_episode(self.context)
        self.assertEqual((self.policy.controls, self.policy.decisions, self.policy.issued), (0, 0, 0))
        result = self.policy.act(self.obs)
        self.assertEqual(result.metadata["structured_output"]["assessment"]["previous_expectation_status"], "initial")
        self.policy.end_episode()
        self.policy.bind_artifact_dir(self.root / "privileged")
        with self.assertRaises(PolicyError):
            self.policy.start_episode(replace(self.context, observation_spec=ObservationSpec(privileged=True)))

    def test_safety_stop_is_explicit_not_native_success(self):
        self.policy.end_episode()
        self.policy = create_policy("gpt6_astra", control_method="codex-planned/v1", safety_stop=True)
        self.addCleanup(self.policy.end_episode)
        self.policy.bind_artifact_dir(self.root / "enabled-stop")
        self.policy.start_episode(self.context)
        self.fake = FakeTransport(self.policy)
        def boot():
            self.policy.transport, self.policy.thread_id = self.fake, "one-thread"
        mocked = patch.object(self.policy, "_boot", side_effect=boot)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.fake.override = lambda value: value.update(actions=[], stop_reason="safety_stop",
            reason="The public view leaves a collision risk that cannot be bounded.")
        result = self.policy.act(self.obs)
        self.assertTrue(result.stop)
        self.assertEqual(result.stop_reason, "safety_stop")
        self.assertIsNone(result.action)
        self.assertEqual(self.policy.controls, 0)
        self.assertTrue(self.policy.descriptor.parameters["safety_stop"])
        self.assertIn("Effective policy stop configuration: safety_stop=true", self.policy.prompt)
        clone = self.policy._preflight_policy()
        self.assertEqual(clone.prompt, self.policy.prompt)
        self.assertTrue(clone.config["safety_stop"])

    def test_disabled_safety_stop_is_rejected_then_corrected_without_execution(self):
        self.assertFalse(self.policy.config["safety_stop"])
        self.assertFalse(self.policy.descriptor.parameters["safety_stop"])
        self.assertEqual(self.policy.config["schema_version"], "starvla-rsi.codex-planned-config/v2")
        properties = self.policy._tool_spec()["inputSchema"]["properties"]
        self.assertEqual(properties["actions"]["minItems"], 1)
        self.assertEqual(properties["stop_reason"], {"type": "null", "enum": [None]})
        self.fake.override = lambda value: value.update(actions=[], stop_reason="safety_stop")
        with self.assertRaises(ActionRejected) as caught:
            self.policy.act(self.obs)
        self.assertEqual(caught.exception.issue.code, "invalid_stop")
        self.assertEqual(caught.exception.issue.field, "safety_stop")
        self.assertEqual((self.policy.controls, self.policy.decisions), (0, 0))
        self.assertIsNone(self.policy.model_summary)
        self.policy.observe_rejection(ActionRejectionFeedback(caught.exception.issue, 1, 0, 0, 0, 1))
        self.fake.override = None
        result = self.policy.act(self.obs)
        self.assertFalse(result.stop)
        self.assertEqual(self.policy.issued, 2)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(len(self.fake.replies), 1)
        self.assertEqual((self.policy.controls, self.policy.decisions), (0, 0))

    def test_custom_prompt_stop_override_is_captured_and_clone_stable(self):
        for enabled in (False, True):
            policy = create_policy("gpt6_astra", control_method="codex-planned/v1",
                                   prompt="Custom generic planning instructions", safety_stop=enabled)
            clone = policy._preflight_policy()
            self.assertEqual(clone._prompt_base, "Custom generic planning instructions")
            self.assertEqual(clone.prompt, policy.prompt)
            self.assertEqual(policy.prompt.count("Effective policy stop configuration:"), 1)
            self.assertEqual(policy.descriptor.parameters["prompt_sha256"], hashlib.sha256(policy.prompt.encode()).hexdigest())
            self.assertIs(policy.descriptor.parameters["effective_config"]["safety_stop"], enabled)

    def test_uncertain_tool_reply_is_not_repeated(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 1, 1))
        with patch.object(self.fake, "reply", side_effect=TimeoutError("private fault")) as reply:
            with self.assertRaises(PolicyCallError):
                self.policy.act(replace(self.obs, step=1))
        self.assertEqual(reply.call_count, 1)
        self.assertIsNone(self.policy.pending_rpc)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(self.policy.observation_steps, {0})

    def test_failed_initial_delivery_does_not_make_evidence_citeable(self):
        with patch.object(self.fake, "request", side_effect=TimeoutError("fixture delivery failure")) as request:
            with self.assertRaises(PolicyCallError):
                self.policy.act(self.obs)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.policy.observation_steps, set())

    def test_terminal_close_has_no_paid_continuation_and_destroys_episode_workspace(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 1, 1))
        public, actor = self.policy.public, self.policy.actor
        self.policy.end_episode()
        self.assertTrue(self.fake.closed)
        self.assertFalse(self.fake.replies)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertFalse(public.exists() or actor.exists())
        self.assertIsNone(self.policy.context)

    def test_minimal_recording_does_not_remove_live_plan_or_images(self):
        self.policy.end_episode()
        self.policy.configure_recording(RecordingOptions(mode="minimal"))
        target = self.root / "minimal"
        self.policy.bind_artifact_dir(target)
        self.policy.start_episode(self.context)
        first = self.policy.act(self.obs)
        second = self.advance(1)
        self.assertEqual(first.action, second.action)
        self.assertEqual(len(self.fake.requests[0][1]["input"]), 2)
        self.assertTrue(list(self.policy.public.rglob("*.png")))
        self.policy.end_episode()
        self.assertFalse(list(target.rglob("*")))

    def test_permission_configuration_cannot_mount_evaluator_or_auth(self):
        settings = {}
        for dotted, value in launch_settings(self.policy.actor, self.policy.public, self.policy.audit).items():
            current = settings
            components = dotted.split(".")
            for part in components[:-1]:
                current = current.setdefault(part, {})
            current[components[-1]] = value
        profile = settings["permissions"]["rsi_direct_actor"]
        self.assertFalse(profile["network"]["enabled"])
        self.assertEqual(profile["filesystem"][str(self.policy.actor)], "write")
        self.assertEqual(profile["filesystem"][str(self.policy.public)], "read")
        self.assertNotIn(str(self.policy.audit), profile["filesystem"])
        self.assertTrue(verify_configuration(settings, self.policy.actor, self.policy.public,
                                             self.policy.audit)["permission_roots_match"])
        for root in ("/private-evaluator", "/private-auth/.codex"):
            altered = deepcopy(settings)
            altered["permissions"]["rsi_direct_actor"]["filesystem"][root] = "read"
            with self.subTest(root=root), self.assertRaises(PolicyError):
                verify_configuration(altered, self.policy.actor, self.policy.public, self.policy.audit)


if __name__ == "__main__":
    unittest.main()
