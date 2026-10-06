"""Offline invocation recovery: owned fake processes only, no CLI/network/SIM."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from benchkit.contracts import Usage, ensure_jsonable
from benchkit.errors import ActionRejected, PolicyCallError
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.checks import test_codex_cli as fixtures
from AgentPolicies.gpt6_astra.transports import codex_cli


class CodexRecoveryChecks(unittest.TestCase):
    setUp = fixtures.CodexCliChecks.setUp
    fake = fixtures.CodexCliChecks.fake
    captured = fixtures.CodexCliChecks.captured

    def call(self, **overrides):
        args = dict(prompt="Frozen public observation", images=[fixtures.PNG], schema=fixtures.SCHEMA,
                    timeout_s=5, max_response_bytes=4096, retry_backoff_s=0)
        args.update(overrides)
        return codex_cli.send(**args)

    def error(self, **overrides):
        with self.assertRaises(PolicyCallError) as caught:
            self.call(**overrides)
        error = caught.exception
        self.assertIsNone(error.__context__)
        self.assertNotIn(fixtures.SECRET, json.dumps(error.metadata))
        return error

    @staticmethod
    def failed(code="timeout", *, cleanup_failed=False, action_text=False, usage=None, diagnostic=None):
        receipt = {"failure_code": code, "wrapper_invocations": 1, "wrapper_retries": 0,
                   "cleanup_failed": cleanup_failed, "action_text_observed": action_text,
                   "cli_executable_sha256": "a" * 64, "event_counts": {}}
        if diagnostic is not None:
            receipt["stderr_diagnostic"] = diagnostic
        return PolicyCallError("bounded failure: " + code, usage=usage or Usage.unavailable(),
                               metadata=receipt, category="infrastructure")

    @staticmethod
    def succeeded(usage=None):
        return {"text": fixtures.TEXT, "usage": (usage or Usage.unavailable()).to_dict(),
                "receipt": {"wrapper_invocations": 1, "wrapper_retries": 0, "cleanup_failed": False,
                            "action_text_observed": True, "cli_executable_sha256": "a" * 64}}

    def test_catalog_stderr_failure_then_success_uses_frozen_inputs_new_workspaces_and_cleanup(self):
        failure = {"mode": "stderr_then_success", "stderr_text": "ERROR failed to refresh available models " + fixtures.SECRET,
                   "events": [], "exit_code": 1}
        self.fake(attempts=[failure, failure, {"mode": "normal", "events": fixtures.stream(), "exit_code": 0}])
        result = self.call()
        receipt = result["receipt"]
        self.assertEqual((receipt["wrapper_invocations"], receipt["wrapper_retries"]), (3, 2))
        self.assertEqual([row["status"] for row in receipt["attempts"]], ["failed", "failed", "completed"])
        self.assertEqual([row["retryable"] for row in receipt["attempts"]], [True, True, False])
        self.assertFalse(receipt["attempts_exhausted"])
        self.assertEqual(result["text"], fixtures.TEXT)
        # A successful final attempt does not turn unknown earlier usage into zero.
        self.assertIsNone(result["usage"]["input_tokens"])
        self.assertEqual(receipt["attempts"][-1]["usage"]["input_tokens"], 10)
        calls = [row for row in self.captured() if "cwd" in row]
        self.assertEqual(len(calls), 3)
        self.assertEqual(len({row["cwd"] for row in calls}), 3)
        self.assertEqual({row["prompt"] for row in calls}, {"Frozen public observation"})
        self.assertTrue(all(row["images"] == [fixtures.PNG.hex()] for row in calls))
        for row in calls:
            self.assertFalse(Path(row["cwd"]).exists())
            with self.assertRaises(ProcessLookupError):
                os.killpg(row["pgid"], 0)
        self.assertNotIn(fixtures.SECRET, json.dumps(result))

    def test_exactly_ten_consecutive_failures_then_infrastructure_error(self):
        self.fake(events=[{"type": "error", "message": "connection reset " + fixtures.SECRET}])
        error = self.error()
        self.assertEqual(error.category, "infrastructure")
        self.assertEqual(error.metadata["failure_code"], "transient_model_error")
        self.assertEqual(error.metadata["wrapper_invocations"], 10)
        self.assertEqual(error.metadata["wrapper_retries"], 9)
        self.assertEqual(len(error.metadata["attempts"]), 10)
        self.assertTrue(error.metadata["attempts_exhausted"])
        self.assertEqual(sum("cwd" in row for row in self.captured()), 10)
        self.assertIsNone(error.usage.input_tokens)

    def test_zero_exit_catalog_incomplete_output_exhausts_as_infrastructure(self):
        self.fake(mode="stderr_then_success", stderr_text="ERROR failed to refresh available models",
                  events=[], exit_code=0)
        error = self.error()
        self.assertEqual(error.category, "infrastructure")
        self.assertEqual(error.metadata["failure_code"], "incomplete_output")
        self.assertEqual(error.metadata["wrapper_invocations"], 10)
        self.assertTrue(error.metadata["attempts_exhausted"])

    def test_default_backoff_per_attempt_timeout_and_success_stops_immediately(self):
        results = [self.failed(), self.failed(), self.succeeded()]
        with patch.object(codex_cli, "_send_once", side_effect=results) as send_once, \
                patch.object(codex_cli.time, "sleep") as sleep:
            result = self.call(retry_backoff_s=10)
        self.assertEqual(send_once.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(10,), (10,)])
        self.assertEqual([call.kwargs["timeout_s"] for call in send_once.call_args_list], [5, 5, 5])
        self.assertEqual(result["receipt"]["retry_policy"]["max_attempts"], 10)
        self.assertEqual(codex_cli.send.__kwdefaults__["max_attempts"], 10)
        self.assertEqual(codex_cli.send.__kwdefaults__["retry_backoff_s"], 10)

    def test_retry_bound_resets_for_next_send_not_episode_global(self):
        with patch.object(codex_cli, "_send_once", side_effect=[self.failed(), self.succeeded(),
                                                               self.failed(), self.succeeded()]):
            results = [self.call(), self.call()]
        self.assertEqual([r["receipt"]["wrapper_invocations"] for r in results], [2, 2])
        self.assertEqual([r["receipt"]["attempts"][0]["attempt"] for r in results], [1, 1])

    def test_caller_mutation_during_failure_cannot_change_next_input(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        images = [fixtures.PNG]
        observed = []

        def attempt(prompt, actual_images, actual_schema, **_):
            observed.append((prompt, list(actual_images), json.dumps(actual_schema, sort_keys=True)))
            if len(observed) == 1:
                schema["properties"]["a"]["type"] = "number"
                images[0] = fixtures.PNG + b"mutated"
                actual_schema["properties"]["a"]["type"] = "boolean"
                raise self.failed()
            return self.succeeded()

        with patch.object(codex_cli, "_send_once", side_effect=attempt):
            self.call(schema=schema, images=images)
        self.assertEqual(observed[0], observed[1])

    def test_security_protocol_unknown_and_candidate_action_failures_do_not_retry(self):
        codes = ("forbidden_item", "model_rerouted", "invalid_event", "unexpected_event", "event_order",
                 "invalid_usage", "invalid_output", "stdout_limit", "stderr_limit", "cli_warning",
                 "stream_io_failed", "runtime_unavailable", "cli_exit_nonzero", "incomplete_output")
        for error in [*(self.failed(code) for code in codes), self.failed(cleanup_failed=True),
                      self.failed(action_text=True), self.failed("cleanup_failed")]:
            with self.subTest(code=error.metadata["failure_code"], receipt=error.metadata), \
                    patch.object(codex_cli, "_send_once", side_effect=error) as send_once, \
                    patch.object(codex_cli.time, "sleep") as sleep:
                rejected = self.error()
                self.assertEqual(send_once.call_count, 1)
                self.assertFalse(rejected.metadata["attempts_exhausted"])
                sleep.assert_not_called()

    def test_auth_permission_tls_and_quota_deny_retry_even_with_timeout_or_catalog_hint(self):
        for body in ("unauthorized HTTP 401", "permission denied", "certificate verify failed",
                     "quota exceeded", "HTTP 403", "no space left on device"):
            diagnostic = codex_cli._stderr_diagnostics((body + " failed to refresh available models").encode())
            with self.subTest(body=body), patch.object(codex_cli, "_send_once",
                    side_effect=self.failed(diagnostic=diagnostic)) as send_once:
                self.error()
                self.assertEqual(send_once.call_count, 1)

    def test_stderr_reroute_remains_fatal_even_with_valid_final_output(self):
        self.fake(mode="stderr_then_success", stderr_text="model rerouted: " + fixtures.SECRET)
        error = self.error()
        self.assertEqual(error.metadata["failure_code"], "model_rerouted")
        self.assertEqual(error.metadata["wrapper_invocations"], 1)

    def test_partial_agent_message_prevents_resampling_after_network_error(self):
        for kind in ("item.started", "item.updated"):
            events = fixtures.stream()[:2]
            if kind == "item.updated":
                events.append({"type": "item.started", "item": {
                    "id": "candidate", "type": "agent_message", "text": ""}})
            events.extend([{"type": kind, "item": {
                "id": "candidate", "type": "agent_message", "text": '{"actions":['}},
                {"type": "error", "message": "connection reset"}])
            with self.subTest(kind=kind):
                self.fake(events=events)
                error = self.error()
                self.assertTrue(error.metadata["action_text_observed"])
                self.assertEqual(error.metadata["wrapper_invocations"], 1)
                self.assertFalse(error.metadata["attempts"][0]["retryable"])

    def test_completed_empty_output_is_not_retried_even_with_network_exit_failure(self):
        for text in ("", "  "):
            with self.subTest(text=text):
                self.fake(mode="stderr_then_success", stderr_text="connection reset",
                          events=fixtures.stream(text), exit_code=1)
                error = self.error(validate_final_json=False)
                self.assertTrue(error.metadata["action_text_observed"])
                self.assertTrue(error.metadata["structured_turn_completed"])
                self.assertEqual(error.metadata["wrapper_invocations"], 1)
                self.assertFalse(error.metadata["attempts"][0]["retryable"])

    def test_known_usage_is_summed_unknown_usage_remains_unknown(self):
        known = Usage(calls=None, input_tokens=10, output_tokens=4, cached_input_tokens=3,
                      estimated_cost_usd=None, latency_s=1)
        for initial, expected in ((known, 20), (Usage.unavailable(), None)):
            with self.subTest(expected=expected), patch.object(codex_cli, "_send_once",
                    side_effect=[self.failed(usage=initial), self.succeeded(known)]):
                result = self.call()
            self.assertEqual(result["usage"]["input_tokens"], expected)
            self.assertIsNone(result["usage"]["calls"])
            self.assertIsNone(result["usage"]["estimated_cost_usd"])

    def test_runtime_digest_change_between_attempts_blocks_dispatch(self):
        executable, readiness = codex_cli._inspect_runtime()
        with patch.object(codex_cli, "_inspect_runtime", return_value=(executable, readiness)), \
                patch.object(codex_cli, "_collect") as collect:
            with self.assertRaises(PolicyCallError) as caught:
                codex_cli._send_once("public", [fixtures.PNG], fixtures.SCHEMA, timeout_s=5,
                    max_response_bytes=4096, expected_executable_sha256="0" * 64)
        collect.assert_not_called()
        self.assertEqual(caught.exception.metadata["wrapper_invocations"], 0)
        self.assertEqual(caught.exception.metadata["failure_code"], "runtime_unavailable")

    def test_invalid_recovery_bounds_never_start_preflight_or_inference(self):
        for overrides in ({"max_attempts": 0}, {"max_attempts": 11}, {"max_attempts": True},
                          {"retry_backoff_s": -1}, {"retry_backoff_s": 11},
                          {"retry_backoff_s": float("nan")}, {"retry_backoff_s": True}):
            with self.subTest(overrides=overrides), patch.object(codex_cli, "_send_once") as send_once:
                error = self.error(**overrides)
                self.assertEqual(error.metadata["wrapper_invocations"], 0)
                self.assertEqual(error.usage.calls, 0)
                send_once.assert_not_called()

    def test_ten_attempt_worst_case_diagnostics_fit_metadata_on_failure_and_success(self):
        phrases = [phrase for kind, values in codex_cli._STDERR_HINTS.items()
                   for phrase in values if kind in {"connection", "dns", "timeout"}
                   or phrase in {"failed to refresh available models", "failed to load model catalog"}]
        body = "ERROR " + " ; ".join(phrases) + " HTTP 500 HTTP 502 HTTP 503 HTTP 504 " + fixtures.SECRET
        failed_events = [{"type": "error", "message": body}]
        failure = {"mode": "stderr_then_success", "stderr_text": body,
                   "events": failed_events, "exit_code": 1}
        successful_stderr = "ERROR WARN WARNING INFO DEBUG " + " ; ".join(
            phrase for values in codex_cli._STDERR_HINTS.values() for phrase in values)
        successful_stderr += " " + " ".join("HTTP " + str(code) for code in range(400, 600))
        for final_success in (False, True):
            with self.subTest(final_success=final_success):
                if self.capture.exists():
                    self.capture.unlink()  # Only this owned synthetic fixture's invocation log.
                final = ({"mode": "stderr_then_success", "stderr_text": successful_stderr,
                          "events": fixtures.stream(), "exit_code": 0} if final_success else failure)
                self.fake(attempts=[failure] * 9 + [final])
                if final_success:
                    result = self.call(images=[fixtures.PNG] * 32)
                    receipt = result["receipt"]
                    # An invalid native action adds a provider_receipt wrapper.
                    ActionRejected(ValidationIssue("invalid_action"), usage=Usage(**result["usage"]),
                                   metadata={"provider_receipt": receipt})
                else:
                    receipt = self.error(images=[fixtures.PNG] * 32).metadata
                self.assertEqual(receipt["wrapper_invocations"], 10)
                self.assertEqual(receipt["wrapper_retries"], 9)
                encoded = json.dumps(ensure_jsonable(receipt), separators=(",", ":")).encode()
                self.assertLessEqual(len(encoded), PolicyCallError.MAX_METADATA_BYTES - 1024)
                self.assertNotIn(fixtures.SECRET, encoded.decode())
                self.assertTrue(all("diagnostic_kinds" in item["receipt"] for item in receipt["attempts"]))


if __name__ == "__main__":
    unittest.main()
