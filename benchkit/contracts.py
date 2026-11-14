"""Dependency-light data contracts shared by policies and benchmarks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Mapping, Sequence, Union

from benchkit.validation import ValidationIssue, validate_action_vector

JsonScalar = Union[None, bool, int, float, str]
JsonValue = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]


def _nonempty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def ensure_jsonable(value: Any, path: str = "value") -> JsonValue:
    """Validate and normalize a value accepted by JSON result artifacts."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            normalized[key] = ensure_jsonable(item, f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [ensure_jsonable(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise TypeError(f"{path} is not JSON-serializable: {type(value).__name__}")


@dataclass(frozen=True)
class ActionSpec:
    """Semantic and numeric action contract exposed by a benchmark adapter."""

    mode: str
    size: int
    names: tuple[str, ...] = ()
    low: tuple[float, ...] | None = None
    high: tuple[float, ...] | None = None
    control_hz: float | None = None
    frame: str | None = None
    rotation: str | None = None
    gripper: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _nonempty(self.mode, "action mode"))
        if self.size <= 0:
            raise ValueError("action size must be positive")
        if self.names and len(self.names) != self.size:
            raise ValueError("action names must match action size")
        if (self.low is None) != (self.high is None):
            raise ValueError("action low and high must be provided together")
        if self.low is not None:
            if len(self.low) != self.size or len(self.high or ()) != self.size:
                raise ValueError("action bounds must match action size")
            if any(not math.isfinite(value) for value in (*self.low, *(self.high or ()))):
                raise ValueError("action bounds must be finite")
            if any(low > high for low, high in zip(self.low, self.high or ())):
                raise ValueError("action lower bound exceeds upper bound")
        if self.control_hz is not None and (not math.isfinite(self.control_hz) or self.control_hz <= 0):
            raise ValueError("control_hz must be finite and positive")

    def validate(self, values: Sequence[float]) -> tuple[float, ...]:
        """Return a normalized action vector or raise TypeError/ValueError.

        Delegates to ``validate_action_vector`` so both entry points share one
        rule set; this form suits adapters that report plain exceptions.
        """
        from benchkit.errors import ActionRejected

        try:
            return validate_action_vector(self, tuple(values))
        except ActionRejected as exc:
            issue = exc.issue
            details = ", ".join(f"{key}={value}" for key, value in issue.to_dict().items()
                                if key not in ("code", "field") and value is not None)
            message = f"action violates its contract: {issue.code}" + (f" ({details})" if details else "")
            raise (TypeError if issue.code == "invalid_type" else ValueError)(message) from None

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(
            {
                "mode": self.mode,
                "size": self.size,
                "names": self.names,
                "low": self.low,
                "high": self.high,
                "control_hz": self.control_hz,
                "frame": self.frame,
                "rotation": self.rotation,
                "gripper": self.gripper,
            }
        )


@dataclass(frozen=True)
class ObservationSpec:
    """Observation channels made available to a policy."""

    cameras: tuple[str, ...] = ()
    state_names: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ("language",)
    privileged: bool = False
    control_feedback_schema: str | None = None

    def __post_init__(self) -> None:
        if self.control_feedback_schema is not None and (
            not isinstance(self.control_feedback_schema, str)
            or not 1 <= len(self.control_feedback_schema) <= 128
            or any(ord(c) < 33 or ord(c) > 126 for c in self.control_feedback_schema)
        ):
            raise ValueError("invalid public control feedback schema")

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(
            {
                "cameras": self.cameras,
                "state_names": self.state_names,
                "modalities": self.modalities,
                "privileged": self.privileged,
                **({"control_feedback_schema": self.control_feedback_schema}
                   if self.control_feedback_schema is not None else {}),
            }
        )


@dataclass(frozen=True)
class BenchmarkDescriptor:
    """Pinned identity of one native benchmark protocol."""

    name: str
    version: str
    protocol_version: str
    source_revision: str

    def __post_init__(self) -> None:
        for field_name in ("name", "version", "protocol_version", "source_revision"):
            object.__setattr__(self, field_name, _nonempty(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(self.__dict__)


@dataclass(frozen=True)
class PolicyDescriptor:
    """Identity and provider provenance for one policy under evaluation."""

    name: str
    kind: str
    model: str | None = None
    provider: str | None = None
    version: str | None = None
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _nonempty(self.name, "policy name"))
        object.__setattr__(self, "kind", _nonempty(self.kind, "policy kind"))
        ensure_jsonable(self.parameters, "policy parameters")

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(
            {
                "name": self.name,
                "kind": self.kind,
                "model": self.model,
                "provider": self.provider,
                "version": self.version,
                "parameters": self.parameters,
            }
        )


@dataclass(frozen=True)
class EpisodeSpec:
    """Evaluator-private scene/task identity, reset seed, and configuration."""

    id: str
    task: str
    seed: int
    instruction: str
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _nonempty(self.id, "episode id"))
        object.__setattr__(self, "task", _nonempty(self.task, "task"))
        object.__setattr__(self, "instruction", _nonempty(self.instruction, "instruction"))
        ensure_jsonable(self.metadata, "episode metadata")

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(
            {
                "id": self.id,
                "task": self.task,
                "seed": self.seed,
                "instruction": self.instruction,
                "metadata": self.metadata,
            }
        )


@dataclass(frozen=True)
class PolicyEpisodeSpec:
    """Public task context; reset seeds and simulator metadata are excluded.

    The runner supplies an opaque episode label instead of the native episode
    ID, which can encode object placement or other private reset parameters.
    """

    id: str
    task: str
    instruction: str

    def __post_init__(self) -> None:
        for field_name in ("id", "task", "instruction"):
            object.__setattr__(self, field_name, _nonempty(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(self.__dict__)


@dataclass(frozen=True)
class Observation:
    """One policy observation; image payloads remain adapter-native in memory."""

    step: int
    instruction: str
    images: Mapping[str, Any] = field(default_factory=dict)
    state: Sequence[float] | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    control_feedback: Mapping[str, JsonValue] | None = None

    def __post_init__(self) -> None:
        if self.step < 0:
            raise ValueError("observation step must be non-negative")
        ensure_jsonable(self.metadata, "observation metadata")
        if self.control_feedback is not None:
            if not isinstance(self.control_feedback, Mapping):
                raise TypeError("public control feedback must be an object")
            ensure_jsonable(self.control_feedback, "public control feedback")

    def log_view(self) -> dict[str, JsonValue]:
        """Return metadata safe for JSON logs without embedding image arrays."""
        state = None if self.state is None else [float(value) for value in self.state]
        return ensure_jsonable(
            {
                "step": self.step,
                "instruction": self.instruction,
                "camera_names": sorted(self.images),
                "state": state,
                "metadata": self.metadata,
                **({"control_feedback": self.control_feedback}
                   if self.control_feedback is not None else {}),
            }
        )


@dataclass(frozen=True)
class Usage:
    """Reported provider usage associated with one or more policy calls.

    These counters enable accounting and rejection of declared budget violations;
    they cannot attest that untrusted policy code made no hidden requests.
    None means unavailable, not zero. Unknown components remain unknown when
    summed; zero defaults are suitable only for policies with no provider usage.
    """

    calls: int | None = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    cached_input_tokens: int | None = 0
    estimated_cost_usd: float | None = 0.0
    latency_s: float | None = 0.0

    def __post_init__(self) -> None:
        counters = (self.calls, self.input_tokens, self.output_tokens, self.cached_input_tokens)
        known_counters = [value for value in counters if value is not None]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in known_counters):
            raise TypeError("usage counters must be integers or None")
        if any(value < 0 for value in known_counters):
            raise ValueError("usage counters must be non-negative")
        for name in ("estimated_cost_usd", "latency_s"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, Real)):
                raise TypeError(f"{name} must be a real number or None")
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")

    @classmethod
    def unavailable(cls, *, latency_s: float | None = None) -> "Usage":
        """Unknown provider accounting, optionally with measured bridge latency."""
        return cls(calls=None, input_tokens=None, output_tokens=None,
                   cached_input_tokens=None, estimated_cost_usd=None, latency_s=latency_s)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(**{
            key: None if value is None or getattr(other, key) is None else value + getattr(other, key)
            for key, value in self.__dict__.items()
        })

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(self.__dict__)


@dataclass(frozen=True)
class EpisodeUsage:
    """A policy's own cumulative usage for one episode, read once after end_episode.

    The runner reconciles it with the sum of per-call usage; per-call records
    stay as measured. Unknown fields are None (``Usage.unavailable()``).
    ``complete`` is False when the total is known to omit some provider usage,
    such as a final response whose usage was never reported.
    """

    total: Usage
    complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.total, Usage):
            raise TypeError("episode usage total must be a Usage")
        if not isinstance(self.complete, bool):
            raise TypeError("episode usage complete must be a bool")


@dataclass(frozen=True)
class ActionChunk:
    """One policy decision containing one or more native action vectors."""

    steps: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.steps, tuple) or any(not isinstance(step, tuple) for step in self.steps):
            raise TypeError("action chunk steps must be tuples; use ActionChunk.from_steps")
        if not self.steps:
            raise ValueError("action chunk must contain at least one step")

    @classmethod
    def from_steps(cls, steps: Sequence[Sequence[float]]) -> "ActionChunk":
        normalized = []
        for step in steps:
            values = []
            for value in step:
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise TypeError("action components must be real numbers")
                values.append(float(value))
            normalized.append(tuple(values))
        return cls(tuple(normalized))


@dataclass(frozen=True)
class PolicyDecision:
    """A chunk to execute or an explicit policy stop signal."""

    action: ActionChunk | None = None
    stop: bool = False
    stop_reason: str | None = None
    note: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    # Unreported usage is unknown; policies without provider calls pass Usage().
    usage: Usage = field(default_factory=Usage.unavailable)

    def __post_init__(self) -> None:
        if not isinstance(self.stop, bool):
            raise TypeError("decision stop must be a boolean")
        if self.action is not None and not isinstance(self.action, ActionChunk):
            raise TypeError("decision action must be an ActionChunk")
        if not isinstance(self.usage, Usage):
            raise TypeError("decision usage must be Usage")
        if self.stop == (self.action is not None):
            raise ValueError("decision must contain exactly one of action or stop")
        if self.stop and not self.stop_reason:
            raise ValueError("stop decisions require stop_reason")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("decision metadata must be a mapping")
        ensure_jsonable(self.metadata, "policy decision metadata")


@dataclass(frozen=True)
class Transition:
    """Native environment response after executing one action vector."""

    observation: Observation
    reward: float = 0.0
    terminated: bool = False
    truncated: bool = False
    info: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.reward):
            raise ValueError("reward must be finite")
        ensure_jsonable(self.info, "transition info")


@dataclass(frozen=True)
class EpisodeContext:
    """Public protocol information supplied to a policy at episode start.

    This data boundary does not sandbox policy code executing in the same process.
    """

    benchmark: BenchmarkDescriptor
    episode: PolicyEpisodeSpec
    observation_spec: ObservationSpec
    action_spec: ActionSpec
    max_steps: int
    max_policy_calls: int | None
    replan_interval: int | None
    budget_mode: str = "horizon"
    invalid_action_handling: str = "terminate"


@dataclass(frozen=True)
class ControlAcknowledgement:
    """One declared public sensor receipt, never Transition.info or reward.

    Payload semantics and closed-key projection belong to the benchmark.
    The transport/runner only binds the receipt to a real acknowledged control.
    """

    environment_step: int
    observation_step: int
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if (type(self.environment_step) is not int or self.environment_step < 1
                or type(self.observation_step) is not int or self.observation_step < 1):
            raise ValueError("control acknowledgement requires positive step indices")
        if not isinstance(self.payload, Mapping) or not self.payload:
            raise ValueError("control acknowledgement requires a public payload")
        if (not isinstance(self.payload.get("schema"), str)
                or type(self.payload.get("control_target")) is not int
                or self.payload["control_target"] != self.observation_step):
            raise ValueError("control payload must bind its schema and observation index")
        object.__setattr__(self, "payload", ensure_jsonable(self.payload))

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable(self.__dict__)


def _validate_control_acks(acks, executed_steps: int, environment_steps: int) -> None:
    if acks is None:
        return  # The benchmark declares no public control channel; counters only.
    if not isinstance(acks, tuple) or len(acks) != executed_steps:
        raise ValueError("control acknowledgements must cover exactly the executed prefix")
    for expected, ack in zip(range(environment_steps - executed_steps + 1, environment_steps + 1), acks):
        if not isinstance(ack, ControlAcknowledgement) or ack.environment_step != expected:
            raise ValueError("control acknowledgements must be contiguous and causal")


@dataclass(frozen=True)
class ExecutionFeedback:
    """Public counters and optionally declared robot-control sensor receipts.

    An action decision counts only once at least one control returned a valid
    transition. Failed/aborted control calls never invent completed actions.
    This optional policy feedback has no reward, success, contacts, task reset
    metadata, or termination flags. Policy stopping preferences are not budgets.
    """

    policy_calls: int
    action_decisions: int
    environment_steps: int
    executed_steps: int
    control_acks: tuple[ControlAcknowledgement, ...] | None = None

    def __post_init__(self) -> None:
        for name in ("policy_calls", "action_decisions", "environment_steps", "executed_steps"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"execution feedback {name} must be a nonnegative integer")
        if not self.executed_steps or not self.action_decisions:
            raise ValueError("execution feedback requires an actually executed action decision")
        if not self.action_decisions <= self.policy_calls:
            raise ValueError("action decisions cannot exceed policy calls")
        if not self.action_decisions <= self.environment_steps or self.executed_steps > self.environment_steps:
            raise ValueError("execution feedback counters are inconsistent")
        _validate_control_acks(self.control_acks, self.executed_steps, self.environment_steps)

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_jsonable({key: value for key, value in self.__dict__.items() if key != "control_acks"}) | (
            {"control_acks": [ack.to_dict() for ack in self.control_acks]} if self.control_acks is not None else {})


@dataclass(frozen=True)
class ActionRejectionFeedback:
    """Public rejection plus acknowledged counters, never native/error state.

    A rejection is one failed action submission, not a reset or hidden retry.
    ``executed_steps`` may be zero or the already-ACKed prefix of this call;
    the rejected vector never increments it. ``rejected_actions`` counts
    rejection events, not guessed numbers of invalid components or vectors.
    """

    issue: ValidationIssue
    policy_calls: int
    action_decisions: int
    environment_steps: int
    executed_steps: int
    rejected_actions: int
    control_acks: tuple[ControlAcknowledgement, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.issue, ValidationIssue):
            raise TypeError("action rejection feedback requires a ValidationIssue")
        for name in ("policy_calls", "action_decisions", "environment_steps",
                     "executed_steps", "rejected_actions"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError("action rejection counters must be nonnegative integers")
        if not 1 <= self.rejected_actions <= self.policy_calls:
            raise ValueError("action rejections require counted policy calls")
        if self.action_decisions > self.policy_calls or self.action_decisions > self.environment_steps:
            raise ValueError("action rejection decision counters are inconsistent")
        if self.executed_steps > self.environment_steps:
            raise ValueError("action rejection prefix exceeds acknowledged controls")
        if self.executed_steps and not self.action_decisions:
            raise ValueError("an acknowledged prefix requires an action decision")
        if not self.executed_steps and self.action_decisions >= self.policy_calls:
            raise ValueError("a zero-control rejection is not an action decision")
        _validate_control_acks(self.control_acks, self.executed_steps, self.environment_steps)

    def to_dict(self) -> dict[str, JsonValue]:
        return {"schema_version": "starvla-rsi.action-rejection-feedback/v1",
            "issue": self.issue.to_dict(), "policy_calls": self.policy_calls,
            "action_decisions": self.action_decisions, "environment_steps": self.environment_steps,
            "executed_steps": self.executed_steps, "rejected_actions": self.rejected_actions,
            **({"control_acks": [ack.to_dict() for ack in self.control_acks]}
               if self.control_acks is not None else {})}
