"""Generic public-context/preview fixtures; no CLI, network or simulator."""
from dataclasses import replace
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

from benchkit.contracts import (ActionRejectionFeedback, ActionSpec, ControlAcknowledgement,
    ExecutionFeedback, Observation, ObservationSpec)
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError
from benchkit.model_profiles import create_policy
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.tools import public_observation as subject
from AgentPolicies.gpt6_astra.tools.persistent_runtime import PersistentRuntime
from AgentPolicies.gpt6_astra.methods.codex_direct import CodexDirectPolicy
from AgentPolicies.gpt6_astra.methods.codex_planned import CodexPlannedPolicy
from AgentPolicies.gpt6_astra.checks import test_codex_direct as fixtures


def png(size):
    stream = io.BytesIO()
    Image.new("RGB", size, (12, 80, 201)).save(stream, format="PNG")
    return stream.getvalue()


class PublicContextChecks(unittest.TestCase):
    def test_landscape_and_portrait_thumbnail_preserve_original_bytes(self):
        for original_size, expected_size in (((640, 480), (480, 360)), ((480, 640), (360, 480))):
            with self.subTest(size=original_size):
                original = png(original_size)
                digest = hashlib.sha256(original).hexdigest()
                preview, dimensions = subject.image_attachment(original, 480)
                with Image.open(io.BytesIO(preview)) as image:
                    self.assertEqual(image.size, expected_size)
                with Image.open(io.BytesIO(original)) as image:
                    self.assertEqual(image.size, original_size)
                self.assertEqual(hashlib.sha256(original).hexdigest(), digest)
                self.assertEqual(dimensions["resampling"], "LANCZOS")

    def test_no_upscale_and_zero_retains_exact_original_png(self):
        for size, edge in (((100, 80), 480), ((640, 480), 0), ((480, 360), 480)):
            with self.subTest(size=size, edge=edge):
                original = png(size)
                actual, dimensions = subject.image_attachment(original, edge)
                self.assertIs(actual, original)
                self.assertFalse(dimensions["resized"])
                self.assertEqual(dimensions["size"], list(size))

    def test_preview_configuration_is_strict_bounded_integer(self):
        for value in (True, False, None, "480", 480.0, -1, 4097, 10**400, float("nan")):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                subject.image_attachment(png((2, 2)), value)
        self.assertEqual(subject.image_edge(4096), 4096)


class DirectPublicChecks(unittest.TestCase):
    setUp = fixtures.DirectChecks.setUp
    next = fixtures.DirectChecks.next

    def test_originals_are_public_and_hash_bound_preview_is_attached(self):
        images = {name: np.full((480, 640, 3), 80, np.uint8) for name in self.obs.images}
        self.policy.act(replace(self.obs, images=images))
        for descriptor, item in zip(self.policy.packet["images"], self.fake.requests[0][1]["input"][1:]):
            original = Path(descriptor["path"]).read_bytes()
            preview = Path(descriptor["codex_preview"]["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(original).hexdigest(), descriptor["sha256"])
            self.assertEqual(hashlib.sha256(preview).hexdigest(), descriptor["codex_preview"]["sha256"])
            self.assertEqual(base64.b64decode(item["url"].split(",", 1)[1]), preview)
            with Image.open(io.BytesIO(original)) as image:
                self.assertEqual(image.size, (640, 480))
            with Image.open(io.BytesIO(preview)) as image:
                self.assertEqual(image.size, (480, 360))

    def test_workspace_only_public_evidence_notes_and_scratch(self):
        self.policy.act(self.obs)
        workspace = self.policy.packet["workspace_context"]
        self.assertEqual(workspace["python_executable"], sys.executable)
        self.assertTrue(Path(workspace["notes_path"]).is_relative_to(self.policy.actor))
        self.assertTrue(Path(workspace["scratch_path"]).is_dir())
        self.assertTrue(Path(workspace["observations_path"]).is_relative_to(self.policy.public))
        self.assertNotIn(str(self.policy.audit), json.dumps(workspace))
        self.assertNotIn("runtime", workspace)
        self.assertIsNone(self.policy.packet["previous_execution"])

    def test_first_public_reference_detached_from_current_and_future_packets(self):
        first = self.policy.act(self.obs)
        original = json.loads(json.dumps(self.policy.initial_robot_state))
        self.assertEqual(original, {"step": 0, "state_names": list(self.context.observation_spec.state_names),
            "values": [.1, .2, .3], "authority": "initial_public_observation_not_action"})
        self.assertNotEqual(first.action.steps[0], tuple(original["values"]))
        reference_path = self.policy.packet["initial_observation_path"]
        self.policy.packet["state"][0] = 999
        self.policy.packet["initial_robot_state"]["values"][0] = 888
        self.policy.packet["initial_robot_state"]["state_names"][0] = "mutated"
        self.assertEqual(self.policy.initial_robot_state, original)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 2, 2))
        self.policy.act(replace(self.obs, step=2, state=(.4, .5, .6)))
        self.assertEqual(self.policy.packet["initial_robot_state"], original)
        self.assertEqual(self.policy.packet["state"], [.4, .5, .6])
        self.assertEqual(self.policy.packet["initial_observation_path"], reference_path)
        self.assertTrue(Path(reference_path).is_file())

    def test_state_none_is_unknown_not_synthetic_home(self):
        self.policy.end_episode()
        self.policy.bind_artifact_dir(Path(self.temp.name) / "no-state")
        self.policy.start_episode(replace(self.context, observation_spec=ObservationSpec()))
        self.policy.act(Observation(0, "Perform the public task"))
        self.assertIsNone(self.policy.packet["initial_robot_state"]["values"])
        self.assertEqual(self.policy.packet["initial_robot_state"]["state_names"], [])
        self.assertIsNone(self.policy.packet["state"])
        self.assertEqual(self.policy.controls, 0)

    def test_unknown_feedback_and_metadata_never_enter_actor_files(self):
        poisoned = {"private-score": 100, "private-layout": 42, "object-truth": [1, 2, 3],
                    "token": "private-secret-marker"}
        self.policy.act(replace(self.obs, control_feedback=poisoned, metadata=poisoned))
        rows = (ControlAcknowledgement(1, 1, {**poisoned, "schema": "unknown-public/v1", "control_target": 1}),)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 1, 1, rows))
        self.policy.act(replace(self.obs, step=1, control_feedback=poisoned, metadata=poisoned))
        text = json.dumps(self.fake.requests) + json.dumps(self.fake.replies)
        text += "".join(path.read_text() for path in self.policy.public.rglob("*.json"))
        for marker in poisoned:
            self.assertNotIn(marker, text)
        self.assertFalse(self.policy.packet["raw_control_feedback_forwarded"])
        self.assertEqual(self.policy.packet["previous_execution"], {
            "policy_calls": 1, "action_decisions": 1, "environment_steps": 1, "executed_steps": 1})
        self.assertEqual(self.policy.packet["recent_executions"][0]["actions"], [[.25, -.5]])

    def test_known_feedback_schema_name_does_not_authorize_payload(self):
        self.policy.end_episode()
        self.policy.bind_artifact_dir(Path(self.temp.name) / "named-feedback")
        self.policy.start_episode(replace(self.context, observation_spec=replace(
            self.context.observation_spec, control_feedback_schema="robodojo.robot-control-feedback/v1")))
        self.policy.act(replace(self.obs, control_feedback={"private-score": 100}))
        self.assertNotIn("private-score", json.dumps(self.fake.requests))

    def test_partial_ack_history_only_contains_real_prefix(self):
        self.policy.act(self.obs)
        self.policy.observe_rejection(ActionRejectionFeedback(ValidationIssue("invalid_action"), 1, 1, 2, 2, 1))
        self.policy.act(replace(self.obs, step=2))
        body = json.loads(self.fake.replies[0][1]["contentItems"][0]["text"])
        self.assertEqual(body["recent_executions"][0]["actions"], [[.25, -.5]] * 2)
        self.assertEqual(body["executed_prefix_controls"], 2)
        self.assertFalse(body["no_execution"])
        self.assertEqual(body["initial_robot_state"]["step"], 0)
        self.assertEqual(len(self.fake.requests), 1)

    def test_zero_rejection_reuses_sensor_document_and_first_reference(self):
        self.fake.override = lambda args: args.update(actions=[[99, 0]])
        with self.assertRaises(ActionRejected) as caught:
            self.policy.act(self.obs)
        packet = self.policy.packet
        self.policy.observe_rejection(ActionRejectionFeedback(caught.exception.issue, 1, 0, 0, 0, 1))
        self.fake.override = None
        self.policy.act(self.obs)
        body = json.loads(self.fake.replies[0][1]["contentItems"][0]["text"])
        for key in ("request_id", "images", "initial_robot_state", "initial_observation_path"):
            self.assertEqual(body[key], packet[key])
        self.assertEqual(body["recent_executions"], [])
        self.assertEqual(len(self.fake.replies[0][1]["contentItems"]), 1)

    def test_varied_dimensions_frames_grippers_cameras_and_safe_paths(self):
        for size, mode in ((7, "delta-pose"), (29, "joint-space")):
            self.policy.end_episode()
            self.policy.bind_artifact_dir(Path(self.temp.name) / ("shape-" + str(size)))
            camera = str(Path(self.temp.name) / ("escape-" + str(size)))
            spec = ActionSpec(mode, size, low=(-2,) * size, high=(2,) * size,
                names=tuple("component_" + str(i) for i in range(size)), frame="declared test frame",
                rotation="native convention", gripper="declared nonbinary command")
            self.policy.start_episode(replace(self.context, action_spec=spec,
                observation_spec=ObservationSpec(cameras=(camera,)), replan_interval=None))
            vector = [i / 30 for i in range(size)]
            self.fake.override = lambda args, vector=vector: args.update(actions=[vector])
            decision = self.policy.act(Observation(0, "Follow this public instruction",
                {camera: self.obs.images["view_a"]}))
            self.assertEqual(decision.action.steps, (tuple(vector),))
            self.assertEqual(self.policy.packet["action_spec"], spec.to_dict())
            self.assertFalse(Path(camera + ".png").exists())
            self.assertEqual(Path(self.policy.packet["images"][0]["path"]).name, "camera-000.png")

    def test_disabled_safety_stop_is_rejected_then_corrected_without_execution(self):
        self.fake.override = lambda args: args.update(actions=[], stop_reason="safety_stop",
            reason="The current public view does not establish a safe motion.")
        with self.assertRaises(ActionRejected) as caught:
            self.policy.act(self.obs)
        self.assertEqual(caught.exception.issue.code, "invalid_stop")
        self.assertEqual((self.policy.issued, self.policy.controls), (1, 0))
        self.assertIsNone(self.policy.pending_action)
        packet = self.policy.packet
        self.policy.observe_rejection(ActionRejectionFeedback(caught.exception.issue, 1, 0, 0, 0, 1))
        self.fake.override = None
        decision = self.policy.act(self.obs)
        self.assertFalse(decision.stop)
        self.assertIsNotNone(decision.action)
        self.assertEqual((self.policy.issued, self.policy.controls), (2, 0))
        reply = json.loads(self.fake.replies[0][1]["contentItems"][0]["text"])
        self.assertEqual(reply["request_id"], packet["request_id"])
        self.assertEqual(reply["rejected_controls_executed"], 0)
        self.assertEqual(len(self.fake.requests), 1)

    def test_new_episode_drops_initial_reference_and_memory(self):
        self.policy.act(self.obs)
        self.policy.observe_execution(ExecutionFeedback(1, 1, 2, 2))
        self.policy.end_episode()
        self.policy.bind_artifact_dir(Path(self.temp.name) / "another-episode")
        self.policy.start_episode(self.context)
        self.policy.act(replace(self.obs, state=(.8, .7, .6)))
        self.assertEqual(self.policy.packet["initial_robot_state"]["values"], [.8, .7, .6])
        self.assertEqual(self.policy.packet["recent_executions"], [])

    def test_closure_exports_only_host_public_images_not_actor_notes(self):
        from benchkit.recording import RecordingOptions
        self.policy.end_episode()
        self.policy.configure_recording(RecordingOptions(images=True))
        self.policy.bind_artifact_dir(Path(self.temp.name) / "image-export")
        self.policy.start_episode(self.context)
        self.policy.act(self.obs)
        (self.policy.actor / "scratch/private-link").symlink_to(self.policy.audit, target_is_directory=True)
        destination = self.policy.audit
        self.policy.end_episode()
        inventory = json.loads((destination / "public_manifest.json").read_text())
        self.assertIn("000000/camera-000.png", inventory)
        self.assertFalse(any("scratch" in path or "NOTES" in path for path in inventory))
        self.assertFalse(self.fake.replies)


class EnabledSafetyStopChecks(unittest.TestCase):
    policy_parameters = {"safety_stop": True}
    setUp = fixtures.DirectChecks.setUp

    def test_explicit_opt_in_stops_without_action_or_success(self):
        self.fake.override = lambda args: args.update(actions=[], stop_reason="safety_stop",
            reason="Public evidence supports this optional policy stop.")
        decision = self.policy.act(self.obs)
        self.assertTrue(decision.stop)
        self.assertIsNone(decision.action)
        self.assertEqual((self.policy.issued, self.policy.controls), (1, 0))
        self.assertNotIn("success", decision.metadata["structured_output"])


class StopConfigurationChecks(unittest.TestCase):
    def test_profile_default_reaches_persistent_method_factories(self):
        from benchkit.model_profiles import load_profile
        from AgentPolicies.gpt6_astra.tools.factory import create_policy as factory
        data = load_profile("gpt6_astra")
        config = {**data["config"], "safety_stop": True}
        for method in ("codex-direct/v3", "codex-planned/v1"):
            policy = factory(config=config, identity=data["profile"]["policy"], control_method=method)
            self.assertTrue(policy.config["safety_stop"])
            policy = factory(config=config, identity=data["profile"]["policy"], control_method=method,
                             safety_stop=False)
            self.assertFalse(policy.config["safety_stop"])

    def test_default_opt_in_and_preflight_prompt_schema_descriptor_agree(self):
        for parameters, enabled in (({}, False), ({"safety_stop": False}, False), ({"safety_stop": True}, True)):
            with self.subTest(parameters=parameters):
                policy = create_policy("gpt6_astra", control_method="codex-direct/v3", **parameters)
                self.assertIs(policy.config["safety_stop"], enabled)
                self.assertIs(policy.descriptor.parameters["safety_stop"], enabled)
                self.assertIn("safety_stop=" + str(enabled).lower(), policy.prompt)
                schema = policy._tool_spec()["inputSchema"]["properties"]
                self.assertEqual(schema["actions"]["minItems"], 0 if enabled else 1)
                self.assertEqual(schema["stop_reason"]["enum"], [None, "safety_stop"] if enabled else [None])
                clone = policy._preflight_policy()
                self.assertEqual(clone.config, policy.config)
                self.assertEqual(clone.prompt, policy.prompt)
                self.assertEqual(clone.descriptor.parameters["prompt_sha256"], policy.descriptor.parameters["prompt_sha256"])

    def test_flag_is_strict_boolean_and_not_a_native_override(self):
        for value in (0, 1, "false", "true", [], {}):
            for method in ("codex-direct/v3", "codex-planned/v1"):
                with self.subTest(value=value, method=method), self.assertRaises((ValueError, TypeError)):
                    create_policy("gpt6_astra", control_method=method, safety_stop=value)
        with self.assertRaisesRegex(ValueError, "only by Direct"):
            create_policy("gpt6_astra", control_method="codex-native/v1", safety_stop=False)


class MethodSelectionChecks(unittest.TestCase):
    def test_separate_methods_share_runtime_not_each_other(self):
        self.assertEqual(CodexDirectPolicy.__bases__, (PersistentRuntime,))
        self.assertEqual(CodexPlannedPolicy.__bases__, (PersistentRuntime,))

    def test_generic_preset_overrides_and_retired_v2_rejected(self):
        for edge in (0, 240, 480, 4096):
            policy = create_policy("gpt6_astra", control_method="codex-direct/v3", image_max_edge=edge)
            self.assertEqual(policy.descriptor.parameters["image_max_edge"], edge)
        for count in (1, 5, 6, 32):
            policy = create_policy("gpt6_astra", control_method="codex-direct/v3", max_chunk_length=count)
            self.assertEqual(policy._tool_spec()["inputSchema"]["properties"]["actions"]["maxItems"], count)
        for invalid in (0, True, 33):
            with self.assertRaises(ValueError):
                create_policy("gpt6_astra", control_method="codex-direct/v3", max_chunk_length=invalid)
        for method in ("codex-direct/v1", "codex-direct/v2"):
            with self.assertRaises(ValueError):
                create_policy("gpt6_astra", control_method=method)

    def test_prompt_return_rule_is_conditional_generic_and_not_automatic(self):
        policy = create_policy("gpt6_astra", control_method="codex-direct/v3")
        self.assertIn("If and only if the current task asks", policy.prompt)
        for forbidden in ("ARX", "Dojo", "25 Hz", "container", "BOTH arms", "robodojo_act"):
            self.assertNotIn(forbidden, policy.prompt)
        self.assertNotIn("required_protocol", policy.config)
        self.assertNotIn("enforce_action_guard", policy.config)


if __name__ == "__main__":
    unittest.main()
