"""Benchmark-owned SimplerEnv service adapter and strict native observation bridge."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import (
    ActionSpec, BenchmarkDescriptor, EpisodeSpec, JsonValue, Observation, ObservationSpec, Transition,
)
from benchkit.errors import CompatibilityError, ProtocolError
from benchkit.registry import register_benchmark

SIMPLER_REVISION = "c701ea271b16b80616d6fed9713c4a50a0adea3b"
MANISKILL_REVISION = "ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682"
# Shared-filesystem Git metadata scans can exceed 15 s before native creation.
# Bound each verification command independently; this is not a control budget.
NATIVE_GIT_TIMEOUT_S = 120
TASK_HORIZONS = {row["id"]: row["native_horizon"] for row in json.loads(
    Path(__file__).with_name("protocol").joinpath("task_catalog.json").read_text(encoding="utf-8"))}


def _revision(root: Path, expected: str) -> dict[str, JsonValue]:
    """Refuse source drift before constructing any environment."""
    git_env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"], check=True,
            capture_output=True, text=True, timeout=NATIVE_GIT_TIMEOUT_S, env=git_env,
        ).stdout.strip()
        if Path(top).resolve() != root.resolve():
            raise CompatibilityError(f"native source must have its own Git root: {root}")
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True, timeout=NATIVE_GIT_TIMEOUT_S, env=git_env,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            check=True, capture_output=True, text=True, timeout=NATIVE_GIT_TIMEOUT_S, env=git_env,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompatibilityError(f"cannot verify upstream Git checkout {root}") from exc
    if revision != expected or dirty:
        raise CompatibilityError(f"upstream must be clean at {expected}: {root} (found {revision})")
    return {"revision": revision, "tracked_dirty": False}


def policy_observation(raw: Mapping[str, Any], camera: str, step: int, instruction: str,
                       proprioception: bool = False) -> Observation:
    """Allowlist RGB and optional robot joint encoders; drop everything else."""
    import numpy as np

    rgb = np.asarray(raw["image"][camera]["rgb"])
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[-1] != 3:
        raise ProtocolError("native RGB must be uint8 H x W x 3")
    state = None
    if proprioception:
        qpos = np.asarray(raw["agent"]["qpos"])
        expected = 11 if camera == "overhead_camera" else 8
        if qpos.shape != (expected,) or not np.isfinite(qpos).all():
            raise ProtocolError(f"expected {expected} finite robot joint encoders")
        state = tuple(float(value) for value in qpos)
    # No raw extra, reset_info, camera matrices, depth, segmentation or metadata.
    return Observation(step=step, instruction=instruction, images={camera: rgb.copy()}, state=state)


def _native_metrics(info: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Snapshot scalar native metrics without calling the stateful scorer again."""
    import numpy as np

    if "success" not in info or not isinstance(info["success"], (bool, np.bool_)):
        raise ProtocolError("native step info must contain boolean success")
    metrics: dict[str, JsonValue] = {"success": bool(info["success"])}
    for key, value in info.get("episode_stats", {}).items():
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(key, str) and key != "success" and isinstance(value, (bool, int, float, str)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ProtocolError("native metric is not finite")
            metrics[key] = value
    return metrics


class SimplerEnvEpisode:
    """Native runtime and private artifacts; never passed to a policy."""

    def __init__(self, benchmark: SimplerEnvBenchmarkAdapter, episode: EpisodeSpec) -> None:
        self.benchmark = benchmark
        self.episode = episode
        self.env: Any = None
        self.artifact_dir: Path | None = None
        self.writer: Any = None
        self.step_count = 0
        self.last_metrics: dict[str, JsonValue] = {"success": False}
        self.success_ever = False
        self.frame_count = 0
        self.horizon_checkpoints: dict[str, JsonValue] = {"native": None, "evaluation": None}

    def bind_artifact_dir(self, path: Path) -> None:
        self.artifact_dir = path
        path.mkdir(parents=True, exist_ok=True)

    def reset(self) -> Observation:
        if self.env is not None:
            raise ProtocolError("a SimplerEnv session permits exactly one reset")
        import gymnasium as gym
        import mani_skill2_real2sim
        import simpler_env

        simpler_root = Path(simpler_env.__file__).resolve().parents[1]
        native_root = Path(mani_skill2_real2sim.__file__).resolve().parents[1]
        provenance = {
            "simpler_env": _revision(simpler_root, SIMPLER_REVISION),
            "mani_skill2_real2sim": _revision(native_root, MANISKILL_REVISION),
            "task": self.episode.task,
            **self.benchmark.budget_metadata(),
            "track": self.benchmark.descriptor.protocol_version,
        }
        if self.artifact_dir is not None:
            atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)

        env_id, native_kwargs = simpler_env.ENVIRONMENT_MAP[self.episode.task]
        # Upstream make mutates ENVIRONMENT_MAP and has tuple obs_mode; use the
        # same registry and a fresh kwargs copy with the documented string mode.
        kwargs = copy.deepcopy(native_kwargs)
        kwargs.update(obs_mode="rgbd", prepackaged_config=True)
        kwargs["renderer_kwargs"] = {"offscreen_only": True, "device": self.benchmark.device}
        if gym.spec(env_id).max_episode_steps != self.benchmark.native_horizon:
            raise CompatibilityError("native horizon differs from the pinned task catalog")
        # Override the TimeLimit at construction, never ignore a truncation or
        # mutate the scorer. This is a predeclared, separately named track.
        self.env = gym.make(env_id, max_episode_steps=self.benchmark.evaluation_horizon, **kwargs)
        if self.benchmark.expected_gpu_uuid is not None:
            from benchmarks.simBenchmarks.SimplerEnv.environment.render_device import assert_render_device

            provenance["render_device"] = assert_render_device(self.benchmark.expected_gpu_uuid)
            if self.artifact_dir is not None:
                atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
        if self.env.spec.max_episode_steps != self.benchmark.evaluation_horizon:
            raise CompatibilityError("effective native TimeLimit differs from evaluation horizon")
        if self.env.action_space.shape != (7,):
            raise CompatibilityError("expected a seven-dimensional native action space")
        for actual, declared in zip(self.env.action_space.low, self.benchmark.action_spec.low or ()):
            if not math.isclose(float(actual), declared, rel_tol=1e-6, abs_tol=1e-6):
                raise CompatibilityError("native action lower bounds drifted")
        for actual, declared in zip(self.env.action_space.high, self.benchmark.action_spec.high or ()):
            if not math.isclose(float(actual), declared, rel_tol=1e-6, abs_tol=1e-6):
                raise CompatibilityError("native action upper bounds drifted")
        raw, _private_reset_info = self.env.reset(seed=self.episode.seed)
        if self.artifact_dir is not None:
            from importlib.metadata import version

            native = self.env.unwrapped
            provenance.update({
                "environment_id": env_id,
                "robot": native.robot_uid,
                "control_mode": native.control_mode,
                "control_hz": native.control_freq,
                "simulation_hz": native.sim_freq,
                "camera": self.benchmark.camera,
                "rgb_shape": list(raw["image"][self.benchmark.camera]["rgb"].shape),
                "packages": {name: version(name) for name in ("numpy", "scipy", "sapien", "gymnasium")},
            })
            atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
        return self._observe(raw)

    def _observe(self, raw: Mapping[str, Any]) -> Observation:
        observation = policy_observation(
            raw, self.benchmark.camera, self.step_count,
            self.env.unwrapped.get_language_instruction(), self.benchmark.proprioception,
        )
        if self.artifact_dir is not None:
            import imageio.v2 as imageio
            from PIL import Image

            rgb = observation.images[self.benchmark.camera]
            frame_path = self.artifact_dir / f"frame-{self.frame_count:06d}.png"
            Image.fromarray(rgb).save(frame_path)
            if self.writer is None:
                self.writer = imageio.get_writer(
                    str(self.artifact_dir / "video.mp4"), fps=self.benchmark.action_spec.control_hz,
                    codec="libx264", macro_block_size=1,
                )
            self.writer.append_data(rgb)
            append_jsonl(self.artifact_dir / "frames.jsonl", {
                "step": self.step_count, "camera": self.benchmark.camera,
                "path": frame_path.name, "sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest(),
                "instruction": observation.instruction,
            })
            self.frame_count += 1
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        import numpy as np

        raw, reward, native_terminated, truncated, info = self.env.step(np.asarray(action, dtype=np.float32))
        self.step_count += 1
        self.last_metrics = _native_metrics(info)
        self.success_ever = self.success_ever or bool(self.last_metrics["success"])
        for label, horizon in (("native", self.benchmark.native_horizon),
                               ("evaluation", self.benchmark.evaluation_horizon)):
            if self.step_count == horizon:
                self.horizon_checkpoints[label] = bool(self.last_metrics["success"])
        return Transition(
            observation=self._observe(raw), reward=float(reward),
            # Native evaluator continues past transient success until horizon or
            # explicit policy stop. Never award success merely by stopping here.
            terminated=False, truncated=bool(truncated),
            info={"native_terminated": bool(native_terminated), **self.last_metrics},
        )

    def metrics(self) -> Mapping[str, JsonValue]:
        return {**self.last_metrics, "success_ever": self.success_ever, "native_steps": self.step_count,
                **self.benchmark.budget_metadata(),
                "success_at_native_horizon": self.horizon_checkpoints["native"],
                "success_at_evaluation_horizon": self.horizon_checkpoints["evaluation"]}

    def artifacts(self) -> Mapping[str, str]:
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        if self.artifact_dir is None:
            return {}
        return {
            name: str(self.artifact_dir / filename)
            for name, filename in (("video", "video.mp4"), ("frames", "frames.jsonl"),
                                   ("native_provenance", "native_provenance.json"))
            if (self.artifact_dir / filename).exists()
        }

    def close(self) -> None:
        try:
            if self.writer is not None:
                self.writer.close()
                self.writer = None
        finally:
            if self.env is not None:
                self.env.close()
                self.env = None


class SimplerEnvBenchmarkAdapter:
    """One robot/task cell; simulator dependencies are imported only on reset."""

    def __init__(self, task: str = "widowx_spoon_on_towel", *,
                 proprioception: bool = False, device: str = "cuda:0",
                 horizon_multiplier: int = 1, budget_mode: str = "horizon",
                 max_policy_calls: int | None = None, replan_interval: int | None = None,
                 action_rejection_feedback: bool = False,
                 interaction_mode: str = "single_response",
                 expected_gpu_uuid: str | None = None) -> None:
        if task not in TASK_HORIZONS:
            raise ValueError(f"unsupported development task {task!r}; choose one of {list(TASK_HORIZONS)}")
        if not isinstance(proprioception, bool):
            raise TypeError("proprioception must be boolean")
        if type(action_rejection_feedback) is not bool:
            raise TypeError("action_rejection_feedback must be boolean")
        if not isinstance(interaction_mode, str) or interaction_mode not in ("single_response", "agent_method"):
            raise ValueError("interaction_mode must be single_response or agent_method")
        if type(horizon_multiplier) is not int or horizon_multiplier not in (1, 2):
            raise ValueError("horizon_multiplier must be 1 (native) or 2 (extended)")
        if budget_mode not in ("horizon", "decisions"):
            raise ValueError("budget_mode must be horizon or decisions")
        if budget_mode == "decisions":
            if horizon_multiplier != 1:
                raise ValueError("decision budgets cannot also select a horizon multiplier")
            if any(type(value) is not int or value <= 0 for value in (max_policy_calls, replan_interval)):
                raise ValueError("decision budgets require positive integer max_policy_calls and replan_interval")
        elif max_policy_calls is not None or replan_interval is not None:
            raise ValueError("adapter decision limits require budget_mode=decisions; use runner limits for horizon mode")
        self.task = task
        self.proprioception = proprioception
        self.action_rejection_feedback = action_rejection_feedback
        self.interaction_mode = interaction_mode
        self.device = device
        if expected_gpu_uuid is not None:
            from benchmarks.simBenchmarks.SimplerEnv.environment.render_device import validate_gpu_uuid

            validate_gpu_uuid(expected_gpu_uuid)
        self.expected_gpu_uuid = expected_gpu_uuid
        self.native_horizon = TASK_HORIZONS[task]
        self.budget_mode = budget_mode
        self.max_policy_calls = max_policy_calls
        self.replan_interval = replan_interval
        self.horizon_multiplier = horizon_multiplier if budget_mode == "horizon" else None
        self.environment_step_cap = (
            max_policy_calls * replan_interval if budget_mode == "decisions"
            else self.native_horizon * horizon_multiplier
        )
        self.evaluation_horizon = self.environment_step_cap
        budget_track = (f"/decision-{max_policy_calls}-prefix-{replan_interval}" if budget_mode == "decisions"
                        else "/extended-2x" if horizon_multiplier == 2 else "")
        google = task.startswith("google_robot_")
        self.camera = "overhead_camera" if google else "3rd_view_camera"
        self.descriptor = BenchmarkDescriptor(
            name="simpler_env", version="0.0.1",
            protocol_version="simpler-prepackaged-development/" + ("rgb-qpos" if proprioception else "rgb")
            + budget_track + ("/action-feedback" if action_rejection_feedback else "")
            + ("/agent-method" if interaction_mode == "agent_method" else "") + "/v1",
            source_revision=SIMPLER_REVISION + ":" + MANISKILL_REVISION,
        )
        self.observation_spec = ObservationSpec(
            cameras=(self.camera,),
            state_names=tuple(f"qpos_{i}" for i in range(11 if google else 8)) if proprioception else (),
            modalities=("language", "rgb", "joint_position") if proprioception else ("language", "rgb"),
        )
        self.action_spec = ActionSpec(
            mode="ee_delta_pose", size=7,
            names=("dx_m", "dy_m", "dz_m", "rx_rad", "ry_rad", "rz_rad", "gripper"),
            low=(-1.0, -1.0, -1.0, -math.pi / 2, -math.pi / 2, -math.pi / 2, -1.0),
            high=(1.0, 1.0, 1.0, math.pi / 2, math.pi / 2, math.pi / 2, 1.0),
            control_hz=3.0 if google else 5.0,
            frame="ee_align (measured-pose delta)" if google else "ee_align2 (accumulated-target delta)",
            rotation="axis-angle rotation vector, radians",
            gripper="+1 close; -1 open; 0 hold (target delta)" if google else "+1 open; -1 close; 0 intermediate (absolute)",
        )

    def budget_metadata(self) -> dict[str, JsonValue]:
        return {
            "interaction_mode": self.interaction_mode,
            "budget_mode": self.budget_mode,
            "max_policy_calls": self.max_policy_calls, "replan_interval": self.replan_interval,
            "environment_step_cap": self.environment_step_cap,
            "native_horizon": self.native_horizon,
            "native_horizon_source": "pinned_gym_registration",
            "evaluation_horizon": self.evaluation_horizon, "horizon_multiplier": self.horizon_multiplier,
        }

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        count = 1 if limit is None else limit
        return [EpisodeSpec(
            id=f"{self.task}-{index:06d}", task=self.task, seed=seed + index,
            instruction="Follow the current instruction in the camera observation.",
            metadata={**self.budget_metadata(),
                      "selection": "prepackaged_seeded_reset"},
        ) for index in range(count)]

    def open_episode(self, episode: EpisodeSpec) -> SimplerEnvEpisode:
        if episode.task != self.task:
            raise ProtocolError("episode task does not match adapter task")
        return SimplerEnvEpisode(self, episode)


@register_benchmark("simpler_env")
def make_simpler_env(parameters: Mapping[str, JsonValue]) -> SimplerEnvBenchmarkAdapter:
    unknown = set(parameters) - {"task", "proprioception", "device", "horizon_multiplier",
                                 "budget_mode", "max_policy_calls", "replan_interval",
                                 "action_rejection_feedback", "interaction_mode", "expected_gpu_uuid"}
    if unknown:
        raise ValueError(f"unknown SimplerEnv parameters: {sorted(unknown)}")
    return SimplerEnvBenchmarkAdapter(**parameters)
