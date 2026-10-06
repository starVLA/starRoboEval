"""Generic persistent direct control over the service-declared native action space.

No benchmark/robot-specific controller, task recipe or simulator access. The
first public observation is a reference, never an executable home trajectory.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
import os
import sys
import uuid

from benchkit.contracts import ActionChunk, PolicyDecision, PolicyDescriptor
from benchkit.validation import validate_action_vector
from AgentPolicies.gpt6_astra.tools.json_io import _invalid_constant, _strict_object
from AgentPolicies.gpt6_astra.tools.persistent_runtime import (
    ROOT, TRANSPORT, PersistentRuntime, _bad, _json, _write,
)
from AgentPolicies.gpt6_astra.tools.public_observation import image_edge, public_state, public_images

METHOD = "codex-direct/v3"


class CodexDirectPolicy(PersistentRuntime):
    def __init__(self, *, identity, prompt=None, timeout_s=None, max_chunk_length=None,
                 min_action_decisions_before_give_up=None, image_max_edge=None, safety_stop=None):
        payload = (ROOT / "configs/codex_direct_v3_config.json").read_bytes()
        self.config = json.loads(payload, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
        if (self.config["control_method"] != METHOD or self.config["transport"] != TRANSPORT
                or self.config["model"] != "gpt-6-astra" or self.config["provider"] != "openai"
                or self.config["reasoning_effort"] != "xhigh" or self.config["ordinary_give_up"] is not False
                or type(self.config["safety_stop"]) is not bool):
            raise ValueError("unsupported Direct preset identity")
        if (min_action_decisions_before_give_up not in (None, 0)
                or isinstance(min_action_decisions_before_give_up, bool)):
            raise ValueError("Direct v3 disables ordinary give-up; no mandatory persistence floor")
        for key, value in (("timeout_s", timeout_s), ("max_chunk_length", max_chunk_length),
                           ("image_max_edge", image_max_edge), ("safety_stop", safety_stop)):
            if value is not None:
                self.config[key] = value
        if type(self.config["safety_stop"]) is not bool:
            raise ValueError("Direct safety_stop must be a boolean")
        if (type(self.config["timeout_s"]) not in (int, float)
                or not math.isfinite(self.config["timeout_s"]) or not 0 < self.config["timeout_s"] <= 900):
            raise ValueError("Direct timeout must be finite and in (0,900]")
        if type(self.config["max_chunk_length"]) is not int or not 1 <= self.config["max_chunk_length"] <= 32:
            raise ValueError("Direct chunks must contain 1..32 controls")
        image_edge(self.config["image_max_edge"])
        self._prompt_base = ((ROOT / "prompts/codex_direct_v3_prompt.txt").read_text()
                             if prompt is None else prompt)
        if not isinstance(self._prompt_base, str) or not self._prompt_base.strip() or len(self._prompt_base) > 32000:
            raise ValueError("Direct prompt must be bounded nonempty text")
        stop_rule = (
            'safety_stop=true: an explained voluntary stop is permitted with actions=[] and stop_reason="safety_stop".'
            if self.config["safety_stop"] else
            'safety_stop=false: voluntary safety stops are disabled for this simulation evaluation. '
            'Submit at least one valid action and stop_reason=null. Do not end the episode merely because '
            'progress is uncertain, an object is dropped, or contact is possible; use public feedback to replan.'
        )
        self.prompt = (self._prompt_base + "\nEffective policy stop configuration: " + stop_rule +
                       " Native termination, execution budgets, protocol errors and external safeguards remain authoritative.\n")
        self.descriptor = PolicyDescriptor(**identity, version=METHOD, parameters={
            "control_method": METHOD, "transport": TRANSPORT, "effective_config": self.config.copy(),
            "preset_sha256": hashlib.sha256(payload).hexdigest(),
            "prompt_sha256": hashlib.sha256(self.prompt.encode()).hexdigest(),
            **{key: self.config[key] for key in ("max_chunk_length", "timeout_s", "image_max_edge",
                                                "ordinary_give_up", "safety_stop", "feedback_projection",
                                                "initial_state_reference")},
            "model_identity_evidence": "requested and app-server-reported; not independent provider attestation",
            "isolation": "public-only actor workspace; explicit Codex permission profile, not kernel attestation",
            "provider_calls": None, "automatic_crash_resume": False,
        })
        super().__init__()
        self._clear_direct()

    def _clear_direct(self):
        self.initial_robot_state = None
        self.initial_observation_path = None
        self.execution_memory = deque(maxlen=self.config["execution_history_decisions"])

    def _preflight_policy(self):
        return CodexDirectPolicy(identity={key: getattr(self.descriptor, key)
            for key in ("name", "kind", "model", "provider")}, prompt=self._prompt_base,
            **{key: self.config[key] for key in ("timeout_s", "max_chunk_length", "image_max_edge", "safety_stop")})

    def start_episode(self, context):
        super().start_episode(context)
        self._clear_direct()
        scratch = self.actor / "scratch"
        scratch.mkdir(mode=0o700)
        notes = self.actor / "NOTES.md"
        with notes.open("x") as stream:
            os.chmod(notes, 0o600)
            stream.write("# Same-episode working notes\n\n"
                         "Keep observed facts separate from hypotheses and intended outcomes.\n"
                         "ACKs confirm execution, not task success; do not record private chain-of-thought.\n")
        self.workspace = {"schema_version": "starvla-rsi.direct-workspace/v3",
            "python_executable": sys.executable, "observations_path": str(self.public),
            "scratch_path": str(scratch), "notes_path": str(notes), "working_directory": str(self.actor),
            "evidence_access": "read_only", "working_files_access": "actor_owned",
            "lifetime": "this_episode_only"}

    def _tool_name(self):
        return "robot_act"

    def _initial_instruction(self):
        return ("Control this single episode with robot_act and the declared native action contract. "
                "Use only public observations and actual execution feedback.\n")

    def _tool_spec(self):
        vector = {"type": "array", "minItems": 1, "maxItems": 256, "items": {"type": "number"}}
        if self.context is not None:
            vector.update(minItems=self.context.action_spec.size, maxItems=self.context.action_spec.size)
        return {"type": "function", "name": self._tool_name(),
            "description": ("Submit direct native action vectors or an explained safety stop. "
                            if self.config["safety_stop"] else "Submit direct native action vectors; voluntary stops are disabled. ") +
                           "The next reply supplies public observations and actual execution feedback; no reset or score query.",
            "inputSchema": {"type": "object", "additionalProperties": False,
                "required": ["request_id", "actions", "reason", "stop_reason"],
                "properties": {
                    "request_id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "actions": {"type": "array", "minItems": 0 if self.config["safety_stop"] else 1,
                                "maxItems": self.config["max_chunk_length"], "items": vector},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "stop_reason": {"type": ["string", "null"] if self.config["safety_stop"] else "null",
                                    "enum": [None, "safety_stop"] if self.config["safety_stop"] else [None]},
                }}}

    def _validate_action(self, arguments, packet):
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
            except (ValueError, RecursionError):
                _bad("invalid_json")
        if type(arguments) is not dict or set(arguments) != {"request_id", "actions", "reason", "stop_reason"}:
            _bad("unexpected_fields")
        if type(arguments["request_id"]) is not str or arguments["request_id"] != packet["request_id"]:
            _bad("invalid_action")
        reason = arguments["reason"]
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
            _bad("invalid_length", "note")
        actions = arguments["actions"]
        if type(actions) is not list or len(actions) > self.config["max_chunk_length"]:
            _bad("invalid_length", "action")
        stop = arguments["stop_reason"]
        if stop == "safety_stop" and not self.config["safety_stop"]:
            _bad("invalid_stop", "safety_stop")
        if stop not in (None, "safety_stop") or (stop is None) != bool(actions):
            _bad("invalid_stop", "safety_stop")
        if any(type(action) is not list for action in actions):
            _bad("invalid_type", "action")
        vectors = [validate_action_vector(self.context.action_spec, action) for action in actions]
        value = json.loads(_json(arguments))
        value["steps"] = len(vectors)
        return value, vectors

    def _decision(self, value, vectors, usage, receipt):
        common = {"note": value["reason"], "usage": usage,
                  "metadata": {"provider_receipt": receipt, "structured_output": value}}
        if value["stop_reason"] is not None:
            self.pending_action = None
            return PolicyDecision(stop=True, stop_reason=value["stop_reason"], **common)
        return PolicyDecision(action=ActionChunk.from_steps(vectors), **common)

    def _feedback(self, feedback):
        proposal = self.pending_action
        previous = self.controls
        super()._feedback(feedback)
        if feedback.executed_steps:
            self.execution_memory.append({"submission": self.issued,
                "control_start": previous + 1, "control_end": self.controls,
                "actions": proposal["actions"][:feedback.executed_steps],
                "authority": "acknowledged_execution_not_task_effect"})

    def _observation(self, observation):
        spec = self.context.observation_spec
        if (type(observation.step) is not int or observation.step != self.controls
                or set(observation.images) != set(spec.cameras)):
            raise ValueError("public observation/counter mismatch")
        state = public_state(observation, spec)
        if not isinstance(observation.instruction, str) or not observation.instruction.strip():
            raise ValueError("missing public task instruction")
        if self.packet is not None and self.rejection is not None and self.feedback["executed_steps"] == 0:
            self.packet = {**self.packet, "action_submissions": self.issued, "previous_execution": self.feedback}
            return self.packet, []
        directory = self.public / f"{self.issued:06d}"
        directory.mkdir()
        attachments, descriptors = public_images(observation, spec.cameras, directory,
            config=self.config, remember=self._remember_public)
        path = directory / "observation.json"
        if self.initial_robot_state is None:
            self.initial_robot_state = {"step": observation.step, "state_names": list(spec.state_names),
                "values": None if state is None else list(state), "authority": "initial_public_observation_not_action"}
            self.initial_observation_path = str(path)
        packet = {"schema_version": "starvla-rsi.direct-observation/v3",
            "instruction": observation.instruction, "state": state, "state_names": list(spec.state_names),
            "action_spec": self.context.action_spec.to_dict(), "images": descriptors,
            "initial_robot_state": json.loads(_json(self.initial_robot_state)),
            "initial_observation_path": self.initial_observation_path,
            "step_id": self.controls, "remaining_controls": self.control_limit - self.controls,
            "executed_decisions": self.decisions, "action_submissions": self.issued,
            "max_action_submissions": self.context.max_policy_calls,
            "max_chunk_length": self.config["max_chunk_length"], "previous_execution": self.feedback,
            "recent_executions": list(self.execution_memory),
            "feedback_projection": self.config["feedback_projection"],
            "raw_control_feedback_forwarded": False, "workspace_context": self.workspace,
            "image_max_edge": self.config["image_max_edge"], "request_id": uuid.uuid4().hex,
            "next_call": {"tool": self._tool_name(), "observation_path": str(path)}}
        self._remember_public(path, _write(path, packet))
        self.packet = packet
        return packet, attachments

    def end_episode(self):
        try:
            super().end_episode()
        finally:
            self._clear_direct()
