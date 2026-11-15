"""One selected R2R episode in Habitat 0.3.3; no model or task-solving helper.

All metrics, scene identifiers, goals and provenance are evaluator-private.
The parent adapter must project only the RGB frame and instruction to its actor.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

HORIZON = 500
SUCCESS_DISTANCE = 3.0
VIDEO_FPS = 10  # Presentation speed only, never a native control frequency.
ACTION_NAMES = ("stop", "move_forward", "turn_left", "turn_right")
# Decompressed bound for one split or GT JSON, shared with the service adapter;
# it caps memory in both processes against an oversized or hostile gzip file.
MAX_DATASET_BYTES = 64 * 1024 * 1024


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_file(path, expected=None):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("native_input_not_file")
    digest = file_digest(path)
    if expected is not None and digest != expected:
        raise ValueError("native_input_hash_changed")
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def scene_path(scenes_dir, scene_id):
    """Map an R2R scene ID under the declared root, as Habitat's R2R loader does.

    Shared by the service adapter and this runtime so both accept the same IDs.
    """
    if not isinstance(scene_id, str):
        raise ValueError("invalid_scene_path")
    prefix = "data/scene_datasets/"
    if scene_id.startswith(prefix):
        scene_id = scene_id[len(prefix):]
    relative = Path(scene_id)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".glb":
        raise ValueError("invalid_scene_path")
    # Contain the dataset-controlled path lexically: symlinks inside the
    # operator-owned scene root (e.g. a linked mp3d/ tree) remain usable.
    return Path(scenes_dir).resolve(strict=True) / relative


def load_selected_episode(dataset_path, scenes_dir, episode_id, expected_sha256=None):
    """Read the declared complete split and select exactly the requested ID."""
    source = checked_file(dataset_path, expected_sha256)
    with gzip.open(source["path"], "rb") as stream:
        content = stream.read(MAX_DATASET_BYTES + 1)
    if len(content) > MAX_DATASET_BYTES:
        raise ValueError("dataset_size_limit")
    document = json.loads(content)
    episodes = document.get("episodes")
    if type(episodes) is not list:
        raise ValueError("invalid_episode_inventory")
    selected = [e for e in episodes if str(e.get("episode_id")) == str(episode_id)]
    if len(selected) != 1:
        raise ValueError("episode_id_missing_or_ambiguous")
    episode = copy.deepcopy(selected[0])
    scene = scene_path(scenes_dir, episode["scene_id"])
    navmesh = scene.with_suffix(".navmesh")
    assets = {"scene": checked_file(scene), "navmesh": checked_file(navmesh)}
    episode["scene_id"] = str(scene)
    return episode, {"dataset": source, "selected_episode_id": str(episode_id),
                     "inventory_episode_count": len(episodes), "assets": assets}


def native_metrics(values, step, stopped, episode_over):
    """Normalize only native measures; never recompute task success."""
    numbers = {}
    for key in ("success", "distance_to_goal", "spl"):
        value = float(values[key])
        if not math.isfinite(value):
            raise ValueError("nonfinite_native_metric")
        numbers[key] = value
    if numbers["success"] not in (0.0, 1.0):
        raise ValueError("invalid_native_success")
    numbers["success"] = bool(numbers["success"])
    numbers.update(native_steps=step, native_horizon=HORIZON,
                   native_stop_called=stopped, native_episode_over=episode_over,
                   success_distance=SUCCESS_DISTANCE)
    return numbers


class NativeRuntime:
    """Lazy single-reset lifecycle. Failed execution is never replayable."""

    def __init__(self, config):
        if type(config) is not dict:
            raise ValueError("invalid_runtime_config")
        for name in ("dataset_path", "scenes_dir", "artifact_dir", "episode_id"):
            if not isinstance(config.get(name), str) or not config[name]:
                raise ValueError("missing_runtime_parameter")
        for name in ("seed", "gpu_id"):
            if type(config.get(name)) is not int or config[name] < 0:
                raise ValueError("invalid_runtime_integer")
        self.config = dict(config)
        self.artifact_dir = Path(config["artifact_dir"]).resolve(strict=True)
        if not self.artifact_dir.is_dir():
            raise ValueError("artifact_directory_required")
        self.env = None
        self.writer = None
        self.frame_log = None
        self.steps = 0
        self.stopped = False
        self.done = False
        self.reset_attempted = False
        self.failed = False
        self.execution_in_flight = False
        self.cached_metrics = None
        self.closed = False
        self.finish_result = None
        self.finish_error = False

    def _progress(self):
        # Evaluator-only evidence survives a failed camera/metric conversion.
        value = dict(native_steps=self.steps, execution_in_flight=self.execution_in_flight,
                     reset_attempted=self.reset_attempted, failed=self.failed)
        (self.artifact_dir / "native_progress.json").write_text(json.dumps(value) + "\n")

    def _initialize(self):
        import habitat
        import habitat_sim
        from habitat.config import read_write
        from habitat.core.dataset import Dataset
        from habitat.tasks.nav.nav import NavigationGoal
        from habitat.tasks.vln.vln import InstructionData, VLNEpisode
        from omegaconf import OmegaConf

        if habitat.__version__ != "0.3.3" or habitat_sim.__version__ != "0.3.3":
            raise ValueError("habitat_version_mismatch")
        episode, provenance = load_selected_episode(
            self.config["dataset_path"], self.config["scenes_dir"], self.config["episode_id"],
            self.config.get("expected_dataset_sha256"))
        if self.config.get("gt_path"):
            provenance["gt_source"] = checked_file(self.config["gt_path"], self.config.get("expected_gt_sha256"))
        episode["episode_id"] = str(episode["episode_id"])
        episode["instruction"] = InstructionData(**episode["instruction"])
        episode["goals"] = [NavigationGoal(**goal) for goal in episode["goals"]]
        dataset = Dataset()
        dataset.episodes = [VLNEpisode(**episode)]
        cfg = habitat.get_config("benchmark/nav/vln_r2r.yaml")
        with read_write(cfg):
            h = cfg.habitat
            h.seed = self.config["seed"]
            h.environment.max_episode_steps = HORIZON
            h.environment.max_episode_seconds = 0
            h.environment.iterator_options.shuffle = False
            h.environment.iterator_options.cycle = False
            h.simulator.forward_step_size = 0.25
            h.simulator.turn_angle = 15
            h.simulator.habitat_sim_v0.allow_sliding = True
            h.simulator.habitat_sim_v0.gpu_device_id = self.config["gpu_id"]
            rgb = h.simulator.agents.main_agent.sim_sensors.rgb_sensor
            rgb.width = 512
            rgb.height = 512
            rgb.hfov = 90
            h.task.measurements.success.success_distance = SUCCESS_DISTANCE
            h.task.measurements.distance_to_goal.distance_to = "POINT"
            h.dataset.scenes_dir = self.config["scenes_dir"]
            h.dataset.data_path = self.config["dataset_path"]
        h = cfg.habitat
        # Reject unexpected native configuration rather than inheriting sensors,
        # actions or measurements from another local task integration.
        if (h.task.type != "VLN-v0" or tuple(h.task.actions) != ACTION_NAMES
                or set(h.task.lab_sensors) != {"instruction_sensor"}
                or set(h.task.measurements) != {"distance_to_goal", "success", "spl"}
                or set(h.simulator.agents.main_agent.sim_sensors) != {"rgb_sensor", "depth_sensor"}):
            raise ValueError("unexpected_native_task_configuration")
        source_root = Path(habitat.__file__).resolve().parent
        relative_sources = ("core/env.py", "core/embodied_task.py", "core/dataset.py",
                            "tasks/nav/nav.py", "tasks/vln/vln.py",
                            "config/default.py", "config/default_structured_configs.py",
                            "config/benchmark/nav/vln_r2r.yaml", "config/habitat/task/vln_r2r.yaml")
        provenance.update(schema_version="starvla-rsi.vln_ce.habitat033-native-provenance/v1",
            process_id=os.getpid(),
            python_executable=sys.executable, python_version=sys.version,
            package_versions={name: importlib.metadata.version(name) for name in
                              ("habitat-sim", "habitat-lab", "numpy", "omegaconf")},
            package_origins={"habitat": str(source_root), "habitat_sim": habitat_sim.__file__},
            key_source_files={name: checked_file(source_root / name) for name in relative_sources},
            effective_config=OmegaConf.to_container(cfg, resolve=True),
            seed=self.config["seed"], video_fps=VIDEO_FPS,
            video_mapping="initial_frame_then_one_per_control", native_control_hz=None,
            limitations="Installed package files and versions; not old Habitat 0.1.7 parity or full asset attestation.")
        with (self.artifact_dir / "native_provenance.json").open("x") as stream:
            json.dump(provenance, stream, indent=2, allow_nan=False)
        # Retain the partially constructed object for cleanup if __init__ raises.
        self.env = habitat.Env.__new__(habitat.Env)
        habitat.Env.__init__(self.env, config=cfg, dataset=dataset)
        self.env.seed(self.config["seed"])

    def _observe(self, observation):
        import numpy as np
        from PIL import Image
        import imageio.v2 as imageio

        rgb = np.asarray(observation["rgb"])
        if rgb.shape != (512, 512, 3) or rgb.dtype != np.uint8:
            raise ValueError("invalid_native_rgb")
        instruction = observation["instruction"]["text"]
        if not isinstance(instruction, str) or not instruction:
            raise ValueError("invalid_native_instruction")
        filename = "rgb-%06d.png" % self.steps
        path = self.artifact_dir / filename
        with path.open("xb") as stream:
            Image.fromarray(rgb).save(stream, format="PNG")
        if self.writer is None:
            if (self.artifact_dir / "rgb.mp4").exists():
                raise ValueError("video_already_exists")
            self.writer = imageio.get_writer(str(self.artifact_dir / "rgb.mp4"), fps=VIDEO_FPS,
                                            codec="libx264", macro_block_size=1)
        self.writer.append_data(rgb)
        if self.frame_log is None:
            self.frame_log = (self.artifact_dir / "frames.jsonl").open("x")
        self.frame_log.write(json.dumps(dict(camera="rgb", path=filename, step=self.steps,
            instruction=instruction, sha256=file_digest(path))) + "\n")
        self.frame_log.flush()
        return dict(step=self.steps, instruction=instruction, frame=filename,
                    metrics=dict(self.cached_metrics))

    def reset(self):
        if self.reset_attempted or self.closed:
            raise RuntimeError("reset_not_repeatable")
        self.reset_attempted = True
        try:
            self._initialize()
            observation = self.env.reset()
            self.cached_metrics = native_metrics(self.env.get_metrics(), 0, False, False)
            result = self._observe(observation)
            self._progress()
            return result
        except Exception:
            self.failed = True
            self._progress()
            raise

    def step(self, action):
        if type(action) is not int or action not in range(len(ACTION_NAMES)):
            raise ValueError("invalid_native_action")
        if not self.reset_attempted or self.cached_metrics is None or self.closed or self.failed or self.done:
            raise RuntimeError("native_session_not_actionable")
        self.execution_in_flight = True
        self._progress()
        try:
            observation = self.env.step(ACTION_NAMES[action])
            self.steps += 1
            self.execution_in_flight = False
            self.stopped = action == 0
            self.done = bool(self.env.episode_over)
            self._progress()
            if self.done != (self.stopped or self.steps >= HORIZON):
                raise RuntimeError("unexpected_native_termination")
            self.cached_metrics = native_metrics(self.env.get_metrics(), self.steps, self.stopped, self.done)
            result = self._observe(observation)
            result.update(terminated=self.stopped, truncated=self.done and not self.stopped, reward=0.0)
            return result
        except Exception:
            self.failed = True
            self._progress()
            raise

    def metrics(self):
        if self.cached_metrics is None:
            raise RuntimeError("native_metrics_unavailable")
        return {**self.cached_metrics, "native_steps": self.steps,
                "metrics_at_native_step": self.cached_metrics["native_steps"],
                "execution_in_flight": self.execution_in_flight, "native_error": self.failed}

    def finish(self):
        if self.closed:
            if self.finish_error:
                raise RuntimeError("native_cleanup_failed")
            return self.finish_result
        errors = []
        for resource in (self.writer, self.frame_log):
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    errors.append(type(exc).__name__)
        if self.env is not None and getattr(self.env, "_sim", None) is not None:
            try:
                self.env.close()
            except Exception as exc:
                errors.append(type(exc).__name__)
        self.closed = True
        try:
            self._progress()
        except Exception as exc:
            errors.append(type(exc).__name__)
        artifacts = {key: filename for key, filename in
                     (("video", "rgb.mp4"), ("frames", "frames.jsonl"),
                      ("native_provenance", "native_provenance.json"))
                     if (self.artifact_dir / filename).is_file()}
        self.finish_result = {"metrics": self.metrics() if self.cached_metrics is not None else None,
                              "artifacts": artifacts}
        self.finish_error = bool(errors)
        if errors:
            raise RuntimeError("native_cleanup_failed")
        return self.finish_result
