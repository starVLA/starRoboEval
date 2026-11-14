"""Server-side private native-worker transport and lifecycle for Direct v2.

This module has no task catalog, action policy, old benchmark factory or native
simulator import. The public adapter supplies reset, observation and action
semantics; this base only correlates the private child-process RPC and closes it.
"""
from __future__ import annotations

import json
import math
from numbers import Real
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from typing import Any, Mapping
import uuid

from benchkit.errors import ProtocolError


SEED = 20260907
CAMERAS = ("cam_head", "cam_left_wrist", "cam_right_wrist")
CLOSE_PROTOCOL = "robodojo-close/v1"
CLOSE_WAIT_SECONDS = 30
CLOSE_TERMINATE_SECONDS = 10
RPC_MAX_RESPONSE_BYTES = 1024 * 1024
RPC_PROTOCOL = "robodojo-private-rpc/v2"


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class NativeOperationError(RuntimeError):
    """A correlated worker error; the transport remains synchronized."""


def validate_tick_result(message: Mapping[str, Any], expected_targets: int) -> tuple[bool, bool, bool, float]:
    """Validate one native acknowledgement without exposing its private map."""
    metrics = message.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ProtocolError("native RPC metrics must be an object")
    if any(type(message.get(name)) is not bool for name in ("terminated", "truncated")):
        raise ProtocolError("native RPC terminal flags must be boolean")
    for name in ("success", "native_end_flag", "native_alive_flag"):
        if type(metrics.get(name)) is not bool:
            raise ProtocolError(f"native RPC {name} must be boolean")
    reward = metrics.get("native_reward")
    if isinstance(reward, bool) or not isinstance(reward, Real) or not math.isfinite(float(reward)):
        raise ProtocolError("native RPC reward must be finite real")
    for name in ("control_targets", "native_take_action_count", "native_reward_evaluations"):
        if type(metrics.get(name)) is not int or metrics[name] != expected_targets:
            raise ProtocolError(f"native RPC {name} differs from one-target-per-call contract")
    if type(metrics.get("physics_ticks")) is not int or metrics["physics_ticks"] != expected_targets * 10:
        raise ProtocolError("native RPC physics ticks differ from ten-tick interpolation")
    success, terminated, truncated = metrics["success"], message["terminated"], message["truncated"]
    if success != (metrics["native_end_flag"] and metrics["native_alive_flag"]):
        raise ProtocolError("native task success is not end_flag AND alive")
    if terminated != metrics["native_end_flag"] or (terminated and truncated):
        raise ProtocolError("native terminal flags disagree")
    if success != (float(reward) > 1.0 - 1e-3):
        raise ProtocolError("native success and reward disagree")
    return success, terminated, truncated, float(reward)


class RoboDojoEpisode:
    """Correlated private RPC and acknowledged child-process cleanup only."""

    def __init__(self, benchmark, episode) -> None:
        self.benchmark, self.episode = benchmark, episode
        self.artifact_dir: Path | None = None
        self.process: subprocess.Popen | None = None
        self.log: Any = None
        self.steps = 0
        self.finished = False
        self.latest: dict[str, Any] = {"success": False, "native_reward": None,
            "native_benchmark_score": None, "physics_ticks": None}
        self.worker_artifacts: dict[str, Any] = {}
        self.close_attempted = False
        self.close_error: str | None = None
        self.rpc_failure: str | None = None

    def bind_artifact_dir(self, path: Path) -> None:
        self.artifact_dir = path.resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _rpc(self, request: Mapping[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        if self.rpc_failure is not None:
            raise ProtocolError("RoboDojo RPC transport is faulted; no further requests: " + self.rpc_failure)
        try:
            return self._exchange(request, timeout=timeout)
        except NativeOperationError:
            # A complete, correlated error is not an uncertain acknowledgement.
            raise
        except Exception as exc:
            self.rpc_failure = f"{type(exc).__name__}: {exc}"
            raise

    def _exchange(self, request: Mapping[str, Any], *, timeout: float | None) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise ProtocolError("RoboDojo worker is not running")
        if "rpc_id" in request or "rpc_protocol" in request:
            raise ProtocolError("RPC correlation ID and protocol are evaluator-owned")
        rpc_id = uuid.uuid4().hex
        descriptor = self.process.stdout.fileno()
        was_blocking = os.get_blocking(descriptor)
        os.set_blocking(descriptor, False)
        try:
            try:
                pending = os.read(descriptor, 1)
            except BlockingIOError:
                pending = None
            if pending is not None:
                raise ProtocolError("unsolicited RPC bytes or closed response stream before request")
            self.process.stdin.write(json.dumps({**request, "rpc_id": rpc_id,
                "rpc_protocol": RPC_PROTOCOL}, allow_nan=False) + "\n")
            self.process.stdin.flush()
            deadline = time.monotonic() + (self.benchmark.worker_timeout if timeout is None else timeout)
            data = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(descriptor, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError(f"RoboDojo RPC response deadline exceeded after {len(data)} bytes; artifacts retained")
                    try:
                        chunk = os.read(descriptor, min(65536, RPC_MAX_RESPONSE_BYTES + 1 - len(data)))
                    except BlockingIOError:
                        continue
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"RoboDojo RPC response deadline exceeded after {len(data)} bytes; artifacts retained")
                    if not chunk:
                        raise ProtocolError(f"RoboDojo RPC EOF before complete newline response after {len(data)} bytes")
                    data.extend(chunk)
                    if len(data) > RPC_MAX_RESPONSE_BYTES:
                        raise ProtocolError("RoboDojo RPC response exceeds byte limit")
                    if b"\n" in data:
                        line, trailing = bytes(data).split(b"\n", 1)
                        if trailing:
                            raise ProtocolError("multiple/trailing RPC response bytes")
                        try:
                            trailing = os.read(descriptor, 1)
                        except BlockingIOError:
                            trailing = b""
                        if trailing:
                            raise ProtocolError("multiple/trailing RPC response bytes")
                        break
        finally:
            os.set_blocking(descriptor, was_blocking)

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ProtocolError(f"duplicate RPC JSON key: {key}")
                result[key] = value
            return result

        try:
            response = json.loads(line.decode("utf-8"), object_pairs_hook=unique_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ProtocolError(f"nonfinite RPC JSON constant: {value}")))
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError(f"invalid RPC response JSON: {exc}") from exc
        if (not isinstance(response, dict) or type(response.get("ok")) is not bool
                or response.get("rpc_id") != rpc_id or response.get("rpc_protocol") != RPC_PROTOCOL):
            raise ProtocolError("native RPC response has invalid status, version or correlation ID")
        expected = ({"rpc_protocol", "rpc_id", "ok", "result"} if response["ok"]
                    else {"rpc_protocol", "rpc_id", "ok", "operation", "error", "traceback"})
        if set(response) != expected:
            raise ProtocolError("native RPC response fields differ from private protocol")
        if not response["ok"]:
            if (response["operation"] != request.get("op")
                    or not isinstance(response["error"], str)
                    or not isinstance(response["traceback"], str)):
                raise ProtocolError("native RPC error has invalid operation or diagnostic fields")
            raise NativeOperationError(f"RoboDojo native worker: {response.get('error')}")
        result = response["result"]
        if (not isinstance(result, dict) or not isinstance(result.get("metrics", {}), dict)
                or not isinstance(result.get("artifacts", {}), dict)):
            raise ProtocolError("native RPC result/metrics/artifacts must be objects")
        self.latest.update(result.get("metrics", {}))
        self.worker_artifacts.update(result.get("artifacts", {}))
        return result

    def artifacts(self) -> Mapping[str, Any]:
        if not self.close_attempted and self.process is not None and self.process.poll() is None:
            self._rpc({"op": "finalize"})
        return dict(self.worker_artifacts)

    def close(self) -> None:
        if self.process is None:
            return
        if self.close_attempted:
            if self.close_error is not None:
                raise RuntimeError(self.close_error)
            return
        self.close_attempted = True
        errors = []
        receipt = {"protocol": CLOSE_PROTOCOL, "pid": self.process.pid,
            "prepare_ack_received": False, "prepare_receipt_verified": False,
            "app_shutdown_started": False, "app_shutdown_return_observed": False,
            "terminate_sent": False, "kill_sent": False, "child_returncode": None}

        def read_record(name: str) -> dict[str, Any]:
            if self.artifact_dir is None:
                raise ProtocolError("missing close artifact directory")
            path = self.artifact_dir / name
            if path.is_symlink() or not path.is_file():
                raise ProtocolError(f"missing/invalid worker cleanup receipt: {name}")
            value = json.loads(path.read_text())
            if (not isinstance(value, dict) or type(value.get("pid")) is not int
                    or type(value.get("app_created")) is not bool):
                raise ProtocolError(f"worker cleanup receipt has invalid fields: {name}")
            return value

        prepared = None
        try:
            if self.process.poll() is not None:
                raise ProtocolError("native worker exited before cleanup prepare acknowledgement")
            prepared = self._rpc({"op": "close"},
                timeout=min(self.benchmark.worker_timeout, CLOSE_WAIT_SECONDS)).get("cleanup_prepared")
            receipt["prepare_ack_received"] = True
            if (not isinstance(prepared, dict)
                    or set(prepared) != {"protocol", "phase", "pid", "finalization",
                                        "environment_cleanup", "app_created", "errors"}
                    or prepared.get("protocol") != CLOSE_PROTOCOL or prepared.get("phase") != "prepared"
                    or prepared.get("pid") != self.process.pid
                    or prepared.get("finalization") != "completed"
                    or prepared.get("environment_cleanup") not in ("completed", "not_created")
                    or type(prepared.get("app_created")) is not bool or prepared.get("errors") != []):
                raise ProtocolError("invalid native cleanup prepare acknowledgement")
            if read_record("cleanup_prepared.json") != prepared:
                raise ProtocolError("native cleanup prepare acknowledgement/receipt mismatch")
            receipt["prepare_receipt_verified"] = True
        except Exception as exc:
            errors.append(f"prepare: {type(exc).__name__}: {exc}")
        try:
            self.process.wait(timeout=0 if self.rpc_failure is not None else CLOSE_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            errors.append("native worker shutdown wait timed out")
        except Exception as exc:
            errors.append(f"wait: {type(exc).__name__}: {exc}")
        # The worker leads its own process group: signal the group, so native
        # descendants that outlive the worker are stopped too.
        for sig, flag in ((signal.SIGTERM, "terminate_sent"), (signal.SIGKILL, "kill_sent")):
            if self.process.poll() is not None and not _group_alive(self.process.pid):
                break
            try:
                os.killpg(self.process.pid, sig)
                receipt[flag] = True
            except ProcessLookupError:
                pass
            except Exception as exc:
                errors.append(f"{sig.name}: {type(exc).__name__}: {exc}")
            deadline = time.monotonic() + CLOSE_TERMINATE_SECONDS
            while time.monotonic() < deadline and (self.process.poll() is None or _group_alive(self.process.pid)):
                time.sleep(0.1)
        if self.process.poll() is None or _group_alive(self.process.pid):
            errors.append("native worker process group survived SIGKILL")
        receipt["child_returncode"] = self.process.returncode
        if type(self.process.returncode) is not int or self.process.returncode != 0:
            errors.append(f"native worker final return code: {self.process.returncode}")
        try:
            descriptor = self.process.stdout.fileno()
            was_blocking = os.get_blocking(descriptor)
            os.set_blocking(descriptor, False)
            try:
                try:
                    trailing = os.read(descriptor, 1)
                except BlockingIOError:
                    trailing = b""
                if trailing:
                    errors.append("unexpected trailing RPC bytes after worker shutdown")
            finally:
                os.set_blocking(descriptor, was_blocking)
        except Exception as exc:
            errors.append(f"shutdown response drain: {type(exc).__name__}: {exc}")
        if receipt["prepare_receipt_verified"]:
            expected = {"protocol": CLOSE_PROTOCOL, "pid": self.process.pid,
                "phase": "app_shutdown_started", "app_created": prepared["app_created"]}
            try:
                if read_record("app_shutdown_started.json") != expected:
                    raise ProtocolError("native application shutdown start receipt mismatch")
                receipt["app_shutdown_started"] = True
                returned = self.artifact_dir / "app_shutdown_returned.json"
                if returned.exists() or returned.is_symlink():
                    if read_record(returned.name) != {**expected, "phase": "app_shutdown_returned"}:
                        raise ProtocolError("native application shutdown return receipt mismatch")
                    receipt["app_shutdown_return_observed"] = True
                if (self.artifact_dir / "app_shutdown_error.json").exists():
                    raise ProtocolError("worker recorded an application shutdown error")
            except Exception as exc:
                errors.append(f"shutdown receipts: {type(exc).__name__}: {exc}")
        for stream in (self.process.stdin, self.process.stdout, self.log):
            if stream:
                try:
                    stream.close()
                except Exception as exc:
                    errors.append(f"stream close: {type(exc).__name__}: {exc}")
        receipt.update(status="failed" if errors else "completed", errors=errors,
            transport_fault=self.rpc_failure)
        try:
            if self.artifact_dir is None:
                raise ProtocolError("missing close artifact directory")
            with (self.artifact_dir / "worker_process_close.json").open("x") as output:
                output.write(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
            self.worker_artifacts["worker_process_close"] = "worker_process_close.json"
        except Exception as exc:
            errors.append(f"parent receipt: {type(exc).__name__}: {exc}")
        if errors:
            self.close_error = "; ".join(errors)
            raise RuntimeError(self.close_error)
