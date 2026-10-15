"""One-observation/one-response file transport for an external visual policy.

The client waits for ``ready.json`` with ``status == "pending"``, reads the
referenced ``observation.json`` and PNG frames, then atomically renames its final
JSON response to the specified ``action.json`` path. A response is either::

    {"request_id": "<copy request_id from ready.json>",
     "actions": [[0, 0, 0, 0, 0, 0, 1]], "usage": {"calls": 1}}

or::

    {"request_id": "<copy request_id from ready.json>", "stop": true,
     "stop_reason": "give_up", "usage": {"calls": 1}}

Usage may additionally contain input_tokens, output_tokens, cached_input_tokens,
estimated_cost_usd, and latency_s. Use ``"usage": null`` when provider accounting
is unavailable (such as an orchestrated code agent), or null individual fields.
Omitted token/cost fields remain unknown, not zero. Both variants accept a short final ``note``;
private reasoning, arbitrary metadata, and extra keys are not accepted. The
bridge measures its own wall-clock latency. Provider usage is client-reported,
so a scored provider integration must independently enforce one inference call.

This transport does not sandbox the client process. For a scored run, arrange
filesystem/process isolation so the client can read only exported observations
and write only its response, never the evaluator's artifacts or simulator.

Wire v3 paths are relative to the mailbox root (including PNG paths), not the
observation directory. Operators must supply an opaque endpoint under a stable
seed/task-independent root; public request IDs never derive from that path.
Wire v3 separates policy-owned persistence settings from benchmark budgets and
reports confirmed execution counters. Historical v2 observations are not rewritten.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import stat
import time
from numbers import Real
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.artifacts import atomic_write_json
from benchkit.contracts import (
    ActionChunk,
    ActionSpec,
    EpisodeContext,
    ExecutionFeedback,
    JsonValue,
    Observation,
    ObservationSpec,
    PolicyDecision,
    PolicyDescriptor,
    Usage,
    ensure_jsonable,
)
from benchkit.errors import InfrastructureError, PolicyError, ProtocolError
from benchkit.registry import register_policy
from AgentPolicies.gpt6_astra.tools.stop_rules import VoluntaryStopRule, with_stop_rule_prompt

SCHEMA_VERSION = "starvla-rsi.mailbox/v3"
_USAGE_COUNTERS = ("calls", "input_tokens", "output_tokens", "cached_input_tokens")
_USAGE_FLOATS = ("estimated_cost_usd", "latency_s")
_PARAMETERS = {
    "directory", "name", "model", "provider", "kind", "timeout_s", "prompt",
    "max_response_bytes", "max_chunk_length", "min_action_decisions_before_give_up",
}


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def new_mailbox_directory(root: str | Path) -> Path:
    """Choose an unused, opaque endpoint below a stable deployment-wide root.

    The root must not encode an episode, task, seed, or campaign date. It is
    selected by the operator, not inferred from evaluator output directories.
    MailboxPolicy atomically creates the returned directory; it is not reused.
    """
    root = Path(root)
    if not root.is_absolute():
        raise ValueError("mailbox root must be an absolute deployment-wide path")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / ("mbx-" + secrets.token_hex(16))


class MailboxPolicy:
    """Export permitted channels and wait once for one structured action reply."""

    def __init__(
        self,
        directory: str | Path,
        *,
        name: str = "mailbox-policy",
        model: str | None = None,
        provider: str | None = None,
        kind: str = "external-policy",
        timeout_s: float = 300.0,
        prompt: str = "",
        max_response_bytes: int = 65536,
        max_chunk_length: int = 64,
        min_action_decisions_before_give_up: int = 0,
    ) -> None:
        self.stop_rule = VoluntaryStopRule(min_action_decisions_before_give_up)
        prompt = with_stop_rule_prompt(prompt, self.stop_rule.minimum)
        timeout_s = _finite_number(timeout_s, "timeout_s")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        _nonempty_string(name, "name")
        _nonempty_string(kind, "kind")
        for label, value in (("model", model), ("provider", provider)):
            if value is not None:
                _nonempty_string(value, label)
        if not isinstance(prompt, str) or len(prompt) > 32768:
            raise ValueError("prompt must be a string of at most 32768 characters")
        max_response_bytes = _positive_integer(max_response_bytes, "max_response_bytes")
        max_chunk_length = _positive_integer(max_chunk_length, "max_chunk_length")
        if max_response_bytes > 1048576:
            raise ValueError("max_response_bytes cannot exceed 1048576")
        if max_chunk_length > 1024:
            raise ValueError("max_chunk_length cannot exceed 1024")
        directory = Path(directory)
        if not directory.is_absolute():
            raise ValueError("mailbox directory must be an absolute, run-specific path")
        self.directory = directory.resolve()
        # Independent of directory names, task IDs and all evaluator RNG seeds.
        self._namespace = secrets.token_hex(16)
        # Never join a prior mailbox: even an empty existing directory is refused.
        self.directory.mkdir(parents=True, exist_ok=False)
        self.timeout_s = timeout_s
        self.prompt = prompt
        self.max_response_bytes = max_response_bytes
        self.max_chunk_length = max_chunk_length
        self._context: EpisodeContext | None = None
        self._episode_index = 0
        self._turn_index = 0
        self._last_step = -1
        self._pending = False
        self._failed = False
        self.descriptor = PolicyDescriptor(
            name=name,
            kind=kind,
            model=model,
            provider=provider,
            version=SCHEMA_VERSION,
            parameters={
                "directory": str(self.directory),
                "timeout_s": timeout_s,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "max_response_bytes": max_response_bytes,
                "max_chunk_length": max_chunk_length,
                "history": "current_observation_only",
                "usage_source": "client_reported_or_unavailable",
                "evaluation_status": "experimental",
                "provider_call_limit_verified": False,
                "public_path_base": "mailbox_root",
                "absolute_paths_exported": False,
                "endpoint_blinding": "operator_must_supply_seed_independent_root_and_opaque_endpoint",
                "policy_stop_rule": self.stop_rule.parameters,
            },
        )
        self._write_ready("idle")

    def _write_ready(self, status: str, **fields: JsonValue) -> None:
        atomic_write_json(
            self.directory / "ready.json",
            {"schema_version": SCHEMA_VERSION, "status": status, **fields},
        )

    def compatibility_errors(
        self, observation_spec: ObservationSpec, action_spec: ActionSpec
    ) -> Sequence[str]:
        errors: list[str] = []
        if observation_spec.privileged:
            errors.append("mailbox requires a non-privileged observation specification")
        if len(set(observation_spec.cameras)) != len(observation_spec.cameras):
            errors.append("camera names must be unique")
        if len(set(observation_spec.state_names)) != len(observation_spec.state_names):
            errors.append("state names must be unique")
        return errors

    def start_episode(self, context: EpisodeContext) -> None:
        if self._context is not None:
            raise PolicyError("mailbox episode already active")
        errors = self.compatibility_errors(context.observation_spec, context.action_spec)
        if errors:
            raise ProtocolError("; ".join(errors))
        self._context = context
        self.stop_rule.start_episode(context)
        self._episode_index += 1
        self._turn_index = 0
        self._last_step = -1
        self._failed = False
        self._write_ready("episode_started")

    def observe_execution(self, feedback: ExecutionFeedback) -> None:
        """Accept counter-only receipts; never infer execution from turn number."""
        if self._context is None:
            raise PolicyError("execution feedback requires an active mailbox episode")
        self.stop_rule.observe_execution(feedback)

    def _export_observation(
        self, observation: Observation, request_id: str, turn_dir: Path
    ) -> dict[str, JsonValue]:
        context = self._context
        if context is None:
            raise PolicyError("mailbox has no active episode")
        spec = context.observation_spec
        if set(observation.images) != set(spec.cameras):
            raise ProtocolError("observation cameras differ from the declared camera set")
        state: list[float] | None = None
        if spec.state_names:
            if observation.state is None or len(observation.state) != len(spec.state_names):
                raise ProtocolError("observation state does not match the declared state names")
            try:
                state = [
                    _finite_number(value, f"state[{index}]")
                    for index, value in enumerate(observation.state)
                ]
            except (ValueError, OverflowError) as exc:
                raise ProtocolError(str(exc)) from exc
        elif observation.state is not None and len(observation.state):
            raise ProtocolError("observation contains undeclared state")
        frames: dict[str, JsonValue] = {}
        if spec.cameras:
            try:
                from PIL import Image
            except ImportError as exc:
                raise InfrastructureError("mailbox RGB export requires Pillow") from exc
            for index, camera in enumerate(spec.cameras):
                frame = observation.images[camera]
                shape = getattr(frame, "shape", ())
                if (
                    len(shape) != 3 or shape[2] != 3 or min(shape[:2]) <= 0
                    or str(getattr(frame, "dtype", "")) != "uint8"
                ):
                    raise ProtocolError(f"camera {camera!r} must be an HxWx3 uint8 RGB array")
                path = turn_dir / f"frame-{index:03d}.png"
                Image.fromarray(frame).save(path, format="PNG")
                frames[camera] = {
                    "path": path.relative_to(self.directory).as_posix(),
                    "encoding": "png", "color_space": "RGB",
                    "width": int(shape[1]), "height": int(shape[0]),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
        # Deliberately never serialize episode identity/seed/metadata, benchmark
        # metadata, or Observation.metadata. Native info is not a policy channel.
        payload = {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "step": observation.step,
            "instruction": observation.instruction,
            "images": frames,
            "state": state,
            "observation_spec": spec.to_dict(),
            "action_spec": context.action_spec.to_dict(),
            "budgets": {
                "budget_mode": context.budget_mode,
                "primary_budget": "policy_decisions" if context.budget_mode == "decisions" else "first_exhausted_limit",
                "max_steps": context.max_steps,
                "max_policy_calls": context.max_policy_calls,
                "replan_interval": context.replan_interval,
                "max_chunk_length": self.max_chunk_length,
                "response_timeout_s": self.timeout_s,
                "max_provider_calls_per_decision": 1,
                "provider_call_limit_verified": False,
            },
            "prompt": self.prompt,
            "history": "current_observation_only",
            "policy_constraints": self.stop_rule.public_view(),
            "control_feedback": self.stop_rule.feedback_view(),
        }
        return payload

    def _read_response(self, path: Path) -> Any:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                details = os.fstat(handle.fileno())
                if not stat.S_ISREG(details.st_mode):
                    raise ValueError("action.json must be a regular file")
                if details.st_size > self.max_response_bytes:
                    raise ValueError("action.json exceeds max_response_bytes")
                payload = handle.read(self.max_response_bytes + 1)
                if len(payload) > self.max_response_bytes:
                    raise ValueError("action.json exceeds max_response_bytes")
            return json.loads(
                payload.decode("utf-8"), object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            raise PolicyError(f"invalid mailbox response: {exc}") from exc

    def _parse_response(
        self, response: Any, request_id: str, elapsed_s: float, turn_dir: Path
    ) -> PolicyDecision:
        context = self._context
        if context is None:
            raise PolicyError("mailbox has no active episode")
        try:
            if not isinstance(response, dict):
                raise ValueError("response must be a JSON object")
            if response.get("request_id") != request_id:
                raise ValueError("response request_id does not match the pending request")
            stopping = "stop" in response
            allowed = {"request_id", "usage", "note"} | (
                {"stop", "stop_reason"} if stopping else {"actions"}
            )
            if set(response) - allowed:
                raise ValueError(f"unknown response keys: {sorted(set(response) - allowed)}")
            if "usage" not in response:
                raise ValueError("usage must be explicit: null or an object with calls")
            raw_usage = response["usage"]
            if raw_usage is None:
                raw_usage = {"calls": None}
            if not isinstance(raw_usage, dict) or "calls" not in raw_usage:
                raise ValueError("usage must be null or an object with an explicit calls count")
            if set(raw_usage) - set(_USAGE_COUNTERS + _USAGE_FLOATS):
                raise ValueError("unknown usage fields")
            for key in _USAGE_COUNTERS:
                value = raw_usage.get(key)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError(f"usage.{key} must be a nonnegative integer or null")
            if raw_usage["calls"] is not None and raw_usage["calls"] > 1:
                raise ValueError("one response may report at most one provider request")
            for key in _USAGE_FLOATS:
                value = raw_usage.get(key)
                if value is not None and _finite_number(value, f"usage.{key}") < 0:
                    raise ValueError(f"usage.{key} must be nonnegative")
            note = response.get("note")
            if note is not None and (not isinstance(note, str) or len(note) > 2000):
                raise ValueError("note must be a string of at most 2000 characters")
            usage = Usage(**{
                **{key: raw_usage.get(key) for key in _USAGE_COUNTERS + _USAGE_FLOATS},
                "latency_s": elapsed_s,
            })
            metadata = {
                "request_id": request_id,
                "observation_path": str(turn_dir / "observation.json"),
                "response_path": str(turn_dir / "accepted_response.json"),
                "structured_response": ensure_jsonable(response),
                "usage_source": "unavailable" if usage.calls is None else "client_reported",
                "provider_call_limit_verified": False,
            }
            if stopping:
                if response["stop"] is not True:
                    raise ValueError("stop must be true")
                reason = _nonempty_string(response.get("stop_reason"), "stop_reason")
                if len(reason) > 200:
                    raise ValueError("stop_reason must contain at most 200 characters")
                return PolicyDecision(
                    stop=True, stop_reason=reason, note=note, metadata=metadata, usage=usage
                )
            actions = response.get("actions")
            if not isinstance(actions, list) or not 1 <= len(actions) <= self.max_chunk_length:
                raise ValueError(f"actions must contain 1 to {self.max_chunk_length} vectors")
            steps: list[tuple[float, ...]] = []
            for index, action in enumerate(actions):
                if not isinstance(action, list):
                    raise ValueError(f"actions[{index}] must be an array")
                numbers = [
                    _finite_number(value, f"actions[{index}][{axis}]")
                    for axis, value in enumerate(action)
                ]
                steps.append(context.action_spec.validate(numbers))
            return PolicyDecision(
                action=ActionChunk(tuple(steps)), note=note, metadata=metadata, usage=usage
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise PolicyError(f"invalid mailbox response: {exc}") from exc

    def act(self, observation: Observation) -> PolicyDecision:
        if self._context is None:
            raise PolicyError("start_episode must precede act")
        if self._pending or self._failed:
            raise PolicyError("mailbox cannot retry an active or failed decision")
        if observation.step <= self._last_step:
            raise PolicyError("mailbox cannot request another response for the same observation step")
        self._turn_index += 1
        self._last_step = observation.step
        request_id = f"{self._namespace}-episode-{self._episode_index:06d}-turn-{self._turn_index:06d}"
        turn_dir = self.directory / request_id
        turn_dir.mkdir(exist_ok=False)
        response_path = turn_dir / "action.json"
        self._pending = True
        started = time.monotonic()
        try:
            exported = self._export_observation(observation, request_id, turn_dir)
            atomic_write_json(turn_dir / "observation.json", exported)
            self._write_ready(
                "pending", request_id=request_id,
                observation_path=(turn_dir / "observation.json").relative_to(self.directory).as_posix(),
                response_path=response_path.relative_to(self.directory).as_posix(),
            )
            deadline = started + self.timeout_s
            while True:
                # lexists also detects a dangling symlink, which must fail rather
                # than silently wait until timeout or follow a later target.
                if os.path.lexists(response_path):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PolicyError(f"mailbox response timed out after {self.timeout_s:g} seconds")
                time.sleep(min(0.05, remaining))
            if time.monotonic() > deadline:
                raise PolicyError(f"mailbox response timed out after {self.timeout_s:g} seconds")
            response = self._read_response(response_path)
            decision = self._parse_response(response, request_id, time.monotonic() - started, turn_dir)
            atomic_write_json(turn_dir / "accepted_response.json", response)
            # Keep the sole submitted bytes even when this policy refuses its
            # own premature stop. The shared evaluator does not own this rule.
            self.stop_rule.validate(decision)
            self._write_ready("consumed", request_id=request_id)
            return decision
        except Exception:
            self._failed = True
            self._write_ready("failed", request_id=request_id)
            raise
        finally:
            self._pending = False

    def end_episode(self) -> None:
        if self._pending:
            raise PolicyError("cannot end an episode while a mailbox response is pending")
        self._context = None
        self._write_ready("episode_closed")


@register_policy("mailbox")
def make_mailbox_policy(parameters: Mapping[str, JsonValue]) -> MailboxPolicy:
    """Construct a mailbox without importing a simulator or provider package."""
    unknown = set(parameters) - _PARAMETERS
    if unknown:
        raise ValueError(f"unknown mailbox parameters: {sorted(unknown)}")
    if "directory" not in parameters:
        raise ValueError("mailbox policy requires directory: an unused absolute run-specific path")
    if not isinstance(parameters["directory"], str):
        raise ValueError("mailbox directory must be a string")
    return MailboxPolicy(**parameters)
