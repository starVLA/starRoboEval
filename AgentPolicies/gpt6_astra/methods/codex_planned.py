"""Generic public-evidence planning over the shared persistent Codex runtime.

No simulator client, benchmark-specific controller, reward reader or action
repair lives here. Model summaries are attributed claims; only ACKed prefixes
enter execution memory. Transport permissions and no-replay lifecycle are
provided by the shared runtime, not inherited from another policy.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
import sys
import uuid

from benchkit.contracts import ActionChunk, PolicyDecision, PolicyDescriptor
from benchkit.errors import PolicyError
from benchkit.validation import validate_action_vector
from AgentPolicies.gpt6_astra.tools.persistent_runtime import (
    ROOT, TRANSPORT, PersistentRuntime, _bad, _json, _write,
)
from AgentPolicies.gpt6_astra.tools.public_observation import image_edge, public_state, public_images
from AgentPolicies.gpt6_astra.tools.json_io import _invalid_constant, _strict_object

METHOD = "codex-planned/v1"


def _object(properties):
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


def _shape(value, schema):
    """Validate this closed tool schema without an optional runtime dependency."""
    kind = schema["type"]
    valid = {"object": type(value) is dict, "array": type(value) is list,
             "string": type(value) is str, "integer": type(value) is int,
             "number": type(value) in (int, float), "null": value is None}
    if not any(valid[k] for k in (kind if isinstance(kind, list) else [kind])):
        _bad("invalid_type")
    if "enum" in schema and value not in schema["enum"]:
        _bad("invalid_action")
    if value is None:
        return
    if kind == "object":
        if set(value) != set(schema["properties"]):
            _bad("unexpected_fields")
        for key, child in schema["properties"].items():
            _shape(value[key], child)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 2**31):
            _bad("invalid_length")
        for item in value:
            _shape(item, schema["items"])
    elif kind == "string":
        if not value.strip() or len(value) > schema.get("maxLength", 512):
            _bad("invalid_length")
    elif kind in ("number", "integer"):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            _bad("non_finite")
        if value < schema.get("minimum", -math.inf):
            _bad("out_of_bounds")


class CodexPlannedPolicy(PersistentRuntime):
    def __init__(self, *, identity, prompt=None, timeout_s=None, max_chunk_length=None,
                 image_max_edge=None, min_action_decisions_before_give_up=None, safety_stop=None):
        payload = (ROOT / "configs/codex_planned_config.json").read_bytes()
        self.config = json.loads(payload, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
        if (self.config["schema_version"] != "starvla-rsi.codex-planned-config/v2"
                or self.config["control_method"] != METHOD or self.config["transport"] != TRANSPORT
                or self.config["model"] != "gpt-6-astra" or self.config["provider"] != "openai"
                or self.config["reasoning_effort"] != "xhigh" or self.config["ordinary_give_up"] is not False
                or type(self.config["safety_stop"]) is not bool):
            raise ValueError("unsupported planned preset identity")
        if (min_action_decisions_before_give_up not in (None, 0)
                or isinstance(min_action_decisions_before_give_up, bool)):
            raise ValueError("planned v1 disables ordinary give-up; no mandatory persistence floor")
        for key, value in (("timeout_s", timeout_s), ("max_chunk_length", max_chunk_length),
                           ("image_max_edge", image_max_edge), ("safety_stop", safety_stop)):
            if value is not None:
                self.config[key] = value
        if type(self.config["safety_stop"]) is not bool:
            raise ValueError("planned safety_stop must be a boolean")
        if (type(self.config["timeout_s"]) not in (int, float)
                or not math.isfinite(self.config["timeout_s"]) or not 0 < self.config["timeout_s"] <= 900):
            raise ValueError("planned timeout must be finite and in (0,900]")
        if type(self.config["max_chunk_length"]) is not int or not 1 <= self.config["max_chunk_length"] <= 32:
            raise ValueError("planned chunks must contain 1..32 controls")
        image_edge(self.config["image_max_edge"])
        self._prompt_base = ((ROOT / "prompts/codex_planned_prompt.txt").read_text()
                             if prompt is None else prompt)
        if not isinstance(self._prompt_base, str) or not self._prompt_base.strip() or len(self._prompt_base) > 32000:
            raise ValueError("planned prompt must be bounded nonempty text")
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
                                                "ordinary_give_up", "safety_stop", "feedback_projection")},
            "summary_authority": "model-authored claims, not verified task state or success",
            "model_identity_evidence": "requested and app-server-reported; not independent provider attestation",
            "isolation": "public-only actor workspace; explicit Codex permission profile, not kernel attestation",
            "provider_calls": None, "automatic_crash_resume": False,
        })
        super().__init__()
        self._clear_planning()

    def _clear_planning(self):
        self.model_summary = None
        self.execution_memory = deque(maxlen=self.config["execution_history_decisions"])
        self.observation_steps = set()

    def _preflight_policy(self):
        return CodexPlannedPolicy(identity={key: getattr(self.descriptor, key)
            for key in ("name", "kind", "model", "provider")}, prompt=self._prompt_base,
            **{key: self.config[key] for key in ("timeout_s", "max_chunk_length", "image_max_edge", "safety_stop")})

    def compatibility_errors(self, observation_spec, action_spec):
        errors = []
        if observation_spec.privileged:
            errors.append("planned method rejects privileged observations")
        for names in (observation_spec.cameras, observation_spec.state_names):
            if (len(set(names)) != len(names)
                    or any(not isinstance(name, str) or not name.strip() for name in names)):
                errors.append("public sensor names must be unique nonempty strings")
        if type(action_spec.size) is not int or not 1 <= action_spec.size <= 256:
            errors.append("planned method supports 1..256 declared numeric components")
        return errors

    def _context_errors(self, context):
        errors = self.compatibility_errors(context.observation_spec, context.action_spec)
        if (context.invalid_action_handling != "feedback" or context.budget_mode != "horizon"
                or type(context.max_steps) is not int or context.max_steps <= 0
                or type(context.max_policy_calls) is not int or context.max_policy_calls <= 0
                or (context.replan_interval is not None and (type(context.replan_interval) is not int
                    or context.replan_interval < self.config["max_chunk_length"]))):
            errors.append("planned method requires feedback, positive horizon/call cap and an unshortened method prefix")
        return errors

    def start_episode(self, context):
        super().start_episode(context)
        self._clear_planning()
        scratch = self.actor / "scratch"
        scratch.mkdir(mode=0o700)
        self.workspace = {"schema_version": "starvla-rsi.planned-workspace/v1",
            "python_executable": sys.executable, "observations_path": str(self.public),
            "scratch_path": str(scratch), "working_directory": str(self.actor),
            "evidence_access": "read_only", "working_files_access": "actor_owned",
            "lifetime": "this_episode_only"}

    def _tool_name(self):
        return "planned_act"

    def _initial_instruction(self):
        return ("Plan and control this single episode with planned_act. Inspect the generic declared action "
                "contract; use only public evidence and keep predictions distinct from observations.\n")

    def _turn(self, text, images=()):
        super()._turn(text, images)
        # A prepared sensor file alone is not delivery. This records a locally
        # acknowledged request, not independent provider consumption evidence.
        self.observation_steps.add(self.packet["step_id"])

    def _reply(self, packet, images):
        super()._reply(packet, images)
        # The inherited reply clears pending_rpc before writing: ambiguity is
        # terminal and cannot promote this observation or replay the tool reply.
        self.observation_steps.add(packet["step_id"])

    def _tool_spec(self):
        text = {"type": "string", "minLength": 1, "maxLength": 512}
        identifier = {**text, "maxLength": 64}
        step = {"type": "integer", "minimum": 0}
        vector = {"type": "array", "minItems": 1, "maxItems": 256, "items": {"type": "number"}}
        if self.context is not None:
            vector.update(minItems=self.context.action_spec.size, maxItems=self.context.action_spec.size)
        schema = _object({
            "request_id": identifier,
            "plan": _object({"goal": text,
                "subgoals": {"type": "array", "minItems": 1, "maxItems": self.config["max_subgoals"],
                    "items": _object({"id": identifier, "description": text, "expected_evidence": text})},
                "active_subgoal": identifier}),
            "assessment": _object({"observation_step": step,
                "previous_expectation_status": {"type": "string",
                    "enum": ["initial", "supported", "not_observed", "uncertain"]}, "evidence": text}),
            "memory": {"type": "array", "maxItems": self.config["max_memory_entries"],
                "items": _object({"kind": {"type": "string", "enum": ["observed", "hypothesis"]},
                                  "statement": text, "observation_step": step})},
            "expected_observation": text,
            "actions": {"type": "array", "minItems": 0 if self.config["safety_stop"] else 1,
                        "maxItems": self.config["max_chunk_length"], "items": vector},
            "stop_reason": {"type": ["string", "null"] if self.config["safety_stop"] else "null",
                            "enum": [None, "safety_stop"] if self.config["safety_stop"] else [None]},
            "reason": {**text, "maxLength": 1024},
        })
        return {"name": self._tool_name(), "description":
            ("Submit a concise public plan/evidence summary and direct native actions, or an explained safety stop. "
             if self.config["safety_stop"] else
             "Submit a concise public plan/evidence summary and direct native actions; voluntary stops are disabled. ") +
            "The next reply contains actual acknowledged execution and public observations; no reset or score query.",
            "inputSchema": schema}

    def _validate_action(self, arguments, packet):
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
            except (ValueError, RecursionError):
                _bad("invalid_json")
        if type(arguments) is dict and arguments.get("stop_reason") == "safety_stop" and not self.config["safety_stop"]:
            _bad("invalid_stop", "safety_stop")
        _shape(arguments, self._tool_spec()["inputSchema"])
        if arguments["request_id"] != packet["request_id"]:
            _bad("invalid_action")
        plan, assessment = arguments["plan"], arguments["assessment"]
        identifiers = [item["id"] for item in plan["subgoals"]]
        if len(set(identifiers)) != len(identifiers) or plan["active_subgoal"] not in identifiers:
            _bad("invalid_action")
        initial = assessment["previous_expectation_status"] == "initial"
        if (assessment["observation_step"] != self.controls or initial != (self.model_summary is None)
                or any(item["observation_step"] not in self.observation_steps for item in arguments["memory"])):
            _bad("invalid_action", "memory")
        if (arguments["stop_reason"] is None) != bool(arguments["actions"]):
            _bad("invalid_stop", "safety_stop")
        vectors = [validate_action_vector(self.context.action_spec, action) for action in arguments["actions"]]
        # Detach transport-owned input before retaining the public summary.
        value = json.loads(_json(arguments))
        value["steps"] = len(vectors)
        return value, vectors

    def _decision(self, value, vectors, usage, receipt):
        common = {"note": value["reason"], "usage": usage,
                  "metadata": {"provider_receipt": receipt, "structured_output": value,
                               "summary_authority": "model_authored_unverified"}}
        if value["stop_reason"] is not None:
            self.pending_action = None
            return PolicyDecision(stop=True, stop_reason=value["stop_reason"], **common)
        return PolicyDecision(action=ActionChunk.from_steps(vectors), **common)

    def _feedback(self, feedback):
        proposal = self.pending_action
        previous = self.controls
        # The shared lifecycle validates submission/prefix/counter causality.
        # Raw schema-specific control payloads remain outside the actor packet.
        super()._feedback(feedback)
        if feedback.executed_steps:
            self.execution_memory.append({"submission": self.issued,
                "control_start": previous + 1, "control_end": self.controls,
                "actions": proposal["actions"][:feedback.executed_steps],
                "authority": "acknowledged_execution_not_task_effect"})
            self.model_summary = {"authority": "model_authored_unverified",
                "based_on_observation_step": proposal["assessment"]["observation_step"],
                "plan": proposal["plan"], "assessment": proposal["assessment"],
                "memory": proposal["memory"], "expected_observation": proposal["expected_observation"]}

    def _observation(self, observation):
        spec = self.context.observation_spec
        if (type(observation.step) is not int or observation.step != self.controls
                or set(observation.images) != set(spec.cameras)):
            raise ValueError("public observation/counter mismatch")
        state = public_state(observation, spec)
        if not isinstance(observation.instruction, str) or not observation.instruction.strip():
            raise ValueError("missing public task instruction")
        if self.packet is not None and self.rejection is not None and self.feedback["executed_steps"] == 0:
            self.packet = {**self.packet, "action_submissions": self.issued,
                           "previous_execution": self.feedback}
            return self.packet, []
        directory = self.public / f"{self.issued:06d}"
        directory.mkdir()
        attachments, descriptors = public_images(observation, spec.cameras, directory,
            config=self.config, remember=self._remember_public)
        path = directory / "observation.json"
        packet = {"schema_version": "starvla-rsi.planned-observation/v1",
            "instruction": observation.instruction, "state": state, "state_names": list(spec.state_names),
            "action_spec": self.context.action_spec.to_dict(), "images": descriptors,
            "step_id": self.controls, "remaining_controls": self.control_limit - self.controls,
            "executed_decisions": self.decisions, "action_submissions": self.issued,
            "max_action_submissions": self.context.max_policy_calls,
            "max_chunk_length": self.config["max_chunk_length"], "previous_execution": self.feedback,
            "recent_executions": list(self.execution_memory), "model_summary": self.model_summary,
            "summary_semantics": "model-authored claims, not verified truth; ACKs establish execution only",
            "available_observation_steps": sorted(self.observation_steps | {self.controls}),
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
            self._clear_planning()
