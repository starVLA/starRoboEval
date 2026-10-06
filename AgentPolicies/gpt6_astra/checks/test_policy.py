"""Pure native IO/factory checks; no CLI, API request or simulator."""
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from benchkit.contracts import Observation, ObservationSpec, Usage
from benchkit.errors import PolicyError
from AgentPolicies.gpt6_astra.tools.factory import create_policy, METHODS, ROOT
from AgentPolicies.gpt6_astra.tools.native_io import NativeActionIO
from AgentPolicies.gpt6_astra.checks.fixtures import context
from AgentPolicies.gpt6_astra.checks.test_codex_native import cli_result

IDENTITY = {"name": "fixture", "kind": "direct-model", "model": "gpt-6-astra", "provider": "openai"}
CONFIG = json.loads((ROOT / "configs/config.json").read_text())


class NativeIOChecks(unittest.TestCase):
    def setUp(self):
        self.policy = create_policy(config=CONFIG, identity=IDENTITY)
        self.policy.start_episode(context())
        self.obs = Observation(0, "Move to the target", metadata={"hidden-marker": "never forward"})

    def parse(self, **changes):
        value = {"stop": False, "stop_reason": None, "actions": [[.25, -.5]], "note": "move"}
        value.update(changes)
        return self.policy._action_text(json.dumps(value), Usage(calls=1), {"source": "fake"})

    def test_io_is_not_an_api_policy_or_dispatcher(self):
        self.assertIsInstance(self.policy, NativeActionIO)
        self.assertFalse(hasattr(NativeActionIO, "act"))
        public, images = self.policy._request(self.obs)
        self.assertEqual(images, [])
        self.assertEqual(public["instruction"], self.obs.instruction)
        self.assertEqual(public["action_spec"]["size"], 2)
        for hidden in ("hidden-marker", "private-source", "fixture-task", "opaque"):
            self.assertNotIn(hidden, json.dumps(public))
        self.assertNotIn("model", public)
        self.assertNotIn("input", public)

    def test_declared_finite_state_only(self):
        self.policy.end_episode()
        self.policy.start_episode(context(observation_spec=ObservationSpec(state_names=("joint", "gripper"))))
        public, _ = self.policy._request(replace(self.obs, state=(.1, .2)))
        self.assertEqual(public["state_names"], ["joint", "gripper"])
        self.assertEqual(public["state"], [.1, .2])
        for state in (None, (1,), (True, 0), (float("nan"), 0), (float("inf"), 0)):
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.policy._request(replace(self.obs, state=state))

    def test_undeclared_state_and_privileged_contract_rejected(self):
        with self.assertRaises(ValueError):
            self.policy._request(replace(self.obs, state=(0,)))
        self.policy.end_episode()
        with self.assertRaises(PolicyError):
            self.policy.start_episode(context(observation_spec=ObservationSpec(privileged=True)))

    def test_original_png_roundtrip_and_camera_order(self):
        self.policy.end_episode()
        self.policy.start_episode(context(observation_spec=ObservationSpec(cameras=("left", "right"))))
        pixels = {"left": np.array([[[1, 2, 3]]], dtype=np.uint8),
                  "right": np.array([[[254, 128, 0]]], dtype=np.uint8)}
        _, images = self.policy._request(replace(self.obs, images=pixels))
        for camera, payload in zip(("left", "right"), images):
            with Image.open(io.BytesIO(payload)) as actual:
                self.assertTrue(np.array_equal(np.asarray(actual), pixels[camera]))
        for invalid in ({}, {"left": pixels["left"]}, {**pixels, "private": pixels["left"]}):
            with self.assertRaises(ValueError):
                self.policy._request(replace(self.obs, images=invalid))

    def test_actions_exact_and_never_repaired(self):
        decision = self.parse()
        self.assertEqual(decision.action.steps, ((.25, -.5),))
        for change in ({"actions": []}, {"actions": [[2, 0]]}, {"actions": [[0]]},
                       {"actions": [[True, 0]]}, {"actions": [[float("inf"), 0]]},
                       {"actions": [[0, 0]] * 6}, {"stop_reason": "give_up"}):
            with self.subTest(change=change), self.assertRaises((TypeError, ValueError)):
                self.parse(**change)

    def test_strict_json_rejects_duplicate_unknown_and_nonfinite(self):
        for text in ('{"stop":true,"stop":false}', '{"x":0}', '{"value":NaN}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.policy._action_text(text, Usage(), {})

    def test_native_give_up_and_explained_safety_stop_remain_available(self):
        for reason in ("give_up", "safety_stop"):
            decision = self.parse(stop=True, stop_reason=reason, actions=[])
            self.assertTrue(decision.stop)
        with self.assertRaises(ValueError):
            self.parse(stop=True, stop_reason="safety_stop", actions=[], note=" ")
        with self.assertRaises(ValueError):
            self.parse(stop=True, stop_reason="give_up")
        with self.assertRaises(ValueError):
            self.parse(note="x" * 513)

    def test_retry_preset_is_explicit_but_does_not_add_policy_decisions(self):
        with patch("AgentPolicies.gpt6_astra.transports.codex_cli.send", return_value=cli_result()) as send:
            decision = self.policy.act(self.obs)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["max_attempts"], 10)
        self.assertEqual(send.call_args.kwargs["retry_backoff_s"], 10.0)
        self.assertEqual(self.policy.issued, 1)
        self.assertEqual(self.policy.rule.completed, 0)
        self.assertEqual(len(decision.action.steps), 2)


class FactoryChecks(unittest.TestCase):
    def test_exact_active_set_and_default(self):
        self.assertEqual(METHODS, ("codex-native/v1", "codex-direct/v3", "codex-planned/v1"))
        self.assertEqual(create_policy(config=CONFIG, identity=IDENTITY).descriptor.version, "codex-native/v1")

    def test_retired_methods_are_rejected_not_aliased(self):
        for method in ("responses-native/v1", "codex-eef/v1", "codex-eef/v2", "codex-direct/v1", "codex-direct/v2", "unknown"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                create_policy(config=CONFIG, identity=IDENTITY, control_method=method)

    def test_profile_default_prompt_selects_each_own_method_preset(self):
        default = (ROOT / "prompts/codex_native_prompt.txt").read_text()
        for method, stem in (("codex-native/v1", "codex_native"), ("codex-direct/v3", "codex_direct_v3"),
                             ("codex-planned/v1", "codex_planned")):
            with self.subTest(method=method):
                policy = create_policy(config=CONFIG, identity=IDENTITY, control_method=method, prompt=default)
                expected = (ROOT / "prompts" / (stem + "_prompt.txt")).read_text()
                if method in ("codex-direct/v3", "codex-planned/v1"):
                    self.assertEqual(policy._prompt_base, expected)
                    self.assertTrue(policy.prompt.startswith(expected))
                    self.assertIn("Effective policy stop configuration: safety_stop=false", policy.prompt)
                else:
                    self.assertEqual(policy.prompt, expected)
                custom = create_policy(config=CONFIG, identity=IDENTITY, control_method=method, prompt="custom public instructions")
                if method in ("codex-direct/v3", "codex-planned/v1"):
                    self.assertEqual(custom._prompt_base, "custom public instructions")
                    self.assertIn("Effective policy stop configuration: safety_stop=false", custom.prompt)
                else:
                    self.assertEqual(custom.prompt, "custom public instructions")

    def test_native_never_inherits_registry_dojo_guard_or_preview(self):
        policy = create_policy(config=CONFIG, identity=IDENTITY)
        self.assertNotIn("enforce_action_guard", policy.config)
        self.assertNotIn("image_max_edge", policy.config)
        for override in ({"enforce_action_guard": False}, {"image_max_edge": 480}):
            with self.assertRaises(ValueError):
                create_policy(config=CONFIG, identity=IDENTITY, **override)


if __name__ == "__main__":
    unittest.main()
