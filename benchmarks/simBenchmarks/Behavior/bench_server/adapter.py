"""BEHAVIOR DefaultWrapper service; all native execution stays private."""
from pathlib import Path

from benchkit.contracts import BenchmarkDescriptor, EpisodeSpec, Transition
from benchkit.errors import ProtocolError
from benchkit.sim_server.wire import decode_observation
from benchmarks.simBenchmarks.Behavior.bench_server.protocol import (
    ACTION_SPEC, EVALUATION_MODES, FIRST_INSTANCE, MODE_PUBLIC_INDICES, NATIVE_SEED, OBSERVATION_SPEC,
    PROTOCOL, REVISION, TASK, task_definition,
)
from benchmarks.simBenchmarks.Behavior.bench_server.native_worker_client import NativeWorkerClient


class BehaviorEpisode:
    def __init__(self, benchmark, episode):
        self.benchmark, self.episode = benchmark, episode
        self.worker = NativeWorkerClient(benchmark)
        self.artifact_dir = None
        self.steps = 0
        self.reset_attempted = self.ready = self.finished = False
        self.latest = {"success": False, "control_steps": 0, "physics_ticks": None,
                       "native_benchmark_score": None, "native_episode_complete": False}
        self.artifact_map = None

    def bind_artifact_dir(self, path):
        self.artifact_dir = Path(path).resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _observation(self, result):
        observation = decode_observation(result["observation"], OBSERVATION_SPEC)
        if observation.step != self.steps or observation.instruction != self.benchmark.task_spec.instruction:
            raise ProtocolError("native observation identity/count differs")
        if any(image.shape != (224, 224, 3) for image in observation.images.values()):
            raise ProtocolError("native RGB size differs")
        metrics = result.get("metrics")
        if not isinstance(metrics, dict) or metrics.get("control_steps") != self.steps or metrics.get("physics_ticks") != self.steps * 4:
            raise ProtocolError("native control/physics counters differ")
        self.latest = metrics
        return observation

    def reset(self):
        if self.reset_attempted or self.artifact_dir is None:
            raise ProtocolError("reset requires bound artifacts and one unattempted claim")
        self.reset_attempted = True
        self.worker.start(self.artifact_dir, self.episode)
        observation = self._observation(self.worker.rpc("reset"))
        self.ready = True
        return observation

    def step(self, action):
        values = ACTION_SPEC.validate(action)
        if not self.ready or self.finished or self.steps >= self.benchmark.environment_step_cap:
            raise ProtocolError("BEHAVIOR episode is not running")
        result = self.worker.rpc("step", action=list(values))
        self.steps += 1
        observation = self._observation(result)
        if any(type(result.get(key)) is not bool for key in ("terminated", "truncated")):
            raise ProtocolError("native terminal flags must be boolean")
        self.finished = result["terminated"] or result["truncated"]
        # Native Evaluator intentionally feeds zero reward to its metrics;
        # binary success/Q live in private metrics, not actor observations.
        return Transition(observation, 0.0, result["terminated"], result["truncated"], {})

    def metrics(self):
        if self.worker.error_metrics is not None:
            self.latest.update(self.worker.error_metrics)
        if self.ready and not self.worker.closed and not self.worker.uncertain:
            self.latest = self.worker.rpc("metrics")
        return dict(self.latest)

    def artifacts(self):
        if self.artifact_map is None:
            self.finished = True
            if self.worker.process is not None and not self.worker.closed and not self.worker.uncertain:
                result = self.worker.rpc("finalize")
                self.latest = result["metrics"]
                self.artifact_map = result["artifacts"]
            else:
                self.artifact_map = {}
        return dict(self.artifact_map)

    def close(self):
        self.finished = True
        self.worker.close()


class BehaviorBenchmarkAdapter:
    action_spec = ACTION_SPEC
    observation_spec = OBSERVATION_SPEC

    def __init__(self, deployment_manifest, deployment_manifest_sha256, worker_python, gpu_id=0, worker_timeout=1800,
                 task=TASK, evaluation_mode="fast"):
        if evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"evaluation_mode must be one of {', '.join(EVALUATION_MODES)}; got {evaluation_mode!r}")
        self.evaluation_mode = evaluation_mode
        self.public_indices = MODE_PUBLIC_INDICES[evaluation_mode]  # one rollout each, for the deployed task only
        self.task_spec = task_definition(task)
        self.task = self.task_spec.name
        self.environment_step_cap = self.task_spec.control_cap  # native timeout fires on this control
        for value in (deployment_manifest, worker_python):
            if not isinstance(value, str) or not Path(value).is_absolute() or ".." in Path(value).parts:
                raise ValueError("explicit absolute deployment manifest/interpreter paths required")
        if (not isinstance(deployment_manifest_sha256, str) or len(deployment_manifest_sha256) != 64
                or any(c not in "0123456789abcdef" for c in deployment_manifest_sha256)):
            raise ValueError("deployment manifest SHA256 required")
        if type(gpu_id) is not int or gpu_id < 0 or type(worker_timeout) is not int or not 1 <= worker_timeout <= 3600:
            raise ValueError("invalid GPU or bounded worker timeout")
        self.deployment_manifest = Path(deployment_manifest)
        self.deployment_manifest_sha256 = deployment_manifest_sha256
        self.worker_python = Path(worker_python)
        self.gpu_id, self.worker_timeout = gpu_id, worker_timeout
        self.claimed = False

    @property
    def descriptor(self):
        return BenchmarkDescriptor("behavior", "2026-v3.9.2-defaultwrapper-selected-tasks",
                                   PROTOCOL.format(mode=self.evaluation_mode), REVISION)

    def episodes(self, seed, limit=None):
        count = len(self.public_indices)
        if type(seed) is not int or not 0 <= seed < 2**32 or (limit is not None and (type(limit) is not int or not 1 <= limit <= count)):
            raise ValueError(f"uint32 harness seed and limit in 1..{count} required")
        return tuple(EpisodeSpec(f"{self.task}-public{index}-instance{FIRST_INSTANCE + index}-rollout0", self.task, seed,
            self.task_spec.instruction,
            {"evaluation_mode": self.evaluation_mode, "native_seed": NATIVE_SEED, "public_index": index,
             "native_instance": FIRST_INSTANCE + index, "native_timeout_steps": self.task_spec.native_timeout_steps,
             "native_control_cap": self.environment_step_cap, "environment_step_cap": self.environment_step_cap,
             "selection": "selected DefaultWrapper case; no full RGBD parity"})
            for index in self.public_indices[:limit])

    def open_episode(self, episode):
        if self.claimed or episode not in self.episodes(episode.seed):
            raise ProtocolError("BEHAVIOR claims one listed case per process; launch each with --episode-id")
        self.claimed = True
        return BehaviorEpisode(self, episode)


def make_behavior(parameters):
    allowed = {"deployment_manifest", "deployment_manifest_sha256", "worker_python", "gpu_id", "worker_timeout",
               "task", "evaluation_mode"}
    if set(parameters) - allowed:
        raise ValueError("unknown BEHAVIOR server parameters")
    return BehaviorBenchmarkAdapter(**parameters)
