"""CALVIN single-task cases and native five-task chains: public RGB/language to native relative control."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import (ActionSpec, BenchmarkDescriptor, EpisodeSpec, JsonValue,
                               Observation, ObservationSpec, Transition)
from benchkit.errors import ProtocolError
from benchmarks.simBenchmarks.calvin.bench_server.protocol import long_horizon, single_task
from benchmarks.simBenchmarks.calvin.environment import runtime

CAMERAS = ("rgb_static", "rgb_gripper")
SHAPES = {"rgb_static": (200, 200, 3), "rgb_gripper": (84, 84, 3)}
TASK_HORIZON = 360  # Native evaluate_policy.py EP_LEN per instruction.
CHAIN_HORIZON = TASK_HORIZON * long_horizon.SEQUENCE_LENGTH  # max: chain ceiling; each subtask still stops at 360
EVALUATION_MODES = ("fast", "max", "example")  # fast: blog subset; example: first fast episode
SELECTIONS = {"fast": "single-task-d-validation", "example": "single-task-d-validation",
              "max": "long-horizon-1000"}
PROTOCOL = "calvin-fa03f01/{selection}/rgb-relative7/{mode}/v1"
CHAIN_TASK = "long_horizon_chain"  # Public episode task label in max; never names a future subtask.


def policy_observation(raw: Any, step: int, instruction: str) -> Observation:
    import numpy as np
    if not isinstance(raw, Mapping) or not isinstance(raw.get("rgb_obs"), Mapping):
        raise ProtocolError("CALVIN native observation must contain rgb_obs")
    images = {}
    for camera in CAMERAS:
        frame = raw["rgb_obs"].get(camera)
        if not isinstance(frame, np.ndarray) or frame.shape != SHAPES[camera] or frame.dtype != np.uint8:
            raise ProtocolError(f"CALVIN {camera} must be native {SHAPES[camera]} uint8 RGB")
        images[camera] = np.array(frame, copy=True, order="C")
    # No depth, scene_obs, robot_obs, task oracle, future language or reset metadata.
    return Observation(step=step, instruction=instruction, images=images)


def native_action(vector):
    import numpy as np
    action = np.array(vector, dtype=np.float64, copy=True)
    action[-1] = 1 if action[-1] > 0 else -1  # Retained RGB evaluator's sign convention.
    # Native relative_to_absolute mutates its array slices. Never alias the
    # normalized action record or return its scaled values to the actor.
    return action


class CalvinEpisode:
    def __init__(self, benchmark: CalvinBenchmarkAdapter, episode: EpisodeSpec):
        self.benchmark, self.episode = benchmark, episode
        self.case = benchmark.cases[episode.id]
        self.chain = benchmark.evaluation_mode == "max"  # five subtasks, no reset in between
        self.tasks = tuple(self.case["tasks"]) if self.chain else (self.case["task"],)
        self.native = self.trace = None
        self.artifact_dir: Path | None = None
        self.writers = {}
        self.reset_attempted = self.native_reset_returned = self.reset_completed = False
        self.finished = self.closed = self.finalized = self.success = self.control_error = False
        self.close_error: BaseException | None = None
        self.step_count = self.started_controls = self.acknowledged_controls = 0
        self.subtask_index = self.subtask_controls = 0
        self.completed_subtasks = []
        self.native_outcome = "not_started"
        self.start_info = None

    @property
    def instruction(self):  # Only the current subtask's language is ever public.
        return self.benchmark.instructions[self.tasks[self.subtask_index]]

    def bind_artifact_dir(self, path: Path):
        if self.artifact_dir is not None or self.reset_attempted or self.closed or self.finalized:
            raise ProtocolError("CALVIN artifacts must be bound once before reset")
        path.mkdir(parents=True, exist_ok=True)
        # Preserve the service's lexical root (e.g. macOS /var -> /private/var)
        # so its relative artifact export does not reject a canonicalized alias.
        self.artifact_dir = path.absolute()

    def _log(self, event, **values):
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_events.jsonl", {"event": event, **values})

    def reset(self):
        if self.reset_attempted or self.closed or self.finalized:
            raise ProtocolError("CALVIN permits one reset attempt for its predeclared case")
        self.reset_attempted = True
        try:
            if self.artifact_dir is None:
                raise ProtocolError("CALVIN reset requires a model-owned artifact directory")
            provenance = runtime.readiness(self.benchmark.source_root, self.benchmark.dataset_root)
            case = self.case
            if self.chain:  # Native get_env_state_for_initial_condition, recomputed here.
                robot_obs, scene_obs = long_horizon.env_state(case["initial_condition"])
                selection = {"selected_case": {**case, "robot_obs": robot_obs, "scene_obs": scene_obs,
                                               "condition_seed": long_horizon.condition_seed(case["initial_condition"])},
                             "sequences_sha256": long_horizon.SEQUENCES_SHA256,
                             "native_subtask_horizon": TASK_HORIZON, "native_horizon": CHAIN_HORIZON,
                             "policy_memory": "one policy session per five-subtask chain; native model.reset() "
                                              "per subtask has no service hook"}
            else:
                robot_obs, scene_obs = case["robot_obs"], case["scene_obs"]
                selection = {"selected_case": dict(case), "panel_sha256": single_task.PANEL_SHA256,
                             "native_horizon": TASK_HORIZON,
                             "policy_memory": "one fresh policy session per independent task case"}
            self.native = runtime.prepare_native(self.benchmark.source_root, self.benchmark.dataset_root,
                                                 {task: self.benchmark.instructions[task] for task in self.tasks})
            self.trace = self.native.trace
            provenance.update({"protocol_version": self.benchmark.protocol,
                               "evaluation_mode": self.benchmark.evaluation_mode, **selection,
                               "physics_hz": 240, "control_hz": 30, "physics_ticks_per_control": 8,
                               "action_grouping": "agent_owned",
                               "observation": {"cameras": list(CAMERAS), "shapes": SHAPES,
                                               "image_transform": "none; exact native RGB copies", "state": None},
                               "action": {"mode": self.benchmark.action_spec.mode, "dtype": "float64 writable copy",
                                          "translation_m_per_unit": 0.02, "euler_rad_per_unit": 0.05,
                                          "reference": "previous commanded target pose, world coordinates",
                                          "gripper": "positive opens, zero/negative closes",
                                          "bounds": "development protocol restricts all 7 inputs to [-1,1]; native itself does not clip first six",
                                          "controller": "native PyBullet numerical IK, use_ik_fast=False; no task planner"},
                               "configuration_overrides": {"omit_camera": "tactile", "show_gui": False,
                                                           "use_vr": False, "use_scene_info": True},
                               "video": {"codec": "OpenCV mp4v", "fps": 30, "frames": "reset plus one per completed control",
                                         "encoding_conversion": "RGB to BGR for OpenCV only; no flip/crop/resize"}})
            atomic_write_json(self.artifact_dir / "native_provenance.json", provenance)
            self._log("native_construction_start", expert_screening=False)
            self.native.construct()
            self._log("native_construction_end", physics_ticks=self.trace.completed_ticks["construction"],
                      initialization="native robot/scene load; fixed episode state applied next")
            import numpy as np
            self.trace.phase = "reset"
            if self.chain:
                self._log("reset_start", chain=case["chain"], reset_attempt=1)
            else:
                self._log("reset_start", task=case["task"], trial=case["trial"], reset_attempt=1)
            raw = self.native.env.reset(robot_obs=np.array(robot_obs, dtype=np.float64),
                                        scene_obs=np.array(scene_obs, dtype=np.float64))
            self.native_reset_returned = True
            if self.trace.completed_ticks["reset"] != 1:
                raise ProtocolError("CALVIN native fixed reset must complete exactly one physics tick")
            self.start_info = self.native.env.get_info()
            self.native_outcome = "in_progress"
            if self.chain:
                self._log("subtask_start", index=0, task=self.tasks[0], instruction=self.instruction)
            observation = self._observe(raw)
            self.reset_completed = True
            self._log("reset_end", physics_ticks=self.trace.completed_ticks["reset"], policy_controls=0)
            return observation
        except BaseException:
            self.finished = True
            self.native_outcome = "reset_error"
            try:
                self.close()
            except BaseException as exc:
                self._log("reset_cleanup_error", error_type=type(exc).__name__)
            raise

    def _observe(self, raw):
        observation = policy_observation(raw, self.step_count, self.instruction)
        if self.artifact_dir is not None:
            import cv2
            for camera, frame in observation.images.items():
                path = self.artifact_dir / f"{camera}-{self.step_count:06d}.png"
                bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                if not cv2.imwrite(str(path), bgr):
                    raise ProtocolError("CALVIN PNG writer failed")
                if camera not in self.writers:
                    writer = cv2.VideoWriter(str(self.artifact_dir / f"{camera}.mp4"),
                                             cv2.VideoWriter_fourcc(*"mp4v"), 30, (frame.shape[1], frame.shape[0]))
                    if not writer.isOpened():
                        writer.release()
                        raise ProtocolError("CALVIN MP4 writer failed to open")
                    self.writers[camera] = writer
                self.writers[camera].write(bgr)
                append_jsonl(self.artifact_dir / "frames.jsonl", {
                    "camera": camera, "step": self.step_count, "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "rgb_sha256": hashlib.sha256(frame.tobytes()).hexdigest(),
                    "policy_physics_ticks": self.trace.completed_ticks["control"],
                })
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.native is None or not self.reset_completed or self.closed or self.finished or self.finalized:
            raise ProtocolError("cannot control an uninitialized or finished CALVIN case")
        vector = self.benchmark.action_spec.validate(action)
        self.trace.phase = "control"
        before = self.trace.completed_ticks["control"]
        self.started_controls += 1
        index = self.subtask_index
        task = self.tasks[index]
        self._log("action_start", control=self.started_controls, action=list(vector),
                  **({"subtask_index": index} if self.chain else {}))
        try:
            raw, reward, done, current_info = self.native.env.step(native_action(vector))
            self.step_count += 1
            self.subtask_controls += 1
            controls = self.subtask_controls  # of this subtask, before any advance
            if reward != 0 or done is not False or self.trace.completed_ticks["control"] - before != 8:
                raise ProtocolError("CALVIN native step contract differs")
            # Native rollout: the current subtask against the info captured at its start.
            achieved = self.native.oracle.get_task_info_for_set(self.start_info, current_info, {task})
            if not isinstance(achieved, set) or not achieved.issubset({task}):
                raise ProtocolError("CALVIN native oracle returned an invalid task result")
            if achieved:
                self.completed_subtasks.append({"index": index, "task": task, "controls": controls,
                                                "completion_control": self.step_count})
                if len(self.completed_subtasks) == len(self.tasks):
                    self.finished = self.success = True
                    self.native_outcome = "sequence_success" if self.chain else "task_success"
                else:
                    # Native evaluate_sequence: no scene reset, a new private
                    # baseline and the next annotation. The ACK exposes only the
                    # new public instruction; the agent driver owns its reaction.
                    self.subtask_index += 1
                    self.subtask_controls = 0
                    self.start_info = self.native.env.get_info()
            elif self.subtask_controls >= TASK_HORIZON:
                self.finished = True  # A failed subtask ends the chain, as native.
                self.native_outcome = "subtask_horizon_failure" if self.chain else "task_horizon_failure"
            if self.chain and (achieved or self.finished):
                self._log("subtask_end", index=index, task=task, controls=controls, native_success=bool(achieved),
                          completion_depth=len(self.completed_subtasks), stop_reason=self.native_outcome)
                if achieved and not self.finished:
                    self._log("subtask_start", index=self.subtask_index, task=self.tasks[self.subtask_index],
                              instruction=self.instruction)
            elif self.finished:
                self._log("task_end", task=task, controls=self.step_count, native_success=self.success,
                          stop_reason=self.native_outcome)
            self._log("action_end", control=self.step_count, native_task_success=bool(achieved),
                      policy_physics_ticks=self.trace.completed_ticks["control"],
                      **({"subtask_index": index} if self.chain else {}))
            observation = self._observe(raw)
            info = ({"native_completion_depth": len(self.completed_subtasks)} if self.chain
                    else {"native_task_success": self.success})
            result = Transition(observation=observation, reward=float(bool(achieved)),
                                terminated=self.success, truncated=self.finished and not self.success,
                                info={**info, "native_steps": self.step_count})
            self.acknowledged_controls += 1
            return result
        except BaseException:
            self.finished = self.control_error = True
            self.native_outcome = "control_error"
            self._log("action_error", started_controls=self.started_controls,
                      completed_controls=self.step_count, acknowledged_controls=self.acknowledged_controls,
                      physics_ticks=self.trace.completed_ticks["control"], replay_allowed=False)
            raise

    def metrics(self) -> Mapping[str, JsonValue]:
        ticks = dict(self.trace.completed_ticks) if self.trace is not None else {"construction": 0, "reset": 0, "control": 0}
        started_ticks = dict(self.trace.started_ticks) if self.trace is not None else dict(ticks)
        if self.chain:  # Native evaluate_sequence result: completed subtasks in a row, 0-5.
            depth = len(self.completed_subtasks)
            scope = {"chain": self.case["chain"], "tasks": list(self.tasks), "completion_depth": depth,
                     "success_at_depth": {str(n): depth >= n for n in range(1, len(self.tasks) + 1)},
                     "completed_subtasks": list(self.completed_subtasks),
                     "current_subtask_index": self.subtask_index, "current_subtask_controls": self.subtask_controls,
                     "native_subtask_horizon": TASK_HORIZON, "native_horizon": CHAIN_HORIZON,
                     "aggregate_scope": "one native five-subtask chain of get_sequences(1000)",
                     "reward_semantics": "wrapper numeric encoding of current native subtask completion; "
                                         "no native shaped reward"}
        else:
            scope = {"task": self.case["task"], "trial": self.case["trial"], "native_horizon": TASK_HORIZON,
                     "aggregate_scope": "one independent task case; not the native 1000-sequence chain score",
                     "reward_semantics": "wrapper numeric encoding of native task completion; no native shaped reward"}
        return {"success": self.success, **scope,
                "native_steps": self.step_count, "started_controls": self.started_controls,
                "acknowledged_controls": self.acknowledged_controls, "native_outcome": self.native_outcome,
                "policy_physics_ticks": ticks["control"], "policy_simulated_seconds": ticks["control"] / 240,
                "initialization_physics_ticks": ticks["construction"] + ticks["reset"],
                "completed_physics_ticks_by_phase": ticks, "started_physics_ticks_by_phase": started_ticks,
                "reset_attempted": self.reset_attempted,
                "native_reset_returned": self.native_reset_returned, "reset_completed": self.reset_completed,
                "control_error": self.control_error, "evaluation_mode": self.benchmark.evaluation_mode}

    def _close_writers(self):
        writers, self.writers = self.writers, {}
        errors = []
        for camera, writer in writers.items():
            try:
                writer.release()
                path = self.artifact_dir / f"{camera}.mp4"
                if not path.is_file() or path.stat().st_size == 0:
                    raise ProtocolError("CALVIN video finalization produced no bytes")
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ProtocolError("CALVIN media finalization failed") from errors[0]

    def artifacts(self):
        self.finalized = True
        self._close_writers()
        if self.artifact_dir is None:
            return {}
        if self.native_outcome == "in_progress":
            self.native_outcome = "externally_stopped_incomplete"
        atomic_write_json(self.artifact_dir / "native_metrics.json", self.metrics())
        files = {f"{camera}_video": f"{camera}.mp4" for camera in CAMERAS}
        files.update({"frames": "frames.jsonl", "native_events": "native_events.jsonl",
                      "native_provenance": "native_provenance.json", "native_cleanup": "native_cleanup.json",
                      "native_metrics": "native_metrics.json"})
        return {key: str(self.artifact_dir / name) for key, name in files.items()
                if (self.artifact_dir / name).is_file()}

    def close(self):
        if self.closed:
            if self.close_error is not None:
                raise ProtocolError("previous CALVIN cleanup failed") from self.close_error
            return
        self.closed = True
        errors = []
        try:
            self._close_writers()
        except BaseException as exc:
            errors.append(exc)
        native, self.native = self.native, None
        receipt = {"constructed": False, "native_close_returned": False, "clients": []}
        if native is not None:
            try:
                receipt, native_errors = native.close()
                errors.extend(native_errors)
            except BaseException as exc:
                errors.append(exc)
        if self.native_outcome == "in_progress":
            self.native_outcome = "externally_stopped_incomplete"
        receipt["error_types"] = [type(exc).__name__ for exc in errors]
        if self.artifact_dir is not None:
            try:
                atomic_write_json(self.artifact_dir / "native_cleanup.json", receipt)
                # The shared service deliberately denies metrics RPC after a
                # reset/control fault. Persist counters for final artifact
                # transfer, even when no successful reset response existed.
                atomic_write_json(self.artifact_dir / "native_metrics.json", self.metrics())
            except BaseException as exc:
                errors.append(exc)
        if errors:
            self.close_error = errors[0]
            raise ProtocolError("CALVIN native/media cleanup failed") from errors[0]


class CalvinBenchmarkAdapter:
    def __init__(self, source_root: str, dataset_root: str, evaluation_mode: str = "fast"):
        if evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"evaluation_mode must be one of {', '.join(EVALUATION_MODES)}; got {evaluation_mode!r}")
        for name, value in (("source_root", source_root), ("dataset_root", dataset_root)):
            if (not isinstance(value, str) or not value or not Path(value).is_absolute()
                    or ".." in Path(value).parts):
                raise ValueError(f"{name} must be an explicit absolute path")
        self.source_root, self.dataset_root = Path(source_root), Path(dataset_root)
        try:
            scene = runtime.dataset_scene(self.dataset_root)
        except OSError as exc:
            raise ValueError(f"dataset_root has no readable CALVIN {runtime.DATASET_CONFIG}") from exc
        if scene != runtime.SCENE:  # The pinned reset vectors are scene-D validation states.
            raise ValueError(f"CALVIN cases need scene {runtime.SCENE}; dataset config declares {scene!r}")
        rows = single_task.panel_record()["cases"]  # Task-major: 34 tasks x 4 trials.
        self.instructions = {row["task"]: row["instruction"] for row in rows}  # native annotation [task][0]
        if evaluation_mode == "max":  # Native get_sequences(1000) order.
            self.cases = {f"calvin-chain{index:04d}": {"chain": index, "initial_condition": condition,
                                                       "tasks": list(tasks)}
                          for index, (condition, tasks) in enumerate(long_horizon.sequences())}
        else:
            self.cases = {f"{row['task']}-trial{row['trial']:02d}": row
                          for row in (rows[:1] if evaluation_mode == "example" else rows)}
        self.evaluation_mode = evaluation_mode
        self.environment_step_cap = CHAIN_HORIZON if evaluation_mode == "max" else TASK_HORIZON
        self.protocol = PROTOCOL.format(selection=SELECTIONS[evaluation_mode], mode=evaluation_mode)
        self.claimed = False

    @property
    def descriptor(self):
        return BenchmarkDescriptor(name="calvin", version=SELECTIONS[self.evaluation_mode],
                                   protocol_version=self.protocol, source_revision=runtime.NATIVE_REVISION)
    @property
    def observation_spec(self):
        return ObservationSpec(cameras=CAMERAS, modalities=("language", "rgb"), privileged=False)

    @property
    def action_spec(self):
        return ActionSpec(mode="calvin_native_relative_euler7_debug_normalized", size=7,
                          names=("dx", "dy", "dz", "droll", "dpitch", "dyaw", "gripper"),
                          low=(-1.0,) * 7, high=(1.0,) * 7, control_hz=30,
                          frame="world-frame increments to previous commanded target; 0.02 m per input unit",
                          rotation="native Euler xyz additive increments; 0.05 rad per input unit",
                          gripper="positive opens, zero/negative closes; mapped to native +1/-1")

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("harness seed must be an integer in [0, 2**32)")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("episode limit must be a positive integer")
        if self.evaluation_mode == "max":
            # The public spec carries only the first instruction; later ones arrive one by one.
            episodes = tuple(EpisodeSpec(id=episode_id, task=CHAIN_TASK, seed=seed,
                                         instruction=self.instructions[case["tasks"][0]],
                                         metadata={
                                             "evaluation_mode": self.evaluation_mode, "chain": case["chain"],
                                             "environment_step_cap": CHAIN_HORIZON,
                                             "native_subtask_horizon": TASK_HORIZON,
                                             "native_horizon_source": "native evaluate_policy.py EP_LEN=360 per "
                                                                      "subtask, five subtasks, stop at first failure",
                                             "sequences_sha256": long_horizon.SEQUENCES_SHA256,
                                             "native_environment_seed": 0,
                                             "sample_selection": "native get_sequences(1000) order; no seed search, "
                                                                 "retries or success screening",
                                         }) for episode_id, case in self.cases.items())
            return episodes[:limit]
        episodes = tuple(EpisodeSpec(id=episode_id, task=case["task"], seed=seed, instruction=case["instruction"],
                                     metadata={
                                         "evaluation_mode": self.evaluation_mode, "trial": case["trial"],
                                         "environment_step_cap": TASK_HORIZON,
                                         "native_horizon_source": "native evaluate_policy.py EP_LEN=360 per instruction",
                                         "panel_sha256": single_task.PANEL_SHA256, "native_environment_seed": 0,
                                         "sample_selection": "pinned D validation reset; no seed search, retries or success screening",
                                     }) for episode_id, case in self.cases.items())
        return episodes[:limit]

    def open_episode(self, episode):
        if episode not in self.episodes(episode.seed):
            raise ProtocolError("CALVIN episode differs from its declared schedule")
        if self.claimed:
            raise ProtocolError("CALVIN one-case service already claimed; no automatic retry")
        self.claimed = True
        return CalvinEpisode(self, episode)


def make_calvin(parameters: Mapping[str, JsonValue]):
    allowed = {"source_root", "dataset_root", "evaluation_mode"}
    if set(parameters) - allowed:
        raise ValueError(f"unknown CALVIN parameters: {sorted(set(parameters) - allowed)}")
    if not {"source_root", "dataset_root"}.issubset(parameters):
        raise ValueError("CALVIN needs explicit pinned native source and official dataset paths")
    return CalvinBenchmarkAdapter(**parameters)
