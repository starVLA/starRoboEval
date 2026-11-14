"""Agent-host case sequencer for a bench-host gateway (trusted driver side).

Each lane owns one gateway slot. It takes the next case of the selected
profile panel, leases it, runs the declared client command against the
forwarded slot endpoint with the lease token, and releases the lease. Switching
benchmark, task or episode is a different catalog case: no shell on the bench
host and no change to the per-episode SIM protocol.

A lane stops at its first engineering error, keeping the record. The first
start records the planned case list (after --case-file, before --limit) in
plan.json; a rerun planning other cases is refused. A case
without a completion record is leased again when rerunning with the same
output directory, in a new attempt directory beside the old one, with a run ID
naming the case and the lease; cases with a completion record are skipped, and
a corrupt one stops the run. A crash is not an attempt, but a nonzero exit
after an episode opened can also be a recorded policy error, which is a
result: review the client record before rerunning such a case. This tool does
not stop a new output directory from running completed cases again; doing so
would be an unauthorized second attempt. The gateway token stays in this
process; the client command receives only its lease's service token.

A first Ctrl-C starts no new case and lets running clients finish; a second
one, SIGTERM or SIGHUP interrupts them. Each lease is released after its client
process group is gone. Leases recorded but left unreleased by a killed sequencer
are released, after their orphaned clients are stopped, when it next starts with
the same output directory. A lease launched but not yet recorded when the
sequencer died stays held: an operator or a gateway restart must free that slot.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

from benchkit.artifacts import append_jsonl, atomic_write_json, utc_now
from benchkit.sim_server.gateway import GATEWAY_PROTOCOL, RPC_TIMEOUT_S, SERVICE_TOKEN_ENV, group_alive
from benchkit.sim_server.wire import MAX_MESSAGE_BYTES, dumps, loads

PLACEHOLDERS = ("endpoint", "benchmark", "seed", "episodes", "run_id", "case_id", "episode_id", "output_dir")
# Bounded wait after each signal to an interrupted client group before escalating.
CLIENT_STOP_SIGNALS = ((signal.SIGINT, 30.0), (signal.SIGTERM, 10.0), (signal.SIGKILL, 10.0))
FINAL_LEASE_STATES = ("released", "startup_failed")
COMPLETION_KEYS = ("case_id", "lease_id", "client_returncode", "episodes_opened", "cleanup", "finished_at")
PLAN_SCHEMA = "starvla-rsi.remote-run-plan/v1"


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


def case_directory(case_id: str) -> str:
    """Directory name of one case under cases/ (also the client run ID stem).

    Starts with a letter or digit, so an unprefixed run ID stays valid.
    """
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", case_id).strip("-_.")[:96] or "case"
    return f"{stem}-{hashlib.sha256(case_id.encode()).hexdigest()[:8]}"


def _render(template, values: dict):
    if isinstance(template, str):
        return template.format(**values)
    if isinstance(template, list):
        return [_render(item, values) for item in template]
    if isinstance(template, dict):
        return {key: _render(value, values) for key, value in template.items()}
    raise ValueError("client command templates contain only strings, lists and objects")


def _started(pid: int) -> str | None:
    """Process start time (ps on macOS and Linux): a reused pid has another one.

    None (no ps, or no lstart support) only disables the orphan stop.
    """
    try:
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                                env={**os.environ, "LC_ALL": "C", "TZ": "UTC"}, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


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
        while not self.runner.stopping:
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
        # Startup releases every unreleased lease recorded here, so one sequencer per directory.
        self.dir_lock = (self.root / "sequence.lock").open("a")
        try:
            fcntl.flock(self.dir_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another remote-run is using this output directory") from None
        # Plain flags, set by the signal handler (Event.set could deadlock in a re-entered handler).
        self.stopping = self.aborting = False
        self.lock = threading.Lock()
        self.pending: queue.Queue = queue.Queue()

    def log(self, event: str, **fields) -> None:
        with self.lock:
            append_jsonl(self.root / "sequence.jsonl", {"timestamp": utc_now(), "event": event, **fields})
        try:
            print(json.dumps({"event": event, **fields}), flush=True)
        except OSError:
            pass  # A hung-up terminal must not stop lease release.

    def interrupt(self, signum, _frame) -> None:
        # Flags only; the main thread logs them. Signals after an abort change nothing.
        if signum != signal.SIGINT or self.stopping:
            self.aborting = True
        self.stopping = True

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
        self.record_plan(profile, [row["case_id"] for row in rows])
        selected = [row for row in rows if not self.completed(row["case_id"])]
        return selected[:self.args.limit] if self.args.limit else selected

    def record_plan(self, profile: dict, case_ids: list[str]) -> None:
        """Fix the planned cases of this directory on first start; a rerun must match.

        The plan is the publication denominator; --limit only bounds one sitting.
        """
        plan = {"schema_version": PLAN_SCHEMA, "profile": self.args.profile, "panel": self.args.panel,
                "complete_schedule_required": profile["complete_schedule_required"], "case_ids": case_ids}
        path = self.root / "plan.json"
        if not path.exists():
            atomic_write_json(path, plan, overwrite=False)
            return
        recorded = json.loads(path.read_text(encoding="utf-8"))
        if recorded != plan:
            raise ValueError(f"{path} plans different cases (profile, panel or case list); "
                             "use a new output directory for another plan")

    def completed(self, case_id: str) -> bool:
        """A case is done only by a valid completion record; a corrupt one stops the run."""
        path = self.root / "cases" / case_directory(case_id) / "completion.json"
        if not path.exists():
            return False
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            valid = (isinstance(record, dict) and set(record) == set(COMPLETION_KEYS)
                     and record["case_id"] == case_id and isinstance(record["lease_id"], str)
                     and record["client_returncode"] == 0 and record["cleanup"] == "verified"
                     and type(record["episodes_opened"]) is int and record["episodes_opened"] > 0)
        except (OSError, ValueError):
            valid = False
        if not valid:
            raise ValueError(f"invalid completion record {path}; inspect it before rerunning")
        return True

    def run_case(self, case: dict, slot: str, local_port: int) -> bool:
        record = self.root / "cases" / case_directory(case["case_id"])
        record.mkdir(parents=True, exist_ok=True)
        try:
            lease = self.gateway.rpc("launch", {"case_id": case["case_id"], "slot": slot})
        except GatewayClientError as exc:
            self.log("launch_failed", slot=slot, case_id=case["case_id"], error=str(exc))
            return False
        token = lease.pop("token")
        attempt = record / lease["lease_id"]
        try:
            attempt.mkdir()
            atomic_write_json(attempt / "lease.json", lease, overwrite=False)
            self.log("leased", slot=slot, case_id=case["case_id"], lease_id=lease["lease_id"])
            values = {"endpoint": f"http://127.0.0.1:{local_port}", "benchmark": lease["benchmark"],
                      "seed": str(lease["seed"]), "episodes": str(lease["episodes"]),
                      "run_id": f"{self.args.run_id_prefix}{case_directory(case['case_id'])}-{lease['lease_id']}",
                      "case_id": case["case_id"],
                      "episode_id": lease["episode_id"], "output_dir": str(attempt / "client")}
            command = _render(self.command, values)
            env = {key: value for key, value in os.environ.items() if key != self.token_env}
            env.update(command.get("env", {}))
            env[SERVICE_TOKEN_ENV] = token
            atomic_write_json(attempt / "client_command.json", {"argv": command["argv"], "cwd": command.get("cwd"),
                              "env_overrides": command.get("env", {})}, overwrite=False)
            returncode = self.run_client(command, env, attempt)
        except BaseException:
            # The gateway has no lease expiry: release before the fault propagates,
            # without letting a release failure replace the fault.
            try:
                self.release(lease["lease_id"], attempt)
            except Exception as exc:
                self.log("release_failed", slot=slot, case_id=case["case_id"], lease_id=lease["lease_id"],
                         error=f"{type(exc).__name__}: {exc}")
            raise
        released = self.release(lease["lease_id"], attempt)
        completion = {"case_id": case["case_id"], "lease_id": lease["lease_id"], "client_returncode": returncode,
                      "episodes_opened": released["episodes_opened"], "cleanup": released["cleanup"],
                      "finished_at": utc_now()}
        # Exit 0 without any opened episode is a driver/configuration fault, not a result.
        ok = returncode == 0 and released["cleanup"] == "verified" and released["episodes_opened"] > 0
        if ok:
            atomic_write_json(record / "completion.json", completion, overwrite=False)
        self.log("closed" if ok else "engineering_error", slot=slot, **completion)
        return ok

    def run_client(self, command: dict, env: dict, attempt: Path) -> int | None:
        if self.aborting:
            return None
        with (attempt / "client.log").open("x") as log:
            # Its own session keeps a terminal Ctrl-C away from the client; the sequencer decides.
            process = subprocess.Popen(command["argv"], cwd=command.get("cwd"), env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                atomic_write_json(attempt / "client_process.json",
                                  {"pid": process.pid, "started": _started(process.pid)}, overwrite=False)
                while process.poll() is None and not self.aborting:
                    time.sleep(0.5)
            finally:
                # Also ends descendants that outlive the client, before its lease is released.
                if process.poll() is None or group_alive(process.pid):
                    self.stop_group(attempt, process.pid, process)
            return process.returncode

    def stop_group(self, attempt: Path, pgid: int, process: subprocess.Popen | None = None) -> None:
        """Signal only a client's own process group, escalating until it is gone."""
        for sig, seconds in CLIENT_STOP_SIGNALS:
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Not ours, or only zombies remain (macOS): nothing this sequencer may signal.
                self.log("client_group_not_signalled", attempt=str(attempt), pgid=pgid)
                return
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if (process is None or process.poll() is not None) and not group_alive(pgid):
                    return
                time.sleep(0.2)
        self.log("client_group_survived", attempt=str(attempt), pgid=pgid)

    def release(self, lease_id: str, attempt: Path) -> dict:
        released = self.gateway.rpc("release", {"lease_id": lease_id})
        # A concurrent stop (gateway shutdown) returns its in-progress state: wait for the final one.
        deadline = time.monotonic() + RPC_TIMEOUT_S
        while released["state"] not in FINAL_LEASE_STATES:
            if time.monotonic() > deadline:
                raise GatewayClientError(f"lease_not_final: {released['state']}")
            time.sleep(2.0)
            released = self.gateway.rpc("lease", {"lease_id": lease_id})
        atomic_write_json(attempt / "release.json", released, overwrite=False)
        return released

    def release_stale(self) -> None:
        """Release leases recorded here without a release record (a killed sequencer)."""
        for path in sorted(self.root.glob("cases/*/*/lease.json")):
            attempt = path.parent
            if (attempt / "release.json").exists() or (attempt / "release_unknown.json").exists():
                continue
            lease_id = json.loads(path.read_text(encoding="utf-8"))["lease_id"]
            client = attempt / "client_process.json"
            try:
                recorded = json.loads(client.read_text(encoding="utf-8")) if client.exists() else None
                pid, started = (recorded["pid"], recorded["started"]) if recorded else (None, None)
            except (OSError, ValueError, KeyError, TypeError):
                self.log("client_record_unreadable", attempt=str(attempt))
                pid = started = None
            # An orphaned client is stopped first; only a leader with the recorded start time is ours.
            if type(pid) is int and started is not None and _started(pid) == started:
                self.stop_group(attempt, pid)
            try:
                released = self.release(lease_id, attempt)
            except GatewayClientError as exc:
                if str(exc) != "unknown_lease":
                    raise
                # A restarted gateway stopped its services at shutdown and forgot the lease.
                atomic_write_json(attempt / "release_unknown.json", {"lease_id": lease_id, "checked_at": utc_now()},
                                  overwrite=False)
                self.log("stale_lease_unknown", lease_id=lease_id)
                continue
            self.log("stale_lease_released", lease_id=lease_id, state=released["state"],
                     cleanup=released["cleanup"])

    def join(self, lanes: list[Lane]) -> None:
        reported = set()
        for lane in lanes:
            while lane.is_alive():
                lane.join(timeout=0.5)
                for event, flag in (("stop_requested", self.stopping), ("abort_requested", self.aborting)):
                    if flag and event not in reported:
                        reported.add(event)
                        self.log(event)

    def run(self) -> int:
        slots = dict(self.args.slot)
        description = self.gateway.rpc("describe", {})
        described = {row["id"]: row for row in description["slots"]}
        unknown = [slot for slot in slots if slot not in described]
        if unknown:
            raise ValueError(f"unknown gateway slots: {', '.join(unknown)}")
        self.release_stale()
        cases = self.select(description)
        self.log("selected", profile=self.args.profile, panel=self.args.panel, cases=len(cases), slots=list(slots))
        for case in cases:
            self.pending.put(case)
        lanes = [Lane(self, slot, port) for slot, port in slots.items()]
        # Leases exist only from here: signals now stop or abort the lanes instead of raising.
        signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        previous = {sig: signal.signal(sig, self.interrupt) for sig in signals}
        try:
            for lane in lanes:
                lane.start()
            self.join(lanes)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
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
