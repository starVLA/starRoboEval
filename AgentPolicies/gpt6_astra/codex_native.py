"""Generic persistent direct control over the service-declared native action space.

No benchmark/robot-specific controller, task recipe or simulator access. The
first public observation is a reference, never an executable home trajectory.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import os
import sys
import uuid

from benchkit.contracts import ActionChunk, PolicyDecision, PolicyDescriptor
from benchkit.model_profiles import validate_configuration
from benchkit.validation import validate_action_vector
from AgentPolicies.gpt6_astra.tools.json_io import _invalid_constant, _strict_object
from AgentPolicies.gpt6_astra.tools.persistent_runtime import (
    ROOT, TRANSPORT, PersistentRuntime, _bad, _json, _write,
)
from AgentPolicies.gpt6_astra.tools.public_observation import public_state, public_images
from AgentPolicies.gpt6_astra.tools.stagnation_review import RepeatedCommandReview

METHOD = "codex-native/v2"


class CodexNativePolicy(PersistentRuntime):
    METHOD = METHOD

    def __init__(self, *, identity, prompt=None, timeout_s=None, max_chunk_length=None,
                 image_max_edge=None, safety_stop=None,
                 allow_task_completion=None, stagnation_review=None, stagnation_window=None):
        payload = (ROOT / "configs/codex_native_config.json").read_bytes()
        self.config = json.loads(payload, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
        for key, value in (("timeout_s", timeout_s), ("max_chunk_length", max_chunk_length),
                           ("image_max_edge", image_max_edge), ("safety_stop", safety_stop),
                           ("allow_task_completion", allow_task_completion),
                           ("stagnation_review", stagnation_review), ("stagnation_window", stagnation_window)):
            if value is not None:
                self.config[key] = value
        # The policy's own schema is the single source of identity and ranges,
        # checked before any actor/runtime starts.
        schema = json.loads((ROOT / "configs/configuration.schema.json").read_bytes(),
                            object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
        validate_configuration("gpt6_astra", self.config, schema)
        self._prompt_base = ((ROOT / "configs/codex_native_prompt.txt").read_text()
                             if prompt is None else prompt)
        if not isinstance(self._prompt_base, str) or not self._prompt_base.strip() or len(self._prompt_base) > 32000:
            raise ValueError("Codex native prompt must be bounded nonempty text")
        self.prompt = self._effective_prompt()
        self.descriptor = PolicyDescriptor(**identity, version=self.METHOD, parameters={
            "control_method": self.METHOD, "transport": TRANSPORT, "effective_config": self.config.copy(),
            "preset_sha256": hashlib.sha256(payload).hexdigest(),
            "prompt_sha256": hashlib.sha256(self.prompt.encode()).hexdigest(),
            **{key: self.config[key] for key in ("max_chunk_length", "timeout_s", "image_max_edge",
                                                "ordinary_give_up", "safety_stop", "feedback_projection",
                                                "initial_state_reference", "allow_task_completion",
                                                "stagnation_review", "stagnation_window")},
            "model_identity_evidence": "requested and app-server-reported; not independent provider attestation",
            "isolation": "public-only actor workspace; explicit Codex permission profile, not kernel attestation",
            "provider_calls": None, "automatic_crash_resume": False,
        })
        super().__init__()
        self._clear_native()

    def _stop_rule(self):
        completion = (
            'allow_task_completion=true: when you believe the task is complete, call robot_act '
            'with the current request_id, actions=[], stop_reason="task_complete", and a concise reason. '
            'This normally ends the interaction immediately. No extra verification, holding actions, '
            'or waiting for the execution budget is required. Your declaration is recorded separately '
            'from native success and scoring; it does not award success. '
            if self.config["allow_task_completion"] else
            'allow_task_completion=false: task_complete is not available in this configuration. '
        )
        safety = (
            'safety_stop=true: an explained voluntary safety stop is permitted with '
            'actions=[] and stop_reason="safety_stop". '
            if self.config["safety_stop"] else
            'safety_stop=false: the safety_stop reason is disabled. '
        )
        return completion + safety + (
            'For continued control, submit at least one valid action and stop_reason=null. '
            'Ordinary give-up is not enabled; uncertainty alone is not a task-completion declaration.'
        )

    def _effective_prompt(self):
        return (self._prompt_base + "\nEffective policy stop configuration: " + self._stop_rule() +
                " Native termination, execution budgets, protocol errors and external safeguards remain authoritative.\n")

    def _stop_reasons(self):
        return (("safety_stop",) if self.config["safety_stop"] else ()) + (
            ("task_complete",) if self.config["allow_task_completion"] else ())

    def _tool_description(self):
        if self.config["allow_task_completion"]:
            return ('Submit direct native actions, or declare task completion with actions=[] and '
                    'stop_reason="task_complete" to normally end the interaction without another control or check. '
                    'Completion is your judgment, not a native success claim. ' +
                    ('An explained safety_stop with actions=[] is also permitted. ' if self.config["safety_stop"] else ''))
        return ("Submit direct native action vectors or an explained safety stop. "
                if self.config["safety_stop"] else "Submit direct native action vectors; voluntary stops are disabled. ")

    def _chunk_limit(self):
        # A driver/service execution prefix narrows what one episode may offer.
        prefix = self.context.replan_interval if self.context is not None else None
        ceiling = self.config["max_chunk_length"]
        return ceiling if prefix is None else min(ceiling, prefix)

    def _clear_native(self):
        self.initial_robot_state = None
        self.initial_observation_path = None
        self.execution_memory = deque(maxlen=self.config["execution_history_decisions"])
        self.review = RepeatedCommandReview(self.config["stagnation_review"], self.config["stagnation_window"])

    def _preflight_policy(self):
        return CodexNativePolicy(identity={key: getattr(self.descriptor, key)
            for key in ("name", "kind", "model", "provider")}, prompt=self._prompt_base,
            **{key: self.config[key] for key in ("timeout_s", "max_chunk_length", "image_max_edge", "safety_stop",
                                               "allow_task_completion", "stagnation_review", "stagnation_window")})

    def start_episode(self, context):
        super().start_episode(context)
        self._clear_native()
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
        stop_reasons = self._stop_reasons()
        feedback_hint = (
            "For continued control, the next reply supplies public observations and actual execution feedback; no reset or score query."
            if "task_complete" in stop_reasons else
            "The next reply supplies public observations and actual execution feedback; no reset or score query."
        )
        return {"type": "function", "name": self._tool_name(),
            "description": self._tool_description() + feedback_hint,
            "inputSchema": {"type": "object", "additionalProperties": False,
                "required": ["request_id", "actions", "reason", "stop_reason"],
                "properties": {
                    "request_id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "actions": {"type": "array", "minItems": 0 if stop_reasons else 1,
                                "maxItems": self._chunk_limit(), "items": vector},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "stop_reason": {"type": ["string", "null"] if stop_reasons else "null",
                                    "enum": [None, *stop_reasons]},
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
        if type(actions) is not list or len(actions) > self._chunk_limit():
            _bad("invalid_length", "action")
        stop = arguments["stop_reason"]
        if stop not in (None, *self._stop_reasons()) or (stop is None) != bool(actions):
            _bad("invalid_stop", "stop_reason")
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
        before = self.packet.get("state") if self.packet is not None else None
        previous = self.controls
        super()._feedback(feedback)
        if feedback.executed_steps:
            self.execution_memory.append({"submission": self.issued,
                "control_start": previous + 1, "control_end": self.controls,
                "actions": proposal["actions"][:feedback.executed_steps],
                "authority": "acknowledged_execution_not_task_effect"})
            self.review.acknowledge(proposal["actions"][:feedback.executed_steps], before)

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
            "max_chunk_length": self._chunk_limit(), "previous_execution": self.feedback,
            "recent_executions": list(self.execution_memory),
            "feedback_projection": self.config["feedback_projection"],
            "raw_control_feedback_forwarded": False, "workspace_context": self.workspace,
            "image_max_edge": self.config["image_max_edge"], "request_id": uuid.uuid4().hex,
            "next_call": {"tool": self._tool_name(), "observation_path": str(path)}}
        self._extend_packet(packet)
        self._remember_public(path, _write(path, packet))
        self.packet = packet
        return packet, attachments

    def _extend_packet(self, packet):
        # The recorded packet schema remains distinct from the method identity.
        packet["schema_version"] = "starvla-rsi.direct-observation/v4"
        packet["policy_review"] = self.review.feedback(packet["state"], packet["state_names"])

    def end_episode(self):
        try:
            super().end_episode()
        finally:
            self._clear_native()


def create_policy(*, config, identity, **parameters):
    """Create the single active method; retired identities are never aliases."""
    if config.get("control_method") != METHOD:
        raise ValueError("unknown or retired model control method")
    if "stagnation_window" in parameters:
        # Choosing a review window turns the review on.
        if parameters.setdefault("stagnation_review", True) is not True:
            raise ValueError("stagnation_window conflicts with a disabled stagnation_review")
    for key in ("timeout_s", "max_chunk_length", "image_max_edge", "safety_stop",
                "allow_task_completion", "stagnation_review", "stagnation_window"):
        parameters.setdefault(key, config[key])
    return CodexNativePolicy(identity=identity, **parameters)
