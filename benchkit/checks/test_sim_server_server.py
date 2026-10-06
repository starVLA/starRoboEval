"""Independent CPU-only server lifecycle checks; never launch native simulators."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from benchkit.contracts import ActionSpec, BenchmarkDescriptor, EpisodeSpec, Observation, ObservationSpec, Transition
from benchkit.sim_server import server
from benchkit.sim_server.wire import PROTOCOL, dumps, loads


class NativeFixture:
    def __init__(self):
        self.calls = []
        self.folder = None
        self.fail = None
        self.mapping = None

    def bind_artifact_dir(self, path):
        self.folder = path
        self.calls.append("bind")

    def reset(self):
        self.calls.append("reset")
        if self.fail == "reset":
            raise RuntimeError("synthetic reset fault")
        return Observation(0, "Move")

    def step(self, action):
        self.calls.append(("step", action))
        if self.fail == "step":
            raise RuntimeError("synthetic step fault")
        return Transition(Observation(1, "Move"), 1.0, terminated=True, info={"private_score": 3})

    def metrics(self):
        self.calls.append("metrics")
        return {"success": True}

    def artifacts(self):
        self.calls.append("artifacts")
        (self.folder / "native.txt").write_bytes(b"native artifact\n")
        return self.mapping if self.mapping is not None else {"native": str(self.folder / "native.txt")}

    def close(self):
        self.calls.append("close")
        (self.folder / "late_close.txt").write_bytes(b"post-close receipt\n")
        if self.fail == "close":
            raise RuntimeError("synthetic close fault")


class AdapterFixture:
    descriptor = BenchmarkDescriptor("fixture", "1", "fixture/v1", "fixed")
    observation_spec = ObservationSpec()
    action_spec = ActionSpec("scalar", 1, low=(-1.0,), high=(1.0,))

    def __init__(self):
        self.native = []

    def episodes(self, seed, limit=None):
        return [EpisodeSpec(str(i), "task", seed, "Move") for i in range(limit or 2)]

    def open_episode(self, episode):
        native = NativeFixture()
        self.native.append(native)
        return native


class ServerChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "service"
        self.adapter = AdapterFixture()
        self.service = server.BenchmarkService(self.adapter, root=self.root, seed=7)

    def open(self, eid="0"):
        return self.service.dispatch("open", {"episode_id": eid})["session_id"]

    def reset(self, sid):
        return self.service.dispatch("reset", {"session_id": sid, "sequence": 0})

    def finish(self, sid):
        return self.service.dispatch("finish", {"session_id": sid})

    def test_describe_is_read_only_and_private(self):
        description = self.service.dispatch("describe", {})
        self.assertEqual(description["seed"], 7)
        self.assertEqual(len(description["episodes"]), 2)
        self.assertFalse(self.adapter.native)
        self.assertFalse(self.service.claims)

    def test_unknown_extra_fields_and_busy_do_not_open(self):
        for params in ({"episode_id": "missing"}, {"episode_id": "0", "seed": 99}):
            with self.assertRaises(server.ServiceError):
                self.service.dispatch("open", params)
        sid = self.open()
        for eid in ("0", "1"):
            with self.assertRaises(server.ServiceError):
                self.open(eid)
        self.assertEqual(len(self.adapter.native), 1)
        self.assertTrue((self.root / "episodes" / sid / "claim.json").is_file())

    def test_reset_once_step_sequence_and_terminal(self):
        sid = self.open()
        native = self.adapter.native[0]
        self.assertEqual(native.calls, ["bind"])
        with self.assertRaises(server.ServiceError):
            self.service.dispatch("step", {"session_id": sid, "sequence": 0, "action": [0]})
        self.assertEqual(self.reset(sid)["observation"]["step"], 0)
        for sequence in (0, True, 1.0, -1, 2):
            with self.assertRaises(server.ServiceError):
                self.service.dispatch("step", {"session_id": sid, "sequence": sequence, "action": [0]})
        with self.assertRaises(server.ServiceError):
            self.service.dispatch("reset", {"session_id": sid, "sequence": 1})
        result = self.service.dispatch("step", {"session_id": sid, "sequence": 1, "action": [0]})
        self.assertTrue(result["transition"]["terminated"])
        self.assertNotIn("private_score", result["transition"]["observation"]["metadata"])
        with self.assertRaises(server.ServiceError):
            self.service.dispatch("step", {"session_id": sid, "sequence": 2, "action": [0]})
        self.assertEqual(native.calls.count("reset"), 1)
        self.assertEqual(sum(isinstance(call, tuple) for call in native.calls), 1)

    def test_invalid_actions_never_execute_or_consume_sequence(self):
        sid = self.open()
        self.reset(sid)
        for action in ([True], [float("nan")], [2], [], [0, 0], "0", (0,)):
            with self.subTest(action=action), self.assertRaises(server.ServiceError):
                self.service.dispatch("step", {"session_id": sid, "sequence": 1, "action": action})
        self.assertEqual(self.service.sessions[sid]["sequence"], 1)
        self.assertEqual(self.adapter.native[0].calls, ["bind", "reset"])

    def test_sequential_controls_have_no_server_owned_five_step_prefix(self):
        class LongEpisode(NativeFixture):
            horizon = 8

            def step(self, action):
                self.calls.append(("step", action))
                controls = sum(isinstance(call, tuple) for call in self.calls)
                return Transition(Observation(controls, "Move"), 0.0,
                                  truncated=controls == self.horizon)

        native = LongEpisode()
        self.adapter.environment_step_cap = native.horizon
        self.service = server.BenchmarkService(
            self.adapter, root=self.root.parent / "long-episode", seed=7)
        budget = self.service.dispatch("describe", {})["budget"]
        self.assertIsNone(budget["replan_interval"])
        self.assertEqual(budget["environment_step_cap"], 8)
        with patch.object(self.adapter, "open_episode", return_value=native):
            sid = self.open()
        self.reset(sid)

        # One driver-selected prefix can repeat a target more than five times.
        # The service sees only normal single-action requests, not decisions.
        for sequence in range(1, 7):
            result = self.service.dispatch("step", {
                "session_id": sid, "sequence": sequence, "action": [0.25]})
            self.assertEqual(result["transition"]["observation"]["step"], sequence)
            self.assertFalse(result["transition"]["terminated"])
            self.assertFalse(result["transition"]["truncated"])
            self.assertEqual(self.service.sessions[sid]["controls"], sequence)
            self.assertEqual(self.service.sessions[sid]["state"], "running")

        # More controls still respect the fake native horizon/terminal state.
        for sequence in (7, 8):
            result = self.service.dispatch("step", {
                "session_id": sid, "sequence": sequence, "action": [0.25]})
            self.assertEqual(result["transition"]["truncated"], sequence == 8)
        with self.assertRaisesRegex(server.ServiceError, "invalid_session_state"):
            self.service.dispatch("step", {
                "session_id": sid, "sequence": 9, "action": [0.25]})
        self.assertEqual(native.calls.count("reset"), 1)
        self.assertEqual([call for call in native.calls if isinstance(call, tuple)],
                         [("step", (0.25,))] * 8)
        self.assertEqual(self.service.sessions[sid]["controls"], 8)
        self.assertEqual(self.service.sessions[sid]["state"], "terminal")
        self.assertIsNone(self.finish(sid)["cleanup_error"])
        self.assertEqual(native.calls.count("close"), 1)

    def test_native_step_fault_cannot_be_replayed(self):
        sid = self.open()
        self.reset(sid)
        self.adapter.native[0].fail = "step"
        for sequence in (1, 1, 2):
            with self.assertRaises(server.ServiceError):
                self.service.dispatch("step", {"session_id": sid, "sequence": sequence, "action": [0]})
        self.assertEqual(sum(isinstance(call, tuple) for call in self.adapter.native[0].calls), 1)
        self.assertEqual(self.service.sessions[sid]["controls"], 0)
        self.assertEqual(self.service.sessions[sid]["state"], "faulted")

    def test_finish_normalizes_absolute_paths_and_retains_late_receipt(self):
        sid = self.open()
        self.reset(sid)
        final = self.finish(sid)
        self.assertIsNone(final["cleanup_error"])
        self.assertEqual(final["artifacts"], {"native": "native.txt", "server_media_retention": "server_media_retention.json"})
        inventory = {row["path"]: row for row in final["files"]}
        self.assertIn("late_close.txt", inventory)
        for path, row in inventory.items():
            response = self.service.dispatch("read_artifact", {"session_id": sid, "path": path, "offset": 0})
            data = base64.b64decode(response["data"], validate=True)
            self.assertEqual(len(data), row["size_bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
        self.assertEqual(self.finish(sid), final)
        self.assertEqual(self.adapter.native[0].calls.count("artifacts"), 1)
        self.assertEqual(self.adapter.native[0].calls.count("close"), 1)
        with self.assertRaises(server.ServiceError):
            self.open()
        self.open("1")

    def test_close_failure_blocks_next_episode_and_preserves_files(self):
        sid = self.open()
        self.adapter.native[0].fail = "close"
        final = self.finish(sid)
        self.assertEqual(final["cleanup_error"], "native_close_failed")
        self.assertIn("late_close.txt", {row["path"] for row in final["files"]})
        with self.assertRaisesRegex(server.ServiceError, "server_busy"):
            self.open("1")
        self.finish(sid)
        self.assertEqual(self.adapter.native[0].calls.count("close"), 1)

    def test_cache_exclusion_preserves_originals_and_reports_exact_scope(self):
        self.service = server.BenchmarkService(self.adapter, root=self.root.parent / "excluded", seed=7,
                                              excluded_artifact_directories=("cache",))
        sid = self.open()
        folder = self.adapter.native[0].folder
        (folder / "cache" / "ov").mkdir(parents=True)
        cached = folder / "cache" / "ov" / "texture.bin"
        cached.write_bytes(b"native runtime cache")
        (folder / "cache-observation.txt").write_bytes(b"not in excluded directory")
        final = self.finish(sid)
        paths = {row["path"] for row in final["files"]}
        self.assertFalse(any(path.startswith("cache/") for path in paths))
        self.assertIn("cache-observation.txt", paths)
        self.assertIn("native.txt", paths)
        self.assertIn("late_close.txt", paths)
        self.assertEqual(cached.read_bytes(), b"native runtime cache")
        receipt = json.loads((folder / "sim_server_session.json").read_text())
        self.assertEqual(receipt["excluded_artifact_directories"], ["cache"])
        self.assertIsNone(final["cleanup_error"])
        with self.assertRaises(server.ServiceError):
            self.service.dispatch("read_artifact", {"session_id": sid, "path": "cache/ov/texture.bin", "offset": 0})

    def test_excluded_named_artifact_is_an_explicit_error_not_silent_omission(self):
        self.service = server.BenchmarkService(self.adapter, root=self.root.parent / "named-exclusion", seed=7,
                                              excluded_artifact_directories=("cache",))
        sid = self.open()
        native = self.adapter.native[0]
        (native.folder / "cache").mkdir()
        (native.folder / "cache" / "score.json").write_bytes(b"{}")
        native.mapping = {"score": "cache/score.json"}
        final = self.finish(sid)
        self.assertEqual(final["cleanup_error"], "named_artifact_missing")
        self.assertEqual(final["artifacts"], {"server_media_retention": "server_media_retention.json"})
        self.assertTrue((native.folder / "cache" / "score.json").is_file())

    def test_missing_named_file_has_consistent_receipt(self):
        sid = self.open()
        self.adapter.native[0].mapping = {"missing": "not_created.txt"}
        final = self.finish(sid)
        receipt = json.loads((self.root / "episodes" / sid / "sim_server_session.json").read_text())
        self.assertEqual(final["cleanup_error"], "named_artifact_missing")
        self.assertEqual(receipt["cleanup_error"], final["cleanup_error"])
        self.assertEqual(final["artifacts"], {"server_media_retention": "server_media_retention.json"})

    def test_new_service_cannot_reuse_existing_storage(self):
        self.open()
        with self.assertRaises(FileExistsError):
            server.BenchmarkService(AdapterFixture(), root=self.root, seed=7)

    def media(self, *, video=b"fixture finalized video", nested=False):
        sid = self.open()
        folder = self.adapter.native[0].folder
        parent = folder / "frames" if nested else folder
        parent.mkdir(exist_ok=True)
        image = parent / "camera-000.png"
        image.write_bytes(b"fixture observation image")
        if video is not None:
            (folder / "camera.mp4").write_bytes(video)
        (folder / "frames.jsonl").write_text('{"path":"camera-000.png"}\n')
        self.adapter.native[0].mapping = {"frame": str(image), "frame_manifest": "frames.jsonl"}
        return sid, folder, image

    def retention(self, folder):
        return json.loads((folder / "server_media_retention.json").read_text())

    def test_default_keeps_server_video_and_metadata_but_prunes_closed_frames(self):
        sid, folder, image = self.media(nested=True)
        payload = image.read_bytes()
        self.assertTrue(image.exists())  # Live files are untouched before finish.
        final = self.finish(sid)
        self.assertFalse(image.exists())
        self.assertTrue((folder / "camera.mp4").exists())
        self.assertTrue((folder / "frames.jsonl").exists())
        paths = {row["path"] for row in final["files"]}
        self.assertNotIn("frames/camera-000.png", paths)
        self.assertNotIn("frame", final["artifacts"])
        omitted = self.retention(folder)["omitted_files"]
        self.assertEqual(omitted, [{"path": "frames/camera-000.png", "size_bytes": len(payload),
                                   "sha256": hashlib.sha256(payload).hexdigest()}])
        self.assertTrue((self.root / (sid + "-media-retention-intent.json")).is_file())
        self.assertEqual(self.finish(sid), final)
        self.assertEqual(self.adapter.native[0].calls.count("close"), 1)

    def test_frame_optin_retains_original_images(self):
        self.service = server.BenchmarkService(self.adapter, root=self.root.parent / "keep", seed=7,
                                              retain_frame_images=True)
        sid, folder, image = self.media()
        final = self.finish(sid)
        self.assertTrue(image.exists())
        self.assertIn("frame", final["artifacts"])
        self.assertEqual(self.retention(folder)["omitted_files"], [])
        self.assertTrue(self.retention(folder)["retain_frame_images"])

    def test_missing_or_empty_video_preserves_sole_images(self):
        for video in (None, b""):
            with self.subTest(video=video):
                self.service = server.BenchmarkService(AdapterFixture(), root=self.root.parent / ("missing" if video is None else "empty"), seed=7)
                self.adapter = self.service.adapter
                sid, folder, image = self.media(video=video)
                self.finish(sid)
                self.assertTrue(image.exists())
                self.assertEqual(self.retention(folder)["warning"], "video_unavailable_images_preserved")

    def test_failed_native_close_preserves_images(self):
        sid, folder, image = self.media()
        self.adapter.native[0].fail = "close"
        final = self.finish(sid)
        self.assertTrue(image.exists())
        self.assertEqual(final["cleanup_error"], "native_close_failed")
        self.assertEqual(self.retention(folder)["warning"], "native_finalization_or_close_failed_images_preserved")

    def test_missing_camera_video_preserves_images(self):
        self.adapter.observation_spec = ObservationSpec(cameras=("head", "wrist"))
        sid, folder, image = self.media()
        self.finish(sid)
        self.assertTrue(image.exists())
        self.assertEqual(self.retention(folder)["warning"], "video_coverage_incomplete_images_preserved")

    def test_complete_validation_and_durable_intent_precede_any_deletion(self):
        sid, folder, image = self.media()
        with patch.object(server, "_durable_media_record", wraps=server._durable_media_record) as record, \
                patch.object(server, "_unlink_media", wraps=server._unlink_media) as unlink:
            def verify_order(*args):
                self.assertTrue((self.root / (sid + "-media-retention-intent.json")).is_file())
                return original(*args)
            unlink.side_effect = verify_order
            # Use the original wrapped function, not the mock itself.
            original = unlink._mock_wraps
            self.finish(sid)
            self.assertEqual(record.call_count, 2)
            self.assertEqual(unlink.call_count, 1)
        self.assertFalse(image.exists())

    def test_predelete_failure_preserves_all_images(self):
        sid, folder, image = self.media()
        with patch.object(server, "_verify_media", side_effect=server.ServiceError("changed")):
            final = self.finish(sid)
        self.assertTrue(image.exists())
        self.assertIsNone(final["cleanup_error"])
        self.assertEqual(self.retention(folder)["omitted_files"], [])
        self.assertEqual(self.retention(folder)["status"], "warning")

    def test_partial_prune_records_actual_removed_files_without_changing_outcome(self):
        sid, folder, image = self.media()
        second = folder / "camera-001.png"
        second.write_bytes(b"second frame")
        original = server._unlink_media
        def unlink(root, relative, expected, removed):
            if relative == second.name:
                raise OSError("fixture failure")
            return original(root, relative, expected, removed)
        with patch.object(server, "_unlink_media", side_effect=unlink):
            final = self.finish(sid)
        self.assertFalse(image.exists())
        self.assertTrue(second.exists())
        self.assertIsNone(final["cleanup_error"])
        self.assertEqual([row["path"] for row in self.retention(folder)["omitted_files"]], [image.name])

    def test_media_unlink_rejects_symlink_parent_and_replaced_file(self):
        sid, folder, image = self.media(nested=True)
        row = {"path": "frames/camera-000.png", "size_bytes": image.stat().st_size,
               "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
        expected = server._verify_media(folder, row)
        outside = Path(self.temp.name) / "outside-media"
        outside.mkdir()
        (outside / image.name).write_bytes(b"protected")
        (folder / "frames").rename(folder / "saved-frames")
        (folder / "frames").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            server._unlink_media(folder, row["path"], expected, set())
        self.assertEqual((outside / image.name).read_bytes(), b"protected")
        direct = folder / "replacement.png"
        direct.write_bytes(b"changed")
        with self.assertRaises(server.ServiceError):
            server._unlink_media(folder, direct.name, expected, set())

    def test_media_rejects_hardlink_without_deletion(self):
        sid, folder, image = self.media()
        os.link(image, folder / "linked.png")
        self.finish(sid)
        self.assertTrue(image.exists())
        self.assertEqual(self.retention(folder)["status"], "warning")

    def test_retention_receipt_collision_preserves_images(self):
        sid, folder, image = self.media()
        (folder / "server_media_retention.json").write_text('{"native":true}')
        with self.assertRaisesRegex(server.ServiceError, "media_retention_receipt_collision"):
            self.finish(sid)
        self.assertTrue(image.exists())

    def test_intent_write_failure_preserves_images_and_returns_warning(self):
        sid, folder, image = self.media()
        original = server._durable_media_record
        def write(root, name, value):
            if name.endswith("-intent.json"):
                raise OSError("fixture failure")
            return original(root, name, value)
        with patch.object(server, "_durable_media_record", side_effect=write):
            final = self.finish(sid)
        self.assertTrue(image.exists())
        self.assertIsNone(final["cleanup_error"])
        self.assertEqual(self.retention(folder)["status"], "warning")

    def test_artifacts_reject_unknown_traversal_and_invalid_offsets(self):
        sid = self.open()
        with self.assertRaises(server.ServiceError):
            self.service.dispatch("read_artifact", {"session_id": sid, "path": "native.txt", "offset": 0})
        self.finish(sid)
        for path, offset in (("../service.json", 0), ("/etc/passwd", 0), ("native.txt", -1),
                             ("native.txt", True), ("native.txt", 99999), ("unknown", 0)):
            with self.subTest(path=path, offset=offset), self.assertRaises(server.ServiceError):
                self.service.dispatch("read_artifact", {"session_id": sid, "path": path, "offset": offset})

    def test_no_follow_regular_file_or_directory(self):
        folder = Path(self.temp.name) / "links"
        folder.mkdir()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "secret").write_bytes(b"secret")
        (folder / "file").symlink_to(outside / "secret")
        (folder / "directory").symlink_to(outside, target_is_directory=True)
        for path in ("file", "directory/secret"):
            with self.subTest(path=path), self.assertRaises(OSError):
                server.open_regular(folder, path)

    def test_changed_artifact_size_is_rejected(self):
        sid = self.open()
        self.finish(sid)
        (self.root / "episodes" / sid / "native.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(server.ServiceError, "artifact_changed"):
            self.service.dispatch("read_artifact", {"session_id": sid, "path": "native.txt", "offset": 0})

    def test_artifact_limit_fails_closed_without_repeated_finalize(self):
        sid = self.open()
        with patch.object(server, "MAX_ARTIFACT_BYTES", 1):
            with self.assertRaisesRegex(server.ServiceError, "artifact_limit_exceeded"):
                self.finish(sid)
        with self.assertRaisesRegex(server.ServiceError, "artifact_finalization_failed"):
            self.finish(sid)
        self.assertEqual(self.adapter.native[0].calls.count("artifacts"), 1)
        self.assertEqual(self.adapter.native[0].calls.count("close"), 1)

    def test_http_auth_correlation_and_no_native_calls(self):
        httpd = server.make_http_server(self.service, token="a" * 32, port=0)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            request_id = uuid.uuid4().hex
            body = dumps({"protocol": PROTOCOL, "request_id": request_id, "server_id": None,
                          "op": "describe", "params": {}})
            for credential, expected in (("wrong", 401), ("Bearer " + "a" * 32, 200)):
                connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
                try:
                    connection.request("POST", "/rpc", body, {"Authorization": credential})
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    payload = response.read()
                    if expected == 200:
                        self.assertEqual(loads(payload)["request_id"], request_id)
                finally:
                    connection.close()
            self.assertFalse(self.adapter.native)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_listener_rejects_nonloopback_or_weak_tokens(self):
        for kwargs in ({"host": "0.0.0.0", "token": "a" * 32}, {"token": "weak"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                server.make_http_server(self.service, **kwargs)


if __name__ == "__main__":
    unittest.main()
