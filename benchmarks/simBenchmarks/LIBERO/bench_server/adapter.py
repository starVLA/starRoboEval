"""Benchmark-owned LIBERO service adapter and private native session."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import (
    ActionSpec,
    BenchmarkDescriptor,
    EpisodeSpec,
    JsonValue,
    Observation,
    ObservationSpec,
    Transition,
)
from benchkit.errors import CompatibilityError, ProtocolError
from benchkit.registry import register_benchmark

LIBERO_REVISION = "8f1084e3132a39270c3a13ebe37270a43ece2a01"
FIRST_PASS_SEED = 20260907
# Historical public name retained for compatibility. This is the retained
# StarVLA LIBERO-10 evaluator reference, not a universal official LIBERO limit.
NATIVE_HORIZON = 520
SETTLE_STEPS = 10
CAMERAS = ("agentview", "robot0_eye_in_hand")
TASK_NAMES = (
    "LIVING_ROOM_SCENE2_put_both_the_alphabet_soup_and_the_tomato_sauce_in_the_basket",
    "LIVING_ROOM_SCENE2_put_both_the_cream_cheese_box_and_the_butter_in_the_basket",
    "KITCHEN_SCENE3_turn_on_the_stove_and_put_the_moka_pot_on_it",
    "KITCHEN_SCENE4_put_the_black_bowl_in_the_bottom_drawer_of_the_cabinet_and_close_it",
    "LIVING_ROOM_SCENE5_put_the_white_mug_on_the_left_plate_and_put_the_yellow_and_white_mug_on_the_right_plate",
)
INSTRUCTIONS = (
    "put both the alphabet soup and the tomato sauce in the basket",
    "put both the cream cheese box and the butter in the basket",
    "turn on the stove and put the moka pot on it",
    "put the black bowl in the bottom drawer of the cabinet and close it",
    "put the white mug on the left plate and put the yellow and white mug on the right plate",
)


def task_catalog() -> dict[str, dict[str, Any]]:
    """Load the packaged native task identities without importing a simulator."""
    path = resources.files("benchmarks.simBenchmarks.LIBERO.bench_server.protocol").joinpath("libero_catalog.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("schema_version") != "starvla-rsi.libero-task-catalog/v1"
            or payload.get("upstream_revision") != LIBERO_REVISION):
        raise CompatibilityError("LIBERO catalog schema or source revision differs")
    expected_counts = {"libero_spatial": 10, "libero_object": 10, "libero_goal": 10,
                       "libero_90": 90, "libero_10": 10}
    rows = payload["suites"]
    result = {row["suite"]: row for row in rows}
    if len(rows) != 5 or set(result) != set(expected_counts):
        raise CompatibilityError("LIBERO catalog must contain the five frozen suites")
    for name, count in expected_counts.items():
        row = result[name]
        if (row["task_count"] != count or row["task_order_index"] != 0
                or len(row["tasks"]) != count
                or [task["native_id"] for task in row["tasks"]] != list(range(count))):
            raise CompatibilityError(f"LIBERO catalog task count/order differs for {name}")
    if (tuple(row["native_name"] for row in result["libero_10"]["tasks"][:5]) != TASK_NAMES
            or tuple(row["instruction"] for row in result["libero_10"]["tasks"][:5]) != INSTRUCTIONS):
        raise CompatibilityError("LIBERO catalog differs from historical first-five identities")
    return result


def policy_observation(
    raw: Mapping[str, Any], step: int, instruction: str, proprioception: bool = False,
) -> Observation:
    """Copy only the two fixed RGB views and optionally robot joint encoders."""
    import numpy as np

    images: dict[str, Any] = {}
    for camera in CAMERAS:
        if f"{camera}_image" not in raw:
            raise ProtocolError(f"native observation omitted {camera}")
        frame = np.asarray(raw[f"{camera}_image"])
        if frame.dtype != np.uint8 or frame.shape != (256, 256, 3):
            raise ProtocolError(f"{camera} must be a 256x256 uint8 RGB image")
        # Fixed retained-LIBERO orientation transform, shared by every policy.
        images[camera] = np.ascontiguousarray(frame[::-1, ::-1]).copy()
    state = None
    if proprioception:
        if "robot0_joint_pos" not in raw or "robot0_gripper_qpos" not in raw:
            raise ProtocolError("native observation omitted declared robot joint encoders")
        arm = np.asarray(raw["robot0_joint_pos"])
        gripper = np.asarray(raw["robot0_gripper_qpos"])
        if arm.shape != (7,) or gripper.shape != (2,):
            raise ProtocolError("LIBERO qpos track requires 7 arm and 2 gripper positions")
        values = np.concatenate((arm, gripper))
        if not np.isfinite(values).all():
            raise ProtocolError("robot joint encoders must be finite")
        state = tuple(float(value) for value in values)
    # No object-state, EEF/object true poses, reward, success, reset seed, camera
    # calibration, simulator state or other native fields cross this boundary.
    return Observation(step=step, instruction=instruction, images=images, state=state)


def _source_root() -> Path:
    package = importlib.util.find_spec("libero")
    if package is None or not package.submodule_search_locations:
        raise CompatibilityError(
            "LIBERO namespace is not importable: add the pinned source root to PYTHONPATH; "
            "this is required even after its editable install (see the LIBERO README)"
        )
    root = Path(next(iter(package.submodule_search_locations))).resolve().parent
    git_env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        top_level = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"], check=True,
            capture_output=True, text=True, timeout=20, env=git_env,
        ).stdout.strip()
        if Path(top_level).resolve() != root:
            raise CompatibilityError("LIBERO source must have its own Git checkout, not inherit a parent")
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True, timeout=20, env=git_env,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            check=True, capture_output=True, text=True, timeout=60, env=git_env,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompatibilityError("cannot verify the installed LIBERO source checkout") from exc
    if revision != LIBERO_REVISION or dirty:
        raise CompatibilityError(f"LIBERO must be a clean checkout at {LIBERO_REVISION}")
    for package_name, expected in (
        ("robosuite", "1.4.0"), ("mujoco", "3.2.3"), ("numpy", "1.24.4"), ("torch", "2.5.1+cpu"),
    ):
        if importlib.metadata.version(package_name) != expected:
            raise CompatibilityError(f"this LIBERO track requires {package_name}=={expected}")
    config_dir = os.environ.get("LIBERO_CONFIG_PATH")
    if not config_dir or not (Path(config_dir) / "config.yaml").is_file():
        raise CompatibilityError(
            "set LIBERO_CONFIG_PATH to the configured environment directory before importing LIBERO"
        )
    return root


class LiberoEpisode:
    """Private native environment, reset-state loader and native success scorer."""

    def __init__(self, benchmark: LiberoBenchmarkAdapter, episode: EpisodeSpec) -> None:
        self.benchmark = benchmark
        self.episode = episode
        self.env: Any = None
        self.artifact_dir: Path | None = None
        self.writers: dict[str, Any] = {}
        self.step_count = 0
        self.success = False
        self.finished = False

    def bind_artifact_dir(self, path: Path) -> None:
        self.artifact_dir = path
        path.mkdir(parents=True, exist_ok=True)

    def reset(self) -> Observation:
        root = _source_root()
        import numpy as np
        import robosuite
        from libero.libero import benchmark as native_benchmark
        from libero.libero import get_libero_path
        from libero.libero.envs import OffScreenRenderEnv

        for key, suffix in (("bddl_files", "bddl_files"), ("init_states", "init_files"), ("assets", "assets")):
            if Path(get_libero_path(key)).resolve() != root / "libero" / "libero" / suffix:
                raise CompatibilityError(f"LIBERO {key} path is outside the pinned source checkout")
        suite_name = self.benchmark.suite
        suite = native_benchmark.get_benchmark_dict()[suite_name](task_order_index=0)
        task_id = int(self.episode.metadata["task_id"])
        task = suite.get_task(task_id)
        frozen = self.benchmark.suite_catalog["tasks"][task_id]
        if (suite.n_tasks != self.benchmark.suite_catalog["task_count"]
                or task.name != frozen["native_name"] or task.language != frozen["instruction"]):
            raise CompatibilityError("native LIBERO task identity/order differs from the frozen catalog")
        bddl = Path(suite.get_task_bddl_file_path(task_id))
        if hashlib.sha256(bddl.read_bytes()).hexdigest() != frozen["bddl_sha256"]:
            raise CompatibilityError("native task BDDL hash differs from the frozen catalog")
        initial_file = Path(get_libero_path("init_states")) / task.problem_folder / task.init_states_file
        initial_states = suite.get_task_init_states(task_id)
        if len(initial_states) != frozen["released_initial_state_count"]:
            raise CompatibilityError("pinned LIBERO task initial-state count differs from the catalog")
        controller = robosuite.load_controller_config(default_controller="OSC_POSE")
        if (
            controller["input_min"] != -1 or controller["input_max"] != 1
            or controller["output_max"] != [0.05, 0.05, 0.05, 0.5, 0.5, 0.5]
            or controller["output_min"] != [-0.05, -0.05, -0.05, -0.5, -0.5, -0.5]
            or controller["control_delta"] is not True
        ):
            raise CompatibilityError("native OSC_POSE action scaling differs from the declared contract")
        provenance = {
            "upstream_revision": LIBERO_REVISION,
            "suite": suite_name, "selection_scope": self.benchmark.scope,
            "task_order_index": 0, "task_id": task_id,
            "task_name": task.name, "initial_state_index": 0,
            "available_initial_states": len(initial_states), "reset_seed": self.episode.seed,
            "bddl_sha256": hashlib.sha256(bddl.read_bytes()).hexdigest(),
            "initial_states_file_sha256": hashlib.sha256(initial_file.read_bytes()).hexdigest(),
            "selected_state_sha256": hashlib.sha256(np.asarray(initial_states[0]).tobytes()).hexdigest(),
            **self.benchmark.budget_metadata(), "settle_steps": SETTLE_STEPS,
            "native_engine_horizon": self.benchmark.native_engine_horizon,
            "image_transform": "native_rgb[::-1,::-1], contiguous copy; no resize or crop",
            "controller": controller,
            "versions": {name: importlib.metadata.version(name) for name in (
                "libero", "robosuite", "mujoco", "numpy", "torch", "imageio", "imageio-ffmpeg",
            )},
        }
        if self.artifact_dir is not None:
            atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
        np.random.seed(self.episode.seed)
        self.env = OffScreenRenderEnv(
            bddl_file_name=str(bddl), camera_heights=256, camera_widths=256,
            camera_names=list(CAMERAS), camera_depths=False, camera_segmentations=None,
            render_gpu_device_id=self.benchmark.render_gpu_device_id,
            # Keep native observable construction intact: this pin crashes when
            # use_object_obs=False. policy_observation drops all object fields.
            control_freq=20, horizon=self.benchmark.native_engine_horizon,
        )
        low, high = self.env.env.action_spec
        if not np.array_equal(low, np.full(7, -1.0)) or not np.array_equal(high, np.full(7, 1.0)):
            raise CompatibilityError("native LIBERO action bounds must be seven dimensions in [-1, 1]")
        self.env.seed(self.episode.seed)
        self.env.reset()
        raw = self.env.set_init_state(initial_states[0])
        for _ in range(SETTLE_STEPS):
            raw, _reward, native_success, _info = self.env.step([0.0] * 6 + [-1.0])
            if native_success:
                raise ProtocolError("task succeeded during initialization before any policy decision")
        self.step_count = 0
        self.success = False
        self.finished = False
        return self._observe(raw)

    def _observe(self, raw: Mapping[str, Any]) -> Observation:
        observation = policy_observation(
            raw, self.step_count, self.episode.instruction, self.benchmark.proprioception,
        )
        if self.artifact_dir is not None:
            import imageio.v2 as imageio
            from PIL import Image

            for camera, rgb in observation.images.items():
                path = self.artifact_dir / f"{camera}-{self.step_count:06d}.png"
                Image.fromarray(rgb).save(path)
                if camera not in self.writers:
                    self.writers[camera] = imageio.get_writer(
                        str(self.artifact_dir / f"{camera}.mp4"), fps=20, codec="libx264", macro_block_size=1,
                    )
                self.writers[camera].append_data(rgb)
                append_jsonl(self.artifact_dir / "frames.jsonl", {
                    "step": self.step_count, "camera": camera, "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.env is None or self.finished:
            raise ProtocolError("cannot step an uninitialized or finished LIBERO episode")
        action = self.benchmark.action_spec.validate(action)
        raw, reward, done, _private_info = self.env.step(list(action))
        self.step_count += 1
        # Pinned BDDLBaseDomain.step assigns done = self._check_success(). Never
        # call that predicate again or infer success from generated model text.
        self.success = bool(done)
        truncated = self.step_count >= self.benchmark.environment_step_cap and not self.success
        self.finished = self.success or truncated
        return Transition(
            observation=self._observe(raw), reward=float(reward), terminated=self.success, truncated=truncated,
            info={"native_success": self.success, "native_steps": self.step_count},
        )

    def metrics(self) -> Mapping[str, JsonValue]:
        return {"success": self.success, "native_steps": self.step_count, "settle_steps": SETTLE_STEPS,
                **self.benchmark.budget_metadata()}

    def _close_writers(self) -> None:
        for writer in self.writers.values():
            writer.close()
        self.writers.clear()

    def artifacts(self) -> Mapping[str, str]:
        self._close_writers()
        if self.artifact_dir is None:
            return {}
        files = {camera + "_video": camera + ".mp4" for camera in CAMERAS}
        files.update(frames="frames.jsonl", native_provenance="native_provenance.json")
        return {key: str(self.artifact_dir / name) for key, name in files.items()
                if (self.artifact_dir / name).exists()}

    def close(self) -> None:
        try:
            self._close_writers()
        finally:
            if self.env is not None:
                self.env.close()
                self.env = None


class LiberoBenchmarkAdapter:
    """One fixed initial state per selected task; no sampling or success retries."""

    def __init__(
        self, task_ids: Sequence[int] | None = None, *,
        suite: str = "libero_10", scope: str = "development",
        proprioception: bool = False, render_gpu_device_id: int = 0,
        budget_mode: str = "horizon", max_policy_calls: int | None = None,
        replan_interval: int | None = None,
    ) -> None:
        catalog = task_catalog()
        if not isinstance(suite, str) or suite not in catalog:
            raise ValueError("suite must be one of the five packaged LIBERO suites")
        if scope not in ("development", "task_coverage"):
            raise ValueError("scope must be development or task_coverage")
        if scope == "development" and suite != "libero_10":
            raise ValueError("historical development scope only supports libero_10; select task_coverage explicitly")
        self.suite, self.scope = suite, scope
        self.suite_catalog = catalog[suite]
        count = 5 if scope == "development" else self.suite_catalog["task_count"]
        if task_ids is None:
            task_ids = (0, 1) if scope == "development" else tuple(range(count))
        if (
            not isinstance(task_ids, (list, tuple)) or not task_ids
            or any(type(index) is not int or index not in range(count) for index in task_ids)
            or len(set(task_ids)) != len(task_ids)
            or list(task_ids) != sorted(task_ids)
        ):
            raise ValueError(f"task_ids must be a unique, increasing subset of native indices 0..{count - 1}")
        if not isinstance(proprioception, bool):
            raise TypeError("proprioception must be boolean")
        if type(render_gpu_device_id) is not int or render_gpu_device_id < 0:
            raise ValueError("render_gpu_device_id must be a nonnegative integer")
        if budget_mode not in ("horizon", "decisions"):
            raise ValueError("budget_mode must be horizon or decisions")
        if budget_mode == "decisions":
            if any(type(value) is not int or value <= 0 for value in (max_policy_calls, replan_interval)):
                raise ValueError("decision budgets require positive integer max_policy_calls and replan_interval")
        elif max_policy_calls is not None or replan_interval is not None:
            raise ValueError("adapter decision limits require budget_mode=decisions; use runner limits for horizon mode")
        self.task_ids = tuple(task_ids)
        self.proprioception = proprioception
        self.render_gpu_device_id = render_gpu_device_id
        self.native_horizon = self.suite_catalog["reference_horizon"]
        self.budget_mode = budget_mode
        self.max_policy_calls = max_policy_calls
        self.replan_interval = replan_interval
        self.environment_step_cap = (max_policy_calls * replan_interval
                                     if budget_mode == "decisions" else self.native_horizon)
        self.evaluation_horizon = self.environment_step_cap
        # Fixed initialization steps are not policy decisions. Keep the engine
        # horizon clear of the complete predeclared action budget as well.
        self.native_engine_horizon = max(1000, self.environment_step_cap + SETTLE_STEPS)
        selection = "first2" if set(self.task_ids) <= {0, 1} else "first5"
        protocol = (f"libero10-{selection}-development" if scope == "development"
                    else f"libero-task-coverage/{suite}")
        budget_track = f"/decision-{max_policy_calls}-prefix-{replan_interval}" if budget_mode == "decisions" else ""
        self.descriptor = BenchmarkDescriptor(
            name="libero", version="0.1.0" if scope == "development" else "0.2.0",
            protocol_version=protocol + "/" + ("rgb-qpos" if proprioception else "rgb")
            + budget_track + "/v1",
            source_revision=LIBERO_REVISION,
        )
        self.observation_spec = ObservationSpec(
            cameras=CAMERAS,
            state_names=(tuple(f"arm_qpos_{index}" for index in range(7))
                         + ("gripper_qpos_0", "gripper_qpos_1")) if proprioception else (),
            modalities=("language", "rgb", "joint_position") if proprioception else ("language", "rgb"),
        )
        self.action_spec = ActionSpec(
            mode="normalized_osc_delta_pose", size=7,
            names=("dx_scaled", "dy_scaled", "dz_scaled", "rx_scaled", "ry_scaled", "rz_scaled", "gripper"),
            low=(-1.0,) * 7, high=(1.0,) * 7, control_hz=20.0,
            frame="world: translation component 1 means +0.05 m",
            rotation="world axis-angle delta: rotation component 1 means +0.5 rad",
            gripper="-1 open; +1 close; 0 hold native gripper target",
        )

    def budget_metadata(self) -> dict[str, JsonValue]:
        return {
            "budget_mode": self.budget_mode,
            "max_policy_calls": self.max_policy_calls, "replan_interval": self.replan_interval,
            "environment_step_cap": self.environment_step_cap,
            "native_horizon": self.native_horizon,
            "native_horizon_source": ("retained_starvla_libero10_evaluator_reference" if self.suite == "libero_10"
                                      else f"retained_starvla_{self.suite}_evaluator_reference"),
            "evaluation_horizon": self.evaluation_horizon,
        }

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or seed != FIRST_PASS_SEED:
            raise ValueError(f"frozen LIBERO selection requires seed={FIRST_PASS_SEED}")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= len(self.task_ids)):
            raise ValueError("episode limit must select a nonempty prefix without repeating any task")
        return [EpisodeSpec(
            id=f"{('libero10' if self.scope == 'development' else self.suite)}-task{task_id:02d}-init00",
            task=f"{self.suite}/task-{task_id}",
            seed=seed, instruction=self.suite_catalog["tasks"][task_id]["instruction"],
            metadata={"suite": self.suite, "task_id": task_id,
                      "task_name": self.suite_catalog["tasks"][task_id]["native_name"],
                      "task_order_index": 0, "initial_state_index": 0, "attempt": 1,
                      **self.budget_metadata(), "settle_steps": SETTLE_STEPS},
        ) for task_id in self.task_ids[:limit]]

    def open_episode(self, episode: EpisodeSpec) -> LiberoEpisode:
        if episode not in self.episodes(FIRST_PASS_SEED):
            raise ProtocolError("episode differs from the frozen LIBERO selection")
        return LiberoEpisode(self, episode)


@register_benchmark("libero")
def make_libero(parameters: Mapping[str, JsonValue]) -> LiberoBenchmarkAdapter:
    unknown = set(parameters) - {"task_ids", "suite", "scope", "proprioception", "render_gpu_device_id",
                                 "budget_mode", "max_policy_calls", "replan_interval"}
    if unknown:
        raise ValueError(f"unknown LIBERO parameters: {sorted(unknown)}")
    return LiberoBenchmarkAdapter(**parameters)
