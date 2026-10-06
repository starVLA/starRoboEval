"""Private single-episode worker. No SIM import until the one reset request."""
import os
from pathlib import Path
import sys
import traceback

if __name__ == "__main__":
    # Before NumPy, Torch or any SDK import; importing this module for offline
    # tests must not alter the test runner's signal handling.
    from benchmarks.simBenchmarks.Behavior.environment.crash_handler import prepare_crash_handler
    prepare_crash_handler()

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.errors import ProtocolError
from benchkit.sim_server.wire import dumps, loads, encode_observation, MAX_MESSAGE_BYTES
from benchmarks.simBenchmarks.Behavior.bench_server.protocol import (
    ACTION_SPEC, HORIZON, INSTANCE, NATIVE_SEED, OBSERVATION_SPEC, TASK,
)
from benchmarks.simBenchmarks.Behavior.environment.native_bridge import (
    ExternalAction, initialize_evaluator, metric_json, public_observation, validate_loaded,
)

RPC_PROTOCOL = "behavior-private-rpc/v1"


class NativeSession:
    def __init__(self, config):
        self.config = config
        self.root = Path(config["artifact_dir"])
        self.evaluator = self.og = self.policy = None
        self.writers = {}
        self.steps = self.physics_ticks = 0
        self.reset_attempted = self.ready = self.finalized = self.closed = False
        self.terminated = self.truncated = False
        self.execution_unknown = False
        self.latest = {"success": False, "control_steps": 0, "physics_ticks": None,
                       "native_benchmark_score": None, "native_episode_complete": False}

    def reset(self):
        if self.reset_attempted:
            raise ProtocolError("one native reset preparation per claim")
        self.reset_attempted = True
        from benchmarks.simBenchmarks.Behavior.environment.deployment import verify
        identity = verify(self.config["deployment_manifest"], self.config["deployment_manifest_sha256"])
        atomic_write_json(self.root / "native_deployment.json", identity)
        os.environ["OMNIGIBSON_DATA_PATH"] = identity["data_root"]
        os.environ["OMNIGIBSON_APPDATA_PATH"] = str(self.root / "cache" / "appdata")
        os.environ["OMNIGIBSON_GPU_ID"] = str(self.config["gpu_id"])
        os.environ["OMNIGIBSON_HEADLESS"] = "true"
        import omnigibson as og
        self.og = og
        import torch
        from omegaconf import OmegaConf
        from omnigibson.eval.evaluator import Evaluator, resolve_instance_ids
        from omnigibson.eval.utils.eval_utils import seed_everything
        seed_everything(NATIVE_SEED)
        if resolve_instance_ids(TASK, [0], "public_test") != [INSTANCE]:
            raise ProtocolError("native public instance mapping changed")
        self.policy = ExternalAction(lambda values: torch.tensor(values, dtype=torch.float32))
        supplied = self.policy

        class SuppliedActionEvaluator(Evaluator):
            def load_policy(self):
                return supplied

        cfg = OmegaConf.create({"env_wrapper": {"_target_": "omnigibson.eval.wrappers.DefaultWrapper"},
            "policy_name": "external-one-action-bridge", "model": None, "headless": True,
            "partial_scene_load": True, "max_steps": None, "write_video": False,
            "mode": "public_test", "seed": NATIVE_SEED, "task": {"name": TASK}, "robot": None})
        # Preserve a partially initialized object so cleanup owns its env even
        # if native construction raises after allocating simulation resources.
        self.evaluator = SuppliedActionEvaluator.__new__(SuppliedActionEvaluator)
        SuppliedActionEvaluator.__init__(self.evaluator, cfg)
        from benchmarks.simBenchmarks.Behavior.environment.crash_handler import prepare_crash_handler
        atomic_write_json(self.root / "native_crash_handler_after_init.json", prepare_crash_handler())
        loaded = validate_loaded(self.evaluator, og.sim)
        before = int(og.sim.current_time_step_index)
        initialize_evaluator(self.evaluator)
        after = int(og.sim.current_time_step_index)
        self.ready = True
        loaded.update({"reset_load_reset_counter_before": before, "reset_load_reset_counter_after": after,
                       "initialization_scope": "clock samples after constructor and after native reset/load/reset; not total startup physics"})
        atomic_write_json(self.root / "loaded_contract.json", loaded)
        return self.observe()

    def observe(self):
        observation = public_observation(self.evaluator.obs, self.steps)
        import imageio.v2 as imageio
        for name, rgb in observation.images.items():
            if name not in self.writers:
                self.writers[name] = imageio.get_writer(str(self.root / f"video_{name}.mp4"), fps=30,
                                                       macro_block_size=1)
            self.writers[name].append_data(rgb)
        return {"observation": encode_observation(observation, OBSERVATION_SPEC), "metrics": self.summary(),
                "terminated": self.terminated, "truncated": self.truncated}

    def step(self, action):
        if not self.ready or self.finalized or self.terminated or self.truncated or self.steps >= HORIZON:
            raise ProtocolError("native episode is not accepting controls")
        values = ACTION_SPEC.validate(action)
        self.policy.queue(values)
        before = int(self.og.sim.current_time_step_index)
        calls = self.policy.calls
        self.execution_unknown = True
        self.terminated, self.truncated = map(bool, self.evaluator.step())
        self.steps += 1
        after = int(self.og.sim.current_time_step_index)
        delta = after - before
        self.physics_ticks += delta
        self.execution_unknown = False
        append_jsonl(self.root / "native_controls.jsonl", {"control": self.steps, "action": list(values),
            "physics_before": before, "physics_after": after, "physics_delta": delta,
            "terminated": self.terminated, "truncated": self.truncated})
        if self.policy.calls != calls + 1 or self.policy.pending is not None or delta != 4:
            raise ProtocolError("native control/action consumption/physics accounting differs")
        if self.steps == HORIZON and not (self.terminated or self.truncated):
            raise ProtocolError("native horizon did not terminate at configured task cap")
        return self.observe()

    def summary(self):
        if self.ready:
            self.latest.update(success=bool(self.evaluator.env.task.success), control_steps=self.steps,
                physics_ticks=self.physics_ticks, native_episode_complete=self.terminated or self.truncated,
                terminated=self.terminated, truncated=self.truncated,
                in_flight_native_execution_unknown=self.execution_unknown)
        return dict(self.latest)

    def metrics(self):
        self.summary()
        if self.ready:
            native = {}
            for metric in self.evaluator.metrics:
                native.update(metric.aggregate(self.evaluator.env))
            self.latest["native_metrics"] = metric_json(native)
            score = native.get("q_score", {}).get("final")
            self.latest["native_benchmark_score"] = metric_json(score)
        return dict(self.latest)

    def finalize(self):
        if not self.finalized:
            self.finalized = True
            errors = []
            for writer in self.writers.values():
                try:
                    writer.close()
                except Exception as exc:
                    errors.append(exc)
            self.writers = {}
            atomic_write_json(self.root / "native_outcome.json", self.metrics())
            if errors:
                raise errors[0]
        return {"metrics": dict(self.latest), "artifacts": {"native_outcome": "native_outcome.json",
            **{f"video_{name}": f"video_{name}.mp4" for name in OBSERVATION_SPEC.cameras
               if (self.root / f"video_{name}.mp4").is_file()}}}

    def close_prepare(self):
        if self.closed:
            raise ProtocolError("private worker close already requested")
        self.closed = True
        errors = []
        try:
            self.finalize()
        except Exception as exc:
            errors.append(type(exc).__name__)
        env_closed = False
        if self.evaluator is not None and getattr(self.evaluator, "env", None) is not None:
            if hasattr(self.evaluator, "_video_writer"):
                try:
                    self.evaluator.video_writer = None
                except Exception as exc:
                    errors.append(type(exc).__name__)
            try:
                self.evaluator.env.close()
                env_closed = True
            except Exception as exc:
                errors.append(type(exc).__name__)
        receipt = {"pid": os.getpid(), "native_env_close_returned": env_closed,
                   "reset_completed": self.ready, "error_types": errors}
        atomic_write_json(self.root / "native_cleanup_prepared.json", receipt)
        return {"cleanup_prepared": receipt}

    def shutdown(self):
        if not self.closed:
            self.close_prepare()
        og = self.og or sys.modules.get("omnigibson")
        receipt = {"pid": os.getpid(), "shutdown_started": og is not None, "shutdown_return_observed": False}
        atomic_write_json(self.root / "native_shutdown.json", receipt)
        if og is not None:
            og.shutdown()
        receipt["shutdown_return_observed"] = True
        atomic_write_json(self.root / "native_shutdown.json", receipt)


def main():
    # Native libraries write to file descriptor 1; preserve a separate protocol
    # stream and redirect fd1 to the private log before importing any simulator.
    channel = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    config = loads(Path(sys.argv[1]).read_bytes())
    from benchmarks.simBenchmarks.Behavior.environment.crash_handler import prepare_crash_handler
    atomic_write_json(Path(config["artifact_dir"]) / "native_crash_handler.json", prepare_crash_handler())
    session = NativeSession(config)
    poisoned = False
    try:
        while True:
            line = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 2)
            if not line:
                break
            request = loads(line.rstrip(b"\n"))
            op = request.get("op")
            allowed = {"protocol", "id", "op"} | ({"action"} if op == "step" else set())
            if (set(request) != allowed or request.get("protocol") != RPC_PROTOCOL
                    or type(request.get("id")) is not str or op not in ("reset", "step", "metrics", "finalize", "close")):
                raise ProtocolError("invalid private request envelope")
            response = {"protocol": RPC_PROTOCOL, "id": request["id"]}
            try:
                if poisoned and op in ("reset", "step"):
                    raise ProtocolError("private native session poisoned")
                if op == "step":
                    result = session.step(request["action"])
                elif op == "close":
                    result = session.close_prepare()
                else:
                    result = getattr(session, op)()
                response.update(ok=True, result=result)
            except Exception as exc:
                poisoned = True
                append_jsonl(session.root / "native_errors.jsonl", {"operation": op,
                    "error_type": type(exc).__name__, "traceback": traceback.format_exc()})
                response.update(ok=False, error_type=type(exc).__name__, metrics=session.summary())
            channel.write(dumps(response) + b"\n")
            if op == "close":
                break
    finally:
        session.shutdown()
        channel.close()


if __name__ == "__main__":
    main()
