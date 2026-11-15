"""Native GPT-6-Astra Policy: the model chooses robot actions through Codex.

Each episode is one Codex conversation. Every policy call sends the public
observation packet and waits for one `robot_act` tool call, which becomes the
next action chunk or a stop.
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
from AgentPolicies.gpt6_astra.tools.json_io import compact_json, reject_constant, strict_object, write_json
from AgentPolicies.gpt6_astra.tools.persistent_runtime import TRANSPORT, PersistentRuntime, reject_action
from AgentPolicies.gpt6_astra.tools.public_observation import public_state, public_images
from AgentPolicies.gpt6_astra.tools.stagnation_review import RepeatedCommandReview

TOOL_NAME = "robot_act"
TOOL_FIELDS = ("request_id", "actions", "reason", "stop_reason")  # a reply must carry exactly these keys
# schema_version of each observation packet and of its workspace_context.
OBSERVATION_SCHEMA = "starvla-rsi.direct-observation/v4"
WORKSPACE_SCHEMA = "starvla-rsi.direct-workspace/v3"


# Model-facing text. Any change here changes the prompt or the tool, and so the method.

INITIAL_INSTRUCTION = ("Control this single episode with robot_act and the declared native action contract. "
                       "Use only public observations and actual execution feedback.\n")

NOTES_TEMPLATE = ("# Same-episode working notes\n\n"
                  "Keep observed facts separate from hypotheses and intended outcomes.\n"
                  "ACKs confirm execution, not task success; do not record private chain-of-thought.\n")

COMPLETION_RULE = {
    True: ('allow_task_completion=true: when you believe the task is complete, call robot_act '
           'with the current request_id, actions=[], stop_reason="task_complete", and a concise reason. '
           'This normally ends the interaction immediately. No extra verification, holding actions, '
           'or waiting for the execution budget is required. Your declaration is recorded separately '
           'from native success and scoring; it does not award success. '),
    False: 'allow_task_completion=false: task_complete is not available in this configuration. ',
}
SAFETY_RULE = {
    True: ('safety_stop=true: an explained voluntary safety stop is permitted with '
           'actions=[] and stop_reason="safety_stop". '),
    False: 'safety_stop=false: the safety_stop reason is disabled. ',
}
CONTINUE_RULE = ('For continued control, submit at least one valid action and stop_reason=null. '
                 'Ordinary give-up is not enabled; uncertainty alone is not a task-completion declaration.')
PROMPT_STOP_HEADER = "\nEffective policy stop configuration: "
PROMPT_FOOTER = " Native termination, execution budgets, protocol errors and external safeguards remain authoritative.\n"

TOOL_COMPLETION = ('Submit direct native actions, or declare task completion with actions=[] and '
                   'stop_reason="task_complete" to normally end the interaction without another control or check. '
                   'Completion is your judgment, not a native success claim. ')
TOOL_COMPLETION_SAFETY = 'An explained safety_stop with actions=[] is also permitted. '
TOOL_SAFETY_ONLY = "Submit direct native action vectors or an explained safety stop. "
TOOL_NO_STOP = "Submit direct native action vectors; voluntary stops are disabled. "
TOOL_NEXT_REPLY = "The next reply supplies public observations and actual execution feedback; no reset or score query."
TOOL_NEXT_REPLY_IF_CONTINUED = ("For continued control, the next reply supplies public observations and actual "
                                "execution feedback; no reset or score query.")


# The developer instructions: the profile prompt plus the stop rules this configuration enables.
def effective_prompt(base, config):
    stop_rule = (COMPLETION_RULE[config["allow_task_completion"]] + SAFETY_RULE[config["safety_stop"]]
                 + CONTINUE_RULE)
    return base + PROMPT_STOP_HEADER + stop_rule + PROMPT_FOOTER


# The robot_act description; it mentions only the stops this configuration enables.
def tool_description(config):
    if config["allow_task_completion"]:
        safety = TOOL_COMPLETION_SAFETY if config["safety_stop"] else ""
        return TOOL_COMPLETION + safety + TOOL_NEXT_REPLY_IF_CONTINUED
    return (TOOL_SAFETY_ONLY if config["safety_stop"] else TOOL_NO_STOP) + TOOL_NEXT_REPLY


# Reading step 5 of 6: what the model sees and how its reply becomes a decision. Its act()
# is PersistentRuntime.act (tools/persistent_runtime.py), which calls the hooks below in order:
# _observation -> Codex -> _validate_action -> _decision; feedback then goes through _feedback.
class CodexNativePolicy(PersistentRuntime):
    """What the model sees, and how its replies become decisions.

    PersistentRuntime runs the Codex conversation: it sends each packet, waits
    for the robot_act call, and records usage and audit files. It calls the
    hooks below for the tool (_tool_spec), the observation packet
    (_observation), the reply check (_validate_action) and the resulting
    PolicyDecision (_decision).
    """

    def __init__(self, *, config, identity, prompt):
        self.config = dict(config)  # effective configuration: checked-in config plus command-line overrides
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
            raise ValueError("Codex native prompt must be bounded nonempty text")
        self._prompt_base = prompt  # kept to build the preflight copy
        self.prompt = effective_prompt(prompt, self.config)  # sent once, as the thread's developer instructions
        # Records carry the effective configuration and prompt hash next to the method name.
        self.descriptor = PolicyDescriptor(**identity, parameters={
            "transport": TRANSPORT, "effective_config": dict(self.config),
            "prompt_sha256": hashlib.sha256(self.prompt.encode()).hexdigest()})
        super().__init__()
        self._reset_episode_state()

    def _preflight_policy(self):
        """A fresh copy for the preflight boot, so this instance stays untouched."""
        return CodexNativePolicy(config=self.config, prompt=self._prompt_base, identity={
            key: getattr(self.descriptor, key) for key in ("name", "kind", "model", "provider")})

    # Episode lifecycle

    def _reset_episode_state(self):
        """Same-episode memory; cleared at start and end, so nothing reaches the next episode."""
        self.initial_robot_state = None  # the first packet's state, repeated in every packet
        self.initial_observation_path = None
        # The last few executed decisions, sent as recent_executions.
        self.execution_memory = deque(maxlen=self.config["execution_history_decisions"])
        # Counts repeated constant commands; its feedback() becomes the packet's policy_review.
        self.review = RepeatedCommandReview(self.config["stagnation_review"], self.config["stagnation_window"])

    def start_episode(self, context):
        super().start_episode(context)  # sets context and counters, makes the observations/ and work/ directories
        self._reset_episode_state()
        # The model's own working area: a scratch directory and NOTES.md, owner-only.
        scratch = self.actor / "scratch"
        scratch.mkdir(mode=0o700)
        notes = self.actor / "NOTES.md"
        with notes.open("x") as stream:
            os.chmod(notes, 0o600)
            stream.write(NOTES_TEMPLATE)
        # Sent in every packet as workspace_context.
        self.workspace = {"schema_version": WORKSPACE_SCHEMA,
            "python_executable": sys.executable, "observations_path": str(self.public),
            "scratch_path": str(scratch), "notes_path": str(notes), "working_directory": str(self.actor),
            "evidence_access": "read_only", "working_files_access": "actor_owned",
            "lifetime": "this_episode_only"}

    def end_episode(self):
        try:
            super().end_episode()
        finally:
            self._reset_episode_state()

    # The robot_act tool (hooks called by PersistentRuntime)

    def _tool_name(self):
        return TOOL_NAME

    def _initial_instruction(self):
        return INITIAL_INSTRUCTION  # prefixed to the first packet in the episode's first turn

    def _stop_reasons(self):
        """Stops this configuration enables; with none, every reply must carry actions."""
        return (("safety_stop",) if self.config["safety_stop"] else ()) + (
            ("task_complete",) if self.config["allow_task_completion"] else ())

    def _chunk_limit(self):
        """The configured chunk limit, capped by the episode's replan interval if one is declared."""
        interval = self.context.replan_interval if self.context is not None else None
        ceiling = self.config["max_chunk_length"]
        return ceiling if interval is None else min(ceiling, interval)

    def _tool_spec(self):
        vector = {"type": "array", "minItems": 1, "maxItems": 256, "items": {"type": "number"}}  # preflight: no episode
        if self.context is not None:  # in an episode: every vector has exactly the action size
            vector.update(minItems=self.context.action_spec.size, maxItems=self.context.action_spec.size)
        stop_reasons = self._stop_reasons()
        return {"type": "function", "name": TOOL_NAME,
            "description": tool_description(self.config),
            "inputSchema": {"type": "object", "additionalProperties": False,
                "required": list(TOOL_FIELDS),
                "properties": {
                    "request_id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "actions": {"type": "array", "minItems": 0 if stop_reasons else 1,
                                "maxItems": self._chunk_limit(), "items": vector},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "stop_reason": {"type": ["string", "null"] if stop_reasons else "null",
                                    "enum": [None, *stop_reasons]},
                }}}

    def _validate_action(self, arguments, packet):
        """Check one robot_act reply; a failed check rejects it back to the model.
        Returns the normalized reply and the validated action vectors."""
        if isinstance(arguments, str):  # arguments may arrive as JSON text; parse it strictly
            try:
                arguments = json.loads(arguments, object_pairs_hook=strict_object, parse_constant=reject_constant)
            except (ValueError, RecursionError):
                reject_action("invalid_json")
        if type(arguments) is not dict or set(arguments) != set(TOOL_FIELDS):
            reject_action("unexpected_fields")
        if type(arguments["request_id"]) is not str or arguments["request_id"] != packet["request_id"]:
            reject_action("invalid_action")  # request_id must match this packet
        reason = arguments["reason"]
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
            reject_action("invalid_length", "note")
        actions = arguments["actions"]
        if type(actions) is not list or len(actions) > self._chunk_limit():
            reject_action("invalid_length", "action")
        stop = arguments["stop_reason"]
        if stop not in (None, *self._stop_reasons()) or (stop is None) != bool(actions):  # a stop has no actions
            reject_action("invalid_stop", "stop_reason")
        if any(type(action) is not list for action in actions):
            reject_action("invalid_type", "action")
        # Type, length, finiteness and bounds per the action spec; a failure raises ActionRejected.
        vectors = [validate_action_vector(self.context.action_spec, action) for action in actions]
        value = json.loads(compact_json(arguments))  # plain JSON copy: becomes pending_action and the audit record
        value["steps"] = len(vectors)  # PersistentRuntime bounds the acknowledged prefix by this
        return value, vectors

    def _decision(self, value, vectors, usage, receipt):
        common = {"note": value["reason"], "usage": usage,
                  "metadata": {"provider_receipt": receipt, "structured_output": value}}
        if value["stop_reason"] is not None:
            self.pending_action = None  # a stop executes nothing
            return PolicyDecision(stop=True, stop_reason=value["stop_reason"], **common)
        return PolicyDecision(action=ActionChunk.from_steps(vectors), **common)

    # Observations and execution feedback

    def _feedback(self, feedback):
        """Also remember the executed controls for recent_executions and the stagnation review."""
        # Read these before super() advances the counters and clears pending_action.
        proposal = self.pending_action
        state_before = self.packet.get("state") if self.packet is not None else None
        first_control = self.executed_controls + 1
        super()._feedback(feedback)
        if feedback.executed_steps:  # only when controls ran; otherwise memory and review stay unchanged
            executed = proposal["actions"][:feedback.executed_steps]  # only the prefix that actually ran
            self.execution_memory.append({"submission": self.action_submissions,
                "control_start": first_control, "control_end": self.executed_controls,
                "actions": executed, "authority": "acknowledged_execution_not_task_effect"})
            self.review.acknowledge(executed, state_before)

    def _observation(self, observation):
        """The packet for the next call: a new one, or the previous one again
        after a rejection that executed nothing."""
        state = self._checked_state(observation)  # checked even when the packet is resent
        if self._rejected_without_execution():
            return self._resend_packet(), []  # no images: the model already received them with this packet
        return self._new_packet(observation, state)

    def _checked_state(self, observation):
        """Check the observation against the declared spec and the ACKed counter; return its public state."""
        spec = self.context.observation_spec
        if (type(observation.step) is not int or observation.step != self.executed_controls  # follows the last ACK
                or set(observation.images) != set(spec.cameras)):
            raise ValueError("public observation/counter mismatch")
        state = public_state(observation, spec)
        if not isinstance(observation.instruction, str) or not observation.instruction.strip():
            raise ValueError("missing public task instruction")
        return state

    def _rejected_without_execution(self):
        """True right after a rejected reply that executed nothing."""
        return self.packet is not None and self.rejection is not None and self.feedback["executed_steps"] == 0

    def _resend_packet(self):
        """Nothing moved, so the model gets the same packet back with updated counters."""
        # Same request_id as before, so the corrected reply must echo it.
        self.packet = {**self.packet, "action_submissions": self.action_submissions,
                       "previous_execution": self.feedback}
        return self.packet

    def _new_packet(self, observation, state):
        spec = self.context.observation_spec
        directory = self.public / f"{self.action_submissions:06d}"  # one folder per new packet
        directory.mkdir()
        # Writes the PNGs; attachments go to the model as images, descriptors into the packet.
        attachments, descriptors = public_images(observation, spec.cameras, directory,
            config=self.config, remember=self._remember_public)
        path = directory / "observation.json"
        if self.initial_robot_state is None:  # the episode's first packet
            self.initial_robot_state = {"step": observation.step, "state_names": list(spec.state_names),
                "values": None if state is None else list(state), "authority": "initial_public_observation_not_action"}
            self.initial_observation_path = str(path)
        # What the model reads: public observation, counters, recent executions and its workspace.
        # request_id is new for every packet; the robot_act reply must echo it.
        packet = {"schema_version": OBSERVATION_SCHEMA,
            "instruction": observation.instruction, "state": state, "state_names": list(spec.state_names),
            "action_spec": self.context.action_spec.to_dict(), "images": descriptors,
            "initial_robot_state": json.loads(compact_json(self.initial_robot_state)),
            "initial_observation_path": self.initial_observation_path,
            "step_id": self.executed_controls, "remaining_controls": self.control_limit - self.executed_controls,
            "executed_decisions": self.executed_decisions, "action_submissions": self.action_submissions,
            "max_action_submissions": self.context.max_policy_calls,
            "max_chunk_length": self._chunk_limit(), "previous_execution": self.feedback,
            "recent_executions": list(self.execution_memory),
            "feedback_projection": self.config["feedback_projection"],
            "raw_control_feedback_forwarded": False, "workspace_context": self.workspace,
            "image_max_edge": self.config["image_max_edge"], "request_id": uuid.uuid4().hex,
            "next_call": {"tool": TOOL_NAME, "observation_path": str(path)},
            "policy_review": self.review.feedback(state, list(spec.state_names))}
        self._remember_public(path, write_json(path, packet))  # listed by size and hash in the public manifest
        self.packet = packet  # kept for a resend and for state_before in _feedback
        return packet, attachments


# The profile's factory (configs/profile.json); benchkit.model_profiles.create_policy calls it.
def create_policy(*, config, schema, identity, prompt, **overrides):
    """Build the policy from the profile configuration and the given overrides, checked against the schema."""
    overrides = {key: value for key, value in overrides.items() if value is not None}  # None: option not given
    if "stagnation_window" in overrides:
        # Choosing a review window turns the review on.
        if overrides.setdefault("stagnation_review", True) is not True:
            raise ValueError("stagnation_window conflicts with a disabled stagnation_review")
    effective = {**config, **overrides}  # overrides win over the checked-in configuration
    validate_configuration(config["profile_id"], effective, schema)  # every field must fit the schema
    return CodexNativePolicy(config=effective, identity=identity, prompt=prompt)
