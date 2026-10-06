"""Correlated, bounded private child-process RPC. Never retries a native action."""
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
import uuid

from benchkit.artifacts import atomic_write_json
from benchkit.errors import ProtocolError
from benchkit.sim_server.wire import dumps, loads, MAX_MESSAGE_BYTES
from benchmarks.simBenchmarks.Behavior.environment.deployment import digest

RPC_PROTOCOL = "behavior-private-rpc/v1"


class NativeOperationError(ProtocolError):
    """Correlated error: no more controls, but cleanup RPC remains possible."""


class NativeWorkerClient:
    def __init__(self, benchmark):
        self.benchmark = benchmark
        self.root = self.process = self.log = None
        self.started = self.poisoned = self.closed = False
        self.close_error = None
        self.uncertain = False
        self.error_metrics = None

    def start(self, artifact_dir):
        if self.started:
            raise ProtocolError("private worker can start only once")
        self.started = True
        self.root = Path(artifact_dir)
        manifest = self.benchmark.deployment_manifest
        if digest(manifest) != self.benchmark.deployment_manifest_sha256:
            raise ProtocolError("deployment manifest hash differs")
        identity = loads(Path(manifest).read_bytes())
        source = Path(identity["source_root"])
        python = self.benchmark.worker_python
        if identity["runtime"]["executable"] != str(python) or digest(python) != identity["runtime"]["executable_sha256"]:
            raise ProtocolError("worker executable differs from deployment capture")
        repo = Path(__file__).resolve().parents[4]
        cache = self.root / "cache"
        cache.mkdir(exist_ok=False)
        config = {"artifact_dir": str(self.root), "deployment_manifest": str(manifest),
                  "deployment_manifest_sha256": self.benchmark.deployment_manifest_sha256,
                  "gpu_id": self.benchmark.gpu_id}
        config_path = self.root / "private_worker_config.json"
        atomic_write_json(config_path, config)
        env = os.environ.copy()
        # Native child needs no server credentials or model-provider keys.
        for key in tuple(env):
            if key.startswith(("RSI_SIM_SERVER_", "OPENAI_", "ANTHROPIC_")) or key in (
                    "PYTHONHOME", "CUDA_VISIBLE_DEVICES", "OMNIGIBSON_REMOTE_STREAMING"):
                env.pop(key)
        env.update(PYTHONPATH=os.pathsep.join(map(str, (repo, source / "OmniGibson", source / "bddl3", source / "joylo"))),
                   PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
                   XDG_CACHE_HOME=str(cache), TORCH_EXTENSIONS_DIR=str(cache / "torch_extensions"),
                   MPLCONFIGDIR=str(cache / "matplotlib"))
        self.log = (self.root / "native_worker.log").open("xb")
        try:
            # Register CPython's real crash handler before native imports may
            # enable AMX/XSTATE. Late sigaltstack registration can fail with
            # ENOMEM on affected kernels; do not disable or replace the handler.
            self.process = subprocess.Popen([str(python), "-X", "faulthandler", "-B", "-m",
                "benchmarks.simBenchmarks.Behavior.environment.native_worker", str(config_path)],
                cwd=self.root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.log, bufsize=0, start_new_session=True)
        except BaseException:
            self.log.close()
            raise

    def rpc(self, op, **values):
        if self.process is None or self.closed or self.uncertain or (self.poisoned and op in ("reset", "step")):
            raise ProtocolError("private native channel unavailable or poisoned")
        try:
            return self._rpc(op, **values)
        except NativeOperationError:
            self.poisoned = True
            raise
        except BaseException:
            self.poisoned = self.uncertain = True
            raise

    def _rpc(self, op, **values):
        identifier = uuid.uuid4().hex
        process = self.process
        descriptor = process.stdout.fileno()
        os.set_blocking(descriptor, False)
        try:
            try:
                pending = os.read(descriptor, 1)
            except BlockingIOError:
                pending = None
            if pending is not None:
                raise ProtocolError("unsolicited native bytes or EOF")
            process.stdin.write(dumps({"protocol": RPC_PROTOCOL, "id": identifier, "op": op, **values}) + b"\n")
            process.stdin.flush()
            deadline = time.monotonic() + self.benchmark.worker_timeout
            data = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(descriptor, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("native response deadline exceeded; no replay")
                    chunk = os.read(descriptor, min(65536, MAX_MESSAGE_BYTES + 2 - len(data)))
                    if not chunk:
                        raise ProtocolError("native worker closed before response")
                    data.extend(chunk)
                    if len(data) > MAX_MESSAGE_BYTES + 1:
                        raise ProtocolError("native response exceeds size limit")
                    if b"\n" in data:
                        line, trailing = bytes(data).split(b"\n", 1)
                        if trailing:
                            raise ProtocolError("multiple native responses")
                        response = loads(line)
                        break
            if (response.get("id") != identifier or response.get("protocol") != RPC_PROTOCOL
                    or type(response.get("ok")) is not bool):
                raise ProtocolError("uncorrelated native response")
            expected = {"protocol", "id", "ok", "result"} if response["ok"] else {"protocol", "id", "ok", "error_type", "metrics"}
            if set(response) != expected:
                raise ProtocolError("native response fields differ")
            if not response["ok"]:
                if not isinstance(response["metrics"], dict) or type(response["error_type"]) is not str:
                    raise ProtocolError("native error receipt differs")
                self.error_metrics = response["metrics"]
                raise NativeOperationError("native worker failed: " + response["error_type"])
            if not isinstance(response["result"], dict):
                raise ProtocolError("native result must be an object")
            return response["result"]
        finally:
            os.set_blocking(descriptor, True)

    def close(self):
        if self.closed:
            if self.close_error:
                raise ProtocolError(self.close_error)
            return
        self.closed = True
        if self.process is None:
            return
        receipt = {"pid": self.process.pid, "prepare_ack": False, "forced_termination": False,
                   "child_returncode": None, "errors": []}
        try:
            if self.process.poll() is not None:
                raise ProtocolError("native worker exited before close")
            # Correlated operation-level errors leave a readable worker, but
            # uncertain transport failures must not cause another RPC/replay.
            if self.uncertain:
                raise ProtocolError("uncertain private channel; terminating owned worker")
            response = self._rpc("close")
            prepared = response.get("cleanup_prepared")
            disk = loads((self.root / "native_cleanup_prepared.json").read_bytes())
            if prepared != disk or disk.get("pid") != self.process.pid or disk.get("error_types"):
                raise ProtocolError("native cleanup prepare receipt invalid")
            receipt["prepare_ack"] = True
            self.process.wait(timeout=60)
            shutdown = loads((self.root / "native_shutdown.json").read_bytes())
            receipt["shutdown"] = shutdown
            if self.process.returncode != 0 or shutdown.get("pid") != self.process.pid:
                raise ProtocolError("native worker shutdown failed")
        except BaseException as exc:
            receipt["errors"].append(type(exc).__name__)
            self.close_error = "BEHAVIOR native cleanup failed; see worker_cleanup.json"
        finally:
            if self.process.poll() is None:
                receipt["forced_termination"] = True
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=10)
            receipt["child_returncode"] = self.process.returncode
            for stream in (self.process.stdin, self.process.stdout, self.log):
                if stream:
                    stream.close()
            atomic_write_json(self.root / "worker_cleanup.json", receipt)
        if self.close_error:
            raise ProtocolError(self.close_error)
