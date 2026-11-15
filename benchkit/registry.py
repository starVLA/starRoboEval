"""Shared diagnostic policies selectable with ``--policy``; benchmarks come from their services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Mapping

from benchkit.contracts import JsonValue
from benchkit.interfaces import Policy

PolicyFactory = Callable[[Mapping[str, JsonValue]], Policy]


def _policies() -> dict[str, PolicyFactory]:
    # Imported on use; both fixtures are dependency-free.
    from benchkit.diagnostics.constant import make_constant
    from benchkit.diagnostics.smoke import make_scripted_policy

    return {"constant": make_constant, "scripted": make_scripted_policy}


def create_policy(name: str, parameters: Mapping[str, JsonValue] | None = None) -> Policy:
    """Construct a diagnostic policy or report the available names."""
    policies = _policies()
    normalized = name.strip().lower()
    if normalized not in policies:
        raise KeyError(f"unknown policy {name!r}; available: {', '.join(sorted(policies))}")
    return policies[normalized](parameters or {})


def policy_names() -> list[str]:
    """Names accepted by ``--policy``."""
    return sorted(_policies())
