"""Public, closed robot-only feedback for one acknowledged native control.

This module is dependency-light and never opens an environment or an artifact.
The benchmark constructs this observation channel from explicitly named robot
measurements and the command it just executed. No native metrics/info mapping
is a public observation. DLS errors below describe the PRE-control measurement;
they are not a prediction or a claim that the physical robot reached its target.
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Any, Mapping, Sequence

from benchkit.errors import ProtocolError


SCHEMA = "starvla-rsi.robodojo.robot-control-feedback/v1"
_SIDES = ("left", "right")
_PAYLOAD_KEYS = frozenset(("schema", "control_target", "diagnostic_phase",
    "executed_joint_command", "post_robot_state", "ik_diagnostics"))
_DIAGNOSTIC_KEYS = frozenset(("target_position_error_m", "target_rotation_error_rad",
    "proposed_joint_delta", "bounded_task_delta", "measured_fk_check"))
_FK_KEYS = frozenset(("position_error_m", "rotation_error_rad", "passed"))


def _closed(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ProtocolError(f"invalid robot feedback {label} fields")
    return value


def _number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ProtocolError(f"invalid robot feedback {label} number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ProtocolError(f"invalid robot feedback {label} number") from error
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise ProtocolError(f"invalid robot feedback {label} number")
    return number


def _vector(value: Any, size: int, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ProtocolError(f"invalid robot feedback {label} vector")
    return [_number(item, label) for item in value]


def _state(value: Any) -> list[float]:
    state = _vector(value, 28, "post state")
    if any(not 0 <= state[index] <= 1 for index in (6, 13)):
        raise ProtocolError("invalid robot feedback last commanded opening")
    for start in (17, 24):
        if abs(math.hypot(*state[start:start + 4]) - 1) > 1e-4:
            raise ProtocolError("invalid robot feedback measured quaternion")
    return state


def validate_robot_feedback(value: Any, *, expected_control_target: int | None = None,
                            expected_robot_state: Sequence[float] | None = None) -> dict[str, Any]:
    """Validate the closed schema and return a detached, JSON-safe projection.

    The adapter additionally binds the control counter and post-state to this
    exact ACK's already validated observation. A reset has no receipt. The
    public joint14 values are the native input command, not sensed joint values;
    measured joints/EEF are separately present in ``post_robot_state``.
    """
    row = _closed(value, _PAYLOAD_KEYS, "payload")
    if row["schema"] != SCHEMA or row["diagnostic_phase"] != "pre_control":
        raise ProtocolError("invalid robot feedback schema or diagnostic phase")
    step = row["control_target"]
    if type(step) is not int or step < 1:
        raise ProtocolError("invalid robot feedback control counter")
    if expected_control_target is not None:
        if type(expected_control_target) is not int or expected_control_target < 1 or step != expected_control_target:
            raise ProtocolError("robot feedback does not match this acknowledged control")
    command = _vector(row["executed_joint_command"], 14, "native command")
    if any(not 0 <= command[index] <= 1 for index in (6, 13)):
        raise ProtocolError("invalid robot feedback commanded opening")
    state = _state(row["post_robot_state"])
    if expected_robot_state is not None and state != _state(expected_robot_state):
        raise ProtocolError("robot feedback does not match this observation's measured state")
    arms = _closed(row["ik_diagnostics"], frozenset(_SIDES), "arms")
    diagnostics = {}
    for side in _SIDES:
        source = _closed(arms[side], _DIAGNOSTIC_KEYS, "DLS diagnostic")
        fk = _closed(source["measured_fk_check"], _FK_KEYS, "FK diagnostic")
        position = _number(fk["position_error_m"], "FK position error", nonnegative=True)
        rotation = _number(fk["rotation_error_rad"], "FK rotation error", nonnegative=True)
        if fk["passed"] is not True or position >= .002 or rotation >= .01:
            raise ProtocolError("robot feedback lacks the required measured FK check")
        diagnostics[side] = {
            "target_position_error_m": _number(source["target_position_error_m"], "target position error", nonnegative=True),
            "target_rotation_error_rad": _number(source["target_rotation_error_rad"], "target rotation error", nonnegative=True),
            "proposed_joint_delta": _vector(source["proposed_joint_delta"], 6, "joint delta"),
            "bounded_task_delta": _vector(source["bounded_task_delta"], 6, "task delta"),
            "measured_fk_check": {"position_error_m": position, "rotation_error_rad": rotation, "passed": True},
        }
    return {"schema": SCHEMA, "control_target": step, "diagnostic_phase": "pre_control",
        "executed_joint_command": command, "post_robot_state": state, "ik_diagnostics": diagnostics}


def make_robot_feedback(control_target: int, executed_joint_command: Sequence[float],
                        post_robot_state: Sequence[float], ik_diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    """Project only named robot fields from the worker's private DLS receipt.

    Private source mappings may contain other evaluator-only fields; none is
    copied with a wildcard or accepted by the public validator. This function
    must be called only after the real control and its native counter checks.
    It reads no files, object state, scorer, environment handle or camera data.
    """
    try:
        arms = {side: {
            "target_position_error_m": ik_diagnostics[side]["target_position_error_m"],
            "target_rotation_error_rad": ik_diagnostics[side]["target_rotation_error_rad"],
            "proposed_joint_delta": ik_diagnostics[side]["proposed_joint_delta"],
            "bounded_task_delta": ik_diagnostics[side]["bounded_task_delta"],
            "measured_fk_check": {key: ik_diagnostics[side]["measured_fk_check"][key]
                for key in ("position_error_m", "rotation_error_rad", "passed")},
        } for side in _SIDES}
    except (KeyError, TypeError) as error:
        raise ProtocolError("missing robot-only native conversion receipt") from error
    return validate_robot_feedback({"schema": SCHEMA, "control_target": control_target,
        "diagnostic_phase": "pre_control", "executed_joint_command": executed_joint_command,
        "post_robot_state": post_robot_state, "ik_diagnostics": arms})
