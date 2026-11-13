"""Agent-host case sequencer for a bench-host gateway (trusted driver side).

Each lane owns one gateway slot. It takes the next case of the selected
profile panel, leases it, runs the declared client command against the
forwarded slot endpoint with the lease token, and releases the lease. Switching
benchmark, task or episode is a different catalog case: no shell on the bench
host and no change to the per-episode SIM protocol.

A lane stops at its first engineering error, keeping the record. A case
without a completion record is leased again when rerunning with the same
output directory, in a new attempt directory beside the old one; cases with a
completion record are skipped. A crash is not an attempt, but a nonzero exit
after an episode opened can also be a recorded policy error, which is a
result: review the client record before rerunning such a case. This tool does
not stop a new output directory from running completed cases again; doing so
would be an unauthorized second attempt. The gateway token stays in this
process; the client command receives only its lease's service token.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import uuid

from benchkit.artifacts import append_jsonl, atomic_write_json, utc_now
from benchkit.sim_server.gateway import GATEWAY_PROTOCOL, RPC_TIMEOUT_S, SERVICE_TOKEN_ENV
from benchkit.sim_server.wire import MAX_MESSAGE_BYTES, dumps, loads

PLACEHOLDERS = ("endpoint", "benchmark", "seed", "episodes", "run_id", "case_id", "episode_id", "output_dir")


class GatewayClientError(Exception):
    pass


def _loopback(endpoint: str) -> int:
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("endpoint must be http://127.0.0.1:PORT (a forwarded port)")
    return parsed.port


class GatewayClient:
    """Administrative gateway client for a trusted driver; never a model tool."""

    def __init__(self, endpoint: str, token: str, *, timeout: float = RPC_TIMEOUT_S):
        self._port, self._token, self._timeout = _loopback(endpoint), token, timeout

    def rpc(self, op: str, params: dict) -> dict:
        request_id = uuid.uuid4().hex
        connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=self._timeout)
        try:
            connection.request("POST", "/rpc", body=dumps({"protocol": GATEWAY_PROTOCOL, "request_id": request_id,
                                                          "op": op, "params": params}),
                               headers={"Authorization": "Bearer " + self._token,
                                        "Content-Type": "application/json", "Connection": "close"})
            response = connection.getresponse()
            body = response.read(MAX_MESSAGE_BYTES + 1)
            if response.status != 200 or len(body) > MAX_MESSAGE_BYTES:
                raise GatewayClientError("gateway_transport_" + str(response.status))
            result = loads(body)
            if result.get("protocol") != GATEWAY_PROTOCOL or result.get("request_id") != request_id:
                raise GatewayClientError("gateway_uncorrelated_response")
            if result.get("ok") is not True:
                raise GatewayClientError(result.get("error", {}).get("code", "gateway_error"))
            return result["result"]
        finally:
            connection.close()

    def cases(self, profile: str, panel: str) -> list[dict]:
        rows, offset = [], 0
        while True:
            page = self.rpc("cases", {"profile": profile, "panel": panel, "offset": offset, "limit": 1000})
            rows += page["cases"]
            offset += len(page["cases"])
            if offset >= page["total"] or not page["cases"]:
                return rows


def _safe(case_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", case_id).strip("-")[:96]
    return f"{stem}-{hashlib.sha256(case_id.encode()).hexdigest()[:8]}"


def _render(template, values: dict):
    if isinstance(template, str):
        return template.format(**values)
    if isinstance(template, list):
        return [_render(item, values) for item in template]
    if isinstance(template, dict):
        return {key: _render(value, values) for key, value in template.items()}
    raise ValueError("client command templates contain only strings, lists and objects")


def load_client_command(path: Path) -> dict:
    command = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(command, dict) or not {"argv"} <= set(command) <= {"argv", "cwd", "env"}
            or not isinstance(command["argv"], list) or not command["argv"]
            or any(not isinstance(item, str) for item in command["argv"])
            or not isinstance(command.get("cwd", ""), str)
            or not isinstance(command.get("env", {}), dict)
            or any(not isinstance(value, str) for value in command.get("env", {}).values())):
        raise ValueError("client command needs argv (strings), optional cwd (string) and env (string map)")
    if SERVICE_TOKEN_ENV in command.get("env", {}):
        raise ValueError("the lease token is supplied by the sequencer")
    try:
        _render(command, {name: name for name in PLACEHOLDERS})
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise ValueError(f"bad placeholder ({exc}); allowed: {', '.join(PLACEHOLDERS)}") from None
    return command


class Lane(threading.Thread):
    def __init__(self, runner: "Sequencer", slot: str, local_port: int):
        super().__init__(name=f"lane-{slot}", daemon=True)
        self.runner, self.slot, self.local_port = runner, slot, local_port
        self.error: str | None = None

    def run(self):
        while not self.runner.stopping.is_set():
            try:
                case = self.runner.pending.get_nowait()
            except queue.Empty:
                return
            try:
                ok = self.runner.run_case(case, self.slot, self.local_port)
            except Exception as exc:  # A sequencer fault is an engineering error, not a result.
                self.runner.log("lane_fault", slot=self.slot, case_id=case["case_id"], error=f"{type(exc).__name__}: {exc}")
                ok = False
            if not ok:
                self.error = case["case_id"]
                return


class Sequencer:
    def __init__(self, args):
        token = os.environ.get(args.gateway_token_env, "")
        self.gateway = GatewayClient(args.gateway, token)
        self.token_env = args.gateway_token_env
        self.args = args
        self.command = load_client_command(args.client_command)
        self.root = args.output_dir.absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.pending: queue.Queue = queue.Queue()

    def log(self, event: str, **fields) -> None:
        with self.lock:
            append_jsonl(self.root / "sequence.jsonl", {"timestamp": utc_now(), "event": event, **fields})
        print(json.dumps({"event": event, **fields}), flush=True)

    def select(self, description: dict) -> list[dict]:
        profile = description["profiles"].get(self.args.profile)
        if profile is None:
            raise ValueError(f"unknown gateway profile: {self.args.profile}")
        if profile["complete_schedule_required"] and (self.args.case_file or self.args.limit):
            raise ValueError("this benchmark requires its complete schedule; omit --case-file and --limit")
        rows = self.gateway.cases(self.args.profile, self.args.panel)
        if self.args.case_file:
            wanted = json.loads(self.args.case_file.read_text(encoding="utf-8"))
            if not isinstance(wanted, list) or any(not isinstance(x, str) for x in wanted):
                raise ValueError("case file must be a JSON list of case IDs")
            if len(set(wanted)) != len(wanted):
                raise ValueError("case file lists a case more than once")
            by_id = {row["case_id"]: row for row in rows}
            missing = [case_id for case_id in wanted if case_id not in by_id]
            if missing:
                raise ValueError(f"{len(missing)} listed cases are not in the {self.args.panel} panel")
            rows = [by_id[case_id] for case_id in wanted]
        selected = [row for row in rows
                    if not (self.root / "cases" / _safe(row["case_id"]) / "completion.json").exists()]
        return selected[:self.args.limit] if self.args.limit else selected

    def run_case(self, case: dict, slot: str, local_port: int) -> bool:
        record = self.root / "cases" / _safe(case["case_id"])
        record.mkdir(parents=True, exist_ok=True)
        try:
            lease = self.gateway.rpc("launch", {"case_id": case["case_id"], "slot": slot})
        except GatewayClientError as exc:
            self.log("launch_failed", slot=slot, case_id=case["case_id"], error=str(exc))
            return False
        token = lease.pop("token")
        attempt = record / lease["lease_id"]
        attempt.mkdir()
        atomic_write_json(attempt / "lease.json", lease, overwrite=False)
        self.log("leased", slot=slot, case_id=case["case_id"], lease_id=lease["lease_id"])
        values = {"endpoint": f"http://127.0.0.1:{local_port}", "benchmark": lease["benchmark"],
                  "seed": str(lease["seed"]), "episodes": str(lease["episodes"]),
                  "run_id": self.args.run_id_prefix + _safe(case["case_id"]), "case_id": case["case_id"],
                  "episode_id": lease["episode_id"], "output_dir": str(attempt / "client")}
        command = _render(self.command, values)
        env = {key: value for key, value in os.environ.items() if key != self.token_env}
        env.update(command.get("env", {}))
        env[SERVICE_TOKEN_ENV] = token
        atomic_write_json(attempt / "client_command.json", {"argv": command["argv"], "cwd": command.get("cwd"),
                          "env_overrides": command.get("env", {})}, overwrite=False)
        returncode = None
        try:
            with (attempt / "client.log").open("x") as log:
                returncode = subprocess.run(command["argv"], cwd=command.get("cwd"), env=env,
                                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT).returncode
        finally:
            released = self.gateway.rpc("release", {"lease_id": lease["lease_id"]})
            atomic_write_json(attempt / "release.json", released, overwrite=False)
        completion = {"case_id": case["case_id"], "lease_id": lease["lease_id"], "client_returncode": returncode,
                      "episodes_opened": released["episodes_opened"], "cleanup": released["cleanup"],
                      "finished_at": utc_now()}
        # Exit 0 without any opened episode is a driver/configuration fault, not a result.
        ok = returncode == 0 and released["cleanup"] == "verified" and released["episodes_opened"] > 0
        if ok:
            atomic_write_json(record / "completion.json", completion, overwrite=False)
        self.log("closed" if ok else "engineering_error", slot=slot, **completion)
        return ok

    def run(self) -> int:
        slots = dict(self.args.slot)
        description = self.gateway.rpc("describe", {})
        described = {row["id"]: row for row in description["slots"]}
        unknown = [slot for slot in slots if slot not in described]
        if unknown:
            raise ValueError(f"unknown gateway slots: {', '.join(unknown)}")
        cases = self.select(description)
        self.log("selected", profile=self.args.profile, panel=self.args.panel, cases=len(cases), slots=list(slots))
        for case in cases:
            self.pending.put(case)
        lanes = [Lane(self, slot, port) for slot, port in slots.items()]
        for lane in lanes:
            lane.start()
        try:
            for lane in lanes:
                while lane.is_alive():
                    lane.join(timeout=1.0)
        except KeyboardInterrupt:
            # Running cases finish and are released; no new case starts.
            self.stopping.set()
            self.log("stop_requested")
            for lane in lanes:
                lane.join()
        errors = [lane.error for lane in lanes if lane.error]
        self.log("finished", engineering_errors=errors, remaining=self.pending.qsize())
        return 1 if errors else 0


def _slot(value: str) -> tuple[str, int]:
    name, _, port = value.partition("=")
    if not name or not port.isdigit():
        raise argparse.ArgumentTypeError("use SLOT_ID=LOCAL_FORWARDED_PORT")
    return name, int(port)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rsi-bench remote-run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--gateway", required=True, help="forwarded gateway control endpoint http://127.0.0.1:PORT")
    parser.add_argument("--gateway-token-env", default="RSI_GATEWAY_TOKEN")
    parser.add_argument("--profile", required=True, help="catalog profile, one benchmark deployment")
    parser.add_argument("--panel", choices=("default", "full"), default="default",
                        help="default: first N episodes per task (catalog, normally 5); full: every native episode; "
                             "equal for a benchmark that requires its complete schedule")
    parser.add_argument("--case-file", type=Path,
                        help="optional JSON list of case IDs, in run order; refused when the complete schedule is required")
    parser.add_argument("--limit", type=int,
                        help="run at most this many selected cases; refused when the complete schedule is required")
    parser.add_argument("--slot", type=_slot, action="append", required=True,
                        help="SLOT_ID=LOCAL_PORT; one sequential lane per slot")
    parser.add_argument("--client-command", type=Path, required=True,
                        help="JSON {argv, cwd, env} with placeholders " + ", ".join("{%s}" % p for p in PLACEHOLDERS))
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="sequencer records; reuse to continue, use a new one to run cases again")
    args = parser.parse_args(argv)
    if len({slot for slot, _ in args.slot}) != len(args.slot):
        parser.error("each slot may appear once")
    return Sequencer(args).run()


if __name__ == "__main__":
    sys.exit(main())
