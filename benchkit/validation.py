"""Closed, actor-safe action-validation data; no simulator or model imports.

An issue describes only a deterministic input rejection. It must never carry
native exceptions, task state, response text, credentials or unknown outcomes.
The service, policy and trusted driver may share this DTO without sharing
control authority. Raising ``ActionRejected`` promises that the rejected
vector itself has not executed; previously acknowledged prefix controls remain
real and are accounted for separately by the driver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from benchkit.contracts import ActionSpec


@dataclass(frozen=True)
class ValidationIssue:
    """Bounded public explanation of an invalid input, never raw error text.

    ``action_index`` is an optional zero-based component index within the named
    field. ``limit`` is a single violated/required bound, not a hidden-state
    value or an arbitrary container. Nonfinite or wrong-type input values are
    represented by ``actual=None`` rather than copied into the feedback.
    """

    code: str
    field: str = "action"
    actual: int | float | None = None
    limit: int | float | None = None
    action_index: int | None = None

    CODES: ClassVar[frozenset[str]] = frozenset({
        "invalid_json", "unexpected_fields", "invalid_type", "invalid_length",
        "non_finite", "out_of_bounds", "quaternion_not_unit",
        "translation_limit", "rotation_limit", "gripper_binary_required",
        "invalid_stop", "invalid_action",
    })
    FIELDS: ClassVar[frozenset[str]] = frozenset({
        "action", "response", "steps", "memory", "note", "safety_stop", "stop_reason",
        "left", "right", "left.pose", "right.pose",
        "left.opening", "right.opening", "left.translation_m",
        "right.translation_m", "left.rotation_rad", "right.rotation_rad",
        "left.quaternion_norm", "right.quaternion_norm",
    })
    MAX_ACTION_INDEX: ClassVar[int] = 2**31 - 1
    KEYS: ClassVar[frozenset[str]] = frozenset({
        "code", "field", "actual", "limit", "action_index",
    })

    def __post_init__(self) -> None:
        if type(self.code) is not str or self.code not in self.CODES:
            raise ValueError("unknown validation issue code")
        if type(self.field) is not str or self.field not in self.FIELDS:
            raise ValueError("unsupported validation issue field")
        for name in ("actual", "limit"):
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) not in (int, float):
                raise ValueError("validation issue values must be finite numbers or null")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("validation issue values must be finite numbers or null")
        if self.action_index is not None and (
            type(self.action_index) is not int
            or not 0 <= self.action_index <= self.MAX_ACTION_INDEX
        ):
            raise ValueError("validation issue component index is invalid")

    def to_dict(self) -> dict:
        return {"code": self.code, "field": self.field, "actual": self.actual,
                "limit": self.limit, "action_index": self.action_index}

    @classmethod
    def from_dict(cls, value: dict) -> "ValidationIssue":
        if type(value) is not dict or "code" not in value or set(value) - cls.KEYS:
            raise ValueError("validation issue must contain only supported fields")
        return cls(**value)


def validate_action_vector(spec: "ActionSpec", values) -> tuple[float, ...]:
    """Validate the generic ActionSpec contract without executing any control.

    Only known input shape/type/finite/bound failures become typed rejections.
    No broad exception handler reclassifies infrastructure or adapter failures.
    Semantic validators such as quaternion checks remain benchmark-owned.
    """
    # Lazy import avoids contracts -> validation -> errors -> contracts cycles.
    from benchkit.errors import ActionRejected

    if not isinstance(values, (list, tuple)):
        raise ActionRejected(ValidationIssue("invalid_type"))
    if len(values) != spec.size:
        raise ActionRejected(ValidationIssue("invalid_length", actual=len(values), limit=spec.size))
    normalized = []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ActionRejected(ValidationIssue("invalid_type", action_index=index))
        try:
            number = float(value)
        except OverflowError:
            raise ActionRejected(ValidationIssue("non_finite", action_index=index)) from None
        if not math.isfinite(number):
            raise ActionRejected(ValidationIssue("non_finite", action_index=index))
        if spec.low is not None and spec.high is not None:
            if number < spec.low[index]:
                raise ActionRejected(ValidationIssue("out_of_bounds", actual=number,
                    limit=spec.low[index], action_index=index))
            if number > spec.high[index]:
                raise ActionRejected(ValidationIssue("out_of_bounds", actual=number,
                    limit=spec.high[index], action_index=index))
        normalized.append(number)
    return tuple(normalized)
