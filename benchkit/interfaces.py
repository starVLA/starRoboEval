"""Runtime protocols implemented by benchmark and policy adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol, Sequence

from benchkit.contracts import (
    ActionRejectionFeedback,
    ActionSpec,
    BenchmarkDescriptor,
    EpisodeContext,
    EpisodeSpec,
    ExecutionFeedback,
    JsonValue,
    Observation,
    ObservationSpec,
    PolicyDecision,
    PolicyDescriptor,
    Transition,
)


class EpisodeSession(Protocol):
    """One native benchmark episode opened by an adapter."""

    def reset(self) -> Observation: ...

    def step(self, action: tuple[float, ...]) -> Transition: ...

    def metrics(self) -> Mapping[str, JsonValue]: ...

    def artifacts(self) -> Mapping[str, str]: ...

    def close(self) -> None: ...


class ArtifactBoundEpisodeSession(EpisodeSession, Protocol):
    """Optional session capability for runner-owned video/observation artifacts.

    The runner calls this once, before reset, with a newly created directory
    inside the episode's run directory. Sessions without this capability keep
    the original EpisodeSession interface.
    """

    def bind_artifact_dir(self, path: Path) -> None: ...


class BenchmarkAdapter(Protocol):
    """Factory and protocol metadata for one pinned benchmark runtime."""

    @property
    def descriptor(self) -> BenchmarkDescriptor: ...

    @property
    def observation_spec(self) -> ObservationSpec: ...

    @property
    def action_spec(self) -> ActionSpec: ...

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]: ...

    def open_episode(self, episode: EpisodeSpec) -> EpisodeSession: ...


class Policy(Protocol):
    """A model constrained to one observation-to-decision call at a time."""

    @property
    def descriptor(self) -> PolicyDescriptor: ...

    def compatibility_errors(
        self, observation_spec: ObservationSpec, action_spec: ActionSpec
    ) -> Sequence[str]: ...

    def start_episode(self, context: EpisodeContext) -> None: ...

    def act(self, observation: Observation) -> PolicyDecision: ...

    def end_episode(self) -> None: ...


class RuntimeCheckablePolicy(Policy, Protocol):
    """Optional model-owned local readiness, before any native attempt.

    No model request, task context, simulator, action generation or usage event
    is allowed. Check local dependencies/credential presence only; release any
    temporary clients. Success returns None; failures use PolicyPreflightError.
    A profile opts in through its declared runtime_preflight setting.
    """

    def preflight_runtime(self) -> None: ...


class ExecutionAwarePolicy(Policy, Protocol):
    """Optional public receipt, sent after a control chunk is executed.

    The runner neither knows nor enforces a policy's persistence/stop rule.
    Policies can use actual execution receipts for their own state and limits.
    A separately declared robot-control sensor channel may supply ordered
    control acknowledgements. No private simulator metadata or scoring crosses
    this capability. The hook records feedback without calling a model or SIM.
    """

    def observe_execution(self, feedback: ExecutionFeedback) -> None: ...


class ActionRejectionAwarePolicy(Policy, Protocol):
    """Required opt-in for feedback-mode invalid actions, without another call.

    For a rejected call this replaces observe_execution, including when a
    prefix already executed. The next Policy.act receives the unchanged last
    acknowledged observation. The hook must not request a model or simulator.
    """

    def observe_rejection(self, feedback: ActionRejectionFeedback) -> None: ...
