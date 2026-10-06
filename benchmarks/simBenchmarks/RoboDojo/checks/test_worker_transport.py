"""Private worker framing and bounded failure cleanup with real CPU children."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchkit.errors import ProtocolError
from benchmarks.simBenchmarks.RoboDojo.bench_server import native_worker_client as transport


CHILD = r'''
import json, os, pathlib, signal, sys, time
root, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
if mode == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
for line in sys.stdin:
    request = json.loads(line)
    with (root / "received.jsonl").open("a") as log:
        log.write(json.dumps(request) + "\n")
    if mode in ("hang", "ignore_term"):
        time.sleep(60)
    response = {"rpc_protocol": request["rpc_protocol"], "rpc_id": request["rpc_id"],
                "ok": True, "result": {"metrics": {"probe": 1}}}
    if mode == "wrong_id":
        response["rpc_id"] = "unrelated"
    elif mode == "eof":
        sys.exit(0)
    elif mode == "partial":
        print('{"ok":', end="", flush=True)
        time.sleep(60)
    elif mode in ("operation_error", "wrong_operation", "bad_error", "bad_traceback") and request["op"] == "reset":
        response = {"rpc_protocol": request["rpc_protocol"], "rpc_id": request["rpc_id"],
                    "ok": False, "operation": "reset", "error": "synthetic native failure",
                    "traceback": "synthetic"}
        if mode == "wrong_operation":
            response["operation"] = "step"
        elif mode == "bad_error":
            response["error"] = {}
        elif mode == "bad_traceback":
            response["traceback"] = []
    elif mode == "healthy_close" and request["op"] == "close":
        prepared = {"protocol": "robodojo-close/v1", "phase": "prepared", "pid": os.getpid(),
                    "finalization": "completed", "environment_cleanup": "not_created",
                    "app_created": False, "errors": []}
        (root / "cleanup_prepared.json").write_text(json.dumps(prepared))
        response["result"] = {"cleanup_prepared": prepared}
        print(json.dumps(response), flush=True)
        for phase in ("app_shutdown_started", "app_shutdown_returned"):
            (root / (phase + ".json")).write_text(json.dumps({"protocol": "robodojo-close/v1",
                "pid": os.getpid(), "phase": phase, "app_created": False}))
        sys.exit(0)
    print(json.dumps(response), flush=True)
'''


class WorkerTransportChecks(unittest.TestCase):
    def start_worker(self, mode):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        episode = transport.RoboDojoEpisode(SimpleNamespace(worker_timeout=0.25), None)
        episode.bind_artifact_dir(root)
        child = subprocess.Popen([sys.executable, "-u", "-c", CHILD, str(root), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        episode.process = child

        def reap():
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
            for stream in (child.stdin, child.stdout):
                if stream and not stream.closed:
                    stream.close()
        self.addCleanup(reap)
        return episode, root

    def test_valid_correlated_response_does_not_fault_transport(self):
        episode, _ = self.start_worker("normal")
        self.assertEqual(episode._rpc({"op": "probe"}), {"metrics": {"probe": 1}})
        self.assertEqual(episode._rpc({"op": "probe"}), {"metrics": {"probe": 1}})
        self.assertIsNone(episode.rpc_failure)

    def test_correlated_operation_error_allows_read_only_finalization(self):
        episode, root = self.start_worker("operation_error")
        with self.assertRaisesRegex(RuntimeError, "synthetic native failure"):
            episode._rpc({"op": "reset"})
        self.assertIsNone(episode.rpc_failure)
        self.assertEqual(episode.artifacts(), {})
        requests = [json.loads(line)["op"] for line in (root / "received.jsonl").read_text().splitlines()]
        self.assertEqual(requests, ["reset", "finalize"])

    def test_uncertain_responses_latch_and_cleanup_without_another_rpc(self):
        for mode in ("hang", "partial", "wrong_id", "eof", "ignore_term",
                     "wrong_operation", "bad_error", "bad_traceback"):
            with self.subTest(mode=mode):
                episode, root = self.start_worker(mode)
                with self.assertRaises((TimeoutError, ProtocolError)):
                    episode._rpc({"op": "reset"})
                self.assertIsNotNone(episode.rpc_failure)
                original_failure = episode.rpc_failure
                with self.assertRaisesRegex(ProtocolError, "transport is faulted"):
                    episode._rpc({"op": "step", "action": []})
                if episode.process.poll() is None:
                    with self.assertRaisesRegex(ProtocolError, "transport is faulted"):
                        episode.artifacts()
                started = time.monotonic()
                with patch.object(transport, "CLOSE_TERMINATE_SECONDS", 0.15), self.assertRaises(RuntimeError):
                    episode.close()
                self.assertLess(time.monotonic() - started, 3)
                self.assertIsNotNone(episode.process.poll())
                receipt = json.loads((root / "worker_process_close.json").read_text())
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(receipt["transport_fault"], original_failure)
                self.assertFalse(receipt["prepare_ack_received"])
                if mode == "ignore_term":
                    self.assertTrue(receipt["kill_sent"])
                requests = [json.loads(line)["op"] for line in (root / "received.jsonl").read_text().splitlines()]
                self.assertEqual(requests, ["reset"])
                # Close is idempotent, including its retained error and receipt.
                before = (root / "worker_process_close.json").read_bytes()
                with self.assertRaises(RuntimeError):
                    episode.close()
                self.assertEqual((root / "worker_process_close.json").read_bytes(), before)

    def test_healthy_close_verifies_receipts_and_is_idempotent(self):
        episode, root = self.start_worker("healthy_close")
        episode.close()
        before = (root / "worker_process_close.json").read_bytes()
        receipt = json.loads(before)
        self.assertEqual(receipt["status"], "completed")
        self.assertIsNone(receipt["transport_fault"])
        self.assertEqual(receipt["child_returncode"], 0)
        self.assertTrue(receipt["prepare_receipt_verified"])
        self.assertTrue(receipt["app_shutdown_return_observed"])
        self.assertFalse(receipt["terminate_sent"])
        episode.close()
        self.assertEqual((root / "worker_process_close.json").read_bytes(), before)

    def test_healthy_transport_close_has_its_own_short_prepare_deadline(self):
        episode, root = self.start_worker("hang")
        episode.benchmark.worker_timeout = 1200
        started = time.monotonic()
        with patch.object(transport, "CLOSE_WAIT_SECONDS", 0.25), self.assertRaises(RuntimeError):
            episode.close()
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNotNone(episode.process.poll())
        receipt = json.loads((root / "worker_process_close.json").read_text())
        self.assertIn("TimeoutError", receipt["transport_fault"])
        self.assertTrue(receipt["terminate_sent"])
        requests = [json.loads(line)["op"] for line in (root / "received.jsonl").read_text().splitlines()]
        self.assertEqual(requests, ["close"])


if __name__ == "__main__":
    unittest.main()
