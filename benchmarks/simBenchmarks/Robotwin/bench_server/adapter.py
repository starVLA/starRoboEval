"""RoboTwin clean fixed-seed track: RGB, language and robot state to native qpos."""
from __future__ import annotations

import gc
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import (ActionSpec, BenchmarkDescriptor, EpisodeSpec, JsonValue,
                               Observation, ObservationSpec, Transition)
from benchkit.errors import CompatibilityError, ProtocolError
from benchkit.registry import register_benchmark
from benchmarks.simBenchmarks.Robotwin.environment import runtime

CAMERAS = ("head_camera", "left_camera", "right_camera")
IMAGE_SHAPE = (240, 320, 3)
NATIVE_HORIZON = 400
PROTOCOL = "robotwin-local-content/clean-fixed-seed/qpos14-rgb320-state14/fast-v3"
COMPAT_PROTOCOL = "robotwin-local-content/clean-fixed-seed/qpos14-rgb320-state14-oidn233/fast-v4"


def policy_observation(raw: Any, step: int, instruction: str, state: Sequence[float]) -> Observation:
    import numpy as np
    if not isinstance(raw, Mapping) or not isinstance(raw.get("observation"), Mapping):
        raise ProtocolError("native RoboTwin observation must contain cameras")
    images = {}
    for camera in CAMERAS:
        item = raw["observation"].get(camera)
        frame = item.get("rgb") if isinstance(item, Mapping) else None
        if not isinstance(frame, np.ndarray) or frame.shape != IMAGE_SHAPE or frame.dtype != np.uint8:
            raise ProtocolError(f"RoboTwin {camera} must be native 240x320 uint8 RGB")
        images[camera] = np.array(frame, copy=True, order="C")
    # joint_action.vector is commanded drive targets, NOT measured encoders.
    # State is supplied separately by the declared native measured-state APIs.
    # No endpose, front view, calibration, task info, reset seed or native score.
    return Observation(step=step, instruction=instruction, images=images,
                       state=runtime.validate_robot_state(state))


class RoboTwinEpisode:
    def __init__(self, benchmark: RoboTwinBenchmarkAdapter, episode: EpisodeSpec):
        self.benchmark, self.episode = benchmark, episode
        self.env = None
        self.scene_counter = None
        self.artifact_dir: Path | None = None
        self.writers = {}
        self.jit_cache = None
        self.step_count = self.native_steps = self.physics_ticks = 0
        self.acknowledged_controls = 0
        self.native_reset_returned = False
        self.reset_completed = False
        self.success = self.finished = self.reset_attempted = self.closed = self.finalized = False
        self.close_error: BaseException | None = None
        self.top_events = []
        self.control_error = False
        self.provenance = None

    def bind_artifact_dir(self, path: Path) -> None:
        if self.artifact_dir is not None or self.reset_attempted or self.closed or self.finalized:
            raise ProtocolError("RoboTwin artifacts must be bound once before reset")
        path.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = path.resolve()

    def _log(self, event: str, **values) -> None:
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_events.jsonl", {"event": event, **values})

    def reset(self) -> Observation:
        if self.reset_attempted or self.closed or self.finalized:
            raise ProtocolError("RoboTwin permits one reset attempt per predeclared episode")
        self.reset_attempted = True
        try:
            if self.artifact_dir is None:
                raise ProtocolError("RoboTwin native reset requires a model-owned artifact directory for its private JIT cache")
            self.jit_cache = self.artifact_dir / "cache" / "curobo-jit"
            self.jit_cache.mkdir(parents=True, exist_ok=False)
            self.provenance = runtime.readiness(self.benchmark.source_root,
                                               self.benchmark.deployment_manifest_sha256,
                                               self.benchmark.renderer_runtime)
            self.provenance["protocol_version"] = self.benchmark.descriptor.protocol_version
            # Retain the verified runtime choice even if native import/setup fails.
            atomic_write_json(self.artifact_dir / "native_provenance.json", self.provenance)
            self._log("native_construction_start", task=self.episode.task,
                      native_seed=self.benchmark.native_seed, expert_screening=False)
            with runtime.native_directory(self.benchmark.source_root, self.jit_cache):
                self.env = runtime.create_native(self.benchmark.source_root, self.episode.task)
                runtime.verify_loaded_renderer(self.provenance, require_cuda_plugin=False)
                config = runtime.resolved_native_config(self.benchmark.source_root, self.episode.task)
                self._log("reset_start", native_seed=self.benchmark.native_seed,
                          initialization="native setup_demo, homestate/open-gripper/planner initialization/stability checks; no expert play_once")
                self.env.setup_demo(now_ep_num=0, seed=self.benchmark.native_seed, is_test=True, **config)
                self.native_reset_returned = True
                self._log("reset_returned")
                compiled = runtime.verify_compiled_control(self.env)
                # Native initialization is unchanged. Only subsequent task-side
                # scene.step calls are counted; no C++ scene handle is replaced.
                self.scene_counter = runtime.SceneStepCounter(self.env.scene)
                self.env.scene = self.scene_counter
                for side in ("left", "right"):
                    name = f"{side}_mplib_planner"
                    setattr(self.env.robot, name, runtime.TOPPRecorder(getattr(self.env.robot, name), side, self.top_events))
                self.provenance.update({"task": self.episode.task, "native_seed": self.benchmark.native_seed,
                                        "evaluation_mode": "fast", "sample_selection": "one predeclared unscreened native seed",
                                        "native_source_revision": None, "compiled_contract": compiled,
                                        "resolved_native_config": config, "protocol_version": self.benchmark.descriptor.protocol_version,
                                        "instruction_source": f"description/task_instruction/{self.episode.task}.json:full_description",
                                        "observation": {"cameras": list(CAMERAS), "shape": list(IMAGE_SHAPE),
                                                        "image_transform": "none; copy native RGB bytes",
                                                        "state": runtime.state_provenance()},
                                        "initialization_physics_ticks": None,
                                        "initialization_count_note": "native setup includes stability settling; not instrumented or counted as model controls",
                                        "jit_cache": {"path": str(self.jit_cache), "source": "per-episode evaluator-owned TORCH_EXTENSIONS_DIR",
                                                      "excluded_from_artifact_transfer": True, "identity": "derived native CUDA build cache; not loaded-memory attestation"},
                                        "video_timebase": "10-fps presentation of one public frame per control, not physical control frequency"})
                if self.artifact_dir is not None:
                    atomic_write_json(self.artifact_dir / "native_provenance.json", self.provenance)
                self._log("reset_end", native_horizon=NATIVE_HORIZON, policy_controls=0)
                observation = self._observe()
                renderer_loaded = runtime.verify_loaded_renderer(self.provenance, require_cuda_plugin=True)
                if renderer_loaded:
                    self.provenance["renderer_loaded_paths"] = renderer_loaded
                    atomic_write_json(self.artifact_dir / "native_provenance.json", self.provenance)
                self.reset_completed = True
                return observation
        except BaseException:
            self.finished = True
            try:
                self.close()
            except Exception as exc:
                self._log("reset_cleanup_error", error_type=type(exc).__name__)
            raise

    def _observe(self) -> Observation:
        observation = policy_observation(self.env.get_obs(), self.step_count, self.episode.instruction,
                                         runtime.robot_state(self.env))
        if self.artifact_dir is not None:
            import imageio.v2 as imageio
            from PIL import Image
            for camera, frame in observation.images.items():
                path = self.artifact_dir / f"{camera}-{self.step_count:06d}.png"
                Image.fromarray(frame).save(path)
                if camera not in self.writers:
                    self.writers[camera] = imageio.get_writer(str(self.artifact_dir / f"{camera}.mp4"),
                                                            fps=10, codec="libx264", macro_block_size=1)
                self.writers[camera].append_data(frame)
                append_jsonl(self.artifact_dir / "frames.jsonl", {
                    "camera": camera, "step": self.step_count, "control": self.step_count, "policy_physics_ticks": self.physics_ticks,
                    "policy_simulated_seconds": self.physics_ticks / 250, "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "rgb_sha256": hashlib.sha256(frame.tobytes()).hexdigest(),
                })
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.env is None or self.closed or self.finished or self.finalized:
            raise ProtocolError("cannot control an uninitialized or finished RoboTwin episode")
        vector = self.benchmark.action_spec.validate(action)
        if self.native_steps >= NATIVE_HORIZON:
            raise ProtocolError("native RoboTwin control horizon exhausted")
        previous_top = len(self.top_events)
        self._log("action_start", control=self.step_count + 1, action=list(vector), action_type="qpos")
        try:
            with runtime.native_directory(self.benchmark.source_root, self.jit_cache):
                self.env.take_action(vector, action_type="qpos")
                self.native_steps = int(self.env.take_action_cnt)
                self.physics_ticks = self.scene_counter.steps
                if self.native_steps != self.step_count + 1 or type(self.env.eval_success) is not bool:
                    raise ProtocolError("native RoboTwin control count or cached success differs")
                self.step_count += 1
                self.success = self.env.eval_success  # Native take_action checks success each physics tick.
                self.finished = self.success or self.native_steps >= NATIVE_HORIZON
                self._log("action_end", control=self.step_count, native_steps=self.native_steps,
                          policy_physics_ticks=self.physics_ticks, native_success=self.success,
                          native_topp=self.top_events[previous_top:])
                observation = self._observe()
            transition = Transition(observation=observation, reward=float(self.success), terminated=self.success,
                              truncated=self.finished and not self.success,
                              info={"native_success": self.success, "native_steps": self.native_steps,
                                    "policy_physics_ticks": self.physics_ticks})
            self.acknowledged_controls += 1
            return transition
        except BaseException:
            self.finished = self.control_error = True
            self.native_steps = int(getattr(self.env, "take_action_cnt", self.native_steps))
            self.physics_ticks = self.scene_counter.steps
            self._log("action_error", native_started_controls=self.native_steps,
                      acknowledged_controls=self.acknowledged_controls, completed_physics_ticks=self.physics_ticks,
                      native_topp=self.top_events[previous_top:], replay_allowed=False)
            raise

    def metrics(self) -> Mapping[str, JsonValue]:
        return {"success": self.success, "native_steps": self.native_steps,
                "acknowledged_controls": self.acknowledged_controls, "completed_native_controls": self.step_count,
                "native_horizon": NATIVE_HORIZON, "reset_attempted": self.reset_attempted,
                "native_reset_returned": self.native_reset_returned, "reset_completed": self.reset_completed,
                "policy_physics_ticks": self.physics_ticks, "policy_simulated_seconds": self.physics_ticks / 250,
                "initialization_physics_ticks": None, "native_source_revision": None,
                "reward_semantics": "wrapper numeric encoding of cached native success; no shaped reward",
                "control_error": self.control_error,
                "native_topp_fallbacks": sum(row["status"] != "native_path" for row in self.top_events),
                "counter_scope": "started native qpos targets and completed task-side physics steps; errored native calls are never replayed"}

    def _close_writers(self) -> None:
        writers, self.writers = self.writers, {}
        errors = []
        for writer in writers.values():
            try:
                writer.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ProtocolError("RoboTwin media finalization failed") from errors[0]

    def artifacts(self) -> Mapping[str, str]:
        self.finalized = True
        self._close_writers()
        if self.artifact_dir is None:
            return {}
        files = {f"{camera}_video": f"{camera}.mp4" for camera in CAMERAS}
        files.update({"frames": "frames.jsonl", "native_events": "native_events.jsonl",
                      "native_provenance": "native_provenance.json", "native_cleanup": "native_cleanup.json"})
        return {key: str(self.artifact_dir / name) for key, name in files.items()
                if (self.artifact_dir / name).is_file()}

    def close(self) -> None:
        if self.closed:
            if self.close_error is not None:
                raise ProtocolError("previous RoboTwin cleanup failed") from self.close_error
            return
        self.closed = True
        errors = []
        try:
            self._close_writers()
        except BaseException as exc:
            errors.append(exc)
        env, self.env = self.env, None
        native_returned = False
        if env is not None:
            try:
                if self.scene_counter is not None:
                    env.scene = self.scene_counter.scene
                with runtime.native_directory(self.benchmark.source_root, self.jit_cache):
                    env.close_env()
                native_returned = True
            except BaseException as exc:
                errors.append(exc)
        self.scene_counter = None
        del env
        gc.collect()
        if self.artifact_dir is not None:
            try:
                atomic_write_json(self.artifact_dir / "native_cleanup.json", {
                    "native_close_returned": native_returned, "python_references_released": True,
                    "error_types": [type(exc).__name__ for exc in errors],
                    "scope": "native close_env and reference release; native gym close does not attest GPU reclamation; stop this one-episode server process after result transfer",
                })
            except BaseException as exc:
                errors.append(exc)
        if errors:
            self.close_error = errors[0]
            raise ProtocolError("RoboTwin native cleanup failed") from errors[0]


class RoboTwinBenchmarkAdapter:
    budget_mode = "horizon"
    environment_step_cap = NATIVE_HORIZON

    def __init__(self, source_root: str, deployment_manifest_sha256: str, task: str = "lift_pot",
                 native_seed: int = 100000, evaluation_mode: str = "fast",
                 renderer_runtime: str = runtime.BUNDLED_RENDERER):
        if (not isinstance(source_root, str) or not source_root or not Path(source_root).is_absolute()
                or ".." in Path(source_root).parts):
            raise ValueError("source_root must be an explicit absolute deployment path")
        if (not isinstance(deployment_manifest_sha256, str) or len(deployment_manifest_sha256) != 64
                or any(c not in "0123456789abcdef" for c in deployment_manifest_sha256)):
            raise ValueError("deployment_manifest_sha256 must be 64 lowercase hexadecimal characters")
        if not isinstance(task, str) or task not in runtime.TASK_INSTRUCTIONS or evaluation_mode != "fast":
            raise ValueError("only explicit clean lift_pot/click_bell fast tasks are implemented; native full is unsupported")
        if type(native_seed) is not int or not 0 <= native_seed < 2**32:
            raise ValueError("native_seed must be an integer in [0, 2**32)")
        if not isinstance(renderer_runtime, str) or renderer_runtime not in runtime.RENDERER_RUNTIMES:
            raise ValueError("renderer_runtime must be a declared pinned track")
        self.source_root = Path(source_root)
        self.deployment_manifest_sha256 = deployment_manifest_sha256
        self.task, self.native_seed = task, native_seed
        self.renderer_runtime = renderer_runtime
        self.claimed = False

    @property
    def descriptor(self) -> BenchmarkDescriptor:
        return BenchmarkDescriptor(name="robotwin", version="local-2.0-clean-development",
                                   protocol_version=(PROTOCOL if self.renderer_runtime == runtime.BUNDLED_RENDERER else COMPAT_PROTOCOL),
                                   source_revision=f"content-inventory-sha256:{runtime.NATIVE_INVENTORY_SHA256}")

    @property
    def observation_spec(self) -> ObservationSpec:
        return ObservationSpec(cameras=CAMERAS, state_names=runtime.STATE_NAMES,
                               modalities=("language", "rgb", "joint_position", "gripper_command"), privileged=False)

    @property
    def action_spec(self) -> ActionSpec:
        names = (*runtime.JOINT_NAMES[:6], "left_gripper", *runtime.JOINT_NAMES[6:], "right_gripper")
        return ActionSpec(mode="robotwin_aloha_absolute_joint_targets", size=14, names=names,
                          low=((-10.0,) * 6 + (0.0,)) * 2, high=((10.0,) * 6 + (1.0,)) * 2,
                          control_hz=None, frame="absolute native Aloha arm joint coordinates in radians",
                          rotation="joint coordinates; no EEF pose, IK or task planning interface",
                          gripper="normalized absolute native gripper command: 0 closed, 1 open; native scale [-0.01,0.045] m")

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("harness seed must be an integer in [0, 2**32)")
        if limit is not None and (type(limit) is not int or limit != 1):
            raise ValueError("this single-task server permits exactly one episode")
        return (EpisodeSpec(id=f"{self.task}-native-seed{self.native_seed}-episode000", task=self.task,
                            seed=seed, instruction=runtime.TASK_INSTRUCTIONS[self.task], metadata={
                                "evaluation_mode": "fast", "native_seed": self.native_seed,
                                "task_config": "demo_clean", "native_horizon": NATIVE_HORIZON,
                                "native_horizon_source": "task_config/_eval_step_limit.yml",
                                "native_source_revision": None, "expert_screening": False,
                                "instruction_selection": "fixed native full_description; no expert-derived placeholders",
                                "sample_selection": "predeclared unscreened seed; one attempt; no retry",
                            }),)

    def open_episode(self, episode: EpisodeSpec) -> RoboTwinEpisode:
        if episode not in self.episodes(episode.seed):
            raise ProtocolError("RoboTwin episode differs from its fixed schedule")
        if self.claimed:
            raise ProtocolError("RoboTwin one-episode service already claimed; start no automatic retry")
        self.claimed = True
        return RoboTwinEpisode(self, episode)


@register_benchmark("robotwin")
def make_robotwin(parameters: Mapping[str, JsonValue]) -> RoboTwinBenchmarkAdapter:
    allowed = {"source_root", "deployment_manifest_sha256", "task", "native_seed", "evaluation_mode", "renderer_runtime"}
    if set(parameters) - allowed:
        raise ValueError(f"unknown RoboTwin parameters: {sorted(set(parameters) - allowed)}")
    if not {"source_root", "deployment_manifest_sha256"}.issubset(parameters):
        raise ValueError("RoboTwin requires an explicit content-pinned deployment root and manifest digest")
    return RoboTwinBenchmarkAdapter(**parameters)
