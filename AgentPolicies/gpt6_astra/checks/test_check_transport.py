"""Offline diagnostic dispatch fixtures; all CLI and inference calls are mocked."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from AgentPolicies.gpt6_astra.tools import check_transport


class CheckTransportChecks(unittest.TestCase):
    def run_fixture(self, request):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "new-diagnostic"
        arguments = ["check_transport", "--output", str(output)]
        if request:
            arguments.append("--request")
        result = {"text": '{"ready":true,"image_count":3}',
                  "usage": {"calls": None}, "receipt": {"mocked": True}}
        with patch("sys.argv", arguments), patch("builtins.print"), \
                patch.object(check_transport, "preflight_runtime", return_value={}) as preflight, \
                patch.object(check_transport, "send", return_value=result) as send:
            status = check_transport.main()
        self.assertEqual(status, 0)
        preflight.assert_called_once_with()
        return json.loads((output / "result.json").read_text()), send

    def test_explicit_request_means_one_cli_attempt_not_native_default_ten(self):
        record, send = self.run_fixture(True)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["max_attempts"], 1)
        self.assertEqual(send.call_args.kwargs["retry_backoff_s"], 0)
        self.assertEqual(len(send.call_args.args[1]), 3)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["wrapper_retries"], 0)
        self.assertIsNone(record["usage"]["calls"])
        self.assertEqual(record["benchmark_attempts"], 0)
        self.assertFalse(record["simulator_started"])

    def test_no_request_never_dispatches(self):
        record, send = self.run_fixture(False)
        send.assert_not_called()
        self.assertEqual(record["status"], "preflight_passed_no_inference")


if __name__ == "__main__":
    unittest.main()
