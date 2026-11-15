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

from benchmarks.simBenchmarks.SimplerEnv.bench_server.protocol import max_matrix

SIMPLER_REVISION = "c701ea271b16b80616d6fed9713c4a50a0adea3b"
MANISKILL_REVISION = "ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682"
# Shared-filesystem Git metadata scans can exceed 15 s before native creation.
# Bound each verification command independently; this is not a control budget.
NATIVE_GIT_TIMEOUT_S = 120
TASK_HORIZONS = {row["id"]: row["native_horizon"] for row in json.loads(
    Path(__file__).with_name("protocol").joinpath("task_catalog.json").read_text(encoding="utf-8"))}
# Real overlays referenced by the `max` matrices, hashed from the pinned checkout.
OVERLAY_SHA256 = {
    "bridge_real_eval_1.png": "1d25ac179f7cdace1de14d5dab9496d52099231ea3e3d60eb3fe422c9802b611",
    "bridge_sink.png": "86b50fa15ede8e2c28cc01b6adffc40b79f7136130547c6ee905cf91b4aff188",
    "google_coke_can_real_eval_1.png": "4218cc93e73c97fb4c275ec1c015fc51ae5c4d5d0c3ea9018bef31d0b71a87ba",
    "google_move_near_real_eval_1.png": "c9bf9ace717a1895d1e0f2af2c4c5b0a2c8c030717cd1f44380074f640e06bd3",
    "open_drawer_a0.png": "a98b68b0a6b097af38b463e7b30371ec30eb15391f62fe9f03f16b97a0f6359b",
    "open_drawer_a1.png": "fef25cffac02dd31898514fee63d2b0b9e763448f657da4a1be007f5fd4cf5d0",
    "open_drawer_a2.png": "75aeff00694ed2e4c9c299fc7a20bed1b3b7d6f863b28dc5964ea1931ea7069b",
    "open_drawer_b0.png": "6665d9e3b2185c615994a5bdd435e2004c0374ebb1aa9480b7392c1dcc5277a5",
    "open_drawer_b1.png": "5a106aa95d35a9ea5b0c3ae21e9aaea6496855494ab6c8d07dd25181615ad599",
    "open_drawer_b2.png": "7b2eb39e654224fa5e8201eaa2614f76e72baa3881a0242b61c84e903d65ab48",
    "open_drawer_c0.png": "3bb62bf601598467c3a9cc515abcc9b43a37bd1b2296b431420b5806367b04a9",
    "open_drawer_c1.png": "72746163c07514e6dda4e4145961f619be0439814917b913a035295bf65bd7be",
    "open_drawer_c2.png": "84b9eb5ac8a8eb8faa1866f8761af318f89e876c9b4d6632d47ead4c6854db9e",
}


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
        row = self.benchmark.reference_rows_by_id.get(self.episode.id)  # only `max` matrix episodes
        reference = None if row is None else row["native"]
        provenance = {
            "simpler_env": _revision(simpler_root, SIMPLER_REVISION),
            "mani_skill2_real2sim": _revision(native_root, MANISKILL_REVISION),
            "task": self.episode.task,
            **self.benchmark.budget_metadata(),
            "track": self.benchmark.descriptor.protocol_version,
        }
        if row is not None:  # recorded before the overlay check can fail
            provenance["reference_episode"] = copy.deepcopy(
                {key: row[key] for key in ("matrix", "variant", "episode_index", "upstream_script")})
        if self.artifact_dir is not None:
            atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)

        renderer_kwargs = {"offscreen_only": True, "device": self.benchmark.device}
        if reference is None:
            env_id, native_kwargs = simpler_env.ENVIRONMENT_MAP[self.episode.task]
            # Upstream make mutates ENVIRONMENT_MAP and has tuple obs_mode; use the
            # same registry and a fresh kwargs copy with the documented string mode.
            kwargs = copy.deepcopy(native_kwargs)
            kwargs.update(obs_mode="rgbd", prepackaged_config=True, renderer_kwargs=renderer_kwargs)
        else:
            env_id, kwargs = self._reference_kwargs(simpler_root, reference, renderer_kwargs, provenance)
        if gym.spec(env_id).max_episode_steps != self.benchmark.native_horizon:
            raise CompatibilityError("native horizon differs from the pinned task catalog")
        # Override the TimeLimit at construction, never ignore a truncation or
        # mutate the scorer. This is a predeclared, separately named track.
        if reference is None:
            self.env = gym.make(env_id, max_episode_steps=self.benchmark.evaluation_horizon, **kwargs)
        else:
            from simpler_env.utils.env.env_builder import build_maniskill2_env

            self.env = build_maniskill2_env(env_id, max_episode_steps=self.benchmark.evaluation_horizon, **kwargs)
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
        if reference is None:
            raw, _private_reset_info = self.env.reset(seed=self.episode.seed)
        else:  # upstream passes no seed; a fresh env draws its fixed construction-time episode seed
            raw, _private_reset_info = self.env.reset(options=self._reference_reset_options(reference))
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

    @staticmethod
    def _reference_kwargs(simpler_root: Path, reference: Mapping[str, Any], renderer_kwargs: dict[str, Any],
                          provenance: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Environment kwargs as `run_maniskill2_eval_single_episode` passes them to the env builder."""
        overlay = reference["rgb_overlay_path"]
        if overlay is not None:
            path = simpler_root / overlay  # script paths are relative to the SimplerEnv root
            if not path.is_file():
                raise CompatibilityError(f"missing pinned real overlay {overlay}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            pinned = OVERLAY_SHA256.get(path.name)
            if pinned is not None and digest != pinned:
                raise CompatibilityError(f"real overlay {overlay} differs from the pinned bytes")
            provenance["rgb_overlay"] = {"path": overlay, "sha256": digest, "pinned": pinned is not None}
            overlay = str(path)
        kwargs = {
            **reference["env_build_kwargs"], "obs_mode": "rgbd", "robot": reference["robot"],
            "sim_freq": reference["sim_freq"], "control_mode": reference["control_mode"],
            "control_freq": reference["control_freq"], "scene_name": reference["scene_name"],
            "camera_cfgs": {"add_segmentation": True},  # upstream default; segmentation never reaches the policy
            "rgb_overlay_path": overlay, "renderer_kwargs": renderer_kwargs,
        }
        provenance["reference_build_kwargs"] = {
            key: value for key, value in kwargs.items() if key not in ("rgb_overlay_path", "renderer_kwargs")}
        return reference["env_id"], kwargs

    @staticmethod
    def _reference_reset_options(reference: Mapping[str, Any]) -> dict[str, Any]:
        """Robot and object reset options exactly as the upstream evaluator builds them."""
        import numpy as np
        from sapien.core import Pose
        from transforms3d.euler import euler2quat

        quat = (Pose(q=euler2quat(*reference["robot_init_rpy"]))
                * Pose(q=reference["robot_init_rot_quat_center"])).q
        options: dict[str, Any] = {"robot_init_options": {
            "init_xy": np.array(reference["robot_init_xy"]), "init_rot_quat": quat}}
        if reference["obj_init_xy"] is not None:
            options["obj_init_options"] = {"init_xy": np.array(reference["obj_init_xy"])}
        else:
            options["obj_init_options"] = {"episode_id": reference["obj_episode_id"]}
        return options

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


EVALUATION_MODES = ("fast", "max", "example")  # fast: blog subset; max: one pinned matrix; example: first fast episode
FAST_RESETS = 5  # seeded resets per task, episode seeds launch seed + 0..4


class SimplerEnvBenchmarkAdapter:
    """One robot/task cell; simulator dependencies are imported only on reset."""

    def __init__(self, task: str = "widowx_spoon_on_towel", *,
                 proprioception: bool = False, device: str = "cuda:0",
                 horizon_multiplier: int = 1,
                 action_rejection_feedback: bool = False,
                 interaction_mode: str = "single_response",
                 expected_gpu_uuid: str | None = None,
                 evaluation_mode: str = "fast",
                 reference_matrix: str | None = None) -> None:
        if evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"evaluation_mode must be one of {', '.join(EVALUATION_MODES)}; got {evaluation_mode!r}")
        if task not in TASK_HORIZONS:
            raise ValueError(f"unsupported SimplerEnv task {task!r}; choose one of {list(TASK_HORIZONS)}")
        if not isinstance(proprioception, bool):
            raise TypeError("proprioception must be boolean")
        if type(action_rejection_feedback) is not bool:
            raise TypeError("action_rejection_feedback must be boolean")
        if not isinstance(interaction_mode, str) or interaction_mode not in ("single_response", "agent_method"):
            raise ValueError("interaction_mode must be single_response or agent_method")
        if type(horizon_multiplier) is not int or horizon_multiplier not in (1, 2):
            raise ValueError("horizon_multiplier must be 1 (native) or 2 (extended)")
        if reference_matrix is not None and evaluation_mode != "max":
            raise ValueError("reference_matrix applies only to evaluation_mode max")
        if evaluation_mode == "max":  # one matrix per service run, as upstream runs one script
            reference_matrix = max_matrix.VISUAL_MATCHING if reference_matrix is None else reference_matrix
            available = max_matrix.available_matrices(task)
            if reference_matrix not in available:
                raise ValueError(f"reference_matrix for {task} must be one of {', '.join(available)}; "
                                 f"got {reference_matrix!r}")
        self.task = task
        self.evaluation_mode = evaluation_mode
        self.reference_matrix = reference_matrix
        self.reference_rows = (max_matrix.reference_matrix(task, reference_matrix)
                               if evaluation_mode == "max" else [])
        self.reference_rows_by_id = {row["id"]: row for row in self.reference_rows}
        if any(row["native"]["max_episode_steps"] != TASK_HORIZONS[task] for row in self.reference_rows):
            raise CompatibilityError("reference matrix horizon differs from the pinned task catalog")
        self.episode_count = (len(self.reference_rows) if evaluation_mode == "max"
                              else 1 if evaluation_mode == "example" else FAST_RESETS)
        self.proprioception = proprioception
        self.action_rejection_feedback = action_rejection_feedback
        self.interaction_mode = interaction_mode
        self.device = device
        if expected_gpu_uuid is not None:
            from benchmarks.simBenchmarks.SimplerEnv.environment.render_device import validate_gpu_uuid

            validate_gpu_uuid(expected_gpu_uuid)
        self.expected_gpu_uuid = expected_gpu_uuid
        self.native_horizon = TASK_HORIZONS[task]
        self.horizon_multiplier = horizon_multiplier
        self.environment_step_cap = self.evaluation_horizon = self.native_horizon * horizon_multiplier
        budget_track = "-extended-2x" if horizon_multiplier == 2 else ""  # budget joins the selection segment
        selection = ("reference-" + reference_matrix.replace("_", "-")  # reference-visual-matching, ...
                     if evaluation_mode == "max" else "prepackaged-seeded")
        google = task.startswith("google_robot_")
        self.camera = "overhead_camera" if google else "3rd_view_camera"
        self.descriptor = BenchmarkDescriptor(
            name="simpler_env", version="0.0.1",
            protocol_version=f"simpler-env-{SIMPLER_REVISION[:7]}/{selection}{budget_track}/"
            + ("rgb-qpos" if proprioception else "rgb") + ("-action-feedback" if action_rejection_feedback else "")
            + ("-agent-method" if interaction_mode == "agent_method" else "") + f"/{evaluation_mode}/v1",
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
            "environment_step_cap": self.environment_step_cap,
            "native_horizon": self.native_horizon,
            "native_horizon_source": "pinned_gym_registration",
            "evaluation_horizon": self.evaluation_horizon, "horizon_multiplier": self.horizon_multiplier,
        }

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError("episode limit must be a positive integer or None")
        count = self.episode_count if limit is None else min(limit, self.episode_count)
        if self.evaluation_mode == "max":
            return [EpisodeSpec(
                id=row["id"], task=self.task, seed=seed + index,  # seed is recorded only; native reset is seedless
                instruction="Follow the current instruction in the camera observation.",
                metadata={**self.budget_metadata(), "evaluation_mode": "max", "selection": "reference_matrix",
                          "matrix": row["matrix"], "matrix_tag": max_matrix.MATRIX_TAGS[row["matrix"]],
                          "variant": copy.deepcopy(row["variant"]), "episode_index": row["episode_index"],
                          "upstream_script": row["upstream_script"], "native_reset": "seedless_upstream_options",
                          "native": copy.deepcopy(row["native"])},  # copies; the adapter's rows stay private
            ) for index, row in enumerate(self.reference_rows[:count])]
        return [EpisodeSpec(
            id=f"{self.task}-{index:06d}", task=self.task, seed=seed + index,
            instruction="Follow the current instruction in the camera observation.",
            metadata={**self.budget_metadata(), "evaluation_mode": self.evaluation_mode,
                      "selection": "prepackaged_seeded_reset"},
        ) for index in range(count)]

    def open_episode(self, episode: EpisodeSpec) -> SimplerEnvEpisode:
        if episode.task != self.task:
            raise ProtocolError("episode task does not match adapter task")
        if self.evaluation_mode == "max" and episode.id not in self.reference_rows_by_id:
            raise ProtocolError(f"episode {episode.id!r} is not in the selected {self.reference_matrix} matrix")
        return SimplerEnvEpisode(self, episode)


def make_simpler_env(parameters: Mapping[str, JsonValue]) -> SimplerEnvBenchmarkAdapter:
    unknown = set(parameters) - {"task", "proprioception", "device", "horizon_multiplier",
                                 "action_rejection_feedback", "interaction_mode", "expected_gpu_uuid",
                                 "evaluation_mode", "reference_matrix"}
    if unknown:
        raise ValueError(f"unknown SimplerEnv parameters: {sorted(unknown)}")
    return SimplerEnvBenchmarkAdapter(**parameters)
