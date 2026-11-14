"""Private SIMPLE worker transport and process lifecycle.

The adapter owns reset payloads, public observations, actions and native scoring.
This client only launches the pinned worker, transports RPC and closes artifacts.
No native simulator or model is imported here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from typing import Any, Mapping

from benchkit.errors import CompatibilityError, ProtocolError

CLOSE_TIMEOUT = 60  # bound graceful close; close() then terminates the worker


def worker_environment(benchmark, artifact_dir: Path, repo: Path,
    environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build worker settings; toolchain location is an operator input, not a pin."""
    source = benchmark.simple_root
    env = dict(os.environ if environ is None else environ)
    for name in ("CUDA_VISIBLE_DEVICES", "MAX_EPISODE_STEPS", "SUCCESS_CRITERIA"):
        env.pop(name, None)
    env.update({
        "PYTHONPATH": os.pathsep.join(map(str, (repo, source / "src", source / "third_party/curobo/src",
            source / "third_party", source / "third_party/unitree_sdk2_python"))),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "PYTHONFAULTHANDLER": "1", "SIMPLE_ISAAC_GPU_ID": str(benchmark.gpu_id),
        "MUJOCO_GL": "egl", "PYOPENGL_PLATFORM": "egl", "SIMPLE_DISABLE_TUI": "1",
        "OMNI_KIT_ACCEPT_EULA": "YES", "ACCEPT_EULA": "Y",
        "SIMPLE_ISAAC_CPU_THREADS": "8", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
        "GIT_OPTIONAL_LOCKS": "0", "MODIFIED_POLICY_SWITCH_BEHAVIOR": "0",
        "TORCH_EXTENSIONS_DIR": str(artifact_dir / "cache/torch_extensions"),
        "XDG_CACHE_HOME": str(artifact_dir / "cache"),
    })
    if benchmark.cuda_root is not None:
        env["CUDA_HOME"] = str(benchmark.cuda_root)
        for name, suffix in (("CPATH", "include"), ("LD_LIBRARY_PATH", "lib")):
            path = str(benchmark.cuda_root / "targets/x86_64-linux" / suffix)
            env[name] = os.pathsep.join(filter(None, (path, env.get(name, ""))))
    return env


class NativeWorkerClient:
    def __init__(self, benchmark, episode) -> None:
        self.benchmark, self.episode = benchmark, episode
        self.artifact_dir: Path | None = None
        self.process: subprocess.Popen | None = None
        self.log: Any = None
        self.broken = False
        self.worker_artifacts: dict[str, Any] = {}

    def bind_artifact_dir(self, path: Path) -> None:
        self.artifact_dir = path.resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _rpc(self, request: Mapping[str, Any], timeout: float | None = None) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise ProtocolError("SIMPLE worker is not running")
        if self.broken:
            raise ProtocolError("SIMPLE worker transport failed earlier; no further RPC")
        try:
            result = self._exchange(request, self.benchmark.worker_timeout if timeout is None else timeout)
        except BaseException:
            # A late response to this request could be misread as the next one.
            self.broken = True
            raise
        if not result.get("ok"):
            raise RuntimeError(f"SIMPLE native worker: {result.get('error')}; inspect native_error.json")
        return result["result"]

    def _exchange(self, request: Mapping[str, Any], timeout: float) -> dict[str, Any]:
        self.process.stdin.write(json.dumps(request, allow_nan=False).encode() + b"\n")
        self.process.stdin.flush()
        # Read raw bytes under one deadline: a partial line must not block.
        descriptor = self.process.stdout.fileno()
        deadline = time.monotonic() + timeout
        data = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_READ)
            while b"\n" not in data:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("SIMPLE worker timed out; inspect native_worker.log")
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    raise RuntimeError(f"SIMPLE worker exited ({self.process.poll()}); inspect native_worker.log")
                data.extend(chunk)
        line, trailing = bytes(data).split(b"\n", 1)
        if trailing:
            raise ProtocolError("SIMPLE worker sent more than one response")
        result = json.loads(line)
        if not isinstance(result, dict):
            raise ProtocolError("SIMPLE worker response must be an object")
        return result

    def _start_worker(self) -> None:
        if self.process is not None:
            raise ProtocolError("an episode session may be reset only once")
        if self.artifact_dir is None:
            raise ProtocolError("SIMPLE requires an artifact directory before reset")
        repo = Path(__file__).resolve().parents[4]
        worker = repo / "benchmarks/simBenchmarks/SIMPLE/environment/native_worker.py"
        source = self.benchmark.simple_root
        python = self.benchmark.python_executable
        if not python.is_file() or not worker.is_file():
            raise CompatibilityError("missing configured SIMPLE interpreter or RSI native worker")
        env = worker_environment(self.benchmark, self.artifact_dir, repo)
        self.log = (self.artifact_dir / "native_worker.log").open("x")
        try:
            self.process = subprocess.Popen(
                [str(python), str(worker)], cwd=source, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.log, bufsize=0,
            )
        except BaseException:
            self.log.close()
            raise

    def artifacts(self) -> Mapping[str, Any]:
        if self.process is not None and self.process.poll() is None:
            self.worker_artifacts = self._rpc({"op": "finalize"})
        return dict(self.worker_artifacts)

    def close(self) -> None:
        if self.process is not None:
            try:
                # A broken transport gets no graceful close RPC: a stale late
                # response could be read as its acknowledgement.
                if not self.broken and self.process.poll() is None:
                    try:
                        self._rpc({"op": "close"}, timeout=CLOSE_TIMEOUT)
                        self.process.wait(timeout=30)
                    except Exception:
                        pass  # fall through to forced termination
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=10)
            finally:
                for stream in (self.process.stdin, self.process.stdout):
                    if stream:
                        stream.close()
                if self.log:
                    self.log.close()
