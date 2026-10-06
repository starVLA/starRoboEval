"""Public native-vector observation encoding and action parsing; no provider API."""
from __future__ import annotations

import hashlib
import io
import json
import math
from numbers import Real

from benchkit.contracts import ActionChunk, PolicyDecision, PolicyDescriptor
from benchkit.errors import PolicyError
from AgentPolicies.policy_support.stop_rules import VoluntaryStopRule, with_stop_rule_prompt
from AgentPolicies.gpt6_astra.tools.json_io import _invalid_constant, _strict_object


class NativeActionIO:
    """Model-owned request/parse boundary over a benchmark-declared action space.

    Image encoding is lossless; actions are validated, never clamped, repaired,
    planned or replaced. This helper performs no inference, provider dispatch or native simulator access.
    """

    def __init__(self, *, config, identity, prompt, timeout_s=None, max_chunk_length=None,
                 min_action_decisions_before_give_up=None):
        self.config = dict(config)
        for key, value in (("timeout_s", timeout_s), ("max_chunk_length", max_chunk_length),
                           ("min_action_decisions_before_give_up", min_action_decisions_before_give_up)):
            if value is not None:
                self.config[key] = value
        if (isinstance(self.config["timeout_s"], bool)
                or not isinstance(self.config["timeout_s"], (float, int))
                or not math.isfinite(self.config["timeout_s"])
                or not 0 < self.config["timeout_s"] <= 3600):
            raise ValueError("timeout_s must be finite and in (0, 3600]")
        if type(self.config["max_chunk_length"]) is not int or not 1 <= self.config["max_chunk_length"] <= 32:
            raise ValueError("max_chunk_length must be an integer in [1, 32]")
        self.rule = VoluntaryStopRule(self.config["min_action_decisions_before_give_up"])
        self.prompt = with_stop_rule_prompt(prompt, self.rule.minimum)
        self.descriptor = PolicyDescriptor(**identity, version=self.config["control_method"], parameters={
            "transport": self.config["transport"], "history": self.config["history"],
            "reasoning_effort": self.config["reasoning_effort"],
            "max_output_tokens": self.config["max_output_tokens"],
            "timeout_s": self.config["timeout_s"], "max_chunk_length": self.config["max_chunk_length"],
            "max_image_pixels": self.config["max_image_pixels"],
            "max_response_bytes": self.config["max_response_bytes"],
            "prompt_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
            "policy_stop_rule": self.rule.parameters,
        })
        self.context = None

    def compatibility_errors(self, observation_spec, action_spec):
        errors = []
        if observation_spec.privileged:
            errors.append("native-vector policy rejects privileged observations")
        if len(set(observation_spec.cameras)) != len(observation_spec.cameras):
            errors.append("camera names must be unique")
        if action_spec.size > 256:
            errors.append("native-vector policy supports at most 256 action components")
        return errors

    def start_episode(self, context):
        errors = self.compatibility_errors(context.observation_spec, context.action_spec)
        if errors:
            raise PolicyError("; ".join(errors))
        self.context = context
        self.rule.start_episode(context)

    def observe_execution(self, feedback):
        self.rule.observe_execution(feedback)

    def end_episode(self):
        self.context = None
        self.rule.feedback = None

    def _schema(self):
        return {
            "type": "object", "additionalProperties": False,
            "required": ["stop", "stop_reason", "actions", "note"],
            "properties": {
                "stop": {"type": "boolean"},
                "stop_reason": {"type": ["string", "null"], "enum": ["give_up", "safety_stop", None]},
                "actions": {"type": "array", "maxItems": self.config["max_chunk_length"], "items": {
                    "type": "array", "minItems": self.context.action_spec.size,
                    "maxItems": self.context.action_spec.size, "items": {"type": "number"}}},
                "note": {"type": ["string", "null"], "maxLength": 512},
            },
        }

    def _request(self, observation):
        if self.context is None:
            raise ValueError("episode not started")
        spec = self.context.observation_spec
        if set(observation.images) != set(spec.cameras):
            raise ValueError("images must exactly match declared cameras")
        state = None
        if spec.state_names:
            if observation.state is None or len(observation.state) != len(spec.state_names):
                raise ValueError("state must match declared state names")
            if any(isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(x)
                   for x in observation.state):
                raise ValueError("state must be finite numbers")
            state = [float(x) for x in observation.state]
        elif observation.state is not None:
            raise ValueError("undeclared state is not permitted")
        if not isinstance(observation.instruction, str) or not observation.instruction.strip():
            raise ValueError("task instruction is missing")
        public = {
            "instruction": observation.instruction,
            "action_spec": self.context.action_spec.to_dict(),
            "state_names": list(spec.state_names), "state": state,
            "control_feedback": self.rule.feedback_view(), "policy_constraints": self.rule.public_view(),
            "limits": {"max_steps": self.context.max_steps, "max_policy_calls": self.context.max_policy_calls,
                       "replan_interval": self.context.replan_interval, "budget_mode": self.context.budget_mode,
                       "max_chunk_length": self.config["max_chunk_length"]},
        }
        images = []
        if spec.cameras:
            import numpy as np
            from PIL import Image

            pixels = 0
            for camera in spec.cameras:
                array = observation.images[camera]
                if (not isinstance(array, np.ndarray) or array.dtype != np.uint8 or array.ndim != 3
                        or array.shape[2] != 3 or not array.shape[0] or not array.shape[1]):
                    raise ValueError("camera requires an RGB uint8 HWC array")
                pixels += array.shape[0] * array.shape[1]
                if pixels > self.config["max_image_pixels"]:
                    raise ValueError("observation exceeds total image pixel limit")
                buffer = io.BytesIO()
                Image.fromarray(array).save(buffer, format="PNG")
                images.append(buffer.getvalue())
        return public, images

    def _action_text(self, text, usage, receipt):
        """Parse native actions without fabricating a provider response envelope."""
        if not isinstance(text, str) or len(text.encode()) > self.config["max_response_bytes"]:
            raise ValueError("expected one bounded structured output")
        value = json.loads(text, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
        if not isinstance(value, dict) or set(value) != {"stop", "stop_reason", "actions", "note"}:
            raise ValueError("wrong output fields")
        if type(value["stop"]) is not bool or not isinstance(value["actions"], list):
            raise ValueError("invalid stop/actions types")
        if value["note"] is not None and (not isinstance(value["note"], str) or len(value["note"]) > 512):
            raise ValueError("invalid public note")
        common = {"note": value["note"], "usage": usage,
                  "metadata": {"provider_receipt": receipt, "structured_output": value}}
        if value["stop"]:
            if value["actions"] or value["stop_reason"] not in ("give_up", "safety_stop"):
                raise ValueError("stop must have no actions and a permitted reason")
            if value["stop_reason"] == "safety_stop" and (not value["note"] or not value["note"].strip()):
                raise ValueError("safety stop requires a public safety explanation")
            decision = PolicyDecision(stop=True, stop_reason=value["stop_reason"], **common)
        else:
            if value["stop_reason"] is not None or not 1 <= len(value["actions"]) <= self.config["max_chunk_length"]:
                raise ValueError("action decision has invalid reason or chunk length")
            if any(not isinstance(vector, list) for vector in value["actions"]):
                raise ValueError("action vectors must be arrays")
            vectors = [self.context.action_spec.validate(vector) for vector in value["actions"]]
            decision = PolicyDecision(action=ActionChunk.from_steps(vectors), **common)
        self.rule.validate(decision)
        return decision
