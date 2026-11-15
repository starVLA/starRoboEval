"""RoboDojo Direct v2 sensors and EEF control behind the SIM service.

Robot-only kinematics is a fixed benchmark control conversion, not an action
proposer.  The public server exposes only ``DirectEEFBenchmarkAdapter`` with
the versioned robot-control ACK enabled.
"""
from __future__ import annotations

import hashlib
import math
from numbers import Real
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
from typing import Any, Mapping, Sequence

from benchkit.contracts import ActionSpec, BenchmarkDescriptor, EpisodeSpec, Observation, ObservationSpec, Transition, Usage
from benchkit.errors import ActionRejected, CompatibilityError, ProtocolError
from benchkit.validation import ValidationIssue, validate_action_vector
from benchmarks.simBenchmarks.RoboDojo.bench_server.native_worker_client import CAMERAS, RoboDojoEpisode, SEED, validate_tick_result
from benchmarks.simBenchmarks.RoboDojo.environment.reference_eef_runtime import load_runtime, pins
from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.robot_feedback import (
    SCHEMA as ROBOT_FEEDBACK_SCHEMA, validate_robot_feedback,
)
from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.reset_stability import load_stable_layouts
from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.task_catalog import load_catalog, task_spec

CONTROL_ALIGNMENT = "reference-eef-direct/8f3d362b"  # pinned reference DLS conversion
TARGET_QUATERNION_TOLERANCE = 1e-4
TASK = "classify_objects"
TASK_SPEC = task_spec(TASK)
NATIVE_INSTRUCTION = TASK_SPEC["native_instruction"]
INSTRUCTION = TASK_SPEC["public_instruction"]
HORIZON = TASK_SPEC["native_horizon"]
INTERFACE_PROTOCOL = load_catalog()["interface_protocol"]  # observation/action segment of the protocol ID
NATIVE_PIN = pins()["native_revision"][:7]
EVALUATION_MODES = ("fast", "max", "example")  # fast: blog subset; max: first reset-stable layouts; example: first fast episode


def selection_protocol(evaluation_mode: str) -> str:
    # pin / selected task layouts / interface / mode / version
    layouts = "reset-stable-layouts" if evaluation_mode == "max" else "fixed-layouts"  # max: manifest-selected
    return f"robodojo-{NATIVE_PIN}/{TASK.replace('_', '-')}-{layouts}/{INTERFACE_PROTOCOL}/{evaluation_mode}/v1"


def mode_layouts(evaluation_mode: str, task_id: str = TASK, *, stability_manifest: str | None = None,
                 stability_manifest_sha256: str | None = None) -> tuple[tuple[int, ...], dict[str, Any] | None]:
    """Layout IDs of one mode, plus the stability-manifest provenance for `max`.

    The adapter and the native worker both derive the mode's layouts here, so a
    reset outside them fails in either process.
    """
    if evaluation_mode not in EVALUATION_MODES:
        raise ValueError(f"evaluation_mode must be one of {', '.join(EVALUATION_MODES)}; got {evaluation_mode!r}")
    spec = task_spec(task_id)
    selection = spec["evaluation_modes"]["max" if evaluation_mode == "max" else "fast"]
    if evaluation_mode != "max":
        if stability_manifest is not None or stability_manifest_sha256 is not None:
            raise ValueError("stability_manifest belongs to evaluation_mode max only")
        layouts = tuple(selection["layout_ids"])
        return (layouts[:1] if evaluation_mode == "example" else layouts), None  # example: first fast layout
    if (not isinstance(stability_manifest, str) or not Path(stability_manifest).is_absolute()
            or ".." in Path(stability_manifest).parts
            or (stability_manifest_sha256 is not None  # optional pin; compared when supplied
                and (not isinstance(stability_manifest_sha256, str)
                     or re.fullmatch(r"[0-9a-f]{64}", stability_manifest_sha256) is None))):
        raise ValueError("RoboDojo max mode needs an absolute stability_manifest path without '..' and, "
                         "if pinned, its lowercase stability_manifest_sha256; see EVALUATION_PROTOCOL.md")
    snapshot = pins()
    return load_stable_layouts(Path(stability_manifest), stability_manifest_sha256, task=task_id,
        native_revision=snapshot["native_revision"],
        layout_inventory_sha256=snapshot["classify_layout_inventory_sha256"],
        native_eval_seed=spec["native_eval_seed"], required_stable=selection["reset_stable_count"],
        inventory_count=spec["layout_binding"]["inventory_count"])


POSE_FIELDS = ("x_m", "y_m", "z_m", "qw", "qx", "qy", "qz")
STATE_NAMES = tuple(name for side in ("left", "right")
    for name in (*(f"{side}_joint{i}_rad" for i in range(1, 7)), f"{side}_gripper_open_01")) + tuple(
    f"{side}_eef_{field}" for side in ("left", "right") for field in POSE_FIELDS)
ACTION_SPEC = ActionSpec(mode="robodojo_dual_x5_world_eef_target_16", size=16,
    names=tuple(name for side in ("left", "right") for name in (
        *(f"{side}_eef_{field}" for field in POSE_FIELDS), f"{side}_gripper_open_01")),
    control_hz=25.0, frame="world-frame measured ARX X5 link6 poses, not a gripper-tip offset",
    rotation="absolute unit quaternion wxyz for each arm",
    gripper="absolute continuous [0,1], 0 closed / 1 open; pinned native conversion")
OBSERVATION_SPEC = ObservationSpec(cameras=CAMERAS, state_names=STATE_NAMES,
    modalities=("rgb", "language", "proprioception"), privileged=False,
    control_feedback_schema=ROBOT_FEEDBACK_SCHEMA)


def validate_action(values: Sequence[float]) -> tuple[float, ...]:
    """Pure public action checks; no silent normalization or native state read.

    Per-decision motion limits/binary-gripper preferences belong to the
    model, not this benchmark.
    """
    tolerance = TARGET_QUATERNION_TOLERANCE
    vector = validate_action_vector(ACTION_SPEC, values)
    for side, offset in (("left", 0), ("right", 8)):
        norm = math.hypot(*vector[offset + 3:offset + 7])
        if not math.isfinite(norm) or abs(norm - 1.0) > tolerance:
            raise ActionRejected(ValidationIssue("quaternion_not_unit", field=f"{side}.quaternion_norm",
                actual=norm if math.isfinite(norm) else None, limit=tolerance), usage=Usage())
        if not 0 <= vector[offset + 7] <= 1:
            raise ActionRejected(ValidationIssue("out_of_bounds", field=f"{side}.opening",
                actual=vector[offset + 7], limit=0 if vector[offset + 7] < 0 else 1), usage=Usage())
    return vector


def validate_direct_tick_result(message: Mapping[str, Any], expected_targets: int, *, horizon: int = HORIZON):
    """Reuse strict native counter/reward checks, with reference timeout flags."""
    metrics = message.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ProtocolError("native RPC metrics must be an object")
    if any(type(message.get(name)) is not bool for name in ("terminated", "truncated")):
        raise ProtocolError("native RPC terminal flags must be boolean")
    if type(horizon) is not int or horizon <= 0 or type(expected_targets) is not int or not 1 <= expected_targets <= horizon:
        raise ProtocolError("reference control count is outside native horizon")
    # Check native counters against the raw end flag; the reported flags below
    # additionally split horizon timeouts into truncation.
    native_view = {**message, "terminated": metrics.get("native_end_flag"), "truncated": False}
    success, ended, _, reward = validate_tick_result(native_view, expected_targets)
    if expected_targets == horizon and not ended:
        raise ProtocolError("native horizon reached without native termination")
    truncated = bool(ended and not success and expected_targets >= horizon)
    terminated = bool(ended and not truncated)
    if message["terminated"] is not terminated or message["truncated"] is not truncated:
        raise ProtocolError("reference native terminal flags disagree")
    return success, terminated, truncated, reward


def public_state(values: Sequence[float]) -> tuple[float, ...]:
    if not isinstance(values, (tuple, list)) or len(values) != len(STATE_NAMES):
        raise ProtocolError("expected measured qpos14 and EEF14, in the declared fixed order")
    if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(float(v)) for v in values):
        raise ProtocolError("proprioception must contain finite real measurements")
    result = tuple(float(v) for v in values)
    for start in (17, 24):
        if abs(math.sqrt(sum(v * v for v in result[start:start + 4])) - 1) > 1e-4:
            raise ProtocolError("measured EEF quaternion is not unit length")
    return result


def open_frame(root: Path, relative: str):
    """Open only a regular relative path, rejecting every symlink component."""
    if not isinstance(relative, str):
        raise ProtocolError("invalid worker image path")
    name = PurePosixPath(relative)
    if (not relative or relative == "." or "\\" in relative or name.is_absolute()
            or ".." in name.parts or name.as_posix() != relative):
        raise ProtocolError("worker image escaped its artifact directory")
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in name.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(name.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    import stat
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ProtocolError("worker image is not a regular file")
    return os.fdopen(fd, "rb")


class ReferenceEEFEpisode(RoboDojoEpisode):
    """Reuse only correlated private RPC and acknowledged process cleanup."""

    def _observation(self, result: Mapping[str, Any]) -> Observation:
        from PIL import Image
        import numpy as np
        if result.get("instruction") != self.benchmark.instruction or set(result.get("frames", {})) != set(CAMERAS):
            raise ProtocolError("unexpected task language or camera channels")
        images = {}
        for camera in CAMERAS:
            with open_frame(self.artifact_dir, result["frames"][camera]) as stream, Image.open(stream) as image:
                rgb = np.asarray(image).copy()
            if rgb.dtype != np.uint8 or rgb.shape != (480, 640, 3):
                raise ProtocolError("reference cameras require original uint8 480x640x3 RGB")
            images[camera] = rgb
        # No worker metrics, layout fields, object identities or calibration are
        # copied. State is measured joints/EEF and native last gripper commands.
        state = public_state(result["state"])
        feedback = None
        if self.steps:
            feedback = validate_robot_feedback(result.get("control_feedback"),
                expected_control_target=self.steps, expected_robot_state=state)
        elif "control_feedback" in result:
            raise ProtocolError("robot feedback was not declared or no control was acknowledged")
        if feedback is None:
            return Observation(self.steps, self.benchmark.instruction, images, state)
        return Observation(self.steps, self.benchmark.instruction, images, state, control_feedback=feedback)

    def reset(self) -> Observation:
        if self.process is not None or self.artifact_dir is None:
            raise ProtocolError("bind artifacts before the one permitted reset")
        benchmark = self.benchmark
        document = benchmark.runtime_document()
        repo = Path(__file__).resolve().parents[4]
        worker = Path(__file__).resolve().parents[1] / "environment" / benchmark.worker_filename
        if not benchmark.python.is_file() or not worker.is_file():
            raise CompatibilityError("missing native interpreter or reference EEF worker")
        accepted = os.environ.get("OMNI_KIT_ACCEPT_EULA", "N").lower() in ("y", "yes", "1")
        marker = benchmark.python.parent.parent / "lib/python3.11/site-packages/isaacsim/kit/EULA_ACCEPTED"
        if marker.is_file():
            accepted = accepted or (marker.read_text().splitlines() or [""])[0].strip().lower() in ("y", "yes", "1")
        if not accepted:
            raise CompatibilityError("Isaac Sim licence acceptance is unresolved")
        env = os.environ.copy()
        for name in ("CUDA_VISIBLE_DEVICES", "ROBODOJO_USD_ASSET_PREFIX", "EVAL_NUM", "RSI_SIM_SERVER_TOKEN"):
            env.pop(name, None)
        env.update(PYTHONPATH=f"{repo}:{benchmark.source_root}:{document['recording_support']}",
            PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
            OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", XDG_CACHE_HOME=str(self.artifact_dir / "cache"),
            TORCH_EXTENSIONS_DIR=str(self.artifact_dir / "cache/torch_extensions"))
        self.log = (self.artifact_dir / "native_worker.log").open("x")
        self.process = subprocess.Popen([str(benchmark.python), "-B", str(worker)],
            cwd=benchmark.source_root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.log, text=True, bufsize=1, start_new_session=True)
        request = {"op": "reset", "task": benchmark.task, "layout_id": self.episode.metadata["layout_id"],
            "runtime_manifest": str(benchmark.runtime_manifest),
            "runtime_manifest_sha256": benchmark.runtime_manifest_sha256,
            "artifact_dir": str(self.artifact_dir), "gpu_id": benchmark.gpu_id,
            "evaluation_mode": benchmark.evaluation_mode}  # the worker re-derives this mode's layouts
        if benchmark.stability_manifest is not None:  # max: pinned to the digest observed at startup
            request.update(stability_manifest=str(benchmark.stability_manifest),
                stability_manifest_sha256=benchmark.stability_provenance["stability_manifest"]["sha256"])
        return self._observation(self._rpc(request))

    def _accept_step(self, result: Mapping[str, Any]) -> Transition:
        success, terminated, truncated, reward = validate_direct_tick_result(result, self.steps + 1,
            horizon=self.benchmark.native_horizon)
        self.steps += 1
        self.finished = terminated or truncated
        return Transition(self._observation(result), reward, terminated, truncated,
            {"native_success": success, "control_targets": result["metrics"]["control_targets"],
                "physics_ticks": result["metrics"]["physics_ticks"]})

    def step(self, action: Sequence[float]):
        if self.finished:
            raise ProtocolError("cannot step a finished episode")
        return self._accept_step(self._rpc({"op": "step", "action": validate_action(action)}))

    def metrics(self) -> Mapping[str, Any]:
        return {**self.latest, "adapter_step_returns": self.steps,
            "track": self.benchmark.descriptor.protocol_version,
            "native_horizon": self.benchmark.native_horizon}


class DirectEEFBenchmarkAdapter:
    observation_spec = OBSERVATION_SPEC
    action_spec = ACTION_SPEC
    protocol_version = INTERFACE_PROTOCOL
    task = TASK
    instruction = INSTRUCTION
    native_horizon = HORIZON
    allowed_layout_ids = tuple(TASK_SPEC["evaluation_modes"]["fast"]["layout_ids"])
    selection_id = TASK_SPEC["evaluation_modes"]["fast"]["id"]
    stability_manifest = stability_provenance = None  # max only
    worker_filename = "native_eef_worker.py"

    def runtime_document(self):
        return load_runtime(self.runtime_manifest, self.runtime_manifest_sha256)

    @staticmethod
    def pinned_snapshot():
        return pins()

    def validate_action_input(self, values):
        return validate_action(values)  # before the service consumes a sequence

    def __init__(self, *, runtime_manifest: str, runtime_manifest_sha256: str,
                 task_id: str = TASK,
                 evaluation_mode: str = "fast", gpu_id: int = 0,
                 worker_timeout: float = 1200, stability_manifest: str | None = None,
                 stability_manifest_sha256: str | None = None) -> None:
        if evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"evaluation_mode must be one of {', '.join(EVALUATION_MODES)}; got {evaluation_mode!r}")
        self.task_spec = task_spec(task_id)
        if task_id != TASK:
            raise ValueError("task is declared but has no accepted native Direct worker")
        self.task = task_id
        self.native_horizon = self.task_spec["native_horizon"]
        selection = self.task_spec["evaluation_modes"]["max" if evaluation_mode == "max" else "fast"]
        # max: provenance holds the observed manifest digest, pinned or recorded unpinned.
        self.allowed_layout_ids, self.stability_provenance = mode_layouts(evaluation_mode, task_id,
            stability_manifest=stability_manifest, stability_manifest_sha256=stability_manifest_sha256)
        self.stability_manifest = Path(stability_manifest) if evaluation_mode == "max" else None
        self.evaluation_mode = evaluation_mode
        self.selection_id = selection["id"]
        self.instruction = self.task_spec["public_instruction"]
        self.robot_feedback = ROBOT_FEEDBACK_SCHEMA
        if type(gpu_id) is not int or gpu_id < 0:
            raise ValueError("invalid GPU selection")
        if isinstance(worker_timeout, bool) or not isinstance(worker_timeout, Real) or not math.isfinite(worker_timeout) or worker_timeout <= 0:
            raise ValueError("worker_timeout must be finite and positive")
        self.runtime_manifest = Path(runtime_manifest).absolute()
        self.runtime_manifest_sha256 = runtime_manifest_sha256
        snapshot_path = Path(__file__).resolve().parents[1] / "environment/reference_eef_snapshot.json"
        if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != self.task_spec["layout_binding"]["snapshot_sha256"]:
            raise ValueError("task catalog and pinned layout snapshot differ")
        document = self.runtime_document()
        self.source_root = self.runtime_manifest.parent.resolve() / "RoboDojo"
        self.python = Path(document["python"])
        self.layout_ids = self.allowed_layout_ids
        self.gpu_id, self.worker_timeout = gpu_id, float(worker_timeout)
        self.max_policy_calls = None
        self.environment_step_cap = self.native_horizon
        self.descriptor = BenchmarkDescriptor("robodojo", "ee67a146-native", selection_protocol(evaluation_mode),
                                              self.pinned_snapshot()["native_revision"])

    def episodes(self, seed: int = SEED, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or seed != SEED:
            raise ProtocolError("use the declared RSI seed; native startup/eval seed is 0")
        if limit is not None:  # complete mode schedule only; no prefix truncation
            raise ValueError("RoboDojo serves its complete evaluation_mode schedule; omit the episode limit")
        native_seed = self.task_spec["native_eval_seed"]
        simulator_seed = self.task_spec["simulator_initial_seed"]
        max_mode = self.evaluation_mode == "max"
        # max: the layouts an offline reset-only screen found stable, as upstream
        # skips unstable resets; later errors are retained, never replaced.
        schema, kind = (("starvla-rsi.robodojo.reset-stable-layout-selection/v1", "first_reset_stable_layouts")
                        if max_mode else ("starvla-rsi.robodojo.fixed-layout-selection/v1", "fixed_catalog_layouts"))
        result = tuple(EpisodeSpec(f"{self.task}/arx_x5/eval-seed{native_seed}/layout{i}", self.task, seed, self.instruction,
            {"native_eval_seed": native_seed, "simulator_initial_seed": simulator_seed, "reset_seed": i, "layout_id": i,
             "layout_inventory_sha256": self.pinned_snapshot()["classify_layout_inventory_sha256"],
             "native_horizon": self.native_horizon, "environment_step_cap": self.native_horizon,
             "runtime_manifest_sha256": self.runtime_manifest_sha256,
             "evaluation_mode": self.evaluation_mode, "selection_id": self.selection_id,
             # A matching case count is not a parity certificate: upstream also
             # replaces layouts after PhysX-broken or other in-episode errors.
             "case_selection_schema": schema,
             "configured_layout_count": len(self.layout_ids),
             "native_reference_episode_count": self.task_spec["upstream_configured_episodes"],
             "selection_kind": kind,
             **(self.stability_provenance or {}),  # max: manifest {sha256, pinned} and screening counts
             "invalid_case_handling": "retain_error_without_replacement",
             "official_full_protocol": False,
             "robot_feedback_schema": self.robot_feedback,
             "control_alignment": CONTROL_ALIGNMENT,
             "target_quaternion_tolerance": TARGET_QUATERNION_TOLERANCE}) for i in self.layout_ids)
        return result

    def open_episode(self, episode: EpisodeSpec) -> ReferenceEEFEpisode:
        if episode not in self.episodes():
            raise ProtocolError("episode was not in the immutable service schedule")
        return ReferenceEEFEpisode(self, episode)
