"""Bench-host gateway: start operator-catalog cases as per-case SIM services.

Runs on the simulator host beside the native environments. The agent host
reaches only the gateway control port and the slot ports, through forwarded
loopback ports; it needs no shell, file access or process control here. The
operator-owned catalog fixes deployments, devices and seeds, and each profile's
inventory fixes the selectable episodes. A trusted driver may list cases, lease
one, use the leased slot with the unchanged SIM client and release it. It cannot
add cases, change parameters or read server-side files through this interface.

The gateway token is evaluator administration, like the SIM client: never give
it, a lease token or either endpoint to the model actor.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid

from benchkit.artifacts import append_jsonl, atomic_write_json, utc_now
from benchkit.sim_server.cli import SERVICE_MODULES
from benchkit.sim_server.wire import MAX_MESSAGE_BYTES, dumps, loads

GATEWAY_PROTOCOL = "starvla-rsi.bench-gateway/v1"
CATALOG_SCHEMA = "starvla-rsi.gateway-catalog/v1"
INVENTORY_SCHEMA = "starvla-rsi.gateway-inventory/v2"
SERVICE_TOKEN_ENV = "RSI_SIM_SERVER_TOKEN"
DEFAULT_PER_TASK = 5
RELAY_IDLE_S = 3600.0
# A driver waits this long for one gateway reply. A launch, including the stop
# after a failed start, must answer inside it, or the lease would outlive its caller.
RPC_TIMEOUT_S = 3600.0
RPC_MARGIN_S = 120.0
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,256}")
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class GatewayError(Exception):
    """Closed error code returned to the driver; details stay in local logs."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(optional):
        raise ValueError("invalid catalog fields")
    return value


def load_catalog(path: Path) -> dict:
    """Validate the operator catalog; it is fixed for the gateway's lifetime."""
    catalog = _object(json.loads(path.read_text(encoding="utf-8")), ("schema_version", "slots", "profiles"))
    if catalog["schema_version"] != CATALOG_SCHEMA:
        raise ValueError("unsupported catalog schema")
    slots = catalog["slots"]
    if not isinstance(slots, list) or not slots:
        raise ValueError("catalog needs at least one slot")
    for slot in slots:
        _object(slot, ("id", "port"), ("env",))
        if not isinstance(slot["id"], str) or not _NAME.fullmatch(slot["id"]):
            raise ValueError("invalid slot ID")
        if type(slot["port"]) is not int or not 1024 <= slot["port"] <= 65535:
            raise ValueError("invalid slot port")
        _strings_map(slot.get("env", {}))
    if len({s["id"] for s in slots}) != len(slots) or len({s["port"] for s in slots}) != len(slots):
        raise ValueError("duplicate slot ID or port")
    profiles = catalog["profiles"]
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("catalog needs at least one profile")
    for name, profile in profiles.items():
        if not _NAME.fullmatch(name):
            raise ValueError("invalid profile name")
        _object(profile, ("service", "python", "source", "seed"),
                ("parameters", "env", "startup_timeout_s", "stop_timeout_s", "default_per_task",
                 "retain_frame_images"))
        if profile["service"] not in SERVICE_MODULES and profile["service"] != "synthetic":
            raise ValueError(f"unknown service for profile {name}")
        for key in ("python", "source"):
            if not isinstance(profile[key], str) or not Path(profile[key]).is_absolute():
                raise ValueError(f"profile {name} needs an absolute {key}")
        if type(profile["seed"]) is not int:
            raise ValueError("profile seed must be an integer")
        parameters = profile.get("parameters", {})
        if not isinstance(parameters, (dict, str)) or (isinstance(parameters, str) and not Path(parameters).is_absolute()):
            raise ValueError("parameters must be an object or an absolute JSON path")
        _strings_map(profile.get("env", {}))
        for key in ("startup_timeout_s", "stop_timeout_s"):
            if key in profile and (type(profile[key]) not in (int, float) or not 0 < profile[key]):
                raise ValueError(f"invalid {key}")
        if profile.get("startup_timeout_s", 900) + profile.get("stop_timeout_s", 180) + RPC_MARGIN_S > RPC_TIMEOUT_S:
            raise ValueError(f"profile {name}: startup_timeout_s + stop_timeout_s must leave "
                             f"{RPC_MARGIN_S:.0f} s under the {RPC_TIMEOUT_S:.0f} s driver wait")
        per_task = profile.get("default_per_task", DEFAULT_PER_TASK)
        if per_task is not None and (type(per_task) is not int or per_task <= 0):
            raise ValueError("default_per_task must be positive or null (all episodes)")
        if type(profile.get("retain_frame_images", False)) is not bool:
            raise ValueError("retain_frame_images must be boolean")
    return catalog


def _strings_map(value):
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
        raise ValueError("env must map strings to strings")
    if SERVICE_TOKEN_ENV in value:
        raise ValueError("the service token is generated per lease")
    return value


def service_module(profile: dict) -> str:
    return "benchkit.sim_server" if profile["service"] == "synthetic" else SERVICE_MODULES[profile["service"]]


def _parameters_bytes(profile: dict) -> bytes:
    parameters = profile.get("parameters", {})
    if isinstance(parameters, str):
        return dumps(loads(Path(parameters).read_bytes()))
    return dumps(parameters)


def _child_env(profile: dict, slot: dict, *, strip: tuple[str, ...] = ()) -> dict:
    env = {key: value for key, value in os.environ.items() if key not in strip and key != SERVICE_TOKEN_ENV}
    env.update(profile.get("env", {}))
    env.update(slot.get("env", {}))
    return env


def build_inventory(catalog: dict, name: str, *, timeout: float = 1800.0) -> dict:
    """Run the profile's service in --list-episodes mode; no episode is opened."""
    profile = catalog["profiles"][name]
    params = Path(os.environ.get("TMPDIR", "/tmp")) / f"rsi-gateway-inventory-{uuid.uuid4().hex}.json"
    params.write_bytes(_parameters_bytes(profile))
    try:
        output = subprocess.run(
            [profile["python"], "-B", "-m", service_module(profile), "--list-episodes",
             "--parameters", str(params), "--seed", str(profile["seed"])],
            cwd=profile["source"], env=_child_env(profile, {}), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout, check=True).stdout
    finally:
        params.unlink(missing_ok=True)
    listing = json.loads(output.strip().splitlines()[-1])
    episodes = [{"id": e["id"], "task": e["task"]} for e in listing["episodes"]]
    if not episodes or len({e["id"] for e in episodes}) != len(episodes):
        raise ValueError("inventory needs unique episode IDs")
    if type(listing.get("complete_schedule_required")) is not bool:
        raise ValueError("service listing must declare complete_schedule_required")
    return {"schema_version": INVENTORY_SCHEMA, "profile": name, "created_at": utc_now(),
            "profile_sha256": hashlib.sha256(dumps(profile)).hexdigest(),
            "parameters_sha256": hashlib.sha256(_parameters_bytes(profile)).hexdigest(),
            "descriptor": listing["descriptor"], "seed": listing["seed"],
            "complete_schedule_required": listing["complete_schedule_required"], "episodes": episodes}


def panels(inventory: dict, per_task: int | None) -> dict[str, list[str]]:
    """`full` keeps every native episode; `default` is the first N per task.

    A benchmark that requires its complete schedule has no shorter default.
    """
    full = [episode["id"] for episode in inventory["episodes"]]
    if per_task is None or inventory["complete_schedule_required"]:
        return {"full": full, "default": full}
    taken: dict[str, int] = defaultdict(int)
    default = []
    for episode in inventory["episodes"]:
        if taken[episode["task"]] < per_task:
            taken[episode["task"]] += 1
            default.append(episode["id"])
    return {"full": full, "default": default}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Gateway:
    def __init__(self, catalog_path: Path, state_dir: Path, *, strip_env: tuple[str, ...] = ()):
        self.catalog_path = catalog_path.absolute()
        self.catalog = load_catalog(self.catalog_path)
        self.state = state_dir.absolute()
        self.strip_env = strip_env
        self.lock = threading.RLock()
        self.closing = threading.Event()
        self.slots = {slot["id"]: {**slot, "lease": None, "quarantined": False} for slot in self.catalog["slots"]}
        self.inventories, self.panels, self.cases = {}, {}, {}
        for name, profile in self.catalog["profiles"].items():
            path = self.state / "inventory" / f"{name}.json"
            inventory = json.loads(path.read_text(encoding="utf-8"))
            if (inventory.get("schema_version") != INVENTORY_SCHEMA or inventory.get("profile") != name
                    or inventory.get("profile_sha256") != hashlib.sha256(dumps(profile)).hexdigest()
                    or inventory.get("parameters_sha256") != hashlib.sha256(_parameters_bytes(profile)).hexdigest()):
                raise ValueError(f"inventory for {name} is missing or stale; rebuild it")
            self.inventories[name] = inventory
            self.panels[name] = panels(inventory, profile.get("default_per_task", DEFAULT_PER_TASK))
            for episode in inventory["episodes"]:
                self.cases[f"{name}:{episode['id']}"] = (name, episode)
        self.leases: dict[str, dict] = {}
        (self.state / "leases").mkdir(parents=True, exist_ok=True)
        self.description = {
            "gateway_id": uuid.uuid4().hex, "protocol": GATEWAY_PROTOCOL,
            "catalog_sha256": _sha256(self.catalog_path),
            "profiles": {name: {"descriptor": inv["descriptor"], "seed": inv["seed"],
                                "complete_schedule_required": inv["complete_schedule_required"],
                                "panels": {key: len(ids) for key, ids in self.panels[name].items()},
                                "inventory_sha256": _sha256(self.state / "inventory" / f"{name}.json")}
                         for name, inv in self.inventories.items()},
        }
        atomic_write_json(self.state / "gateway-runs" / f"{self.description['gateway_id']}.json",
                          {**self.description, "started_at": utc_now()}, overwrite=False)

    def _event(self, kind: str, **fields) -> None:
        with self.lock:
            append_jsonl(self.state / "events.jsonl", {"timestamp": utc_now(), "event": kind, **fields})

    # -- RPC operations -----------------------------------------------------------
    def dispatch(self, op: str, params: dict) -> dict:
        if not isinstance(params, dict):
            raise GatewayError("invalid_fields")
        if op == "describe":
            if params:
                raise GatewayError("invalid_fields")
            with self.lock:
                slots = [{"id": s["id"], "port": s["port"], "lease_id": s["lease"],
                          "state": "quarantined" if s["quarantined"] else ("leased" if s["lease"] else "idle")}
                         for s in self.slots.values()]
            return {**self.description, "slots": slots}
        if op == "cases":
            if set(params) != {"profile", "panel", "offset", "limit"}:
                raise GatewayError("invalid_fields")
            if params["profile"] not in self.panels or params["panel"] not in ("default", "full"):
                raise GatewayError("unknown_panel")
            offset, limit = params["offset"], params["limit"]
            if type(offset) is not int or type(limit) is not int or offset < 0 or not 0 < limit <= 1000:
                raise GatewayError("invalid_page")
            ids = self.panels[params["profile"]][params["panel"]]
            rows = [{"case_id": f"{params['profile']}:{episode_id}", "episode_id": episode_id,
                     "task": self.cases[f"{params['profile']}:{episode_id}"][1]["task"]}
                    for episode_id in ids[offset:offset + limit]]
            return {"total": len(ids), "cases": rows}
        if op == "launch":
            if set(params) != {"case_id", "slot"}:
                raise GatewayError("invalid_fields")
            return self._launch(params["case_id"], params["slot"])
        if op in ("release", "lease"):
            if set(params) != {"lease_id"} or params["lease_id"] not in self.leases:
                raise GatewayError("unknown_lease")
            if op == "lease":
                return self._public(self.leases[params["lease_id"]])
            return self._release(params["lease_id"])
        raise GatewayError("unknown_operation")

    @staticmethod
    def _public(lease: dict) -> dict:
        keys = ("lease_id", "case_id", "slot", "state", "episodes_opened", "cleanup", "error")
        return {key: lease[key] for key in keys}

    def _launch(self, case_id, slot_id) -> dict:
        if not isinstance(case_id, str) or case_id not in self.cases:
            raise GatewayError("unknown_case")
        with self.lock:
            if self.closing.is_set():
                raise GatewayError("gateway_closing")
            slot = self.slots.get(slot_id) if isinstance(slot_id, str) else None
            if slot is None:
                raise GatewayError("unknown_slot")
            if slot["quarantined"]:
                raise GatewayError("slot_quarantined")
            if slot["lease"] is not None:
                raise GatewayError("slot_busy")
            name, episode = self.cases[case_id]
            profile = self.catalog["profiles"][name]
            lease_id = uuid.uuid4().hex
            root = self.state / "leases" / lease_id
            root.mkdir()
            lease = {"lease_id": lease_id, "case_id": case_id, "slot": slot_id, "state": "launching",
                     "episodes_opened": 0, "cleanup": None, "error": None, "root": root,
                     "process": None, "child_port": None, "token": secrets.token_urlsafe(32)}
            self.leases[lease_id] = lease
            slot["lease"] = lease_id
        try:
            self._event("launch", lease_id=lease_id, case_id=case_id, slot=slot_id)
            server_id = self._start(lease, profile, slot, episode)
        except Exception as exc:
            self._stop(lease, profile, failed=str(exc) if isinstance(exc, GatewayError) else "startup_failed")
            raise GatewayError(lease["error"]) from None
        with self.lock:
            lease["state"] = "ready"
        self._event("ready", lease_id=lease_id, server_id=server_id)
        return {"lease_id": lease_id, "case_id": case_id, "slot": slot_id, "port": slot["port"],
                "token": lease["token"], "benchmark": self.inventories[name]["descriptor"]["name"],
                "seed": profile["seed"], "episode_id": episode["id"], "episodes": 1, "server_id": server_id}

    def _start(self, lease: dict, profile: dict, slot: dict, episode: dict) -> str:
        from benchkit.sim_server.client import SimServerBenchmarkAdapter

        root = lease["root"]
        (root / "parameters.json").write_bytes(_parameters_bytes(profile))
        lease["child_port"] = port = _free_port()
        command = [profile["python"], "-B", "-m", service_module(profile),
                   "--parameters", str(root / "parameters.json"), "--seed", str(profile["seed"]),
                   "--episode-id", episode["id"], "--port", str(port),
                   "--output-dir", str(root / "server"), "--token-env", SERVICE_TOKEN_ENV]
        if profile.get("retain_frame_images"):
            command.append("--retain-frame-images")
        env = _child_env(profile, slot, strip=self.strip_env)
        env[SERVICE_TOKEN_ENV] = lease["token"]
        atomic_write_json(root / "lease.json", {"lease_id": lease["lease_id"], "case_id": lease["case_id"],
                          "slot": slot["id"], "command": command, "cwd": profile["source"],
                          "env_overrides": {**profile.get("env", {}), **slot.get("env", {})}}, overwrite=False)
        with (root / "server.log").open("x") as log:
            lease["process"] = subprocess.Popen(command, cwd=profile["source"], env=env, stdin=subprocess.DEVNULL,
                                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + profile.get("startup_timeout_s", 900)
        expected = self.inventories[self.cases[lease["case_id"]][0]]["descriptor"]["name"]
        while time.monotonic() < deadline and not self.closing.is_set():
            if lease["process"].poll() is not None:
                raise GatewayError("service_exited_during_startup")
            try:
                client = SimServerBenchmarkAdapter(f"http://127.0.0.1:{port}", lease["token"], timeout=30)
            except Exception:
                time.sleep(1.0)
                continue
            if client.descriptor.name != expected or [e.id for e in client.episodes(profile["seed"])] != [episode["id"]]:
                raise GatewayError("service_identity_mismatch")
            return client.describe_data["server_id"]
        raise GatewayError("gateway_closing" if self.closing.is_set() else "service_startup_timeout")

    def _release(self, lease_id: str) -> dict:
        lease = self.leases[lease_id]
        with self.lock:
            if lease["state"] != "ready":
                return self._public(lease)
            lease["state"] = "releasing"
        self._stop(lease, self.catalog["profiles"][self.cases[lease["case_id"]][0]])
        return self._public(lease)

    def _stop(self, lease: dict, profile: dict, failed: str | None = None) -> None:
        """SIGTERM the owned process group; never SIGKILL or retry automatically.

        Always ends in a final state, written to disk before it is published, so
        shutdown neither waits forever nor returns before the record exists.
        """
        process = lease["process"]
        cleanup, opened = "unverified", 0
        try:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=profile.get("stop_timeout_s", 180))
                except subprocess.TimeoutExpired:
                    pass
                deadline = time.monotonic() + 10
                while _group_alive(process.pid) and time.monotonic() < deadline:
                    time.sleep(0.5)
            if process is None or (process.poll() is not None and not _group_alive(process.pid)):
                cleanup = "verified"
            opened = len(list((lease["root"] / "server" / "episodes").glob("*/claim.json")))
        finally:
            final = {"state": "startup_failed" if failed else "released", "episodes_opened": opened,
                     "cleanup": cleanup, "error": failed}
            try:
                atomic_write_json(lease["root"] / "release.json",
                                  {**self._public({**lease, **final}), "released_at": utc_now()}, overwrite=False)
                self._event("stopped", lease_id=lease["lease_id"], **final)
            finally:
                with self.lock:
                    lease.update(final)
                    slot = self.slots[lease["slot"]]
                    slot["lease"] = None
                    if cleanup != "verified":
                        # A surviving native group may hold the GPU: the operator must
                        # inspect it before the slot is used again.
                        slot["quarantined"] = True

    def child_port(self, slot_id: str) -> int | None:
        with self.lock:
            lease_id = self.slots[slot_id]["lease"]
            lease = self.leases.get(lease_id) if lease_id else None
            return lease["child_port"] if lease is not None and lease["state"] == "ready" else None

    def shutdown(self) -> None:
        """Refuse new launches and stop every owned service, including ones still starting."""
        self.closing.set()
        while True:
            with self.lock:
                states = {lease_id: lease["state"] for lease_id, lease in self.leases.items()}
            for lease_id, state in states.items():
                if state == "ready":
                    try:
                        self._release(lease_id)
                    except Exception:
                        pass  # Its stop still reached a final state; keep stopping the others.
            # A starting lease sees `closing` and stops itself on its own thread.
            if not any(state in ("launching", "releasing") for state in states.values()):
                return
            time.sleep(0.5)


def _relay(left: socket.socket, right: socket.socket) -> None:
    """Copy bytes both ways, forwarding half-closes, until both sides finish."""
    peers = {left: right, right: left}
    open_reads = {left, right}
    while open_reads:
        readable, _, _ = select.select(list(open_reads), [], [], RELAY_IDLE_S)
        if not readable:
            return
        for sock in readable:
            data = sock.recv(65536)
            if data:
                peers[sock].sendall(data)
            else:
                open_reads.discard(sock)
                try:
                    peers[sock].shutdown(socket.SHUT_WR)
                except OSError:
                    pass


def make_slot_server(gateway: Gateway, slot_id: str) -> socketserver.ThreadingTCPServer:
    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            port = gateway.child_port(slot_id)
            if port is None:
                return  # No ready lease: close without contacting any service.
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=30) as upstream:
                    upstream.settimeout(None)
                    self.request.settimeout(None)
                    _relay(self.request, upstream)
            except OSError:
                pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", gateway.slots[slot_id]["port"]), Relay)
    server.daemon_threads = True
    return server


def make_control_server(gateway: Gateway, *, token: str, port: int) -> ThreadingHTTPServer:
    if _TOKEN.fullmatch(token) is None:
        raise ValueError("gateway token must have 32..256 URL-safe characters")

    class Handler(BaseHTTPRequestHandler):
        server_version = "RSIBenchGateway/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(60)

        def log_message(self, *_):
            pass  # Never log bearer tokens or request bodies.

        def do_POST(self):
            request_id = None
            try:
                if self.path != "/rpc":
                    self.send_error(404)
                    return
                auth = self.headers.get_all("Authorization", [])
                if len(auth) != 1 or not hmac.compare_digest(auth[0], "Bearer " + token):
                    self.send_error(401)
                    return
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
                    raise GatewayError("invalid_framing")
                length = int(lengths[0])
                if not 0 < length <= MAX_MESSAGE_BYTES:
                    raise GatewayError("invalid_length")
                message = loads(self.rfile.read(length))
                if (set(message) != {"protocol", "request_id", "op", "params"}
                        or message["protocol"] != GATEWAY_PROTOCOL
                        or not isinstance(message["request_id"], str)
                        or re.fullmatch(r"[a-f0-9]{32}", message["request_id"]) is None):
                    raise GatewayError("invalid_envelope")
                request_id = message["request_id"]
                result = gateway.dispatch(message["op"], message["params"])
                payload = dumps({"protocol": GATEWAY_PROTOCOL, "request_id": request_id, "ok": True, "result": result})
            except Exception as exc:
                code = str(exc) if isinstance(exc, GatewayError) else "gateway_request_failed"
                if not isinstance(exc, GatewayError):
                    gateway._event("request_error", error=type(exc).__name__)
                payload = dumps({"protocol": GATEWAY_PROTOCOL, "request_id": request_id,
                                 "ok": False, "error": {"code": code}})
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rsi-bench gateway", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="list one profile's complete native schedule (operator)")
    inventory.add_argument("--catalog", type=Path, required=True)
    inventory.add_argument("--state-dir", type=Path, required=True)
    inventory.add_argument("--profile", required=True)
    serve = commands.add_parser("serve", help="serve catalog cases to one trusted driver")
    serve.add_argument("--catalog", type=Path, required=True)
    serve.add_argument("--state-dir", type=Path, required=True)
    serve.add_argument("--port", type=int, default=18800)
    serve.add_argument("--token-env", default="RSI_GATEWAY_TOKEN")
    args = parser.parse_args(argv)
    if args.command == "inventory":
        catalog = load_catalog(args.catalog)
        if args.profile not in catalog["profiles"]:
            parser.error("unknown profile")
        result = build_inventory(catalog, args.profile)
        atomic_write_json(args.state_dir / "inventory" / f"{args.profile}.json", result)
        per_task = catalog["profiles"][args.profile].get("default_per_task", DEFAULT_PER_TASK)
        print(json.dumps({"profile": args.profile, "episodes": len(result["episodes"]),
                          "panels": {k: len(v) for k, v in panels(result, per_task).items()}}))
        return 0
    token = os.environ.get(args.token_env, "")
    if _TOKEN.fullmatch(token) is None:
        parser.error("set a 32..256 character URL-safe token in the selected environment variable")
    gateway = Gateway(args.catalog, args.state_dir, strip_env=(args.token_env,))
    servers = [make_slot_server(gateway, slot_id) for slot_id in gateway.slots]
    control = make_control_server(gateway, token=token, port=args.port)
    for server in servers:
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True).start()
    print(json.dumps({"status": "listening", "control": f"http://127.0.0.1:{control.server_port}",
                      "slots": {s["id"]: s["port"] for s in gateway.slots.values()},
                      "gateway_id": gateway.description["gateway_id"]}), flush=True)

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        control.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        # A repeated signal must not abort the stop of owned services.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        previous_interrupt = signal.signal(signal.SIGINT, signal.SIG_IGN)
        control.server_close()
        for server in servers:
            server.shutdown()
            server.server_close()
        gateway.shutdown()
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, previous_interrupt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
