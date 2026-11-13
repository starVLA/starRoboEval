"""Bounded, correlated private worker RPC; no simulator or model imports."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from benchkit.errors import InfrastructureError, ProtocolError

MAX_LINE = 16 * 1024 * 1024
# Native Env.close() has already acknowledged before this interval. Habitat's
# interpreter/GPU-library finalizers can nevertheless need more than two seconds.
GRACEFUL_EXIT_TIMEOUT = 15.0


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON")


class NativeOperationError(InfrastructureError):
    """A correlated native error; cleanup may be attempted, never controls."""


class NativeWorkerClient:
    def __init__(self, python_executable, worker, config, artifact_dir, timeout=120):
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("worker timeout must be finite and positive")
        self.timeout = float(timeout)
        self.process = None
        self.log = None
        self.poisoned = False
        self.native_failed = False
        self.closed = False
        self.sequence = 0
        self.last_error = None
        root = Path(artifact_dir)
        config_path = root / "worker_config.json"
        with config_path.open("x") as stream:
            os.chmod(config_path, 0o600)
            json.dump(config, stream, allow_nan=False)
        self.log = (root / "native_worker.log").open("xb")
        environment = os.environ.copy()
        for key in ("PYTHONPATH", "RSI_SIM_SERVER_TOKEN", "CUDA_VISIBLE_DEVICES"):
            environment.pop(key, None)
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1",
                           OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", GIT_OPTIONAL_LOCKS="0",
                           XDG_CACHE_HOME=str(root / "cache"),
                           PYTHONPATH=str(Path(__file__).resolve().parents[4]))
        try:
            self.process = subprocess.Popen(
                [str(python_executable), "-B", str(worker), "--config", str(config_path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                cwd=root, env=environment, start_new_session=True, bufsize=0,
            )
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
        except BaseException:
            self.close()
            raise

    def _terminate(self):
        if self.process is None:
            return
        # The only group signalled is the one created by this Popen invocation.
        for sig, seconds in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                continue
            # Reap any descendants that kept the owned group after the parent.
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                return
        try:
            os.killpg(self.process.pid, 0)
        except ProcessLookupError:
            return
        raise InfrastructureError("VLN-CE owned worker group did not close")

    def request(self, op, params=None):
        if self.closed or self.poisoned or self.process is None:
            raise InfrastructureError("VLN-CE worker transport is unavailable; no replay")
        if self.native_failed and op not in {"metrics", "finish", "close"}:
            raise InfrastructureError("VLN-CE native operation failed; controls are disabled")
        self.sequence += 1
        payload = (json.dumps({"id": self.sequence, "op": op, "params": params or {}}, allow_nan=False) + "\n").encode()
        if len(payload) > MAX_LINE:
            raise ProtocolError("VLN-CE request exceeds private RPC bound")
        deadline = time.monotonic() + self.timeout
        received = bytearray()
        sent = 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdin, selectors.EVENT_WRITE, "write")
                selector.register(self.process.stdout, selectors.EVENT_READ, "read")
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("private RPC deadline")
                    for key, _ in selector.select(min(remaining, 0.2)):
                        if key.data == "write":
                            sent += os.write(key.fileobj.fileno(), payload[sent:sent + 65536])
                            if sent == len(payload):
                                selector.unregister(key.fileobj)
                        else:
                            part = os.read(key.fileobj.fileno(), 65536)
                            if not part:
                                raise EOFError("private worker ended before acknowledgement")
                            received.extend(part)
                            if len(received) > MAX_LINE:
                                raise ValueError("private reply exceeds bound")
                            if b"\n" in received:
                                line, rest = bytes(received).split(b"\n", 1)
                                if rest.strip() or sent != len(payload):
                                    raise ValueError("unexpected private reply framing")
                                response = json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
                                if (type(response) is not dict or type(response.get("id")) is not int
                                        or response["id"] != self.sequence or type(response.get("ok")) is not bool):
                                    raise ValueError("private reply correlation differs")
                                if response["ok"]:
                                    if set(response) != {"id", "ok", "result"} or type(response["result"]) is not dict:
                                        raise ValueError("invalid private result")
                                    return response["result"]
                                if set(response) != {"id", "ok", "error"} or type(response["error"]) is not dict:
                                    raise ValueError("invalid private error")
                                self.native_failed = True
                                self.last_error = "native_operation_failed"
                                raise NativeOperationError("VLN-CE native operation failed; inspect private worker log")
        except NativeOperationError:
            raise
        except BaseException as exc:
            # The outcome may be unknown. Never send another request behind it.
            self.poisoned = True
            self.last_error = "worker_transport_failed"
            self._terminate()
            raise InfrastructureError("VLN-CE private RPC failed; outcome may be unknown; no replay") from exc

    def close(self):
        if self.closed:
            return
        error = None
        try:
            if self.process is not None and self.process.poll() is None and not self.poisoned:
                try:
                    self.request("close")
                    self.process.wait(timeout=GRACEFUL_EXIT_TIMEOUT)
                except BaseException as exc:
                    error = exc
            self._terminate()
        finally:
            self.closed = True
            if self.process is not None:
                for stream in (self.process.stdin, self.process.stdout):
                    if stream is not None:
                        stream.close()
            if self.log is not None:
                self.log.close()
        if error is not None:
            raise InfrastructureError("VLN-CE worker cleanup required termination") from error
