"""Dependency-free diagnostic world, never a participant capability benchmark."""

from __future__ import annotations

import random
from typing import Mapping, Sequence

from benchkit.contracts import (
    ActionChunk,
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
    Usage,
)
from benchkit.registry import register_benchmark, register_policy


class ReachEpisode:
    """Tiny absolute-position world with native success and reward signals."""

    def __init__(self, spec: EpisodeSpec) -> None:
        self.spec = spec
        self.position = 0.0
        self.target = 0.0
        self.done = False
        self._reward = 0.0
        self._step = 0

    def reset(self) -> Observation:
        randomizer = random.Random(self.spec.seed)
        self.target = randomizer.uniform(-0.8, 0.8)
        self.position = -0.8 if self.target >= 0 else 0.8
        self.done = False
        self._step = 0
        return self._observation(0)

    def _observation(self, step: int) -> Observation:
        return Observation(
            step=step,
            instruction=self.spec.instruction,
            state=(self.position,),
            metadata={"target": self.target},
        )

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.done:
            raise RuntimeError("cannot step a completed episode")
        self.position = action[0]
        self._step += 1
        distance = abs(self.target - self.position)
        self.done = distance <= 0.05
        self._reward = max(0.0, 1.0 - distance)
        return Transition(
            observation=self._observation(self._step),
            reward=self._reward,
            terminated=self.done,
            info={"distance": distance},
        )

    def metrics(self) -> Mapping[str, JsonValue]:
        return {"success": self.done, "final_distance": abs(self.target - self.position)}

    def artifacts(self) -> Mapping[str, str]:
        return {}

    def close(self) -> None:
        return None


class ReachBenchmark:
    """Benchmark adapter for the tiny reach world."""

    descriptor = BenchmarkDescriptor(
        name="smoke-reach",
        version="1",
        protocol_version="starvla-rsi.smoke/v1",
        source_revision="builtin",
    )
    observation_spec = ObservationSpec(state_names=("position",), modalities=("language", "state"))
    action_spec = ActionSpec(
        mode="joint_position",
        size=1,
        names=("position",),
        low=(-1.0,),
        high=(1.0,),
        control_hz=10.0,
    )

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        count = 3 if limit is None else limit
        return [
            EpisodeSpec(
                id=f"reach-{index:03d}",
                task="reach",
                seed=seed + index,
                instruction="Move the joint to the target position.",
            )
            for index in range(count)
        ]

    def open_episode(self, episode: EpisodeSpec) -> ReachEpisode:
        return ReachEpisode(episode)


class ScriptedReachPolicy:
    """Reference policy proving that runner wiring, not task skill, is functional."""

    descriptor = PolicyDescriptor(name="smoke-scripted", kind="scripted", version="1")

    def compatibility_errors(
        self, observation_spec: ObservationSpec, action_spec: ActionSpec
    ) -> Sequence[str]:
        errors: list[str] = []
        if action_spec.mode != "joint_position" or action_spec.size != 1:
            errors.append("smoke-scripted requires a 1-D joint_position action")
        if not observation_spec.state_names:
            errors.append("smoke-scripted requires proprioceptive state")
        return errors

    def start_episode(self, context: EpisodeContext) -> None:
        return None

    def act(self, observation: Observation) -> PolicyDecision:
        target = float(observation.metadata["target"])
        return PolicyDecision(
            action=ActionChunk.from_steps(((target,),)),
            note="Move directly to the target in the mock world.",
            usage=Usage(),
        )

    def end_episode(self) -> None:
        return None


@register_benchmark("smoke")
def make_smoke_benchmark(parameters: Mapping[str, JsonValue]) -> ReachBenchmark:
    if parameters:
        raise ValueError(f"smoke benchmark has no parameters: {sorted(parameters)}")
    return ReachBenchmark()


@register_policy("scripted")
def make_scripted_policy(parameters: Mapping[str, JsonValue]) -> ScriptedReachPolicy:
    if parameters:
        raise ValueError(f"scripted policy has no parameters: {sorted(parameters)}")
    return ScriptedReachPolicy()
