"""Client-copy preferences never change live control or native finalization."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchkit.checks.test_sim_server_client import fixture
from benchkit.contracts import Observation, ObservationSpec, Transition
from benchkit.errors import InfrastructureError
from benchkit.recording import RecordingOptions
from benchkit.sim_server.client import SimServerBenchmarkAdapter
from benchkit.sim_server.wire import encode_observation, encode_transition


def inventory(state):
    paths = (
        "sim_server_session.json", "native_result.json", "frames/cam/000000.png",
        "cam.mp4", "frames.jsonl", "video_manifest.json", "native_events.jsonl",
        "private_native_ticks.jsonl", "native_worker.log", "unknown.json",
        "nested/native_result.json", "model_transcript.jsonl", "tools.jsonl",
    )
    state.files = [{"path": path, "size_bytes": len(state.payload),
                    "sha256": hashlib.sha256(state.payload).hexdigest()} for path in paths]
    state.override["finish"] = {"session_id": "session-0", "files": state.files,
        "artifacts": {"item-" + str(i): path for i, path in enumerate(paths)},
        "cleanup_error": None}
    return set(paths)


def session_for(state, endpoint, directory, options):
    adapter = SimServerBenchmarkAdapter(endpoint, "credential")
    session = adapter.open_episode(adapter.episodes(0)[0])
    session.configure_recording(options)
    session.bind_artifact_dir(Path(directory))
    return session


def downloaded(state):
    return {call["params"]["path"] for call in state.calls if call["op"] == "read_artifact"}


MEDIA = {"frames/cam/000000.png", "cam.mp4"}
OPTIONAL_TEXT = {"native_events.jsonl", "private_native_ticks.jsonl", "model_transcript.jsonl", "tools.jsonl"}


class ClientArtifactRetentionTests(unittest.TestCase):
    def test_explicit_images_and_media_copy_preserve_full_inventory(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            all_paths = inventory(state)
            session = session_for(state, endpoint, directory, RecordingOptions(images=True, copy_server_media=True))
            result = session.artifacts()
            self.assertEqual(downloaded(state), all_paths)
            self.assertEqual(len(result), len(all_paths) + 1)
            receipt = json.loads((Path(directory) / "sim_server_receipt.json").read_text())
            self.assertEqual(receipt["client_retention"]["omitted_paths"], [])

    def test_default_keeps_server_media_references_and_all_native_metadata(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            paths = inventory(state)
            session = session_for(state, endpoint, directory, RecordingOptions())
            result = session.artifacts()
            self.assertEqual(downloaded(state), paths - MEDIA)
            receipt = json.loads((Path(directory) / "sim_server_receipt.json").read_text())
            retention = receipt["client_retention"]
            self.assertEqual({row["path"] for row in retention["server_media_references"]}, MEDIA)
            self.assertFalse(retention["media_reference_is_local_copy"])
            self.assertEqual(retention["media_owner"], "benchmark_server")
            self.assertEqual(retention["server_retention_support"], "not_declared_legacy_server")
            self.assertFalse(any(path.endswith((".mp4", ".png")) for path in result.values()))
            self.assertEqual([row["op"] for row in state.calls].count("finish"), 1)
            self.assertNotIn("release_media", [row["op"] for row in state.calls])

    def test_minimal_keeps_compact_outcome_receipt_and_one_finish(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            all_paths = inventory(state)
            session = session_for(state, endpoint, directory, RecordingOptions(mode="minimal"))
            session.reset()
            self.assertEqual(session.step((0.25,)).observation.step, 1)
            self.assertEqual(session.metrics(), {"success": False})
            result = session.artifacts()
            self.assertEqual(session.artifacts(), result)
            session.close()
            session.close()
            compact = all_paths - MEDIA - OPTIONAL_TEXT
            self.assertEqual(downloaded(state), compact)
            self.assertEqual([call["op"] for call in state.calls].count("finish"), 1)
            self.assertEqual([call["op"] for call in state.calls].count("step"), 1)
            receipt = json.loads((Path(directory) / "sim_server_receipt.json").read_text())
            self.assertEqual(len(receipt["finish"]["files"]), len(all_paths))
            retained = receipt["client_retention"]
            self.assertEqual(set(retained["selected_paths"]), compact)
            self.assertEqual(set(retained["omitted_paths"]), all_paths - compact)
            self.assertEqual(retained["native_capture"], "unchanged")
            self.assertEqual(retained["server_capture_control"], "unsupported")
            self.assertFalse(retained["selection_is_download_attestation"])
            self.assertNotIn("credential", json.dumps(receipt))
            for path in result.values():
                self.assertTrue((Path(directory) / path).is_file())

    def test_disabled_images_do_not_disable_live_rgb_or_step(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("RGB codec requires optional NumPy")
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            inventory(state)
            spec = ObservationSpec(cameras=("camera",), modalities=("language", "rgb"))
            state.description["observation_spec"] = spec.to_dict()
            pixels = np.array([[[13, 42, 201]]], dtype=np.uint8)
            state.override["reset"] = {"observation": encode_observation(
                Observation(0, "Do task", {"camera": pixels}), spec)}
            state.override["step"] = {"transition": encode_transition(
                Transition(Observation(1, "Do task", {"camera": pixels}), terminated=True), spec)}
            session = session_for(state, endpoint, directory, RecordingOptions(mode="minimal"))
            self.assertEqual(session.reset().images["camera"].tolist(), pixels.tolist())
            response = session.step((0.25,))
            self.assertEqual(response.observation.images["camera"].tolist(), pixels.tolist())
            self.assertTrue(response.terminated)
            session.close()
            self.assertFalse(any(path.endswith((".png", ".mp4")) for path in downloaded(state)))

    def test_images_only_and_videos_only_use_explicit_categories(self):
        for toggle, expected in (
            ({"images": True, "copy_server_media": True}, {"frames/cam/000000.png"}),
            ({"videos": True, "copy_server_media": True}, {"cam.mp4"}),
            ({"interactions": True}, {"native_events.jsonl", "private_native_ticks.jsonl"}),
            ({"model_io": True, "tool_traces": True}, {"model_transcript.jsonl", "tools.jsonl"}),
        ):
            with self.subTest(toggle=toggle), fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
                paths = inventory(state)
                session = session_for(state, endpoint, directory, RecordingOptions(mode="minimal", **toggle))
                session.close()
                self.assertEqual(downloaded(state), expected | (paths - MEDIA - OPTIONAL_TEXT))

    def test_partial_profile_preserves_unclassified_native_evidence(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            inventory(state)
            session = session_for(state, endpoint, directory, RecordingOptions(model_io=False))
            session.close()
            self.assertIn("native_worker.log", downloaded(state))
            self.assertIn("unknown.json", downloaded(state))
            self.assertNotIn("model_transcript.jsonl", downloaded(state))
            self.assertIn("tools.jsonl", downloaded(state))
            self.assertIn("nested/native_result.json", downloaded(state))
            self.assertIn("native_events.jsonl", downloaded(state))

    def test_recording_is_configured_once_before_bind_or_reset(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            adapter = SimServerBenchmarkAdapter(endpoint, "credential")
            session = adapter.open_episode(adapter.episodes(0)[0])
            with self.assertRaises(InfrastructureError):
                session.configure_recording({"mode": "minimal"})
            session.configure_recording(RecordingOptions(mode="minimal"))
            with self.assertRaises(InfrastructureError):
                session.configure_recording(RecordingOptions())
            session.bind_artifact_dir(Path(directory))
            with self.assertRaises(InfrastructureError):
                session.configure_recording(RecordingOptions())
            session.reset()
            with self.assertRaises(InfrastructureError):
                session.configure_recording(RecordingOptions())
            session.close()

    def test_minimal_still_validates_omitted_inventory_paths(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            state.files = [{"path": "../unretained.mp4", "size_bytes": 1, "sha256": "0" * 64}]
            session = session_for(state, endpoint, directory, RecordingOptions(mode="minimal"))
            with self.assertRaises(InfrastructureError):
                session.artifacts()
            self.assertEqual(downloaded(state), set())
            with self.assertRaises(InfrastructureError):
                session.artifacts()
            self.assertEqual([call["op"] for call in state.calls].count("finish"), 1)

    def test_missing_video_preserves_server_only_image_reference(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            inventory(state)
            finish = state.override["finish"]
            finish["files"] = [row for row in finish["files"] if row["path"] != "cam.mp4"]
            finish["artifacts"] = {key: value for key, value in finish["artifacts"].items() if value != "cam.mp4"}
            session_for(state, endpoint, directory, RecordingOptions()).artifacts()
            receipt = json.loads((Path(directory) / "sim_server_receipt.json").read_text())
            self.assertEqual([row["path"] for row in receipt["client_retention"]["server_media_references"]],
                             ["frames/cam/000000.png"])
            self.assertNotIn("release_media", [row["op"] for row in state.calls])

    def test_server_retention_receipt_is_downloaded_as_essential_metadata(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            inventory(state)
            state.override["finish"]["files"].append({"path": "server_media_retention.json",
                "size_bytes": len(state.payload), "sha256": hashlib.sha256(state.payload).hexdigest()})
            session_for(state, endpoint, directory, RecordingOptions()).artifacts()
            receipt = json.loads((Path(directory) / "sim_server_receipt.json").read_text())
            self.assertEqual(receipt["client_retention"]["server_retention_support"], "server_receipt_available")
            self.assertIn("server_media_retention.json", downloaded(state))

    def test_opt_in_copy_failure_never_releases_server_media(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            inventory(state)
            session = session_for(state, endpoint, directory, RecordingOptions(copy_server_media=True))
            with patch.object(session, "_download", side_effect=OSError("fixture disk failure")):
                with self.assertRaises(InfrastructureError):
                    session.artifacts()
            self.assertTrue((Path(directory) / "sim_server_receipt.json").is_file())
            self.assertNotIn("release_media", [row["op"] for row in state.calls])

    def test_minimal_preserves_cleanup_error_without_retry(self):
        with fixture() as (state, _server, endpoint), tempfile.TemporaryDirectory() as directory:
            inventory(state)
            state.override["finish"]["cleanup_error"] = "native_close_failed"
            session = session_for(state, endpoint, directory, RecordingOptions(mode="minimal"))
            with self.assertRaises(InfrastructureError):
                session.artifacts()
            receipt = json.loads((Path(directory) / "sim_server_receipt.json").read_text())
            self.assertEqual(receipt["finish"]["cleanup_error"], "native_close_failed")
            session.close()
            self.assertEqual([call["op"] for call in state.calls].count("finish"), 1)


if __name__ == "__main__":
    unittest.main()
