"""Offline Codex transport checks using an owned fake executable, never a model."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchkit.errors import PolicyCallError, PolicyPreflightError
from AgentPolicies.gpt6_astra.transports import codex_cli


SECRET = "private-provider-body-or-hidden-reasoning-must-not-persist"
PNG = codex_cli.PNG_SIGNATURE + b"offline-test-image"
TEXT = '{"stop":false,"actions":[[0.1]],"note":"move"}'
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"stop": {"type": "boolean"}}, "required": ["stop"]}


def stream(text=TEXT):
    return [
        {"type": "thread.started", "thread_id": "f49ee5c4-b932-4fba-a5a7-f67f9718de36"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "item-0", "type": "reasoning", "text": SECRET}},
        {"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": text}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 3,
            "output_tokens": 5, "reasoning_output_tokens": 2, "cache_write_input_tokens": 1}},
    ]


class CodexCliChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rsi-fake-codex-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.capture = self.root / "capture.jsonl"
        self.executable = self.root / "fake-codex"
        self.resolver = patch.object(codex_cli, "_resolve_executable", return_value=self.executable)
        self.resolver.start()
        self.addCleanup(self.resolver.stop)
        self.fake()

    def fake(self, *, events=None, mode="normal", exit_code=0, version=codex_cli.CLI_VERSION,
             login="Logged in using ChatGPT", login_code=0, help_text=None, raw=None, stderr_text=None,
             attempts=None):
        if help_text is None:
            help_text = "--ignore-user-config --ignore-rules --strict-config --ephemeral --sandbox " \
                        "--json --output-schema --image --model --color"
        data = {"events": stream() if events is None else events, "mode": mode, "exit_code": exit_code,
                "version": version, "login": login, "login_code": login_code, "help": help_text,
                "capture": str(self.capture), "raw": raw, "secret": SECRET, "stderr_text": stderr_text,
                "attempts": attempts}
        # This executable implements only fixture behavior. No installed Codex
        # executable, auth material, network endpoint or native environment is used.
        script = f"#!{sys.executable}\n" + """
import json, os, pathlib, sys, time
DATA = json.loads(CONFIGURATION)
args = sys.argv[1:]
with open(DATA['capture'], 'a') as handle:
    handle.write(json.dumps({'argv':args}) + '\\n')
if args == ['--version']:
    print('codex-cli ' + DATA['version'])
elif args == ['exec', '--help']:
    print(DATA['help'])
elif args == ['login', 'status']:
    print(DATA['login'], file=sys.stderr)
    sys.exit(DATA['login_code'])
else:
    prompt = sys.stdin.buffer.read().decode()
    if DATA['attempts']:
        previous = sum('cwd' in json.loads(line) for line in pathlib.Path(DATA['capture']).read_text().splitlines())
        DATA.update(DATA['attempts'][min(previous, len(DATA['attempts']) - 1)])
    paths = [args[i + 1] for i, value in enumerate(args) if value == '--image']
    with open(DATA['capture'], 'a') as handle:
        handle.write(json.dumps({'prompt':prompt, 'env':dict(os.environ), 'cwd':os.getcwd(),
            'images':[pathlib.Path(value).read_bytes().hex() for value in paths],
            'pid':os.getpid(), 'pgid':os.getpgrp()}) + '\\n')
    if DATA['mode'] == 'sleep': time.sleep(30)
    if DATA['mode'] == 'child_sleep':
        import signal, subprocess
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        def on_term(*_):
            child.wait(timeout=0.3)
            sys.exit(0)
        signal.signal(signal.SIGTERM, on_term)
        with open(DATA['capture'], 'a') as handle:
            handle.write(json.dumps({'child_pid':child.pid, 'child_pgid':os.getpgid(child.pid)}) + '\\n')
        time.sleep(30)
    if DATA['mode'] == 'private_stderr':
        os.write(2, DATA['secret'].encode())
        time.sleep(30)
    if DATA['mode'] == 'diagnostic_stderr':
        os.write(2, DATA['stderr_text'].encode())
        time.sleep(30)
    if DATA['mode'] == 'stderr_limit': os.write(2, b'x' * 100000)
    if DATA['mode'] == 'stdout_limit': os.write(1, b'x' * 200000)
    if DATA['mode'] == 'notice': os.write(2, b'Reading prompt from stdin...\\n')
    if DATA['mode'] == 'stderr_then_success': os.write(2, DATA['stderr_text'].encode())
    if DATA['raw'] is not None:
        os.write(1, DATA['raw'].encode())
    else:
        for event in DATA['events']:
            os.write(1, json.dumps(event).encode() + b'\\n')
            if DATA['mode'] == 'wait_after_forbidden' and event.get('item', {}).get('type') == 'command_execution':
                time.sleep(30)
    sys.exit(DATA['exit_code'])
"""
        script = script.replace("CONFIGURATION", repr(json.dumps(data)))
        self.executable.write_text(script, encoding="utf-8")
        self.executable.chmod(0o700)

    def call(self, **overrides):
        values = dict(prompt="Public instruction only", images=[PNG], schema=SCHEMA,
                      timeout_s=5, max_response_bytes=4096, max_attempts=1, retry_backoff_s=0)
        values.update(overrides)
        return codex_cli.send(**values)

    def captured(self):
        return [json.loads(line) for line in self.capture.read_text().splitlines()]

    def deadline_after_fake_ready(self, field):
        """Advance the test clock only after the owned fixture records readiness.

        Slow CI process startup must not turn an action-cleanup test into a
        preflight timeout test. A real five-second deadline still bounds a
        missing handshake; the transport's production clock is not changed.
        """
        elapsed = False

        def clock():
            nonlocal elapsed
            if not elapsed and self.capture.exists():
                # Only inspect complete append records, never a partial write.
                lines = self.capture.read_text().splitlines(keepends=True)
                elapsed = any(field in json.loads(line) for line in lines if line.endswith("\n"))
            return time.monotonic() + (10 if elapsed else 0)

        return patch.object(codex_cli, "time", SimpleNamespace(monotonic=clock))

    def failure(self, **overrides):
        with self.assertRaises(PolicyCallError) as caught:
            self.call(**overrides)
        error = caught.exception
        self.assertNotIn(SECRET, str(error))
        self.assertNotIn(SECRET, json.dumps(error.metadata))
        self.assertIsNone(error.__context__)
        self.assertEqual(error.metadata["wrapper_retries"], 0)
        self.assertLessEqual(error.metadata["wrapper_invocations"], 1)
        return error

    def test_preflight_checks_only_version_help_and_local_login(self):
        evidence = codex_cli.preflight_runtime()
        self.assertEqual(evidence["cli_version"], "0.154.0")
        self.assertEqual(evidence["cli_executable_sha256"], hashlib.sha256(self.executable.read_bytes()).hexdigest())
        self.assertFalse(evidence["model_access_verified"])
        self.assertFalse(evidence["provider_access_verified"])
        self.assertEqual([row["argv"] for row in self.captured()],
                         [["--version"], ["exec", "--help"], ["login", "status"]])

    def test_preflight_wrong_version_stops_before_login(self):
        self.fake(version="0.999.0")
        with self.assertRaises(PolicyPreflightError) as caught:
            codex_cli.preflight_runtime()
        self.assertEqual(caught.exception.code, "unsupported")
        self.assertEqual(self.captured(), [{"argv": ["--version"]}])

    def test_preflight_missing_help_flag_or_chatgpt_login_fails_without_secret(self):
        for options, code in (({"help_text": "--json"}, "unsupported"),
                              ({"login": "Logged in using an API key - " + SECRET}, "credentials_missing"),
                              ({"login": "Not logged in", "login_code": 1}, "credentials_missing")):
            with self.subTest(options=tuple(options)):
                self.fake(**options)
                with self.assertRaises(PolicyPreflightError) as caught:
                    codex_cli.preflight_runtime()
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertIsNone(caught.exception.__context__)

    def test_success_has_unknown_provider_calls_and_exact_safe_token_mapping(self):
        result = self.call()
        self.assertEqual(result["text"], TEXT)
        self.assertEqual(result["usage"]["input_tokens"], 10)
        self.assertEqual(result["usage"]["cached_input_tokens"], 3)
        self.assertEqual(result["usage"]["output_tokens"], 5)
        self.assertIsNone(result["usage"]["calls"])
        self.assertIsNone(result["usage"]["estimated_cost_usd"])
        receipt = result["receipt"]
        self.assertEqual(receipt["wrapper_invocations"], 1)
        self.assertEqual(receipt["requested_model"], "gpt-6-astra")
        self.assertEqual(receipt["requested_reasoning_effort"], "xhigh")
        self.assertIsNone(receipt["returned_model"])
        self.assertIsNone(receipt["cli_internal_retries"])
        self.assertFalse(receipt["tool_catalog_verified_empty"])
        self.assertFalse(receipt["tool_events_complete"])
        self.assertFalse(receipt["provider_identity_verified"])
        self.assertTrue(receipt["code_mode_host_required"])
        self.assertFalse(receipt["code_mode_host_identity_verified"])
        self.assertEqual(receipt["enabled_features"], ["skip_host_skill_discovery", "code_mode_host"])
        self.assertEqual(receipt["response_sha256"], hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertEqual(receipt["image_sha256"], [hashlib.sha256(PNG).hexdigest()])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_v2_final_json_validation_belongs_to_policy_without_extra_call(self):
        for final in ('not JSON', '{"steps":NaN}', '{"x":1,"x":2}', '[]'):
            with self.subTest(final=final):
                self.fake(events=stream(final))
                result = self.call(validate_final_json=False)
                self.assertEqual(result["text"], final)
                self.assertEqual(result["receipt"]["wrapper_invocations"], 1)
                self.assertEqual(result["receipt"]["wrapper_retries"], 0)
                self.assertEqual(result["receipt"]["final_output_validation"], "policy-owned/v1")
                self.assertEqual(result["usage"]["input_tokens"], 10)
                self.assertEqual(result["receipt"]["response_sha256"], hashlib.sha256(final.encode()).hexdigest())
                self.assertNotIn(SECRET, json.dumps(result))

    def test_v2_never_relaxes_forbidden_tools_or_duplicate_final_outputs(self):
        forbidden = stream()
        forbidden.insert(2, {"type": "item.completed", "item": {
            "id": "forbidden", "type": "command_execution", "command": SECRET}})
        duplicated = stream()
        duplicated.insert(-1, {"type": "item.completed", "item": {
            "id": "duplicate", "type": "agent_message", "text": TEXT}})
        for events, code in ((forbidden, "forbidden_item"), (duplicated, "invalid_output")):
            with self.subTest(code=code):
                self.fake(events=events)
                error = self.failure(validate_final_json=False)
                self.assertEqual(error.metadata["failure_code"], code)

    def test_final_validation_mode_must_be_boolean_before_dispatch(self):
        for mode in (0, 1, "false", None):
            with self.subTest(mode=mode):
                self.assertEqual(self.failure(validate_final_json=mode).metadata["wrapper_invocations"], 0)

    def test_fixed_argv_opaque_workspace_existing_home_and_filtered_environment(self):
        # Preserve rather than repurpose existing login locations; never copy auth.
        environment = {"HOME": str(Path.home()), "CODEX_HOME": str(self.root / "existing-login-location"),
            "RSI_SIM_SERVER_TOKEN": SECRET, "SSH_AUTH_SOCK": SECRET, "OPENAI_API_KEY": SECRET,
            "CODEX_API_KEY": SECRET, "OPENAI_BASE_URL": SECRET, "ALL_PROXY": SECRET,
            "HTTPS_PROXY": SECRET, "PYTHONPATH": SECRET, "CODEX_THREAD_ID": SECRET}
        with patch.dict(os.environ, environment):
            result = self.call()
        rows = self.captured()
        command = rows[-2]["argv"]
        evidence = rows[-1]
        for flag in ("--ignore-user-config", "--ignore-rules", "--strict-config", "--ephemeral",
                     "--json", "--output-schema", "--image", "--skip-git-repo-check"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(command[command.index("-m") + 1], "gpt-6-astra")
        enabled = [command[i + 1] for i, flag in enumerate(command) if flag == "--enable"]
        disabled = [command[i + 1] for i, flag in enumerate(command) if flag == "--disable"]
        self.assertIn("code_mode_host", enabled)
        self.assertNotIn("code_mode_host", disabled)
        self.assertIn("code_mode", disabled)
        self.assertIn("code_mode_only", disabled)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertNotIn("Public instruction only", command)
        self.assertEqual(evidence["prompt"], "Public instruction only")
        self.assertEqual(evidence["env"]["HOME"], environment["HOME"])
        self.assertEqual(evidence["env"]["CODEX_HOME"], environment["CODEX_HOME"])
        self.assertNotIn(SECRET, json.dumps(evidence))
        self.assertEqual(evidence["images"], [PNG.hex()])
        self.assertEqual(evidence["pid"], evidence["pgid"])
        self.assertFalse(Path(evidence["cwd"]).exists())
        self.assertNotIn(evidence["cwd"], json.dumps(result))

    def test_invalid_inputs_never_launch_a_cli_inference(self):
        cases = ({"timeout_s": True}, {"timeout_s": float("nan")}, {"timeout_s": 0},
                 {"max_response_bytes": True}, {"max_response_bytes": 0},
                 {"max_response_bytes": codex_cli.MAX_RESPONSE_BYTES + 1},
                 {"prompt": ""}, {"prompt": "x" * (codex_cli.MAX_PROMPT_BYTES + 1)},
                 {"images": ["/private/not-an-image.png"]}, {"images": [b"not png"]},
                 {"schema": {"value": float("inf")}})
        for options in cases:
            with self.subTest(fields=tuple(options)):
                error = self.failure(**options)
                self.assertEqual(error.usage.calls, 0)
                self.assertEqual(error.metadata["failure_code"], "invalid_input")
        self.assertFalse(self.capture.exists())

    def test_runtime_failure_before_inference_reports_zero_calls(self):
        self.fake(login="Not logged in", login_code=1)
        error = self.failure()
        self.assertEqual(error.usage.calls, 0)
        self.assertEqual(error.metadata["preflight_error_code"], "credentials_missing")
        self.assertEqual(error.category, "infrastructure")

    def test_changed_executable_between_readiness_and_dispatch_never_infers(self):
        with patch.object(codex_cli, "_binary_digest", side_effect=["0" * 64, "0" * 64, "1" * 64]):
            error = self.failure()
        self.assertEqual(error.usage.calls, 0)
        self.assertEqual(error.metadata["failure_code"], "runtime_unavailable")
        self.assertEqual([row["argv"] for row in self.captured()],
                         [["--version"], ["exec", "--help"], ["login", "status"]])

    def test_forbidden_items_and_warning_model_reroute_are_rejected(self):
        for kind in ("command_execution", "file_change", "mcp_tool_call", "collab_tool_call",
                     "web_search", "todo_list", "view_image", "clock"):
            with self.subTest(kind=kind):
                self.fake(events=stream()[:2] + [{"type": "item.started", "item": {
                    "id": "unsafe", "type": kind, "text": SECRET}}])
                error = self.failure()
                self.assertEqual(error.metadata["failure_code"], "forbidden_item")
                self.assertIsNone(error.usage.calls)
        self.fake(events=stream()[:2] + [{"type": "item.completed", "item": {
            "id": "warning", "type": "error", "message": "model rerouted: " + SECRET}}])
        self.assertEqual(self.failure().metadata["failure_code"], "model_rerouted")

    def test_retry_notice_is_counted_but_never_reinvoked_or_echoed(self):
        self.fake(events=stream()[:2] + [{"type": "error", "message": "Reconnecting... 1/5 " + SECRET}])
        error = self.failure()
        self.assertEqual(error.metadata["cli_retry_notices_observed"], 1)
        self.assertIsNone(error.metadata["cli_internal_retries"])
        self.assertEqual(sum("cwd" in row for row in self.captured()), 1)

    def test_startup_warning_is_classified_before_any_turn_without_raw_text(self):
        message = codex_cli._CODE_MODE_HOST_DISABLED_NOTICE
        self.fake(events=stream()[:1] + [{"type": "item.completed", "item": {
            "id": "warning", "type": "error", "message": message}}])
        error = self.failure()
        self.assertEqual(error.metadata["failure_code"], "cli_warning")
        self.assertEqual(error.metadata["cli_notice_kind"], "code_mode_host_disabled")
        self.assertEqual(error.metadata["cli_notice_phase"], "startup")
        self.assertEqual(error.metadata["cli_notice_sha256"], hashlib.sha256(message.encode()).hexdigest())
        self.assertNotIn("turn.started", error.metadata["event_counts"])
        self.assertEqual(error.metadata["cli_notice_bytes"], 157)
        self.assertEqual(error.metadata["cli_notice_sha256"],
                         "098e801ebc95c9c7312a945849442846324dcf639365a297313248993822711b")
        self.assertNotIn(message, json.dumps(error.metadata))
        self.fake(events=stream()[:1] + [{"type": "item.completed", "item": {
            "id": "warning", "type": "error", "message": SECRET}}])
        self.assertEqual(self.failure().metadata["cli_notice_kind"], "unclassified_warning")

    def test_strict_output_and_event_order(self):
        cases = [stream(text="```json\n{}\n```"), stream(text='{"a":1,"a":2}'),
                 stream(text='{"a":1e999}'), stream(text='{"a":NaN}'), stream(text='[]'),
                 stream()[:-1], stream()[1:], stream() + [{"type": "turn.started"}],
                 stream()[:3] + [stream()[3], {"type": "item.completed", "item": {
                     "id": "second", "type": "agent_message", "text": "{}"}}] + stream()[-1:]]
        for index, events in enumerate(cases):
            with self.subTest(case=index):
                self.fake(events=events)
                self.failure()

    def test_invalid_event_json_duplicate_fields_and_unterminated_line(self):
        for raw in ('not json\n', '{"type":"thread.started","type":"error"}\n',
                    '{"type":"thread.started","thread_id":"unfinished"}',
                    '{"type":"unknown","secret":"' + SECRET + '"}\n'):
            with self.subTest(raw_prefix=raw[:20]):
                self.fake(raw=raw)
                self.failure()

    def test_invalid_token_counters_do_not_become_zero(self):
        for key, value in (("input_tokens", True), ("output_tokens", -1),
                           ("cached_input_tokens", 11), ("input_tokens", None),
                           ("input_tokens", 2 ** 63)):
            with self.subTest(key=key, value=value):
                events = stream()
                events[-1]["usage"][key] = value
                self.fake(events=events)
                error = self.failure()
                self.assertEqual(error.metadata["failure_code"], "invalid_usage")
                self.assertIsNone(error.usage.input_tokens)

    def test_all_zero_cli_usage_is_ambiguous_not_a_measured_zero(self):
        events = stream()
        events[-1]["usage"] = {key: 0 for key in events[-1]["usage"]}
        self.fake(events=events)
        result = self.call()
        for key in ("calls", "input_tokens", "cached_input_tokens", "output_tokens", "estimated_cost_usd"):
            self.assertIsNone(result["usage"][key])
        self.assertEqual(result["receipt"]["cli_token_accounting"], "zero_or_unavailable")
        self.assertEqual(result["receipt"]["cli_reported_token_counters"], events[-1]["usage"])

    def test_duplicate_starts_unknown_updates_and_unfinished_items_fail(self):
        item = {"id": "open-item", "type": "agent_message", "text": "{}"}
        started = {"type": "item.started", "item": item}
        for middle in ([started, started], [{"type": "item.updated", "item": item}], [started]):
            with self.subTest(middle=len(middle)):
                self.fake(events=stream()[:2] + middle + stream()[2:])
                self.failure()
        self.fake(events=stream()[:2] + [started, {"type": "item.updated", "item": item},
            {"type": "item.completed", "item": item}] + stream()[-1:])
        self.assertEqual(self.call()["text"], "{}")

    def test_nonzero_exit_preserves_completed_cli_usage_without_action(self):
        self.fake(exit_code=2)
        error = self.failure()
        self.assertEqual(error.metadata["failure_code"], "cli_exit_nonzero")
        self.assertEqual(error.metadata["cli_exit_code"], 2)
        self.assertEqual(error.usage.input_tokens, 10)
        self.assertIsNone(error.usage.calls)

    def test_stderr_progress_does_not_cancel_a_structured_success(self):
        self.fake(mode="notice")
        self.assertEqual(self.call()["text"], TEXT)
        self.fake(mode="stderr_then_success", stderr_text="ERROR failed to refresh available models " + SECRET)
        result = self.call()
        self.assertEqual(result["text"], TEXT)
        self.assertFalse(result["receipt"]["wrapper_terminated_running_process"])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_stderr_failure_retains_safe_hints_and_termination_evidence(self):
        body = "ERROR stream disconnected before completion: HTTP 503 " + SECRET
        self.fake(mode="diagnostic_stderr", stderr_text=body)
        error = self.failure(timeout_s=1)
        diagnostic = error.metadata["stderr_diagnostic"]
        self.assertEqual(error.metadata["failure_code"], "timeout")
        self.assertEqual(diagnostic["observed_sha256"], hashlib.sha256(body.encode()).hexdigest())
        self.assertEqual(diagnostic["observed_bytes"], len(body.encode()))
        self.assertIn({"kind": "connection", "phrase": "stream disconnected before completion"},
                      diagnostic["recognized_messages"])
        self.assertEqual(diagnostic["observed_http_statuses"], ["503"])
        self.assertEqual(diagnostic["observed_levels"], ["ERROR"])
        self.assertFalse(diagnostic["stream_complete"])
        self.assertFalse(diagnostic["root_cause_verified"])
        self.assertFalse(diagnostic["raw_body_retained"])
        self.assertFalse(diagnostic["capture_truncated"])
        self.assertTrue(error.metadata["wrapper_terminated_running_process"])
        self.assertEqual(error.metadata["cli_exit_code"], -15)

    def test_unknown_stderr_does_not_invent_a_network_cause(self):
        self.fake(mode="private_stderr")
        diagnostic = self.failure(timeout_s=1).metadata["stderr_diagnostic"]
        self.assertEqual(diagnostic["recognized_messages"], [])
        self.assertEqual(diagnostic["observed_http_statuses"], [])
        self.assertEqual(diagnostic["captured_prefix_sha256"], hashlib.sha256(SECRET.encode()).hexdigest())

    def test_diagnostic_projection_discards_all_unrecognized_text(self):
        raw = ("\x1b[31mERROR\x1b[0m state db missing rollout path for thread " + SECRET
               + " Authorization: Bearer sk-test-private-token https://private.example/?token=secret "
               + '{"body":"hidden provider text", "account": 401} HTTP status: 429').encode()
        diagnostic = codex_cli._stderr_diagnostics(raw)
        rendered = json.dumps(diagnostic)
        for private in (SECRET, "sk-test-private-token", "private.example", "hidden provider text"):
            self.assertNotIn(private, rendered)
        self.assertEqual(diagnostic["recognized_messages"],
                         [{"kind": "local_state", "phrase": "state db missing rollout path"}])
        self.assertEqual(diagnostic["observed_http_statuses"], ["429"])
        self.assertFalse(diagnostic["root_cause_verified"])

    def test_stderr_limit_keeps_bounded_prefix_and_counts_observed_bytes(self):
        stats = {}
        with self.assertRaises(codex_cli._Rejected) as caught:
            codex_cli._collect([sys.executable, "-c", "import os; os.write(2,b'x'*200)"],
                cwd=self.root, environment=codex_cli._environment(), input_bytes=b"",
                timeout_s=5, stdout_limit=1024, stderr_limit=64, stats=stats, strict_stderr=True)
        self.assertEqual(caught.exception.code, "stderr_limit")
        diagnostic = stats["stderr_diagnostic"]
        self.assertEqual(diagnostic["captured_prefix_bytes"], 64)
        self.assertEqual(diagnostic["captured_prefix_sha256"], hashlib.sha256(b"x"*64).hexdigest())
        self.assertTrue(diagnostic["capture_truncated"])
        self.assertGreater(diagnostic["observed_bytes"], 64)

    def test_pipe_and_response_limits_are_bounded(self):
        for mode in ("stdout_limit", "stderr_limit"):
            with self.subTest(mode=mode):
                self.fake(mode=mode)
                error = self.failure(max_response_bytes=256)
                self.assertEqual(error.metadata["failure_code"], mode)
                self.assertIsNone(error.usage.calls)
        self.fake(events=stream(text='{"note":"' + 'x' * 1024 + '"}'))
        self.assertEqual(self.failure(max_response_bytes=64).metadata["failure_code"], "stdout_limit")

    def test_timeout_and_forbidden_event_reap_only_owned_process_group(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                     start_new_session=True)
        try:
            self.fake(mode="sleep")
            with self.deadline_after_fake_ready("pid"):
                error = self.failure(timeout_s=5)
            self.assertEqual(error.metadata["failure_code"], "timeout")
            self.assertIsNone(error.usage.calls)
            pid = self.captured()[-1]["pid"]
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            self.assertIsNone(unrelated.poll())
            events = stream()[:2] + [{"type": "item.started", "item": {
                "id": "forbidden", "type": "command_execution", "command": SECRET}}]
            self.fake(mode="wait_after_forbidden", events=events)
            started = time.monotonic()
            self.assertEqual(self.failure().metadata["failure_code"], "forbidden_item")
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=2)

    def test_timeout_reaps_a_child_in_the_same_owned_process_group(self):
        self.fake(mode="child_sleep")
        with self.deadline_after_fake_ready("child_pid"):
            error = self.failure(timeout_s=5)
        self.assertEqual(error.metadata["failure_code"], "timeout")
        rows = self.captured()
        leader = next(row for row in rows if "pid" in row)
        child = next(row for row in rows if "child_pid" in row)
        self.assertEqual(leader["pgid"], child["child_pgid"])
        for pid in (leader["pid"], child["child_pid"]):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_cleanup_failure_is_visible_even_after_complete_output(self):
        cleanup = codex_cli._cleanup
        count = 0

        def failing_after_real_cleanup(process):
            nonlocal count
            count += 1
            cleanup(process)
            if count == 4:
                raise codex_cli._Rejected("cleanup_failed")

        with patch.object(codex_cli, "_cleanup", side_effect=failing_after_real_cleanup):
            error = self.failure()
        self.assertEqual(error.metadata["failure_code"], "cleanup_failed")
        self.assertTrue(error.metadata["cleanup_failed"])
        self.assertEqual(error.usage.input_tokens, 10)
        self.assertIsNone(error.usage.calls)

    def test_spawn_exception_never_exposes_private_message_or_invents_calls(self):
        with patch.object(codex_cli.subprocess, "Popen", side_effect=OSError(SECRET)):
            try:
                self.call()
            except PolicyCallError as error:
                self.assertEqual(error.usage.calls, 0)
                self.assertNotIn(SECRET, traceback.format_exc())
                self.assertIsNone(error.__context__)
            else:
                self.fail("missing executable must fail without an action")


if __name__ == "__main__":
    unittest.main()
