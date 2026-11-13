"""SIMPLE declared-sensor humanoid tracks with a private native WBC worker.

No simulator, torch, WBC training package, or native task module is imported here.
The 36D public action is physical joint/nav targets, NOT a 7D arm delta action.
"""

from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.contracts import (
    ActionSpec, BenchmarkDescriptor, EpisodeSpec, Observation, ObservationSpec, Transition,
)
from benchkit.errors import CompatibilityError, ProtocolError
from benchmarks.simBenchmarks.SIMPLE.bench_server.native_worker_client import NativeWorkerClient

SIMPLE_REVISION = "5e3d6f84e85343e34e9bca8d157f0d7813231185"
TRACK = "simple-native-wbc-development-v1"
SEED = 20260907
TASKS = ("G1WholebodyBendPickMP-v0", "G1WholebodyOpenFaucetTeleop-v0")
INSTRUCTIONS = ("bend to pick up the cracker box", "move forward to the faucet and open it")
INVENTORY_PATH = Path(__file__).with_name("protocol") / "simple_released_tasks.json"
TASK_INVENTORY = json.loads(INVENTORY_PATH.read_text())
INVENTORY_SHA256 = hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest()
TASK_CONFIGS = {row["task_id"]: row for row in TASK_INVENTORY["tasks"]}
FULL_TASKS = tuple(TASK_CONFIGS)
HORIZONS = {task: row["reference_native_horizon"] for task, row in TASK_CONFIGS.items()}


def execution_budget(native_horizon: int, budget_mode: str = "horizon",
    max_policy_calls: int | None = None, replan_interval: int | None = None,
) -> tuple[int, int | None, int | None]:
    """Resolve execution limits without assigning a method's decision cadence.

    The explicit decisions track retains its original 200-by-5 definition.
    Native-horizon services do not advertise or accept method call/prefix caps.
    """
    if type(native_horizon) is not int or native_horizon <= 0:
        raise ValueError("native_horizon must be a positive integer")
    if budget_mode == "horizon":
        if max_policy_calls is not None or replan_interval is not None:
            raise ValueError("horizon mode has no server call/prefix limits; configure these in the agent")
        return native_horizon, None, None
    if budget_mode != "decisions":
        raise ValueError("budget_mode must be horizon or decisions")
    calls = 200 if max_policy_calls is None else max_policy_calls
    prefix = 5 if replan_interval is None else replan_interval
    if type(calls) is not int or calls != 200 or type(prefix) is not int or prefix != 5:
        raise ValueError("the explicit decisions track requires 200 policy calls and prefix cap 5")
    return 1000, calls, prefix


def deployment_path(value: str | Path, name: str, *, resolve_symlinks: bool = True) -> Path:
    """Require operator-selected absolute paths, without opening native assets."""
    if (not isinstance(value, (str, Path)) or not str(value)
            or not Path(value).is_absolute() or ".." in Path(value).parts):
        raise ValueError(f"{name} must be an absolute path without '..'")
    return Path(value).resolve() if resolve_symlinks else Path(value)


def task_config(task: str, task_scope: str = "pilot") -> Mapping[str, Any]:
    """Select an explicit frozen scope without expanding legacy pilot defaults."""
    if task_scope not in ("pilot", "released-12"):
        raise ValueError("task_scope must be pilot or released-12")
    if not isinstance(task, str) or task not in (TASKS if task_scope == "pilot" else FULL_TASKS):
        raise ValueError(f"task outside the frozen SIMPLE {task_scope} scope")
    config = TASK_CONFIGS[task]
    if config["backend_gate"] or config["backend"] not in ("amo", "sonic"):
        raise CompatibilityError(f"unsupported native SIMPLE backend: {config['backend_gate']}")
    return config
ARM_SUFFIXES = (
    "shoulder_pitch_joint", "shoulder_roll_joint", "shoulder_yaw_joint", "elbow_joint",
    "wrist_roll_joint", "wrist_pitch_joint", "wrist_yaw_joint",
)
# These names explicitly preserve the aligned PSI0 codec's legacy left hand order.
LEFT_HAND = tuple("left_hand_" + name + "_joint" for name in (
    "thumb_0", "thumb_1", "thumb_2", "middle_0", "middle_1", "index_0", "index_1",
))
RIGHT_HAND = tuple("right_hand_" + name + "_joint" for name in (
    "thumb_0", "thumb_1", "thumb_2", "index_0", "index_1", "middle_0", "middle_1",
))
ACTION_NAMES = (
    *LEFT_HAND, *RIGHT_HAND,
    *("left_" + name for name in ARM_SUFFIXES),
    *("right_" + name for name in ARM_SUFFIXES),
    "waist_roll_joint", "waist_pitch_joint", "waist_yaw_joint",
    "base_height_m", "forward_velocity_m_s", "lateral_velocity_m_s",
    "native_turn_command", "target_yaw_rad",
)
ACTION_SPEC = ActionSpec(
    mode="simple_physical_joint_nav_36", size=36, names=ACTION_NAMES,
    control_hz=50.0, frame="native G1 joint coordinates; native controller navigation frame",
    rotation="joint radians; waist roll,pitch,yaw; heading radians",
    gripper="14 individual dexterous hand joint position targets (radians)",
)


def task_contract(task: str, *, task_scope: str = "pilot", proprioception: bool = True,
    budget_mode: str = "horizon", max_policy_calls: int | None = None,
    replan_interval: int | None = None,
) -> tuple[BenchmarkDescriptor, EpisodeSpec, ActionSpec, ObservationSpec]:
    """Describe a pinned task without installation paths or native construction."""
    config = task_config(task, task_scope)
    if type(proprioception) is not bool:
        raise ValueError("proprioception must be an explicit boolean")
    if task_scope == "released-12" and not proprioception:
        raise ValueError("released-12 requires RGB+qpos31")
    cap, _, _ = execution_budget(HORIZONS[task], budget_mode, max_policy_calls, replan_interval)
    backend = config["backend"]
    names = list(ACTION_NAMES)
    names[34] = "turning_flag" if backend == "amo" else "turning_gate"
    action_spec = ActionSpec(mode=f"simple_{backend}_physical_joint_nav_36", size=36,
        names=tuple(names), control_hz=50.0, frame=ACTION_SPEC.frame,
        rotation=ACTION_SPEC.rotation, gripper=ACTION_SPEC.gripper)
    observation_spec = ObservationSpec(cameras=("head_stereo_left",),
        state_names=ACTION_NAMES[:31] if proprioception else (),
        modalities=("rgb", "language", "proprioception") if proprioception else ("rgb", "language"))
    modality = "rgb-qpos31" if proprioception else "rgb"
    budget = "decision-200-prefix-5" if budget_mode == "decisions" else f"native-horizon-{HORIZONS[task]}"
    version = "v2" if budget_mode == "decisions" else "v3"
    prefix = "simple" if task_scope == "pilot" else "simple/released-12"
    descriptor = BenchmarkDescriptor("simple_humanoid", "5e3d6f8-patched-native",
        f"{prefix}/{backend}/{modality}/{budget}/{version}", SIMPLE_REVISION)
    episode = EpisodeSpec(id=f"{task}/dr0/ep0", task=task, seed=SEED,
        instruction=config["instruction"], metadata={"dr_level": 0, "episode_index": 0,
            "reference_native_horizon": HORIZONS[task], "environment_step_cap": cap,
            "budget_mode": budget_mode, "track": descriptor.protocol_version,
            **({"task_scope": task_scope, "task_inventory_sha256": INVENTORY_SHA256,
                "native_task_uid": config["task_uid"], "native_backend": backend,
                "reset_metadata_sha256": config["reset_metadata_sha256"],
                "environment_config_sha256": config["environment_config_sha256"]}
                if task_scope == "released-12" else {})})
    return descriptor, episode, action_spec, observation_spec


def decode_action(values: Sequence[float]) -> dict[str, Any]:
    """Extract only physical commands; no normalization or learned statistics."""
    vector = ACTION_SPEC.validate(values)
    return {
        "joint_positions": dict(zip(ACTION_NAMES[:31], vector[:31])),
        "base_height": vector[31], "navigate_cmd": (vector[32], vector[33], vector[34], vector[35]),
    }


def amo_payload(values: Sequence[float], stabilized_torso_ypr: Sequence[float]) -> dict[str, Any]:
    """Aligned MP mapping: waist targets must NOT replace AMO torso orientation."""
    command = decode_action(values)
    torso = tuple(float(value) for value in stabilized_torso_ypr)
    if len(torso) != 3 or not all(math.isfinite(value) for value in torso):
        raise ProtocolError("native stabilized AMO torso must be finite YPR")
    joints = command["joint_positions"]
    vx, vy, yaw_rate, target_yaw = command["navigate_cmd"]
    return {
        "target_qpos": {name: value for name, value in joints.items() if not name.startswith("waist_")},
        "waist_qpos": {name: value for name, value in joints.items() if name.startswith("waist_")},
        "action_command": [vx, target_yaw, vy, command["base_height"] - 0.75, *torso, yaw_rate],
    }


def public_observation(raw: Mapping[str, Any], step: int, instruction: str,
    proprioception: bool = False) -> Observation:
    """RGB and optional named robot encoders; no task state, scores or native info."""
    import numpy as np

    if "head_stereo_left" not in raw:
        raise ProtocolError("native observation omitted head_stereo_left")
    frame = np.asarray(raw["head_stereo_left"])
    if frame.dtype != np.uint8 or frame.shape != (360, 640, 3):
        raise ProtocolError("head_stereo_left must be native 360x640 uint8 RGB")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ProtocolError("native language instruction is missing")
    state = None
    if proprioception:
        joints = raw.get("joint_positions")
        if not isinstance(joints, Mapping) or set(joints) != set(ACTION_NAMES[:31]):
            raise ProtocolError("proprioception requires exactly the 31 declared joint encoders")
        state = tuple(float(joints[name]) for name in ACTION_NAMES[:31])
        if not all(math.isfinite(value) for value in state):
            raise ProtocolError("joint encoders must be finite")
    return Observation(step=step, instruction=instruction, images={"head_stereo_left": frame.copy()}, state=state)


def validate_tick_result(message: Mapping[str, Any], expected_steps: int) -> tuple[bool, bool, bool, float]:
    """Fail closed on malformed worker fields; do not coerce RPC truthiness."""
    for name in ("success", "terminated", "truncated"):
        if type(message.get(name)) is not bool:
            raise ProtocolError(f"native RPC {name} must be a JSON boolean")
    reward = message.get("reward")
    if isinstance(reward, bool) or not isinstance(reward, Real) or not math.isfinite(float(reward)):
        raise ProtocolError("native RPC reward must be a finite real number")
    if type(message.get("native_steps")) is not int or message["native_steps"] != expected_steps:
        raise ProtocolError("native RPC step counter differs from the requested single tick")
    return message["success"], message["terminated"], message["truncated"], float(reward)


class SimpleHumanoidEpisode(NativeWorkerClient):
    def __init__(self, benchmark: SimpleHumanoidBenchmarkAdapter, episode: EpisodeSpec) -> None:
        super().__init__(benchmark, episode)
        self.steps = 0
        self.success = False
        self.finished = False
        self.return_sum = 0.0

    def _observation(self, message: Mapping[str, Any]) -> Observation:
        import numpy as np
        from PIL import Image

        assert self.artifact_dir is not None
        frame = (self.artifact_dir / str(message["frame"])).resolve()
        if not frame.is_relative_to(self.artifact_dir):
            raise ProtocolError("worker image path escaped this episode artifact directory")
        with Image.open(frame) as image:
            raw = {"head_stereo_left": np.asarray(image).copy()}
        if self.benchmark.proprioception:
            raw["joint_positions"] = message["joint_positions"]
        return public_observation(raw, self.steps, str(message["instruction"]), self.benchmark.proprioception)

    def reset(self) -> Observation:
        self._start_worker()
        source = self.benchmark.simple_root
        result = self._rpc({"op": "reset", "task": self.episode.task, "seed": self.episode.seed,
            "artifact_dir": str(self.artifact_dir), "simple_root": str(source),
            "eval_root": str(self.benchmark.eval_root), "diagnostic": self.benchmark.diagnostic,
            "budget_mode": self.benchmark.budget_mode, "environment_step_cap": self.benchmark.environment_step_cap,
            "max_policy_calls": self.benchmark.max_policy_calls, "replan_interval": self.benchmark.replan_interval,
            "proprioception": self.benchmark.proprioception, "protocol_version": self.benchmark.descriptor.protocol_version,
            "task_scope": self.benchmark.task_scope})
        if result["native_horizon"] != HORIZONS[self.episode.task]:
            raise CompatibilityError("native task horizon changed")
        self.worker_artifacts = result.get("artifacts", {})
        return self._observation(result)

    def step(self, action: Sequence[float]) -> Transition:
        if self.finished:
            raise ProtocolError("cannot step a finished SIMPLE episode")
        result = self._rpc({"op": "step", "action": self.benchmark.action_spec.validate(action)})
        success, terminated, truncated, reward = validate_tick_result(result, self.steps + 1)
        self.steps += 1
        self.success = success
        self.finished = terminated or truncated
        self.return_sum += reward
        return Transition(self._observation(result), reward, terminated, truncated,
            {"native_success": self.success, "native_steps": self.steps})

    def diagnostic_hold(self) -> Transition:
        """Evaluator-only one-tick probe; never exposed to policy or rollout RPC."""
        if not self.benchmark.diagnostic or self.steps:
            raise ProtocolError("hold is restricted to the first diagnostic tick")
        result = self._rpc({"op": "diagnostic_hold"})
        success, terminated, truncated, reward = validate_tick_result(result, self.steps + 1)
        self.steps += 1
        self.success = success
        self.finished = terminated or truncated
        self.return_sum += reward
        return Transition(self._observation(result), reward, terminated, truncated,
            {"native_success": self.success, "native_steps": self.steps})

    def metrics(self) -> Mapping[str, Any]:
        return {"success": self.success, "native_steps": self.steps, "native_return": self.return_sum,
            "reference_native_horizon": HORIZONS[self.episode.task],
            "environment_step_cap": self.benchmark.environment_step_cap,
            "track": self.benchmark.descriptor.protocol_version,
            "diagnostic_only": self.benchmark.diagnostic}



class SimpleHumanoidBenchmarkAdapter:
    """One native task/backend per runner; expansion requires an explicit scope."""

    def __init__(self, simple_root: str, eval_root: str, gpu_id: int = 0,
        task_names: Sequence[str] = (TASKS[0],), worker_timeout: float = 900,
        diagnostic: bool = False, proprioception: bool = True, budget_mode: str = "horizon",
        max_policy_calls: int | None = None, replan_interval: int | None = None,
        task_scope: str = "pilot", python_executable: str | None = None,
        cuda_root: str | None = None) -> None:
        self.simple_root = deployment_path(simple_root, "simple_root")
        self.eval_root = deployment_path(eval_root, "eval_root")
        # Launch through a venv's symlink, not its resolved base interpreter.
        self.python_executable = (deployment_path(python_executable, "python_executable", resolve_symlinks=False)
            if python_executable is not None else self.simple_root / ".venv/bin/python")
        self.cuda_root = deployment_path(cuda_root, "cuda_root") if cuda_root is not None else None
        if type(gpu_id) is not int or gpu_id < 0:
            raise ValueError("gpu_id must be a nonnegative integer")
        if isinstance(worker_timeout, bool) or not isinstance(worker_timeout, Real) or not math.isfinite(worker_timeout) or worker_timeout <= 0:
            raise ValueError("worker_timeout must be a positive finite number")
        if type(diagnostic) is not bool:
            raise ValueError("diagnostic must be an explicit boolean")
        self.gpu_id, self.worker_timeout, self.diagnostic = gpu_id, float(worker_timeout), diagnostic
        self.task_names = tuple(task_names)
        if len(self.task_names) != 1:
            raise ValueError("choose exactly one SIMPLE task/backend per adapter/runner")
        config = task_config(self.task_names[0], task_scope)
        self.task_scope = task_scope
        if type(proprioception) is not bool:
            raise ValueError("proprioception must be an explicit boolean")
        if task_scope == "released-12" and not proprioception:
            raise ValueError("released-12 requires RGB+qpos31")
        self.proprioception, self.budget_mode = proprioception, budget_mode
        self.native_horizon = HORIZONS[self.task_names[0]]
        self.environment_step_cap, self.max_policy_calls, self.replan_interval = execution_budget(
            self.native_horizon, budget_mode, max_policy_calls, replan_interval)
        backend = config["backend"]
        self.backend = backend
        self.descriptor, self._episode, self.action_spec, self.observation_spec = task_contract(
            self.task_names[0], task_scope=task_scope, proprioception=proprioception,
            budget_mode=budget_mode, max_policy_calls=max_policy_calls, replan_interval=replan_interval)

    def episodes(self, seed: int = SEED, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or seed != SEED:
            raise ProtocolError(f"frozen SIMPLE development seed is {SEED}")
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError("episode limit must be a positive integer or None")
        episodes = (self._episode,)
        return episodes if limit is None else episodes[:limit]

    def open_episode(self, episode: EpisodeSpec) -> SimpleHumanoidEpisode:
        if episode not in self.episodes():
            raise ProtocolError("episode differs from the frozen SIMPLE task manifest")
        return SimpleHumanoidEpisode(self, episode)

    def aggregate(self, metrics: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        count = len(metrics)
        return {"episodes": count, "successes": sum(bool(item["success"]) for item in metrics),
            "success_rate": sum(bool(item["success"]) for item in metrics) / count if count else 0.0}


def make_simple_humanoid(parameters: Mapping[str, Any]) -> SimpleHumanoidBenchmarkAdapter:
    """CLI construction remains dependency-free; native imports happen at reset."""
    return SimpleHumanoidBenchmarkAdapter(**dict(parameters))
