"""Offline pipe/process fixtures only: no Codex, provider, native SIM or RPC."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from AgentPolicies.gpt6_astra.transports.codex_app_server import (
    RpcError, StdioAppServer, TransportError, TransportLimits, TransportTimeout,
    child_environment,
)


_PRELUDE = """
import json, os, signal, subprocess, sys, time
def emit(value):
    print(json.dumps(value), flush=True)
"""


class AppServerTransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rsi-app-server-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.actor = self.root / "actor"
        self.actor.mkdir()
        self.index = 0

    def start(self, program, *, limits=None, env=None):
        self.index += 1
        transport = StdioAppServer([sys.executable, "-u", "-c", _PRELUDE + program],
            self.root / f"host-{self.index}", cwd=self.actor, limits=limits, env=env)
        self.addCleanup(lambda: transport.close() if not transport.receipt()["closed"] else None)
        return transport

    def eventually(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("offline child condition did not become true")
            time.sleep(0.005)

    def echo(self, prefix=""):
        return prefix + """
for line in sys.stdin:
    request = json.loads(line)
    if 'id' in request and 'method' in request:
        emit({'id': request['id'], 'result': {'method': request['method'], 'params': request['params']}})
"""

    def test_persistent_requests_notifications_tool_reply_and_no_jsonrpc_header(self):
        transport = self.start("""
for line in sys.stdin:
    request = json.loads(line)
    assert 'jsonrpc' not in request
    if request.get('method') == 'initialize':
        emit({'method': 'thread/started', 'params': {'thread': {'id': 'thread-local'}}})
        emit({'id': request['id'], 'result': {'ready': True}})
    elif request.get('method') == 'initialized':
        emit({'id': 'tool-one', 'method': 'item/tool/call', 'params': {'tool': 'robodojo_act'}})
    elif request.get('id') == 'tool-one':
        emit({'method': 'turn/completed', 'params': {'ack': request['result']}})
    else:
        emit({'id': request['id'], 'result': {'same_process': os.getpid()}})
""")
        pid = transport.process.pid
        self.assertEqual(transport.request("initialize", {}, 2), {"ready": True})
        self.assertEqual(transport.next_message(2)["method"], "thread/started")
        transport.notify("initialized", {})
        tool = transport.next_message(2)
        self.assertEqual(tool["id"], "tool-one")
        transport.reply(tool["id"], {"success": True})
        self.assertTrue(transport.next_message(2)["params"]["ack"]["success"])
        self.assertEqual(transport.request("thread/read", {}, 2), {"same_process": pid})
        with self.assertRaises(TransportError) as caught:
            transport.reply(tool["id"], {})
        self.assertEqual(caught.exception.code, "unknown_server_request")
        self.assertEqual(transport.receipt()["counts"]["requests_completed"], 2)

    def test_stderr_warning_is_diagnostic_not_failure_and_is_redacted(self):
        prefix = """
sys.stderr.write('warning: keep this useful diagnostic\\nAuthorization: Bearer local-secret\\nRSI_SIM_SERVER_TOKEN=fixture-private-token\\napi_key=sk-fixture12345678\\n')
sys.stderr.flush()
"""
        transport = self.start(self.echo(prefix))
        self.assertEqual(transport.request("initialize", {}, 2)["method"], "initialize")
        transport.close()
        log = (transport.workspace / "stderr.redacted.log").read_text()
        self.assertIn("keep this useful diagnostic", log)
        self.assertIn("[REDACTED]", log)
        for secret in ("local-secret", "fixture-private-token", "sk-fixture12345678"):
            self.assertNotIn(secret, log)
            self.assertNotIn(secret, json.dumps(transport.diagnostics()))
        self.assertIsNone(transport.diagnostics()["failure_code"])
        self.assertGreater(transport.diagnostics()["counts"]["stderr_redactions"], 0)

    def test_rpc_payload_reasoning_auth_and_unknown_method_are_not_logged(self):
        transport = self.start(self.echo())
        payload = {"reasoning": "PRIVATE_REASONING_FIXTURE", "encryptedContent": "ENCRYPTED_FIXTURE",
                   "auth": {"token": "AUTH_FIXTURE"}, "content": "OBSERVATION_FIXTURE"}
        transport.request("unknown_PRIVATE_METHOD", payload, 2)
        transport.close()
        logs = (transport.workspace / "rpc_metadata.jsonl").read_text()
        summary = json.dumps(transport.diagnostics())
        for secret in ("PRIVATE_REASONING_FIXTURE", "ENCRYPTED_FIXTURE", "AUTH_FIXTURE",
                       "OBSERVATION_FIXTURE", "unknown_PRIVATE_METHOD"):
            self.assertNotIn(secret, logs + summary)
        entries = [json.loads(line) for line in logs.splitlines()]
        self.assertEqual({entry["direction"] for entry in entries}, {"stdin", "stdout"})
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in entries))
        self.assertFalse(transport.receipt()["rpc_payloads_retained"])

    def test_rpc_error_is_safe_and_does_not_hide_reply_code(self):
        transport = self.start("""
for line in sys.stdin:
    request = json.loads(line)
    emit({'id': request['id'], 'error': {'code': -32602, 'message': 'PRIVATE_ERROR_FIXTURE', 'data': {'token': 'private'}}})
""")
        with self.assertRaises(RpcError) as caught:
            transport.request("thread/start", {}, 2)
        self.assertEqual(caught.exception.code, "rpc_error")
        self.assertEqual(caught.exception.rpc_code, -32602)
        self.assertNotIn("PRIVATE_ERROR_FIXTURE", str(caught.exception))
        self.assertIsNone(transport.diagnostics()["failure_code"])
        self.assertEqual(transport.diagnostics()["counts"]["rpc_errors"], 1)

    def test_eof_wakes_waiting_rpc_without_timeout(self):
        transport = self.start("sys.stdin.readline()\nsys.stderr.write('startup failure retained\\n')\n")
        started = time.monotonic()
        with self.assertRaises(TransportError) as caught:
            transport.request("initialize", {}, 5)
        self.assertEqual(caught.exception.code, "stdout_eof")
        self.assertLess(time.monotonic() - started, 2)
        transport.close()
        self.assertIn("startup failure retained", (transport.workspace / "stderr.redacted.log").read_text())

    def test_request_timeout_poisoned_no_reissue_and_process_reaped(self):
        transport = self.start("sys.stdin.readline()\ntime.sleep(30)\n")
        with self.assertRaises(TransportTimeout) as caught:
            transport.request("initialize", {}, 0.15)
        self.assertIsInstance(caught.exception, TimeoutError)
        self.assertEqual(caught.exception.code, "request_timeout")
        with self.assertRaises(TransportError):
            transport.request("initialize", {}, 1)
        self.assertEqual(transport.diagnostics()["counts"]["requests_started"], 1)
        transport.close()
        self.assertTrue(transport.diagnostics()["cleanup"]["process_reaped"])
        self.assertEqual(transport.diagnostics()["wrapper_restarts"], 0)

    def test_event_idle_timeout_allows_explicit_read_only_request(self):
        transport = self.start(self.echo())
        with self.assertRaises(TransportTimeout) as caught:
            transport.next_message(0.02)
        self.assertEqual(caught.exception.code, "event_timeout")
        self.assertIsNone(transport.diagnostics()["failure_code"])
        self.assertEqual(transport.request("thread/read", {}, 2)["method"], "thread/read")

    def test_strict_json_rejects_duplicates_nonfinite_invalid_utf8_and_partial(self):
        values = (b'{"method":"x","method":"y"}\n', b'{"method":"x","params":{"x":NaN}}\n',
                  b'{"method":"x","params":{"x":1e400}}\n', b'\xff\n', b'{"method":"x"}')
        for data in values:
            with self.subTest(data=data):
                transport = self.start(f"sys.stdin.readline()\nos.write(1, {data!r})\n")
                with self.assertRaises(TransportError) as caught:
                    transport.request("initialize", {}, 2)
                self.assertEqual(caught.exception.code, "invalid_json")

    def test_unknown_response_and_invalid_envelope_rejected(self):
        for value, code in (({"id": 999, "result": {}}, "unexpected_response"),
                            ({"method": "notice", "params": [], "id": True}, "invalid_envelope")):
            with self.subTest(code=code):
                transport = self.start(f"sys.stdin.readline()\nemit({value!r})\ntime.sleep(30)\n")
                with self.assertRaises(TransportError) as caught:
                    transport.request("initialize", {}, 2)
                self.assertEqual(caught.exception.code, code)

    def test_parallel_requests_correlate_out_of_order_replies(self):
        transport = self.start("""
first = json.loads(sys.stdin.readline())
second = json.loads(sys.stdin.readline())
emit({'id': second['id'], 'result': second['params']})
emit({'id': first['id'], 'result': first['params']})
time.sleep(30)
""")
        result, errors = {}, []
        def request(index):
            try:
                result[index] = transport.request("thread/read", {"index": index}, 2)
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=request, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertFalse(errors)
        self.assertEqual(result, {0: {"index": 0}, 1: {"index": 1}})

    def test_message_and_queue_limits(self):
        transport = self.start("sys.stdin.readline()\nos.write(1, b'x' * 512)\ntime.sleep(30)\n",
            limits=replace(TransportLimits(), max_message_bytes=128))
        with self.assertRaises(TransportError) as caught:
            transport.request("initialize", {}, 2)
        self.assertEqual(caught.exception.code, "message_limit")
        transport = self.start("""
sys.stdin.readline()
for i in range(3): emit({'method': 'thread/started', 'params': {'index': i}})
time.sleep(30)
""", limits=replace(TransportLimits(), max_queued_messages=2))
        with self.assertRaises(TransportError) as caught:
            transport.request("initialize", {}, 2)
        self.assertEqual(caught.exception.code, "queue_limit")

    def test_stderr_and_metadata_logs_are_bounded_without_failing_request(self):
        transport = self.start(self.echo("sys.stderr.write('warning ' * 1000 + '\\n')\nsys.stderr.flush()\n"),
            limits=replace(TransportLimits(), max_stderr_bytes=40, max_rpc_log_bytes=1))
        transport.request("initialize", {}, 2)
        transport.close()
        summary = transport.diagnostics()
        self.assertTrue(summary["stderr_truncated"])
        self.assertTrue(summary["rpc_log_truncated"])
        self.assertEqual((transport.workspace / "stderr.redacted.log").stat().st_size, 40)
        self.assertEqual((transport.workspace / "rpc_metadata.jsonl").stat().st_size, 0)
        self.assertIsNone(summary["failure_code"])

    def test_oversized_stderr_line_is_omitted_and_following_line_kept(self):
        transport = self.start(self.echo("os.write(2, b'X' * 100 + b'\\nuseful next line\\n')\n"),
            limits=replace(TransportLimits(), max_stderr_line_bytes=32))
        transport.request("initialize", {}, 2)
        transport.close()
        log = (transport.workspace / "stderr.redacted.log").read_text()
        self.assertEqual(log, "useful next line\n")
        self.assertEqual(transport.diagnostics()["counts"]["stderr_omitted_lines"], 1)

    def test_private_create_only_diagnostics_and_separate_cwd(self):
        transport = self.start(self.echo())
        transport.request("initialize", {}, 2)
        transport.close()
        for name in ("rpc_metadata.jsonl", "stderr.redacted.log"):
            self.assertEqual(stat.S_IMODE((transport.workspace / name).stat().st_mode), 0o600)
        with self.assertRaises(TransportError) as caught:
            StdioAppServer(["not-started"], transport.workspace, cwd=self.actor)
        self.assertEqual(caught.exception.code, "workspace_unavailable")
        with self.assertRaises(TransportError):
            StdioAppServer(["not-started"], self.actor / "private", cwd=self.actor)

    def test_environment_allowlist_drops_sim_and_api_tokens(self):
        values = {"PATH": os.environ.get("PATH", "/usr/bin"), "LANG": "C",
                  "RSI_SIM_SERVER_TOKEN": "fake-sim-token", "OPENAI_API_KEY": "fake-api-key",
                  "UNDECLARED_FIXTURE": "fake-private-value"}
        transport = self.start("""
for line in sys.stdin:
    request = json.loads(line)
    emit({'id': request['id'], 'result': sorted(os.environ)})
""", env=values)
        names = transport.request("initialize", {}, 2)
        self.assertIn("PATH", names)
        for name in ("RSI_SIM_SERVER_TOKEN", "OPENAI_API_KEY", "UNDECLARED_FIXTURE"):
            self.assertNotIn(name, names)
        self.assertEqual(child_environment(values), {"PATH": values["PATH"], "LANG": "C"})

    def test_raw_stderr_hash_preserved_but_raw_secret_not_retained(self):
        raw = b"access_token=private-test-token\n"
        transport = self.start(self.echo(f"os.write(2, {raw!r})\n"))
        transport.request("initialize", {}, 2)
        transport.close()
        self.assertEqual(transport.diagnostics()["stream_sha256"]["stderr"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(transport.diagnostics()["counts"]["stderr_bytes"], len(raw))
        self.assertNotIn("private-test-token", (transport.workspace / "stderr.redacted.log").read_text())

    def test_owned_group_cleanup_reaps_leader_and_stops_child(self):
        transport = self.start("""
child = subprocess.Popen([sys.executable, '-u', '-c', "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(30)"], stdout=subprocess.PIPE)
assert child.stdout.readline() == b'ready\\n'
emit({'method': 'thread/started', 'params': {'child_pid': child.pid}})
time.sleep(30)
""")
        child_pid = transport.next_message(2)["params"]["child_pid"]
        transport.close()
        self.assertIsNotNone(transport.process.poll())
        self.assertTrue(transport.diagnostics()["cleanup"]["process_reaped"])
        self.assertTrue(transport.diagnostics()["cleanup"]["readers_stopped"])
        self.assertTrue(transport.diagnostics()["cleanup"]["sent_kill"])
        def stopped():
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                return True
            # On Linux an adopted orphan may briefly remain a non-running zombie.
            path = Path(f"/proc/{child_pid}/stat")
            return path.exists() and ") Z " in path.read_text()
        self.eventually(stopped)
        transport.close()

    def test_spawn_failure_is_sanitized_and_diagnostic_files_closed(self):
        def failing(*args, **kwargs):
            raise OSError("PRIVATE_SPAWN_ERROR")
        with self.assertRaises(TransportError) as caught:
            StdioAppServer(["missing"], self.root / "failed", cwd=self.actor, popen=failing)
        self.assertEqual(caught.exception.code, "spawn_failed")
        self.assertNotIn("PRIVATE_SPAWN_ERROR", str(caught.exception))
        self.assertTrue(caught.exception.diagnostics["cleanup"]["succeeded"])

    def test_invalid_outbound_json_does_not_reach_process(self):
        transport = self.start(self.echo())
        with self.assertRaises(TransportError) as caught:
            transport.request("initialize", {"bad": float("nan")}, 1)
        self.assertEqual(caught.exception.code, "invalid_input")
        self.assertEqual(transport.diagnostics()["counts"]["stdin_bytes"], 0)
        self.assertEqual(transport.request("initialize", {}, 2)["method"], "initialize")

    def test_slow_stdin_is_bounded_without_retry(self):
        transport = self.start("time.sleep(30)\n")
        started = time.monotonic()
        with self.assertRaises(TransportTimeout) as caught:
            transport.request("initialize", {"large": "a" * 1024 * 1024}, 0.1)
        self.assertEqual(caught.exception.code, "write_timeout")
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(transport.diagnostics()["counts"]["requests_started"], 1)

    def test_write_lock_wait_obeys_same_request_deadline(self):
        transport = self.start(self.echo())
        transport._write_lock.acquire()
        started = time.monotonic()
        try:
            with self.assertRaises(TransportTimeout) as caught:
                transport.request("initialize", {}, 0.03)
        finally:
            transport._write_lock.release()
        self.assertEqual(caught.exception.code, "write_timeout")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(transport.receipt()["counts"]["stdin_bytes"], 0)

    def test_closed_transport_never_returns_queued_tool_calls(self):
        transport = self.start("""
emit({'id': 'stale-tool', 'method': 'item/tool/call', 'params': {}})
time.sleep(30)
""")
        self.eventually(lambda: transport.receipt()["counts"]["messages_received"] == 1)
        transport.close()
        with self.assertRaises(TransportError) as caught:
            transport.next_message(1)
        self.assertEqual(caught.exception.code, "closed")

    def test_duplicate_outstanding_server_request_is_rejected(self):
        transport = self.start("""
sys.stdin.readline()
emit({'id': 'duplicate', 'method': 'item/tool/call', 'params': {}})
emit({'id': 'duplicate', 'method': 'item/tool/call', 'params': {}})
time.sleep(30)
""")
        with self.assertRaises(TransportError) as caught:
            transport.request("initialize", {}, 2)
        self.assertEqual(caught.exception.code, "duplicate_server_request")
        with self.assertRaises(TransportError):
            transport.next_message(1)

    def test_limit_and_timeout_values_are_strict(self):
        for kwargs in ({"max_message_bytes": True}, {"max_stderr_bytes": 0},
                       {"write_timeout_s": float("nan")}, {"cleanup_grace_s": 10**400}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TransportError):
                TransportLimits(**kwargs)
        transport = self.start(self.echo())
        for timeout in (True, 0, -1, float("inf"), 10**400):
            with self.subTest(timeout=timeout), self.assertRaises(TransportError):
                transport.request("initialize", {}, timeout)
        self.assertEqual(transport.receipt()["counts"]["stdin_bytes"], 0)

    def test_diagnostic_symlink_is_not_followed_or_overwritten(self):
        workspace = self.root / "bad-host"
        workspace.mkdir()
        target = self.root / "existing-evidence"
        target.write_text("preserve")
        (workspace / "rpc_metadata.jsonl").symlink_to(target)
        with self.assertRaises(TransportError) as caught:
            StdioAppServer(["not-started"], workspace, cwd=self.actor)
        self.assertEqual(caught.exception.code, "workspace_unavailable")
        self.assertEqual(target.read_text(), "preserve")

    def test_cleanup_failure_is_visible_not_silenced(self):
        transport = StdioAppServer([sys.executable, "-u", "-c", _PRELUDE + self.echo()],
            self.root / "expected-cleanup-error", cwd=self.actor)
        def cleanup():
            try:
                transport.close()
            except TransportError:
                if transport.process.poll() is None:
                    raise
        self.addCleanup(cleanup)
        transport.request("initialize", {}, 2)
        real_killpg = os.killpg
        def deny_term(pid, sig):
            if sig == signal.SIGTERM:
                raise PermissionError("private process message")
            return real_killpg(pid, sig)
        with patch("AgentPolicies.gpt6_astra.transports.codex_app_server.os.killpg", side_effect=deny_term):
            with self.assertRaises(TransportError) as caught:
                transport.close()
        self.assertEqual(caught.exception.code, "cleanup_failed")
        self.assertIn("group_term_failed", transport.receipt()["cleanup"]["errors"])
        self.assertTrue(transport.receipt()["cleanup"]["process_reaped"])
        self.assertNotIn("private process message", json.dumps(transport.receipt()))
        # close remains idempotent in effects and consistently reports the error.
        with self.assertRaises(TransportError):
            transport.close()

    def test_emitted_at_ms_official_event_metadata_is_accepted_strictly(self):
        transport = self.start("""
for line in sys.stdin:
    request = json.loads(line)
    emit({'method': 'remoteControl/status/changed', 'params': {'status': 'disabled'}, 'emittedAtMs': 1789630000000})
    emit({'id': request['id'], 'result': {}})
""")
        transport.request("initialize", {}, 2)
        event = transport.next_message(2)
        self.assertEqual(event["method"], "remoteControl/status/changed")
        self.assertEqual(event["emittedAtMs"], 1789630000000)
        for value in (True, -1, 1.5, "1", None):
            with self.subTest(value=value):
                transport = self.start("sys.stdin.readline()\nemit(" + repr(
                    {"method": "remoteControl/status/changed", "params": {}, "emittedAtMs": value}) + ")\ntime.sleep(30)\n")
                with self.assertRaises(TransportError) as caught:
                    transport.request("initialize", {}, 2)
                self.assertEqual(caught.exception.code, "invalid_envelope")

    def test_timestamp_does_not_allow_arbitrary_keys_or_response_extensions(self):
        for message in ({"method": "notice", "params": {}, "span": "unexpected"},
                        {"id": 1, "result": {}, "emittedAtMs": 10}):
            transport = self.start(f"sys.stdin.readline()\nemit({message!r})\ntime.sleep(30)\n")
            with self.assertRaises(TransportError) as caught:
                transport.request("initialize", {}, 2)
            self.assertEqual(caught.exception.code, "invalid_envelope")

    def test_reaped_reused_numeric_pid_never_receives_destructive_group_signal(self):
        transport = self.start(self.echo())
        transport.request("initialize", {}, 2)
        # Deliberately reap this fixture leader before transport close, then
        # simulate an unrelated group acquiring the same numeric identifier.
        transport.process.terminate()
        transport.process.wait(timeout=2)
        calls = []
        def reused_group(pid, sig):
            calls.append((pid, sig))
            if sig != 0:
                self.fail("destructive signal targeted a reaped/reused identifier")
        with patch("AgentPolicies.gpt6_astra.transports.codex_app_server.os.killpg", side_effect=reused_group):
            with self.assertRaises(TransportError) as caught:
                transport.close()
        self.assertEqual(caught.exception.code, "cleanup_failed")
        self.assertTrue(calls)
        self.assertTrue(all(sig == 0 for _, sig in calls))
        self.assertFalse(transport.receipt()["cleanup"]["ownership_proven"])
        self.assertFalse(transport.receipt()["cleanup"]["group_cleanup_verified"])
        self.assertIn("group_ownership_unverified", transport.receipt()["cleanup"]["errors"])

    def test_group_signals_hold_child_wait_lock_and_precede_reaping(self):
        transport = self.start(self.echo())
        transport.request("initialize", {}, 2)
        real_killpg = os.killpg
        observations = []
        def checked(pid, sig):
            if sig != 0:
                observations.append(sig)
                self.assertIsNone(transport.process.returncode)
                acquired = transport.process._waitpid_lock.acquire(blocking=False)
                if acquired:
                    transport.process._waitpid_lock.release()
                self.assertFalse(acquired, "group signal must retain the child lifecycle lock")
            return real_killpg(pid, sig)
        with patch("AgentPolicies.gpt6_astra.transports.codex_app_server.os.killpg", side_effect=checked):
            transport.close()
        self.assertTrue(observations)
        self.assertTrue(transport.receipt()["cleanup"]["ownership_proven"])
        self.assertTrue(transport.receipt()["cleanup"]["process_reaped"])


if __name__ == "__main__":
    unittest.main()
