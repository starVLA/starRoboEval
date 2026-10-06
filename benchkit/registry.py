"""Small explicit registry for installed benchmark and policy adapters."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any, Mapping, TypeVar

from benchkit.contracts import JsonValue
from benchkit.interfaces import BenchmarkAdapter, Policy

T = TypeVar("T")
Factory = Callable[[Mapping[str, JsonValue]], T]

_BENCHMARKS: dict[str, Factory[BenchmarkAdapter]] = {}
_POLICIES: dict[str, Factory[Policy]] = {}
_BUILTINS_LOADED = False
_POLICY_MODULES = {
    "mailbox": "AgentPolicies.anonymous_code_agent.mailbox",
    "constant": "benchkit.diagnostics.constant",
}


def _register(registry: dict[str, Factory[Any]], name: str, factory: Factory[Any]) -> None:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("registry name must not be empty")
    if normalized in registry:
        raise ValueError(f"duplicate registry entry: {normalized}")
    registry[normalized] = factory


def register_benchmark(name: str) -> Callable[[Factory[BenchmarkAdapter]], Factory[BenchmarkAdapter]]:
    """Register a benchmark factory under a stable CLI name."""

    def decorator(factory: Factory[BenchmarkAdapter]) -> Factory[BenchmarkAdapter]:
        _register(_BENCHMARKS, name, factory)
        return factory

    return decorator


def register_policy(name: str) -> Callable[[Factory[Policy]], Factory[Policy]]:
    """Register a policy factory under a stable CLI name."""

    def decorator(factory: Factory[Policy]) -> Factory[Policy]:
        _register(_POLICIES, name, factory)
        return factory

    return decorator


def load_builtins() -> None:
    """Import dependency-free built-ins exactly once."""
    global _BUILTINS_LOADED
    if not _BUILTINS_LOADED:
        import benchkit.diagnostics.smoke  # noqa: F401
        import benchmarks.simBenchmarks.SimplerEnv.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.LIBERO.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.SIMPLE.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.MetaWorld.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.Robotwin.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.DOMINO.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.Behavior.bench_server.adapter  # noqa: F401
        import benchmarks.simBenchmarks.calvin.bench_server.adapter  # noqa: F401
        # Keep the user-facing benchmark directory name; importlib supports it.
        import_module("benchmarks.simBenchmarks.LIBERO-plus.bench_server.adapter")
        import_module("benchmarks.simBenchmarks.VLA-Arena.bench_server.adapter")

        # Preserve the catalog's original stable ID as a CLI alias.
        _register(_BENCHMARKS, "robocasa_365", benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter.make_robocasa365)
        _register(_BENCHMARKS, "simple_humanoid", benchmarks.simBenchmarks.SIMPLE.bench_server.adapter.make_simple_humanoid)

        _BUILTINS_LOADED = True


def create_benchmark(name: str, parameters: Mapping[str, JsonValue] | None = None) -> BenchmarkAdapter:
    """Construct a registered benchmark or report available names."""
    load_builtins()
    normalized = name.strip().lower()
    if normalized not in _BENCHMARKS:
        raise KeyError(f"unknown benchmark {name!r}; installed: {', '.join(sorted(_BENCHMARKS))}")
    return _BENCHMARKS[normalized](parameters or {})


def create_policy(name: str, parameters: Mapping[str, JsonValue] | None = None) -> Policy:
    """Construct a registered policy or report available names."""
    load_builtins()
    normalized = name.strip().lower()
    if normalized not in _POLICIES and normalized in _POLICY_MODULES:
        import_module(_POLICY_MODULES[normalized])
    if normalized not in _POLICIES:
        raise KeyError(f"unknown policy {name!r}; installed: {', '.join(sorted(_POLICIES))}")
    return _POLICIES[normalized](parameters or {})


def registered() -> dict[str, list[str]]:
    """Return registered names without exposing mutable registry state."""
    load_builtins()
    return {"benchmarks": sorted(_BENCHMARKS), "policies": sorted(set(_POLICIES) | set(_POLICY_MODULES))}
