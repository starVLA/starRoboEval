"""Bounded, non-executable JSON for the trusted-driver-to-SIM transport.

Images are inline RGB bytes, never pickles or filesystem references. This codec
validates structure, not information provenance: benchmark adapters still own
the public observation whitelist, including metadata. Transition rewards and
info remain evaluator-only and must never be forwarded as policy observations.
NumPy is loaded only when an image-bearing observation is encoded or decoded.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from collections.abc import Mapping
from numbers import Real
from typing import Any

from benchkit.contracts import Observation, ObservationSpec, Transition
from benchkit.errors import InfrastructureError

PROTOCOL = "starvla-rsi.sim-server/v1"
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
_MAX_DEPTH = 64
_OBSERVATION_FIELDS = {"step", "instruction", "images", "state", "metadata"}
_TRANSITION_FIELDS = {"observation", "reward", "terminated", "truncated", "info"}


class WireError(InfrastructureError):
    """Malformed or oversized SIM transport payload; not a policy failure."""


def _json_value(value: Any, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        raise WireError("SIM JSON nesting exceeds limit")
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise WireError("SIM JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise WireError("SIM JSON object keys must be strings")
        return {key: _json_value(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item, depth + 1) for item in value]
    raise WireError("Unsupported SIM JSON value type")


def dumps(value: Any) -> bytes:
    """Encode finite JSON, enforcing the complete UTF-8 message-size bound."""
    try:
        payload = json.dumps(_json_value(value), allow_nan=False, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise WireError("Invalid SIM JSON value") from exc
    if len(payload) > MAX_MESSAGE_BYTES:
        raise WireError("SIM JSON message exceeds size limit")
    return payload


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WireError("SIM JSON contains duplicate object keys")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise WireError("SIM JSON numbers must be finite")


def loads(payload: bytes) -> dict[str, Any]:
    """Decode one bounded object; reject duplicates, NaN, infinity and junk."""
    if type(payload) is not bytes or not payload or len(payload) > MAX_MESSAGE_BYTES:
        raise WireError("Invalid SIM JSON message size or byte type")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
        if type(value) is not dict:
            raise WireError("SIM JSON message must be an object")
        value = _json_value(value)
        # Also rejects lone Unicode surrogates represented by JSON escapes.
        dumps(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise WireError("Malformed SIM JSON message") from exc


def _object(value: Any, fields: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise WireError("SIM payload requires a string-keyed object")
    if fields is not None and set(value) != fields:
        raise WireError("SIM payload fields do not match the protocol")
    return dict(value)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise WireError("SIM payload requires a finite real number")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise WireError("SIM number cannot be represented") from exc
    if not math.isfinite(result):
        raise WireError("SIM payload requires a finite real number")
    return result


def _check_spec(spec: ObservationSpec) -> None:
    if not isinstance(spec, ObservationSpec) or spec.privileged:
        raise WireError("SIM transport requires a non-privileged observation spec")
    for names in (spec.cameras, spec.state_names):
        if (not isinstance(names, tuple) or any(type(name) is not str or not name for name in names)
                or len(set(names)) != len(names)):
            raise WireError("SIM observation channel names must be unique nonempty strings")


def _observation_fields(data: Any, spec: ObservationSpec) -> dict[str, Any]:
    _check_spec(spec)
    declared = spec.control_feedback_schema is not None
    value = _object(data, _OBSERVATION_FIELDS | ({"control_feedback"} if declared else set()))
    if type(value["step"]) is not int or value["step"] < 0:
        raise WireError("SIM observation step must be a nonnegative integer")
    if type(value["instruction"]) is not str:
        raise WireError("SIM instruction must be a string")
    images = _object(value["images"])
    if set(images) != set(spec.cameras):
        raise WireError("SIM cameras do not match the declared observation spec")
    state = value["state"]
    if not spec.state_names:
        if state is not None:
            raise WireError("SIM state is not declared in the observation spec")
    else:
        if not isinstance(state, (list, tuple)) or len(state) != len(spec.state_names):
            raise WireError("SIM state does not match the declared observation spec")
        state = [_number(item) for item in state]
    if declared:
        feedback = value["control_feedback"]
        if value["step"] == 0:
            if feedback is not None:
                raise WireError("reset cannot carry a control acknowledgement")
        elif feedback is None:
            raise WireError("declared control feedback missing from acknowledgement")
        else:
            feedback = _json_value(_object(feedback))
            if not feedback or feedback.get("schema") != spec.control_feedback_schema:
                raise WireError("control feedback schema differs from declared channel")
            if type(feedback.get("control_target")) is not int or feedback["control_target"] != value["step"]:
                raise WireError("control feedback differs from acknowledged observation index")
        value["control_feedback"] = feedback
    return {**value, "images": images, "state": state,
            "metadata": _json_value(_object(value["metadata"]))}


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:
        raise WireError("NumPy is required for SIM RGB image transport") from exc
    return numpy


def encode_observation(observation: Observation, spec: ObservationSpec) -> dict[str, Any]:
    """Copy one already-whitelisted public observation into JSON data."""
    if not isinstance(observation, Observation):
        raise WireError("SIM adapter did not return an Observation")
    if spec.control_feedback_schema is None and observation.control_feedback is not None:
        raise WireError("undeclared public control feedback")
    value = _observation_fields({"step": observation.step,
                                 "instruction": observation.instruction,
                                 "images": observation.images, "state": observation.state,
                                 "metadata": observation.metadata,
                                 **({"control_feedback": observation.control_feedback}
                                    if spec.control_feedback_schema is not None else {})}, spec)
    encoded = {}
    total_bytes = 0
    np = _numpy() if value["images"] else None
    for camera, pixels in value["images"].items():
        if (not isinstance(pixels, np.ndarray) or pixels.dtype != np.dtype("uint8")
                or pixels.ndim != 3 or pixels.shape[2] != 3
                or pixels.shape[0] <= 0 or pixels.shape[1] <= 0):
            raise WireError("SIM camera requires a nonempty uint8 HWC RGB array")
        total_bytes += 4 * ((pixels.nbytes + 2) // 3)
        if total_bytes > MAX_MESSAGE_BYTES:
            raise WireError("SIM RGB images exceed message size limit")
        encoded[camera] = {"shape": list(pixels.shape), "dtype": "uint8",
                           "encoding": "base64-rgb",
                           "data": base64.b64encode(pixels.tobytes(order="C")).decode("ascii")}
    value["images"] = encoded
    dumps(value)
    return value


def decode_observation(data: Any, spec: ObservationSpec) -> Observation:
    """Validate inline RGB payloads and return independent, writable arrays."""
    dumps(data)  # Also bound direct callers, not just objects returned by loads().
    value = _observation_fields(data, spec)
    decoded = {}
    np = _numpy() if value["images"] else None
    for camera, payload in value["images"].items():
        payload = _object(payload, {"shape", "dtype", "encoding", "data"})
        shape = payload["shape"]
        if (not isinstance(shape, list) or len(shape) != 3
                or any(type(item) is not int or item <= 0 for item in shape)
                or shape[2] != 3 or payload["dtype"] != "uint8"
                or payload["encoding"] != "base64-rgb"):
            raise WireError("Invalid SIM RGB image format")
        size = shape[0] * shape[1] * 3
        encoded = payload["data"]
        if (size > MAX_MESSAGE_BYTES or type(encoded) is not str
                or len(encoded) != 4 * ((size + 2) // 3)):
            raise WireError("SIM RGB shape and payload size do not match")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise WireError("Invalid SIM RGB base64 payload") from exc
        if len(raw) != size or base64.b64encode(raw).decode("ascii") != encoded:
            raise WireError("Noncanonical or incorrect-size SIM RGB payload")
        decoded[camera] = np.frombuffer(raw, dtype=np.uint8).reshape(shape).copy()
    return Observation(step=value["step"], instruction=value["instruction"],
                       images=decoded, state=value["state"], metadata=value["metadata"],
                       control_feedback=value.get("control_feedback"))


def _transition_fields(data: Any) -> dict[str, Any]:
    value = _object(data, _TRANSITION_FIELDS)
    if type(value["terminated"]) is not bool or type(value["truncated"]) is not bool:
        raise WireError("SIM transition termination flags must be booleans")
    return {**value, "reward": _number(value["reward"]),
            "info": _json_value(_object(value["info"]))}


def encode_transition(transition: Transition, spec: ObservationSpec) -> dict[str, Any]:
    if not isinstance(transition, Transition):
        raise WireError("SIM adapter did not return a Transition")
    value = _transition_fields({"observation": encode_observation(transition.observation, spec),
                                "reward": transition.reward, "terminated": transition.terminated,
                                "truncated": transition.truncated, "info": transition.info})
    dumps(value)
    return value


def decode_transition(data: Any, spec: ObservationSpec) -> Transition:
    dumps(data)
    value = _transition_fields(data)
    return Transition(observation=decode_observation(value["observation"], spec),
                      reward=value["reward"], terminated=value["terminated"],
                      truncated=value["truncated"], info=value["info"])
