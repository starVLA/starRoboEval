"""Fixed-manifest DOMINO direct qpos service; native dynamics/scoring stay private."""
from __future__ import annotations

import gc
import hashlib
from pathlib import Path
from typing import Mapping

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import ActionSpec, BenchmarkDescriptor, EpisodeSpec, Observation, ObservationSpec, Transition
from benchkit.errors import ProtocolError
from benchkit.registry import register_benchmark
from benchmarks.simBenchmarks.DOMINO.bench_server.protocol import (
    ACTION_NAMES, CAMERAS, IMAGE_SHAPE, INSTRUCTION, NATIVE_HORIZON,
    NATIVE_REVISION, PROTOCOL, STATE_NAMES, TASK, TASK_CONFIG,
)
from benchmarks.simBenchmarks.DOMINO.environment import runtime
from benchmarks.simBenchmarks.DOMINO.environment.native_outcome import NativeOutcome


def policy_observation(raw, step: int) -> Observation:
    import numpy as np
    if not isinstance(raw, Mapping) or not isinstance(raw.get("observation"), Mapping):
        raise ProtocolError("DOMINO observation must contain native cameras")
    images = {}
    for name in CAMERAS:
        item = raw["observation"].get(name)
        frame = item.get("rgb") if isinstance(item, Mapping) else None
        if not isinstance(frame, np.ndarray) or frame.shape != IMAGE_SHAPE or frame.dtype != np.uint8:
            raise ProtocolError("DOMINO cameras require native 240x320 uint8 RGB")
        images[name] = np.array(frame, copy=True, order="C")
    command = raw.get("joint_action")
    values = command.get("vector") if isinstance(command, Mapping) else None
    if not isinstance(values, (list, tuple, np.ndarray)) or np.shape(values) != (14,):
        raise ProtocolError("DOMINO commanded targets require 14 values")
    state = ActionSpec("commanded_targets", 14).validate(values)
    # Explicit native commanded drive targets, NOT measured encoders. Never
    # forward native camera calibration, object state, scores or motion payload.
    return Observation(step=step, instruction=INSTRUCTION, images=images, state=state,
                       metadata={"state_provenance": "native robot commanded drive/gripper targets; not measured encoders"})


class DOMINOEpisode:
    def __init__(self, benchmark, episode):
        self.benchmark, self.episode = benchmark, episode
        self.env = self.outcome = self.counter = self.cache = None
        self.artifact_dir = None
        self.writers = {}
        self.reset_attempted = self.reset_completed = self.closed = self.finished = False
        self.finalized = self.control_error = False
        self.native_terminal = False
        self.close_error = None
        self.step_count = self.acknowledged_controls = self.native_steps = self.physics_ticks = 0
        self.native_metrics = {"success": False, "manipulation_score": None, "route_completion": None}

    def bind_artifact_dir(self, path):
        if self.artifact_dir is not None or self.reset_attempted or self.closed:
            raise ProtocolError("bind DOMINO artifacts once before reset")
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = path.resolve()

    def _log(self, event, **values):
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_events.jsonl", {"event": event, **values})

    def reset(self):
        if self.reset_attempted or self.closed or self.finalized:
            raise ProtocolError("DOMINO permits one reset attempt")
        self.reset_attempted = True
        try:
            if self.artifact_dir is None:
                raise ProtocolError("DOMINO requires bound artifacts and an owned JIT cache")
            self.cache = self.artifact_dir / "cache/curobo-jit"
            self.cache.mkdir(parents=True, exist_ok=False)
            benchmark = self.benchmark
            provenance = runtime.readiness(benchmark.source_root, benchmark.deployment_manifest_sha256)
            atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
            with runtime.native_directory(benchmark.source_root, self.cache):
                config = runtime.resolved_config(benchmark.source_root)
                task_class, tracker_class, manifest_class = runtime.import_native(benchmark.source_root)
                entry = runtime.load_entry(benchmark.episode_manifest, benchmark.episode_manifest_sha256,
                                           benchmark.native_seed, config, manifest_class)
                self.env = task_class()
                self._log("reset_start", native_seed=benchmark.native_seed, expert_called=False)
                self.env.setup_demo(now_ep_num=0, seed=benchmark.native_seed, is_test=True, **config)
                self.env._saved_dynamic_motion_info = entry["dynamic_motion_info"]
                self.env.set_instruction(INSTRUCTION)
                if not self.env.init_dynamic_motion_for_eval():
                    raise ProtocolError("fixed manifest dynamic initialization rejected; no seed replacement")
                compiled = runtime.verify_compiled(self.env)
                self.outcome = NativeOutcome(self.env, config, tracker_class)
                self.counter = runtime.SceneStepCounter(self.env.scene)
                self.env.scene = self.counter
                provenance.update({"protocol_version": PROTOCOL, "compiled_contract": compiled,
                                   "episode_manifest_sha256": benchmark.episode_manifest_sha256,
                                   "native_seed": benchmark.native_seed, "expert_called": False,
                                   "instruction_selection": "fixed native full_description, not randomized episode wording",
                                   "state_provenance": "native commanded targets; not encoders",
                                   "initialization_physics_ticks": None,
                                   "video_timebase": "10fps presentation, not physical control frequency"})
                observation = self._observe()
                provenance["loaded_oidn_files"] = runtime.verify_loaded_renderer(provenance)
                atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
                self.native_metrics = self.outcome.metrics(benchmark.native_seed)
            self.reset_completed = True
            self._log("reset_end", native_controls=0, initialization_physics_ticks=None)
            return observation
        except BaseException:
            self.finished = True
            try:
                self.close()
            except BaseException as exc:
                self._log("reset_cleanup_error", error_type=type(exc).__name__)
            raise

    def _observe(self):
        observation = policy_observation(self.env.get_obs(), self.step_count)
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
                    "camera": camera, "step": self.step_count, "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "rgb_sha256": hashlib.sha256(frame.tobytes()).hexdigest(),
                    "policy_physics_ticks": self.physics_ticks})
        return observation

    def step(self, action):
        if not self.reset_completed or self.closed or self.finished or self.finalized:
            raise ProtocolError("DOMINO control requires a live initialized episode")
        values = self.benchmark.action_spec.validate(action)
        if self.native_steps >= NATIVE_HORIZON:
            raise ProtocolError("DOMINO horizon exhausted")
        self._log("action_start", action=list(values), control=self.step_count + 1)
        try:
            with runtime.native_directory(self.benchmark.source_root, self.cache):
                self.env.take_action(values, action_type="qpos")
                self.native_steps = int(self.env.take_action_cnt)
                self.physics_ticks = self.counter.steps
                if self.native_steps != self.step_count + 1:
                    raise ProtocolError("native DOMINO target count differs")
                self.step_count += 1
                # Native take_action has already called tracker.on_step once.
                self.outcome.after_action()
                self.finished = self.outcome.finished
                self.native_terminal = self.finished
                self.native_metrics = self.outcome.metrics(self.benchmark.native_seed)
                if self.native_metrics["metrics_tracker_steps"] != self.native_steps:
                    raise ProtocolError("native metrics tracker count differs from completed controls")
                observation = self._observe()
            self._log("action_end", native_controls=self.native_steps,
                      policy_physics_ticks=self.physics_ticks, outcome=self.native_metrics)
            result = Transition(observation, reward=float(self.outcome.success),
                                terminated=self.finished and (self.outcome.success or self.outcome.fail_reason is not None),
                                truncated=self.finished and not self.outcome.success and self.outcome.fail_reason is None,
                                info={"native_success": self.outcome.success, "native_steps": self.native_steps})
            self.acknowledged_controls += 1
            return result
        except BaseException:
            self.control_error = self.finished = True
            self.native_steps = int(getattr(self.env, "take_action_cnt", self.native_steps))
            self.physics_ticks = self.counter.steps
            self._log("action_error", native_started_controls=self.native_steps,
                      acknowledged_controls=self.acknowledged_controls,
                      completed_physics_ticks=self.physics_ticks, replay_allowed=False)
            raise

    def metrics(self):
        return {**self.native_metrics, "native_horizon": NATIVE_HORIZON,
                "native_steps": self.native_steps, "completed_native_controls": self.step_count,
                "acknowledged_controls": self.acknowledged_controls,
                "policy_physics_ticks": self.physics_ticks, "policy_simulated_seconds": self.physics_ticks / 250,
                "reset_attempted": self.reset_attempted, "reset_completed": self.reset_completed,
                "initialization_physics_ticks": None, "control_error": self.control_error,
                "native_terminal": self.native_terminal,
                "native_score_complete": self.native_terminal and not self.control_error,
                "score_scope": "terminal native outcome" if self.native_terminal and not self.control_error else "partial diagnostic/stop/error state; not a completed native task score",
                "native_source_revision": NATIVE_REVISION,
                "reward_semantics": "binary native success; SR is not MS/100"}

    def _close_writers(self):
        writers, self.writers = self.writers, {}
        errors = []
        for writer in writers.values():
            try:
                writer.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ProtocolError("DOMINO media finalization failed") from errors[0]

    def artifacts(self):
        self.finalized = True
        self._close_writers()
        if self.artifact_dir is None:
            return {}
        atomic_write_json(self.artifact_dir / "native_result.json", self.metrics())
        files = {camera + "_video": camera + ".mp4" for camera in CAMERAS}
        files.update({key: key + ".json" for key in ("native_result", "native_provenance", "native_cleanup")})
        files.update(frames="frames.jsonl", native_events="native_events.jsonl")
        return {key: str(self.artifact_dir / filename) for key, filename in files.items()
                if (self.artifact_dir / filename).is_file()}

    def close(self):
        if self.closed:
            if self.close_error:
                raise ProtocolError("previous DOMINO cleanup failed") from self.close_error
            return
        self.closed = True
        errors = []
        try:
            self._close_writers()
        except BaseException as exc:
            errors.append(exc)
        env, self.env = self.env, None
        closed = released = False
        if env is not None:
            if self.counter is not None:
                env.scene = self.counter.scene
            with runtime.native_directory(self.benchmark.source_root, self.cache):
                try:
                    env._metrics_tracker = None
                    env.close_env()
                    closed = True
                except BaseException as exc:
                    errors.append(exc)
                try:
                    env.release_episode_resources()
                    released = True
                except BaseException as exc:
                    errors.append(exc)
        self.counter = self.outcome = None
        del env
        gc.collect()
        if self.artifact_dir is not None:
            try:
                atomic_write_json(self.artifact_dir / "native_cleanup.json", {
                    "native_close_returned": closed, "release_resources_returned": released,
                    "error_types": [type(e).__name__ for e in errors],
                    "scope": "native close/release; process exit separately verifies final cleanup"})
            except BaseException as exc:
                errors.append(exc)
        if errors:
            self.close_error = errors[0]
            raise ProtocolError("DOMINO cleanup failed") from errors[0]


class DOMINOBenchmarkAdapter:
    budget_mode = "horizon"
    environment_step_cap = NATIVE_HORIZON

    def __init__(self, source_root, deployment_manifest_sha256, episode_manifest,
                 episode_manifest_sha256, native_seed=100000, task=TASK, evaluation_mode="fast"):
        if task != TASK or evaluation_mode != "fast":
            raise ValueError("DOMINO supports only the declared fixed click_bell case")
        for value in (source_root, episode_manifest):
            if not isinstance(value, str) or not Path(value).is_absolute() or ".." in Path(value).parts:
                raise ValueError("DOMINO source and trusted manifest require explicit absolute paths")
        for value in (deployment_manifest_sha256, episode_manifest_sha256):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("DOMINO requires SHA256-pinned deployment and trusted manifest")
        if type(native_seed) is not int or not 0 <= native_seed < 2**32:
            raise ValueError("native_seed must be a uint32 integer")
        self.source_root, self.episode_manifest = Path(source_root), Path(episode_manifest)
        self.deployment_manifest_sha256 = deployment_manifest_sha256
        self.episode_manifest_sha256, self.native_seed = episode_manifest_sha256, native_seed
        self.claimed = False

    @property
    def descriptor(self):
        return BenchmarkDescriptor("domino", "9c94f2d-fixed-manifest-sm120", PROTOCOL, NATIVE_REVISION)

    @property
    def observation_spec(self):
        return ObservationSpec(cameras=CAMERAS, state_names=STATE_NAMES, modalities=("language", "rgb", "state"))

    @property
    def action_spec(self):
        return ActionSpec("domino_aloha_absolute_joint_targets", 14, ACTION_NAMES,
                          frame="native absolute Aloha arm joint coordinates in radians", control_hz=None,
                          rotation="joint coordinates; no EEF or task planner RPC",
                          gripper="native normalized absolute command, nominal 0 closed/1 open; native mapping/clipping unchanged")

    def episodes(self, seed, limit=None):
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("harness seed must be uint32")
        if limit is not None and (type(limit) is not int or limit != 1):
            raise ValueError("DOMINO fixed task service contains exactly one selected case")
        return (EpisodeSpec(f"{TASK}-native-seed{self.native_seed}-episode000", TASK, seed, INSTRUCTION,
                            {"native_seed": self.native_seed, "native_horizon": NATIVE_HORIZON,
                             "task_config": TASK_CONFIG, "evaluation_mode": "fast",
                             "episode_manifest_sha256": self.episode_manifest_sha256,
                             "sample_selection": "one predeclared private fixed-manifest entry; no online expert or retry"}),)

    def open_episode(self, episode):
        if episode not in self.episodes(episode.seed) or self.claimed:
            raise ProtocolError("DOMINO case mismatched or already claimed")
        self.claimed = True
        return DOMINOEpisode(self, episode)


@register_benchmark("domino")
def make_domino(parameters):
    allowed = {"source_root", "deployment_manifest_sha256", "episode_manifest",
               "episode_manifest_sha256", "native_seed", "task", "evaluation_mode"}
    if set(parameters) - allowed:
        raise ValueError("unknown DOMINO server parameters")
    return DOMINOBenchmarkAdapter(**parameters)
