"""R2R RGB navigation service; native Habitat alone owns state and scoring."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Mapping

from benchkit.contracts import ActionSpec, BenchmarkDescriptor, EpisodeSpec, Observation, ObservationSpec, Transition, Usage
from benchkit.errors import ActionRejected, ProtocolError
from benchkit.validation import ValidationIssue, validate_action_vector
from ..environment.native_runtime import scene_path
from .native_worker_client import NativeOperationError, NativeWorkerClient

PROTOCOL = "vlnce-r2r-habitat033/rgb512/native500/v1"
HORIZON = 500
ACTION_SPEC = ActionSpec(mode="habitat_discrete_navigation_v0", size=1, names=("action_id",),
    low=(0.0,), high=(3.0,), control_hz=None,
    frame="integer IDs: 0 STOP; 1 MOVE_FORWARD 0.25 m; 2 TURN_LEFT 15 deg; 3 TURN_RIGHT 15 deg; native collision/sliding",
    rotation="native relative yaw; left +15 degrees, right -15 degrees", gripper="not applicable")
OBSERVATION_SPEC = ObservationSpec(cameras=("rgb",), modalities=("language", "rgb"), privileged=False)
MAX_DATA_BYTES = 64 * 1024 * 1024


def _file(value, label):
    if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_file():
        raise ValueError(label + " must be an existing absolute file")
    return Path(value).resolve()


def _read_gzip(path):
    with gzip.open(path, "rb") as stream:
        payload = stream.read(MAX_DATA_BYTES + 1)
    if len(payload) > MAX_DATA_BYTES:
        raise ValueError("R2R JSON exceeds supported size")
    return json.loads(payload)


def validate_action(values):
    result = validate_action_vector(ACTION_SPEC, values)
    if not result[0].is_integer():
        raise ActionRejected(ValidationIssue("invalid_action", actual=result[0], action_index=0), usage=Usage())
    return result


def native_metrics(value, expected_step):
    if not isinstance(value, Mapping) or type(value.get("native_steps")) is not int or value["native_steps"] != expected_step:
        raise ProtocolError("VLN-CE native metrics step differs")
    success = value.get("success")
    if type(success) not in (bool, int, float) or success not in (False, True, 0.0, 1.0):
        raise ProtocolError("VLN-CE native success must be boolean or zero/one")
    result = {"success": bool(success), "native_steps": expected_step}
    for key in ("distance_to_goal", "spl"):
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
            raise ProtocolError("VLN-CE native metric is absent or invalid: " + key)
        if key == "spl" and number > 1:
            raise ProtocolError("VLN-CE native SPL is outside [0,1]")
        result[key] = float(number)
    return result


class VLNCEEpisode:
    def __init__(self, benchmark, episode):
        self.benchmark, self.episode = benchmark, episode
        self.worker = None
        self.artifact_dir = None
        self.steps = 0
        self.known_native_steps = 0
        self.finished = self.reset_attempted = self.finalized = self.closed = False
        self.faulted = False
        self.cached_metrics = {}
        self.cached_artifacts = {}
        self.failure_receipt = None
        self.artifact_attempted = False
        self.artifact_error = None
        self.cleanup_errors = []
        self.close_error = None

    def bind_artifact_dir(self, path):
        if self.artifact_dir is not None or self.reset_attempted:
            raise ProtocolError("VLN-CE artifacts must be bound once before reset")
        self.artifact_dir = Path(path).resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _observation(self, result):
        import numpy as np
        from PIL import Image
        # EpisodeSpec strips outer whitespace. Native R2R instructions may end
        # with a space; normalize that same boundary without rewriting the text.
        instruction = result.get("instruction")
        if (not isinstance(instruction, str) or instruction.strip() != self.episode.instruction
                or type(result.get("step")) is not int or result["step"] != self.steps):
            raise ProtocolError("VLN-CE public observation identity differs")
        frame = result.get("frame")
        if frame != f"rgb-{self.steps:06d}.png":
            raise ProtocolError("VLN-CE frame filename must match the acknowledged step")
        fd = os.open(self.artifact_dir / frame, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ProtocolError("VLN-CE frame is not a regular file")
            with os.fdopen(fd, "rb", closefd=False) as stream, Image.open(stream) as image:
                if image.mode != "RGB" or image.size != (512, 512):
                    raise ProtocolError("VLN-CE requires original RGB 512x512")
                rgb = np.asarray(image).copy()
        finally:
            os.close(fd)
        if rgb.dtype != np.uint8 or rgb.shape != (512, 512, 3):
            raise ProtocolError("invalid VLN-CE RGB array")
        # No native instruction dictionary, trajectory ID, metric, pose or depth.
        return Observation(step=self.steps, instruction=self.episode.instruction, images={"rgb": rgb})

    def _retain_failure_metrics(self, result):
        """Retain read-only native counters without inventing an action ACK."""
        count = result.get("native_steps") if isinstance(result, dict) else None
        measured_at = result.get("metrics_at_native_step") if isinstance(result, dict) else None
        if (type(count) is not int or not self.known_native_steps <= count <= min(self.steps + 1, HORIZON)
                or type(measured_at) is not int or not 0 <= measured_at <= count
                or type(result.get("execution_in_flight")) is not bool
                or type(result.get("native_error")) is not bool):
            raise ProtocolError("VLN-CE failed-operation counters are invalid")
        observed = native_metrics(result, count)
        self.known_native_steps = count
        self.failure_receipt = dict(last_acknowledged_steps=self.steps, known_native_steps=count,
            execution_in_flight=result["execution_in_flight"], metrics_at_native_step=measured_at,
            cached_metrics=observed, metrics_current=measured_at == count and not result["execution_in_flight"],
            outcome="infrastructure_error", score_valid_for_evaluation=False)
        (self.artifact_dir / "native_failure_receipt.json").write_text(
            json.dumps(self.failure_receipt, allow_nan=False, indent=2) + "\n")

    def _recover_correlated_counts(self):
        # A correlated native exception is distinct from an uncertain transport.
        # This read cannot execute/reset a control. Never enqueue it on poison.
        if self.worker is None or self.worker.poisoned:
            return
        timeout = self.worker.timeout
        try:
            self.worker.timeout = min(timeout, 5.0)
            self._retain_failure_metrics(self.worker.request("metrics"))
        except Exception:
            # Preserve the original failure and native_progress.json. Missing
            # recovery never turns an uncertain action into proven zero motion.
            self.failure_receipt = dict(last_acknowledged_steps=self.steps,
                known_native_steps=self.known_native_steps, execution_in_flight=None,
                outcome="infrastructure_error", score_valid_for_evaluation=False,
                counter_recovery="unavailable; inspect native_progress.json")
            try:
                (self.artifact_dir / "native_failure_receipt.json").write_text(
                    json.dumps(self.failure_receipt, indent=2) + "\n")
            except OSError:
                # Evidence storage failure must not replace the control error.
                pass
        finally:
            self.worker.timeout = timeout

    def _retain_cleanup_error(self, phase, error, primary_error):
        """Keep secondary cleanup faults without masking the triggering error."""
        self.cleanup_errors.append(dict(phase=phase, error_type=type(error).__name__, message=str(error)))
        if hasattr(primary_error, "add_note"):
            primary_error.add_note("VLN-CE " + phase + " cleanup also failed: " + type(error).__name__)
        try:
            (self.artifact_dir / "native_cleanup_errors.json").write_text(
                json.dumps(self.cleanup_errors, indent=2) + "\n")
            self.cached_artifacts["native_cleanup"] = "native_cleanup_errors.json"
        except OSError:
            pass

    def reset(self):
        if self.reset_attempted or self.closed or self.artifact_dir is None:
            raise ProtocolError("VLN-CE reset is allowed exactly once with bound artifacts")
        self.reset_attempted = True
        config = self.benchmark.worker_config(self.episode, self.artifact_dir)
        try:
            self.worker = NativeWorkerClient(self.benchmark.python_executable,
                Path(__file__).resolve().parents[1] / "environment/native_worker.py", config,
                self.artifact_dir, self.benchmark.worker_timeout)
            result = self.worker.request("reset")
            self.cached_metrics = native_metrics(result.get("metrics"), 0)
            return self._observation(result)
        except BaseException as exc:
            self.faulted = True
            # Finalize while the correlated worker is still available. Closing
            # it first makes later artifact collection send RPC to a dead child.
            operations = [("artifacts", self.artifacts), ("close", self.close)]
            if isinstance(exc, NativeOperationError):
                operations.insert(0, ("counter_recovery", self._recover_correlated_counts))
            for phase, cleanup in operations:
                try:
                    cleanup()
                except BaseException as cleanup_error:
                    self._retain_cleanup_error(phase, cleanup_error, exc)
            raise

    def step(self, action):
        if self.worker is None or self.closed or self.finalized or self.finished or self.faulted:
            raise ProtocolError("VLN-CE episode is not accepting controls")
        command = int(validate_action(action)[0])
        try:
            result = self.worker.request("step", {"action": command})
            if type(result.get("step")) is not int or result["step"] != self.steps + 1:
                raise ProtocolError("VLN-CE native control counter differs")
            self.steps = result["step"]
            self.known_native_steps = self.steps
            self.cached_metrics = native_metrics(result.get("metrics"), self.steps)
            terminated, truncated = result.get("terminated"), result.get("truncated")
            if (type(terminated) is not bool or type(truncated) is not bool
                    or terminated != (command == 0)
                    or truncated != (self.steps >= HORIZON and command != 0)
                    or self.steps > HORIZON):
                raise ProtocolError("VLN-CE native STOP/horizon flags differ")
            if self.cached_metrics["success"] and command != 0:
                raise ProtocolError("VLN-CE success requires a requested native STOP")
            self.finished = terminated or truncated
            return Transition(self._observation(result), reward=0.0,
                terminated=terminated, truncated=truncated, info=dict(self.cached_metrics))
        except BaseException as exc:
            self.faulted = True
            if isinstance(exc, NativeOperationError):
                self._recover_correlated_counts()
            raise

    def metrics(self):
        if self.faulted:
            raise ProtocolError("VLN-CE metrics are not a valid score after an infrastructure error; inspect native failure evidence")
        return dict(self.cached_metrics)

    def artifacts(self):
        if self.finalized:
            return dict(self.cached_artifacts)
        if self.artifact_attempted:
            raise ProtocolError("VLN-CE artifact finalization already failed; no retry") from self.artifact_error
        self.artifact_attempted = True
        try:
            if self.worker is not None and not self.worker.poisoned:
                result = self.worker.request("finish")
                if self.faulted:
                    # Failed initialization may have no metrics or RGB yet.
                    # Preserve any finalized evidence without inventing a score.
                    if result.get("metrics") is not None:
                        self._retain_failure_metrics(result["metrics"])
                else:
                    self.cached_metrics = native_metrics(result.get("metrics"), self.steps)
                artifacts = result.get("artifacts")
                expected = {"video": "rgb.mp4", "frames": "frames.jsonl", "native_provenance": "native_provenance.json"}
                if (not isinstance(artifacts, dict)
                        or any(expected.get(key) != value for key, value in artifacts.items())
                        or (not self.faulted and artifacts != expected)):
                    raise ProtocolError("VLN-CE native artifact map differs")
                for filename in artifacts.values():
                    path = self.artifact_dir / filename
                    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
                        raise ProtocolError("VLN-CE finalized artifact is absent or unsafe")
                self.cached_artifacts.update(artifacts)
                if self.failure_receipt is not None:
                    self.cached_artifacts["native_failure"] = "native_failure_receipt.json"
        except BaseException as exc:
            self.artifact_error = exc
            raise
        self.finalized = True
        return dict(self.cached_artifacts)

    def close(self):
        if self.closed:
            if self.close_error is not None:
                raise ProtocolError("VLN-CE worker cleanup previously failed") from self.close_error
            return
        self.closed = True
        if self.worker is not None:
            try:
                self.worker.close()
            except BaseException as exc:
                self.close_error = exc
                raise


class VLNCEBenchmarkAdapter:
    environment_step_cap = HORIZON
    budget_mode = "horizon"
    max_policy_calls = None

    def __init__(self, *, dataset_path, scenes_dir, episode_ids, split, python_executable,
                 gpu_id=0, worker_timeout=120, gt_path=None):
        if split not in ("val_seen", "val_unseen"):
            raise ValueError("VLN-CE supports locally scored val_seen or val_unseen")
        if (type(episode_ids) not in (list, tuple) or not episode_ids
                or any(type(x) is not str or not x for x in episode_ids)
                or len(set(episode_ids)) != len(episode_ids)):
            raise ValueError("episode_ids must be an explicit nonempty unique string list")
        self.dataset_path = _file(dataset_path, "dataset_path")
        _file(python_executable, "python_executable")
        # Keep an explicitly selected venv entrypoint: resolving its symlink can
        # select the base Python and silently discard that environment's packages.
        self.python_executable = Path(python_executable).absolute()
        if not os.access(self.python_executable, os.X_OK):
            raise ValueError("python_executable must be executable")
        if not isinstance(scenes_dir, str) or not Path(scenes_dir).is_absolute() or not Path(scenes_dir).is_dir():
            raise ValueError("scenes_dir must be an existing absolute directory")
        if type(gpu_id) is not int or gpu_id < 0:
            raise ValueError("gpu_id must be a nonnegative integer")
        if type(worker_timeout) not in (int, float) or not math.isfinite(worker_timeout) or worker_timeout <= 0:
            raise ValueError("worker_timeout must be finite and positive")
        self.scenes_dir = Path(scenes_dir).resolve()
        self.split, self.gpu_id, self.worker_timeout = split, gpu_id, worker_timeout
        self.dataset_sha256 = hashlib.sha256(self.dataset_path.read_bytes()).hexdigest()
        data = _read_gzip(self.dataset_path)
        episodes = data.get("episodes") if isinstance(data, dict) else None
        if not isinstance(episodes, list) or not episodes:
            raise ValueError("R2R dataset must contain episodes")
        lookup = {}
        for row in episodes:
            identity = str(row["episode_id"])
            if identity in lookup:
                raise ValueError("R2R dataset contains duplicate episode IDs")
            lookup[identity] = row
        if any(identity not in lookup for identity in episode_ids):
            raise ValueError("selected episode ID absent from declared dataset")
        self.selected = tuple(lookup[identity] for identity in episode_ids)
        for row in self.selected:
            try:
                scene = scene_path(self.scenes_dir, row["scene_id"])
            except ValueError:
                raise ValueError("R2R scene must be a relative .glb path under scenes_dir") from None
            if not scene.is_file() or not scene.with_suffix(".navmesh").is_file():
                raise ValueError("selected R2R scene mesh or navmesh is unavailable")
            instruction = row.get("instruction", {}).get("instruction_text")
            if not isinstance(instruction, str) or not instruction.strip():
                raise ValueError("selected episode instruction is missing")
        self.gt_path = _file(gt_path, "gt_path") if gt_path is not None else None
        self.gt_sha256 = None
        if self.gt_path is not None:
            gt = _read_gzip(self.gt_path)
            if not isinstance(gt, dict) or set(lookup) - set(gt):
                raise ValueError("GT must cover the complete declared episode split")
            self.gt_sha256 = hashlib.sha256(self.gt_path.read_bytes()).hexdigest()
        self.claims = set()

    @property
    def descriptor(self):
        return BenchmarkDescriptor(name="vln_ce", version="R2R-v1-3/Habitat-0.3.3", protocol_version=PROTOCOL,
            source_revision="Habitat-Sim/Lab 0.3.3; installed runtime inventory recorded at reset")

    @property
    def observation_spec(self): return OBSERVATION_SPEC

    @property
    def action_spec(self): return ACTION_SPEC

    def validate_action_input(self, values): return validate_action(values)

    def episodes(self, seed, limit=None):
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("seed must be an integer in [0, 2**32)")
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError("episode limit must be positive")
        return tuple(EpisodeSpec(id=f"selection-{i:06d}", task="vlnce_r2r_" + self.split,
            seed=seed, instruction=row["instruction"]["instruction_text"],
            metadata={"native_horizon": HORIZON, "environment_step_cap": HORIZON,
                "budget_mode": "horizon", "split": self.split, "selection_index": i})
            for i, row in enumerate(self.selected[:limit]))

    def worker_config(self, episode, artifact_dir):
        if episode not in self.episodes(episode.seed):
            raise ProtocolError("VLN-CE episode differs from fixed schedule")
        result = dict(dataset_path=str(self.dataset_path), scenes_dir=str(self.scenes_dir),
            episode_id=str(self.selected[episode.metadata["selection_index"]]["episode_id"]),
            seed=episode.seed, gpu_id=self.gpu_id, artifact_dir=str(artifact_dir),
            expected_dataset_sha256=self.dataset_sha256)
        if self.gt_path is not None:
            result.update(gt_path=str(self.gt_path), expected_gt_sha256=self.gt_sha256)
        return result

    def open_episode(self, episode):
        if episode not in self.episodes(episode.seed) or episode.id in self.claims:
            raise ProtocolError("VLN-CE episode is not unclaimed in the fixed schedule")
        self.claims.add(episode.id)
        return VLNCEEpisode(self, episode)


def make_vlnce(parameters):
    allowed = {"dataset_path", "scenes_dir", "episode_ids", "split", "python_executable",
               "gpu_id", "worker_timeout", "gt_path"}
    if not isinstance(parameters, Mapping) or set(parameters) - allowed:
        raise ValueError("unknown VLN-CE server parameters")
    return VLNCEBenchmarkAdapter(**parameters)
