"""Fixed-action harness diagnostic; never a participant model or scored baseline."""

from __future__ import annotations

from typing import Mapping, Sequence

from benchkit.contracts import (
    ActionChunk, ActionSpec, EpisodeContext, JsonValue, Observation, ObservationSpec,
    PolicyDecision, PolicyDescriptor, Usage,
)


class ConstantPolicy:
    def __init__(self, action: Sequence[float], chunk_length: int = 5) -> None:
        if type(chunk_length) is not int or not 1 <= chunk_length <= 1024:
            raise ValueError("chunk_length must be an integer in [1, 1024]")
        self.chunk = ActionChunk.from_steps([action] * chunk_length)
        self.descriptor = PolicyDescriptor(
            name="constant-action-diagnostic", kind="scripted", version="1",
            parameters={"action": list(self.chunk.steps[0]), "chunk_length": chunk_length,
                        "purpose": "infrastructure_validation_only"},
        )

    def compatibility_errors(self, observation_spec: ObservationSpec, action_spec: ActionSpec) -> Sequence[str]:
        try:
            action_spec.validate(self.chunk.steps[0])
        except (ValueError, TypeError) as exc:
            return [str(exc)]
        return []

    def start_episode(self, context: EpisodeContext) -> None:
        pass

    def act(self, observation: Observation) -> PolicyDecision:
        return PolicyDecision(action=self.chunk, usage=Usage())

    def end_episode(self) -> None:
        pass


def make_constant(parameters: Mapping[str, JsonValue]) -> ConstantPolicy:
    if set(parameters) - {"action", "chunk_length"}:
        raise ValueError("constant supports only action and chunk_length")
    return ConstantPolicy(**parameters)
