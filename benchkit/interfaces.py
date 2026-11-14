"""Runtime protocols implemented by benchmark and policy adapters."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from benchkit.contracts import (
    ActionSpec,
    BenchmarkDescriptor,
    EpisodeContext,
    EpisodeSpec,
    JsonValue,
    Observation,
    ObservationSpec,
    PolicyDecision,
    PolicyDescriptor,
    Transition,
)


class EpisodeSession(Protocol):
    """One native benchmark episode opened by an adapter.

    Optional ``bind_artifact_dir(path)``: the runner calls it once, before
    reset, with a new runner-owned directory inside the episode directory.
    """

    def reset(self) -> Observation: ...

    def step(self, action: tuple[float, ...]) -> Transition: ...

    def metrics(self) -> Mapping[str, JsonValue]: ...

    def artifacts(self) -> Mapping[str, str]: ...

    def close(self) -> None: ...


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
    """A model constrained to one observation-to-decision call at a time.

    Optional hooks, found by attribute lookup; none may call a model or SIM:

    - ``observe_execution(ExecutionFeedback)``: public counters and any declared
      control acknowledgements after an executed chunk; never reward or
      private simulator state. Stop/persistence rules stay with the policy.
    - ``observe_rejection(ActionRejectionFeedback)``: required in feedback
      mode; replaces observe_execution for a rejected call. The next ``act``
      receives the unchanged last acknowledged observation.
    - ``preflight_runtime()``: local dependency/credential readiness before
      any attempt; failures raise PolicyPreflightError.
    - ``episode_usage() -> EpisodeUsage``: the policy's own cumulative usage,
      read once right after ``end_episode``; the runner reconciles the
      episode total with it and leaves per-call usage as measured.
    """

    @property
    def descriptor(self) -> PolicyDescriptor: ...

    def compatibility_errors(
        self, observation_spec: ObservationSpec, action_spec: ActionSpec
    ) -> Sequence[str]: ...

    def start_episode(self, context: EpisodeContext) -> None: ...

    def act(self, observation: Observation) -> PolicyDecision: ...

    def end_episode(self) -> None: ...

