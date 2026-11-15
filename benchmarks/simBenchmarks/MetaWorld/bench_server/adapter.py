"""MetaWorld MT50 RGB-only direct control, with a package-pinned native server."""
from __future__ import annotations

import hashlib
import json
import math
import pickle
from numbers import Real
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import (ActionSpec, BenchmarkDescriptor, EpisodeSpec, JsonValue,
                               Observation, ObservationSpec, Transition)
from benchkit.errors import CompatibilityError, ProtocolError
from benchmarks.simBenchmarks.MetaWorld.environment.runtime import (
    PACKAGE_INVENTORY_SHA256, verify_runtime,
)

CAMERA = "corner2"
IMAGE_SHAPE = (480, 480, 3)
NATIVE_HORIZON = 500
SETTLE_STEPS = 1
# The retained stabilization action consumes one step of the native horizon.
# Advertise only the remaining model-selected controls, never 500 plus setup.
CONTROL_CAP = NATIVE_HORIZON - SETTLE_STEPS
CONTROL_HZ = 80.0  # Five native physics ticks, each 0.0025 seconds.
EVALUATION_MODES = ("fast", "max", "example")  # fast: blog subset; max: MT50 50x50; example: first fast episode
FAST_TRIALS = 5  # trials per task; trial k seed = launch seed + k
MAX_GOALS = 50  # native MT50 goal pool size per task; max runs each goal once (metaworld._N_GOALS)
MAX_GOAL_POOL_SEED = 4042  # max mode's fixed metaworld.MT50(seed=...) pool; also its launch seed
IMAGE_TRANSFORMS = {"native": "none; RGB copy", "rot180": "180-degree full-frame rotation; RGB copy"}


def task_catalog() -> tuple[dict, ...]:
    payload = json.loads(Path(__file__).with_name("protocol").joinpath("task_catalog.json").read_text(encoding="utf-8"))
    rows = payload.get("tasks", [])
    if (payload.get("schema_version") != "starvla-rsi.metaworld.task-catalog/v1"
            or payload.get("native_version") != "3.1.1" or len(rows) != 50
            or [r.get("native_id") for r in rows] != list(range(50))
            or len({r.get("name") for r in rows}) != 50):
        raise CompatibilityError("MetaWorld task catalog identity/order differs")
    return tuple(rows)


def policy_observation(frame: Any, step: int, instruction: str,
                       image_orientation: str = "rot180") -> Observation:
    import numpy as np
    if not isinstance(image_orientation, str) or image_orientation not in IMAGE_TRANSFORMS:
        raise ProtocolError("MetaWorld image_orientation must be native or rot180")
    if not isinstance(frame, np.ndarray) or frame.shape != IMAGE_SHAPE or frame.dtype != np.uint8:
        raise ProtocolError("MetaWorld corner2 must be a 480x480 uint8 RGB frame")
    if image_orientation == "rot180":
        frame = frame[::-1, ::-1, :]
    # No native 39-D state, goal coordinates, object poses, rewards or info.
    return Observation(step=step, instruction=instruction,
                       images={CAMERA: np.array(frame, copy=True, order="C")})


def _mt50_task_pool(seed: int, catalog: Sequence[dict]):
    """Native MT50 goal pools for all 50 classes; pure task data, safe to reuse per seed."""
    import metaworld
    names = tuple(row["name"] for row in catalog)
    if tuple(metaworld.ALL_V3_ENVIRONMENTS) != names:
        raise CompatibilityError("installed native MT50 task ordering differs")
    # Never replace this with task-specific (MT1) goal sampling: each class's
    # goals depend on the shared seeded stream consumed by the classes before it.
    pool = metaworld.MT50(seed=seed)  # Seeds, then restores, global NumPy itself.
    if tuple(pool.train_classes) != names or len(pool.train_tasks) != 50 * MAX_GOALS:
        raise CompatibilityError("native MT50 task pool differs from 50 classes x 50 goals")
    return pool


def _class_goals(pool, native_id: int) -> list:
    """The selected class's 50 pool goals, filtered exactly as make_vec MT50 passes them."""
    name = tuple(pool.train_classes)[native_id]
    goals = [task for task in pool.train_tasks if task.env_name == name]
    if len(goals) != MAX_GOALS or goals != pool.train_tasks[native_id * MAX_GOALS:(native_id + 1) * MAX_GOALS]:
        raise CompatibilityError("native MT50 goal pool is not 50 contiguous goals per class")
    return goals


def _pin_goal(env, task) -> None:
    """Max mode: set one pool goal natively and stop the wrapper from resampling it at reset."""
    import gymnasium
    from metaworld.wrappers import RandomTaskSelectWrapper
    selectors, layer = [], env
    while isinstance(layer, gymnasium.Wrapper):  # find the native selector under CheckpointWrapper
        if isinstance(layer, RandomTaskSelectWrapper):
            selectors.append(layer)
        layer = layer.env
    if len(selectors) != 1:
        raise CompatibilityError("expected exactly one native RandomTaskSelectWrapper")
    selectors[0].toggle_sample_tasks_on_reset(False)
    if selectors[0].sample_tasks_on_reset is not False:
        raise CompatibilityError("native goal resampling on reset could not be disabled")
    env.unwrapped.set_task(task)  # native: freezes this goal's rand_vec for every later reset


def _create_native(seed: int, native_id: int, pool):
    import metaworld
    import numpy as np
    np.random.seed(seed)  # Same global NumPy state the native MT50 vector leaves at reset.
    _name, env_cls = tuple(pool.train_classes.items())[native_id]
    # Exactly the call gym.make_vec("Meta-World/MT50", ...) makes for sub-env
    # native_id; the other 49 sub-envs never touch this env's state or RNG.
    return metaworld._init_each_env(
        env_cls=env_cls, tasks=_class_goals(pool, native_id),
        seed=seed, env_id=native_id, num_tasks=50, use_one_hot=False,
        render_mode="rgb_array", camera_name=CAMERA, width=480, height=480)


def _native_success(info: Any) -> bool:
    if not isinstance(info, Mapping) or "success" not in info:
        raise ProtocolError("native MetaWorld step omitted its success field")
    # Native NumPy scalar values are supported, but malformed/non-finite values
    # must not be coerced to True or silently treated as a failure.
    value = info["success"]
    if not isinstance(value, Real):
        raise ProtocolError("native MetaWorld success must be a numeric 0 or 1")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("native MetaWorld success must be 0 or 1") from exc
    if not math.isfinite(number) or number not in (0.0, 1.0):
        raise ProtocolError("native MetaWorld success must be 0 or 1")
    return number == 1.0


class MetaWorldEpisode:
    def __init__(self, benchmark: MetaWorldBenchmarkAdapter, episode: EpisodeSpec):
        self.benchmark, self.episode = benchmark, episode
        self.env = None
        self.artifact_dir: Path | None = None
        self.writer = None
        self.step_count = 0
        self.settle_count = 0
        self.success = False
        self.finished = False
        self.reset_attempted = False
        self.closed = False
        self.finalized = False
        self.last_reward: float | None = None
        self.close_error: BaseException | None = None

    def bind_artifact_dir(self, path: Path) -> None:
        if self.artifact_dir is not None or self.reset_attempted:
            raise ProtocolError("MetaWorld artifacts must be bound exactly once before reset")
        path.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = path

    def _log(self, event: str, **values) -> None:
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_events.jsonl", {"event": event, **values})

    def reset(self) -> Observation:
        if self.reset_attempted or self.closed or self.finalized:
            raise ProtocolError("a MetaWorld episode permits exactly one reset attempt")
        self.reset_attempted = True
        try:
            provenance = self.benchmark.native_runtime()
            self._log("native_construction_start", seed=self.episode.seed)
            pool = self.benchmark.task_pool(self.episode.seed)
            self.env = _create_native(self.episode.seed, self.episode.metadata["native_id"], pool)
            import numpy as np
            low, high = self.env.action_space.low, self.env.action_space.high
            base = self.env.unwrapped
            if (not np.array_equal(low, np.full(4, -1.0))
                    or not np.array_equal(high, np.full(4, 1.0))
                    or base.frame_skip != 5 or base.action_scale != 0.01
                    or base.max_path_length != NATIVE_HORIZON
                    or not math.isclose(float(base.model.opt.timestep), 0.0025, rel_tol=0, abs_tol=1e-12)):
                raise CompatibilityError("native MetaWorld controller or horizon differs")
            # The retained evaluator optionally calls this method, but neither
            # wrapper nor base exposes it in the pinned 3.1.1 wheel. Fail on
            # drift instead of silently introducing a different goal schedule.
            if any(callable(getattr(obj, "iterate_goal_position", None)) for obj in (self.env, base)):
                raise CompatibilityError("unexpected goal iteration method in the pinned MetaWorld runtime")
            goal_index = self.episode.metadata.get("goal_index")  # max mode only
            if goal_index is None:
                goal_selection = {"reset_goal_selection": "native RandomTaskSelectWrapper before base.reset(seed)"}
            else:
                goal = _class_goals(pool, self.episode.metadata["native_id"])[goal_index]
                _pin_goal(self.env, goal)
                goal_selection = {"reset_goal_selection": "native set_task(pool goal) with wrapper resampling disabled",
                                  "goal_index": goal_index, "goal_pool_seed": self.episode.seed,
                                  "mt50_train_task_index": self.episode.metadata["mt50_train_task_index"]}
            provenance.update({"task": self.episode.task, "native_id": self.episode.metadata["native_id"],
                               "reset_seed": self.episode.seed, "native_goal_pool_per_task": MAX_GOALS,
                               "goal_iteration_method": None, **goal_selection,
                               "construction": "native MT50 task pool (once per seed) + native _init_each_env "
                                               "for the selected class, as gym.make_vec MT50 builds it",
                               "camera": CAMERA, "shape": list(IMAGE_SHAPE),
                               "image_orientation": self.benchmark.image_orientation,
                               "image_transform": IMAGE_TRANSFORMS[self.benchmark.image_orientation],
                               "native_horizon": NATIVE_HORIZON, "policy_control_cap": CONTROL_CAP,
                               "settle_steps": SETTLE_STEPS, "control_hz": CONTROL_HZ,
                               "physics_ticks_per_control": 5,
                               "protocol_version": self.benchmark.descriptor.protocol_version})
            if self.artifact_dir is not None:
                atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
            self._log("reset_start")
            self.env.reset(seed=self.episode.seed)
            self._log("reset_end")
            if goal_index is not None:
                rand_vec = np.asarray(pickle.loads(goal.data)["rand_vec"])  # trusted native pool data
                if not base._freeze_rand_vec or not np.array_equal(base._last_rand_vec, rand_vec):
                    raise CompatibilityError("native reset did not keep the pinned MT50 goal")
                self._log("goal_pinned", goal_index=goal_index,
                          rand_vec_sha256=hashlib.sha256(rand_vec.tobytes()).hexdigest())
            self._log("settle_start", action=[0.0, 0.0, 0.0, 0.0])
            _raw, _reward, terminated, truncated, info = self.env.step(np.zeros(4, dtype=np.float32))
            self.settle_count = 1
            settle_success = _native_success(info)
            self._log("settle_end", native_success=settle_success)
            if settle_success or terminated or truncated:
                raise ProtocolError("native task ended during initialization before any policy decision")
            return self._observe()
        except BaseException:
            try:
                self.close()
            except Exception as cleanup_error:
                self._log("reset_cleanup_error", error_type=type(cleanup_error).__name__)
            raise

    def _observe(self) -> Observation:
        observation = policy_observation(self.env.render(), self.step_count, self.episode.instruction,
                                         self.benchmark.image_orientation)
        if self.artifact_dir is not None:
            from PIL import Image
            import imageio.v2 as imageio
            frame = observation.images[CAMERA]
            path = self.artifact_dir / f"{CAMERA}-{self.step_count:06d}.png"
            Image.fromarray(frame).save(path)
            if self.writer is None:
                self.writer = imageio.get_writer(str(self.artifact_dir / f"{CAMERA}.mp4"),
                                                fps=CONTROL_HZ, codec="libx264", macro_block_size=1)
            self.writer.append_data(frame)
            append_jsonl(self.artifact_dir / "frames.jsonl", {
                "camera": CAMERA, "step": self.step_count, "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.env is None or self.closed or self.finished or self.finalized:
            raise ProtocolError("cannot step an uninitialized or finished MetaWorld episode")
        action = self.benchmark.action_spec.validate(action)
        import numpy as np
        self._log("action_start", control=self.step_count + 1, action=list(action))
        try:
            _raw, reward, terminated, truncated, private_info = self.env.step(np.asarray(action, dtype=np.float32))
            self.step_count += 1
            self.success = _native_success(private_info)
            self.last_reward = float(reward)
            if not math.isfinite(self.last_reward):
                raise ProtocolError("native reward must be finite")
            terminated = bool(terminated) or self.success
            truncated = bool(truncated) or (self.step_count >= CONTROL_CAP and not terminated)
            self.finished = terminated or truncated
            self._log("action_end", control=self.step_count, success=self.success,
                      reward=self.last_reward, terminated=terminated, truncated=truncated)
            return Transition(observation=self._observe(), reward=self.last_reward,
                              terminated=terminated, truncated=truncated,
                              info={"native_success": self.success, "native_steps": self.step_count})
        except BaseException:
            self.finished = True  # No replay after a native control or render error.
            raise

    def metrics(self) -> Mapping[str, JsonValue]:
        return {"success": self.success, "native_steps": self.step_count,
                "settle_steps": self.settle_count, "native_steps_including_settle": self.step_count + self.settle_count,
                "policy_physics_ticks": self.step_count * 5,
                "native_horizon": NATIVE_HORIZON, "policy_control_cap": CONTROL_CAP,
                "last_native_reward": self.last_reward}

    def _close_writer(self) -> None:
        writer, self.writer = self.writer, None
        if writer is not None:
            writer.close()

    def artifacts(self) -> Mapping[str, str]:
        self.finalized = True
        self._close_writer()
        if self.artifact_dir is None:
            return {}
        return {key: str(self.artifact_dir / name) for key, name in {
            "corner2_video": "corner2.mp4", "frames": "frames.jsonl",
            "native_provenance": "native_provenance.json", "native_events": "native_events.jsonl",
        }.items() if (self.artifact_dir / name).is_file()}

    def close(self) -> None:
        if self.closed:
            if self.close_error is not None:
                raise ProtocolError("previous native MetaWorld close failed") from self.close_error
            return
        self.closed = True
        errors = []
        try:
            self._close_writer()
        except BaseException as exc:
            errors.append(exc)
        env, self.env = self.env, None
        if env is not None:
            try:
                env.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            self.close_error = errors[0]
            raise ProtocolError("native MetaWorld cleanup failed") from errors[0]


class MetaWorldBenchmarkAdapter:
    # Publish the same cap enforced by MetaWorldEpisode.step, without resetting
    # or importing the native environment during service description.
    environment_step_cap = CONTROL_CAP

    def __init__(self, evaluation_mode: str = "fast", image_orientation: str = "rot180"):
        if evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"evaluation_mode must be one of {', '.join(EVALUATION_MODES)}; got {evaluation_mode!r}")
        self.evaluation_mode = evaluation_mode
        if not isinstance(image_orientation, str) or image_orientation not in IMAGE_TRANSFORMS:
            raise ValueError("MetaWorld image_orientation must be native or rot180")
        self.image_orientation = image_orientation
        self.catalog = task_catalog()
        self.claims: set[str] = set()
        self._runtime: dict | None = None  # Package verification, filled at the first reset.
        self._task_pools: dict[int, Any] = {}  # seed -> native MT50 goal pools (pure data).

    def native_runtime(self) -> dict:
        """Verify the pinned native package once per process; later resets reuse the record."""
        if self._runtime is None:
            self._runtime = verify_runtime()
        return dict(self._runtime)

    def task_pool(self, seed: int):
        if seed not in self._task_pools:
            self._task_pools[seed] = _mt50_task_pool(seed, self.catalog)
        return self._task_pools[seed]

    @property
    def descriptor(self) -> BenchmarkDescriptor:
        camera = "corner2" if self.image_orientation == "native" else "corner2-rot180"
        protocol = f"metaworld-3.1.1/mt50-native500/rgb480-{camera}/{self.evaluation_mode}/v1"
        return BenchmarkDescriptor(name="metaworld", version="MT50-3.1.1", protocol_version=protocol,
                                   source_revision=f"metaworld==3.1.1;inventory-sha256:{PACKAGE_INVENTORY_SHA256}")

    @property
    def observation_spec(self) -> ObservationSpec:
        return ObservationSpec(cameras=(CAMERA,), modalities=("language", "rgb"), privileged=False)

    @property
    def action_spec(self) -> ActionSpec:
        return ActionSpec(mode="metaworld_mocap_delta_xyz_gripper", size=4,
                          names=("delta_x", "delta_y", "delta_z", "gripper_effort"),
                          low=(-1.0,) * 4, high=(1.0,) * 4, control_hz=CONTROL_HZ,
                          frame="native world XYZ; mocap delta = 0.01 m per normalized unit, clipped to workspace",
                          rotation="fixed native mocap quaternion [1,0,1,0]; no rotation command",
                          gripper="native paired actuator efforts [g,-g]; positive closes, negative opens")

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - FAST_TRIALS:
            raise ValueError(f"MetaWorld seed must be an integer in [0, 2**32 - {FAST_TRIALS}]")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ValueError("episode limit must be a positive integer")
        if self.evaluation_mode == "max":
            if seed != MAX_GOAL_POOL_SEED:
                raise ValueError(f"MetaWorld max uses the fixed MT50 goal pool; launch with seed {MAX_GOAL_POOL_SEED}")
            # Task-major like fast: all 50 goals of task 0, then task 1, and so on.
            episodes = tuple(EpisodeSpec(id=f"{row['name']}-seed{seed}-goal{g:02d}", task=row["name"], seed=seed,
                                         instruction=row["instruction"], metadata={"native_id": row["native_id"],
                                         "bucket": row["bucket"], "evaluation_mode": self.evaluation_mode,
                                         "goal_index": g, "goal_pool_seed": seed,
                                         "mt50_train_task_index": row["native_id"] * MAX_GOALS + g,
                                         "native_horizon": NATIVE_HORIZON, "policy_control_cap": CONTROL_CAP,
                                         "environment_step_cap": CONTROL_CAP, "settle_steps": SETTLE_STEPS,
                                         "image_orientation": self.image_orientation})
                             for row in self.catalog for g in range(MAX_GOALS))
            return episodes[:limit]
        trials = 1 if self.evaluation_mode == "example" else FAST_TRIALS
        rows = self.catalog[:1] if self.evaluation_mode == "example" else self.catalog
        episodes = tuple(EpisodeSpec(id=f"{row['name']}-seed{seed + k}-episode{k:03d}", task=row["name"], seed=seed + k,
                                     instruction=row["instruction"], metadata={"native_id": row["native_id"],
                                     "bucket": row["bucket"], "evaluation_mode": self.evaluation_mode, "episode_index": k,
                                     "native_horizon": NATIVE_HORIZON, "policy_control_cap": CONTROL_CAP,
                                     "environment_step_cap": CONTROL_CAP, "settle_steps": SETTLE_STEPS,
                                     "image_orientation": self.image_orientation})
                         for row in rows for k in range(trials))
        return episodes[:limit]

    def open_episode(self, episode: EpisodeSpec) -> MetaWorldEpisode:
        trial = episode.metadata.get("episode_index", 0)  # fast trial k runs with launch seed + k
        try:
            scheduled = episode in self.episodes(episode.seed - trial)
        except (TypeError, ValueError):
            scheduled = False
        if not scheduled:
            raise ProtocolError("MetaWorld episode differs from its predeclared schedule")
        if episode.id in self.claims:
            raise ProtocolError("MetaWorld episode already claimed; retries are not permitted")
        self.claims.add(episode.id)
        return MetaWorldEpisode(self, episode)


def make_metaworld(parameters: Mapping[str, JsonValue]) -> MetaWorldBenchmarkAdapter:
    allowed = {"evaluation_mode", "image_orientation"}
    if set(parameters) - allowed:
        raise ValueError(f"unknown MetaWorld parameters: {sorted(set(parameters) - allowed)}")
    return MetaWorldBenchmarkAdapter(**parameters)
