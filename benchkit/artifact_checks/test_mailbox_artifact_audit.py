"""Synthetic artifact-only fixtures, never simulator or policy capability trials."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import av
import numpy as np
from PIL import Image

TOOLS = Path(__file__).resolve().parents[1] / "audits"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("mailbox_artifact_audit", TOOLS / "mailbox_artifacts.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class MailboxArtifactAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run, self.mailbox = self.root / "run", self.root / "mailbox"
        self.run.mkdir()
        self.mailbox.mkdir()
        self.save(self.mailbox / "ready.json", {"status": "episode_closed", "schema_version": "starvla-rsi.mailbox/v2"})

    def save(self, path, value):
        path.write_text(json.dumps(value))

    def fixture(self, benchmark="simpler_env"):
        cameras = ["agentview", "robot0_eye_in_hand"] if benchmark == "libero" else ["overhead_camera"]
        if benchmark == "robocasa365":
            cameras = list(audit.ROBOCASA_CAMERAS)
        simple = benchmark == "simple_humanoid"
        if simple:
            cameras = ["head_stereo_left"]
        spec = {"cameras": cameras, "modalities": ["language", "rgb"], "privileged": False, "state_names": []}
        action = {"size": 1}
        if simple:
            spec["state_names"] = [f"joint_{index}" for index in range(31)]
            spec["modalities"].append("proprioception")
            action.update(size=36, names=[*spec["state_names"], "height", "vx", "vy", "turn", "heading"])
        protocol = {"budget_mode": "decisions", "primary_budget": "policy_decisions", "max_steps": 10,
                    "max_policy_calls": 2, "replan_interval": 5}
        parameters = {"directory": str(self.mailbox), "max_chunk_length": 5, "timeout_s": 900,
                      "history": "current_observation_only", "prompt_sha256": hashlib.sha256(b"test prompt").hexdigest()}
        self.manifest = {"schema_version": "starvla-rsi.eval/v1", "benchmark": {"name": benchmark},
                         "policy": {"version": "starvla-rsi.mailbox/v2", "parameters": parameters},
                         "observation_spec": spec, "action_spec": action, "protocol": protocol}
        self.result = {"status": "completed", "episode": {"id": "synthetic"}, "success": False,
                       "environment_steps": 1, "policy_calls": 2, "artifacts": {"frames": str(self.run / "frames.jsonl")}}
        size = 256 if benchmark == "robocasa365" else 32
        width, height = (640, 360) if simple else (size, size)
        base = self.run
        if simple:
            base = self.run / "episodes/synthetic/artifacts"
            (base / "rgb").mkdir(parents=True)
            self.simple_base = base
            self.result["episode"].update(task="fixture", instruction="Move.")
            self.result["metrics"] = {"diagnostic_only": False, "native_return": 0.0, "native_steps": 1}
        pixels = np.zeros((height, width, 3), dtype=np.uint8)
        pixels[:, :16, 0] = 200
        pixels[16:, :, 1] = 120
        frames = []
        for camera in cameras:
            for step in range(2):
                path = (base / "rgb" / f"{camera}_{step:06d}.png" if simple
                        else self.run / f"{camera}-{step}.png")
                Image.fromarray(pixels).save(path)
                frames.append({"step": step, "camera": camera, "path": path.name,
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            video = base / f"{camera}.mp4"
            self.video(video, pixels, 2, hz=50 if simple else 20)
            key = "video" if benchmark == "simpler_env" else f"{camera}_video"
            self.result["artifacts"][f"video_{camera}" if simple else key] = video.name if simple else str(video)
        (self.run / "frames.jsonl").write_text("".join(json.dumps(row) + "\n" for row in frames))
        self.events = []
        for step in range(2):
            observation = {"step": step, "instruction": " Move." if simple else "Move.", "state": [0.0] * 31 if simple else None,
                           "camera_names": cameras, "metadata": {}}
            self.events.append({"event": "observation" if step == 0 else "environment_step", "observation": observation})
            self.events.append({"event": "policy_call_start", "policy_call": step + 1})
            request_id = f"opaque-request-{step}"
            turn = self.mailbox / request_id
            turn.mkdir()
            images = {}
            for index, camera in enumerate(cameras):
                path = turn / f"frame-{index:03d}.png"
                Image.fromarray(pixels).save(path)
                images[camera] = {"path": path.relative_to(self.mailbox).as_posix(), "encoding": "png",
                                  "color_space": "RGB", "width": width, "height": height,
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            response = {"request_id": request_id, "usage": None}
            response.update({"actions": [[0]]} if step == 0 else {"stop": True, "stop_reason": "give_up"})
            self.save(turn / "accepted_response.json", response)
            public = {"schema_version": "starvla-rsi.mailbox/v2", "request_id": request_id,
                      "step": step, "instruction": observation["instruction"], "state": observation["state"], "images": images,
                      "observation_spec": spec, "action_spec": action,
                      "history": parameters["history"], "prompt": "test prompt", "budgets": {
                          **protocol, "max_chunk_length": 5, "response_timeout_s": 900,
                          "max_provider_calls_per_decision": 1, "provider_call_limit_verified": False}}
            self.save(turn / "observation.json", public)
            self.events.append({"event": "policy_decision", "policy_call": step + 1, "metadata": {
                "request_id": request_id, "observation_path": str(turn / "observation.json"),
                "response_path": str(turn / "accepted_response.json"), "structured_response": response}})
        if benchmark == "robocasa365":
            control = next(event for event in self.events if event["event"] == "environment_step")
            control.update(action=[0], reward=0.0, terminated=False, truncated=False,
                           info={"native_steps": 1, "native_success": False})
            native = [{"event": "native_action_start", "step": 1, "action": [0]},
                      {"event": "native_action_end", "step": 1, "reward": 0.0,
                       "native_success": False, "native_done": False,
                       "native_truncated": False, "adapter_truncated": False}]
            self.result["artifacts"]["native_actions"] = str(self.run / "native_actions.jsonl")
            self.native_rows(native)
        if simple:
            control = next(event for event in self.events if event["event"] == "environment_step")
            control.update(action=[0] * 36, reward=0.0, terminated=False, truncated=False,
                           info={"native_steps": 1, "native_success": False})
            self.simple_ticks([{"joint_positions": dict.fromkeys(spec["state_names"], 0.0),
                                "reward": 0.0, "success": False, "terminated": False,
                                "truncated": False, "native_steps": 1, "step_wall_seconds": 0.1}])
            self.save(base / "native_provenance.json", {"public_state_names": spec["state_names"],
                      "instruction": " Move.", "selected_task_configuration": {"instruction": " Move."},
                      "task": "fixture", "diagnostic_only": False})
            self.result["artifacts"]["native_provenance"] = "native_provenance.json"
            self.video(base / "head_stereo_right.mp4", pixels, 2, hz=50)
            self.result["artifacts"]["video_head_stereo_right"] = "head_stereo_right.mp4"
            self.refresh_simple_videos()

    def simple_ticks(self, rows):
        (self.simple_base / "private_native_ticks.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    def change_simple_tick(self, mutate):
        rows = [json.loads(line) for line in (self.simple_base / "private_native_ticks.jsonl").read_text().splitlines()]
        mutate(rows)
        self.simple_ticks(rows)

    def refresh_simple_videos(self):
        rows = [{"path": str(path), "size": path.stat().st_size,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "frames": self.result["environment_steps"] + 1, "fps": 50}
                for path in sorted(self.simple_base.glob("*.mp4"))]
        self.save(self.simple_base / "video_manifest.json", rows)
        self.result["artifacts"]["video_manifest"] = "video_manifest.json"

    def native_rows(self, rows):
        (self.run / "native_actions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    def change_native(self, mutate):
        rows = [json.loads(line) for line in (self.run / "native_actions.jsonl").read_text().splitlines()]
        mutate(rows)
        self.native_rows(rows)

    def video(self, path, pixels, count, hz=20):
        with av.open(str(path), "w") as container:
            stream = container.add_stream("libx264", rate=hz)
            stream.height, stream.width, stream.pix_fmt = *pixels.shape[:2], "yuv420p"
            for _ in range(count):
                for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)

    def audit(self):
        return audit.audit_payload(audit.ClosedFiles(self.run), audit.ClosedFiles(self.mailbox),
                                   self.manifest, self.result, self.events,
                                   episode_artifact_base=(self.simple_base.relative_to(self.run)
                                                          if hasattr(self, "simple_base") else None))

    def change_public(self, mutate):
        path = self.mailbox / "opaque-request-0/observation.json"
        value = json.loads(path.read_text())
        mutate(value)
        self.save(path, value)

    def upgrade_v3(self, minimum=0):
        version = "starvla-rsi.mailbox/v3"
        rule = {"stop_constraint_version": "minimum-action-decisions/v2",
                "min_action_decisions_before_give_up": minimum,
                "early_policy_stop_exception": "safety_stop_with_nonempty_note", "scope": "policy"}
        self.manifest["policy"]["version"] = version
        self.manifest["policy"]["parameters"]["policy_stop_rule"] = rule
        self.manifest["protocol"]["execution_feedback_version"] = "starvla-rsi.execution-feedback/v1"
        self.save(self.mailbox / "ready.json", {"status": "episode_closed", "schema_version": version})
        for step in range(2):
            path = self.mailbox / f"opaque-request-{step}/observation.json"
            public = json.loads(path.read_text())
            public.update(schema_version=version,
                          policy_constraints={**rule, "voluntary_stop_allowed": step >= minimum},
                          control_feedback={"policy_calls": step, "action_decisions": step,
                                            "environment_steps": step, "executed_steps": step})
            self.save(path, public)

    def test_mailbox_v3_preserves_native_failure_and_separates_policy_settings(self):
        self.fixture()
        self.upgrade_v3(minimum=1)
        row = self.audit()
        self.assertFalse(row["native_success"])
        self.assertEqual(row["public_observations_verified"], 2)

    def test_mailbox_v3_invented_executed_decisions_rejected(self):
        self.fixture()
        self.upgrade_v3()
        self.change_public(lambda data: data["control_feedback"].update(action_decisions=50))
        with self.assertRaisesRegex(ValueError, "feedback differs"):
            self.audit()

    def test_mailbox_v3_stop_rule_cannot_move_back_to_benchmark_protocol(self):
        self.fixture()
        self.upgrade_v3()
        self.manifest["protocol"]["min_action_decisions_before_give_up"] = 50
        with self.assertRaisesRegex(ValueError, "benchmark protocol"):
            self.audit()

    def test_mailbox_v3_claimed_stop_permission_must_follow_executed_count(self):
        self.fixture()
        self.upgrade_v3(minimum=1)
        self.change_public(lambda data: data["policy_constraints"].update(voluntary_stop_allowed=True))
        with self.assertRaisesRegex(ValueError, "configuration drift"):
            self.audit()

    def test_complete_failure_is_valid_artifact_evidence(self):
        self.fixture()
        row = self.audit()
        self.assertEqual((row["native_pngs_verified"], row["public_images_matched"]), (2, 2))
        self.assertFalse(row["native_success"])
        self.assertEqual(row["videos"][0]["frames"], 2)
        self.assertLess(row["videos"][0]["maximum_png_pixel_mae_255"], 10)

    def test_libero_two_camera_layout(self):
        self.fixture("libero")
        row = self.audit()
        self.assertEqual((row["native_pngs_verified"], row["public_images_matched"], len(row["videos"])), (4, 4, 2))

    def test_robocasa_complete_three_camera_false(self):
        self.fixture("robocasa365")
        row = self.audit()
        self.assertEqual((row["native_pngs_verified"], row["public_images_matched"], len(row["videos"])), (6, 6, 3))
        self.assertEqual(row["native_control_pairs_verified"], 1)
        self.assertFalse(row["native_success"])
        self.assertTrue(all(video["presentation_timestamps_verified_hz"] == 20 for video in row["videos"]))

    def test_robocasa_camera_order_rejected(self):
        self.fixture("robocasa365")
        self.manifest["observation_spec"]["cameras"].reverse()
        with self.assertRaisesRegex(ValueError, "camera/state track"):
            self.audit()

    def test_robocasa_true_native_transition_preserved(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[1].update(native_success=True, reward=1.0))
        control = next(event for event in self.events if event["event"] == "environment_step")
        control.update(reward=1.0, terminated=True)
        control["info"]["native_success"] = True
        self.result["success"] = True
        self.events = self.events[:self.events.index(control) + 1]
        self.result["policy_calls"] = 1
        self.assertTrue(self.audit()["native_success"])

    def test_robocasa_out_of_order_native_step_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[1].update(step=2))
        with self.assertRaisesRegex(ValueError, "end identity"):
            self.audit()

    def test_robocasa_wrong_png_dimensions_rejected(self):
        self.fixture("robocasa365")
        path = self.run / (audit.ROBOCASA_CAMERAS[0] + "-0.png")
        Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(path)
        rows = [json.loads(line) for line in (self.run / "frames.jsonl").read_text().splitlines()]
        rows[0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.run / "frames.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaisesRegex(ValueError, "PNG dimensions"):
            self.audit()

    def test_robocasa_extra_state_rejected(self):
        self.fixture("robocasa365")
        self.manifest["observation_spec"]["state_names"] = ["hidden_pose"]
        with self.assertRaisesRegex(ValueError, "camera/state track"):
            self.audit()

    def test_robocasa_missing_native_control_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, "native action coverage"):
            self.audit()

    def test_robocasa_changed_native_action_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[0].update(action=[1]))
        with self.assertRaisesRegex(ValueError, "native action start"):
            self.audit()

    def test_robocasa_native_success_mismatch_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[1].update(native_success=True))
        with self.assertRaisesRegex(ValueError, "transition mismatch"):
            self.audit()

    def test_robocasa_boolean_native_action_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[0].update(action=[False]))
        with self.assertRaisesRegex(ValueError, "finite nonboolean"):
            self.audit()

    def test_robocasa_boolean_runner_action_rejected(self):
        self.fixture("robocasa365")
        next(event for event in self.events if event["event"] == "environment_step")["action"] = [False]
        with self.assertRaisesRegex(ValueError, "finite nonboolean"):
            self.audit()

    def test_robocasa_nonfinite_native_action_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[0].update(action=[float("inf")]))
        with self.assertRaisesRegex(ValueError, "nonfinite JSON"):
            self.audit()

    def test_robocasa_native_step_requires_integer(self):
        self.fixture("robocasa365")
        control = next(event for event in self.events if event["event"] == "environment_step")
        for value in (True, 1.0):
            with self.subTest(value=repr(value)):
                control["info"]["native_steps"] = value
                with self.assertRaisesRegex(ValueError, "transition mismatch"):
                    self.audit()

    def test_robocasa_numeric_flag_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[1].update(native_done=0))
        with self.assertRaisesRegex(ValueError, "flag type"):
            self.audit()

    def test_robocasa_native_truncation_lost_rejected(self):
        self.fixture("robocasa365")
        self.change_native(lambda rows: rows[1].update(native_truncated=True))
        with self.assertRaisesRegex(ValueError, "native truncation lost"):
            self.audit()

    def test_robocasa_final_score_mismatch_rejected(self):
        self.fixture("robocasa365")
        self.result["success"] = True
        with self.assertRaisesRegex(ValueError, "final native score"):
            self.audit()

    def test_robocasa_video_wrong_frequency_rejected(self):
        self.fixture("robocasa365")
        self.video(self.run / (audit.ROBOCASA_CAMERAS[0] + ".mp4"),
                   np.zeros((256, 256, 3), dtype=np.uint8), 2, hz=25)
        with self.assertRaisesRegex(ValueError, "presentation timestamp"):
            self.audit()

    def test_simple_rgb_only_is_explicitly_unsupported(self):
        self.fixture("simple_humanoid")
        self.manifest["observation_spec"]["state_names"] = []
        with self.assertRaisesRegex(ValueError, "SIMPLE camera/state track"):
            self.audit()

    def test_simple_leading_space_and_private_video_no_png_parity(self):
        self.fixture("simple_humanoid")
        row = self.audit()
        self.assertEqual((row["native_ticks_verified"], row["native_pngs_verified"], row["public_images_matched"]), (1, 2, 2))
        self.assertFalse(row["native_success"])
        private = next(video for video in row["videos"] if video["camera"] == "head_stereo_right")
        self.assertIsNone(private["maximum_png_pixel_mae_255"])
        self.assertEqual(private["presentation_timestamps_verified_hz"], 50)

    def test_simple_true_nonzero_reward_is_preserved(self):
        self.fixture("simple_humanoid")
        self.change_simple_tick(lambda rows: rows[0].update(success=True, terminated=True, reward=0.38))
        control = next(event for event in self.events if event["event"] == "environment_step")
        control.update(reward=0.38, terminated=True)
        control["info"]["native_success"] = True
        self.result["success"] = True
        self.result["metrics"]["native_return"] = 0.38
        self.events = self.events[:self.events.index(control) + 1]
        self.result["policy_calls"] = 1
        self.assertTrue(self.audit()["native_success"])

    def test_simple_public_language_must_not_be_stripped(self):
        self.fixture("simple_humanoid")
        self.change_public(lambda value: value.update(instruction="Move."))
        with self.assertRaisesRegex(ValueError, "scheduled native input"):
            self.audit()

    def test_simple_all_observations_bind_raw_language(self):
        self.fixture("simple_humanoid")
        self.events[0]["observation"]["instruction"] = "Move."
        with self.assertRaisesRegex(ValueError, "raw native language"):
            self.audit()

    def test_simple_boolean_or_nonfinite_reset_encoder_rejected(self):
        self.fixture("simple_humanoid")
        for value in (False, float("inf"), float("nan")):
            with self.subTest(value=repr(value)):
                self.events[0]["observation"]["state"][0] = value
                with self.assertRaisesRegex(ValueError, "31 finite nonboolean"):
                    self.audit()

    def test_simple_boolean_public_encoder_alias_rejected(self):
        self.fixture("simple_humanoid")
        self.change_public(lambda value: value["state"].__setitem__(0, False))
        with self.assertRaisesRegex(ValueError, "public state must"):
            self.audit()

    def test_simple_tick_gap_rejected(self):
        self.fixture("simple_humanoid")
        self.simple_ticks([])
        with self.assertRaisesRegex(ValueError, "tick coverage"):
            self.audit()

    def test_simple_tick_counter_bool_rejected(self):
        self.fixture("simple_humanoid")
        self.change_simple_tick(lambda rows: rows[0].update(native_steps=True))
        with self.assertRaisesRegex(ValueError, "tick counter"):
            self.audit()

    def test_simple_tick_numeric_flag_rejected(self):
        self.fixture("simple_humanoid")
        self.change_simple_tick(lambda rows: rows[0].update(success=0))
        with self.assertRaisesRegex(ValueError, "tick flag"):
            self.audit()

    def test_simple_tick_encoder_mismatch_rejected(self):
        self.fixture("simple_humanoid")
        self.change_simple_tick(lambda rows: rows[0]["joint_positions"].update(joint_0=0.1))
        with self.assertRaisesRegex(ValueError, "encoder mismatch"):
            self.audit()

    def test_simple_tick_reward_bool_rejected(self):
        self.fixture("simple_humanoid")
        self.change_simple_tick(lambda rows: rows[0].update(reward=False))
        with self.assertRaisesRegex(ValueError, "reward/time"):
            self.audit()

    def test_simple_private_video_wrong_hz_rejected(self):
        self.fixture("simple_humanoid")
        self.video(self.simple_base / "head_stereo_right.mp4", np.zeros((360, 640, 3), dtype=np.uint8), 2, hz=25)
        self.refresh_simple_videos()
        with self.assertRaisesRegex(ValueError, "stream rate"):
            self.audit()

    def test_simple_extra_png_rejected(self):
        self.fixture("simple_humanoid")
        (self.simple_base / "rgb/extra.png").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "directory coverage"):
            self.audit()

    def test_simple_video_manifest_hash_mismatch_rejected(self):
        self.fixture("simple_humanoid")
        path = self.simple_base / "video_manifest.json"
        rows = json.loads(path.read_text())
        rows[0]["sha256"] = "0" * 64
        self.save(path, rows)
        with self.assertRaisesRegex(ValueError, "video manifest"):
            self.audit()

    def test_simple_artifact_path_escape_rejected(self):
        self.fixture("simple_humanoid")
        self.result["artifacts"]["native_provenance"] = "../native_provenance.json"
        with self.assertRaisesRegex(ValueError, "unsafe artifact path"):
            self.audit()

    def test_simple_private_video_path_escape_rejected(self):
        self.fixture("simple_humanoid")
        path = self.simple_base / "video_manifest.json"
        rows = json.loads(path.read_text())
        rows[0]["path"] = str(self.root / "outside.mp4")
        self.save(path, rows)
        with self.assertRaisesRegex(ValueError, "outside authorized root"):
            self.audit()

    def test_simple_four_camera_video_layout(self):
        self.fixture("simple_humanoid")
        for camera in ("front_stereo_left", "front_stereo_right"):
            self.video(self.simple_base / f"{camera}.mp4", np.zeros((360, 640, 3), dtype=np.uint8), 2, hz=50)
            self.result["artifacts"][f"video_{camera}"] = f"{camera}.mp4"
        self.refresh_simple_videos()
        videos = self.audit()["videos"]
        self.assertEqual(len(videos), 4)
        self.assertEqual(sum(video["maximum_png_pixel_mae_255"] is None for video in videos), 3)

    def test_simple_zero_control_stop_without_tick_file(self):
        self.fixture("simple_humanoid")
        # These are synthetic fixture files only, never closed native records.
        (self.simple_base / "private_native_ticks.jsonl").unlink()
        (self.simple_base / "rgb/head_stereo_left_000001.png").unlink()
        self.events = self.events[:3]
        self.result.update(environment_steps=0, policy_calls=1)
        self.result["metrics"]["native_steps"] = 0
        response = {"request_id": "opaque-request-0", "stop": True, "stop_reason": "give_up", "usage": None}
        self.events[-1]["metadata"]["structured_response"] = response
        self.save(self.mailbox / "opaque-request-0/accepted_response.json", response)
        for camera in audit.SIMPLE_HEAD_CAMERAS:
            self.video(self.simple_base / f"{camera}.mp4", np.zeros((360, 640, 3), dtype=np.uint8), 1, hz=50)
        self.refresh_simple_videos()
        row = self.audit()
        self.assertEqual((row["native_ticks_verified"], row["native_pngs_verified"], row["decisions"]), (0, 1, 1))
        self.assertFalse(row["native_success"])

    def test_simple_config_language_mismatch_rejected(self):
        self.fixture("simple_humanoid")
        path = self.simple_base / "native_provenance.json"
        native = json.loads(path.read_text())
        native["selected_task_configuration"]["instruction"] = "Move."
        self.save(path, native)
        with self.assertRaisesRegex(ValueError, "configuration instruction"):
            self.audit()

    def test_simple_episode_metadata_mismatch_rejected(self):
        self.fixture("simple_humanoid")
        self.result["episode"]["instruction"] = " Move."
        with self.assertRaisesRegex(ValueError, "episode instruction"):
            self.audit()

    def test_simple_private_video_leaked_publicly_rejected(self):
        self.fixture("simple_humanoid")
        self.manifest["observation_spec"]["cameras"].append("head_stereo_right")
        with self.assertRaisesRegex(ValueError, "camera/state track"):
            self.audit()

    def test_simple_duplicate_video_rejected(self):
        self.fixture("simple_humanoid")
        path = self.simple_base / "video_manifest.json"
        rows = json.loads(path.read_text())
        rows.append(rows[0])
        self.save(path, rows)
        with self.assertRaisesRegex(ValueError, "video identity"):
            self.audit()

    def test_simple_short_private_video_rejected(self):
        self.fixture("simple_humanoid")
        self.video(self.simple_base / "head_stereo_right.mp4", np.zeros((360, 640, 3), dtype=np.uint8), 1, hz=50)
        self.refresh_simple_videos()
        with self.assertRaisesRegex(ValueError, "private video frame count"):
            self.audit()

    def test_simple_result_video_reference_mismatch_rejected(self):
        self.fixture("simple_humanoid")
        self.result["artifacts"]["video_head_stereo_right"] = "head_stereo_left.mp4"
        with self.assertRaisesRegex(ValueError, "result video reference"):
            self.audit()

    def test_simple_duplicate_tick_rejected(self):
        self.fixture("simple_humanoid")
        self.change_simple_tick(lambda rows: rows.append(rows[0]))
        with self.assertRaisesRegex(ValueError, "tick coverage"):
            self.audit()

    def test_simple_final_score_mismatch_rejected(self):
        self.fixture("simple_humanoid")
        self.result["success"] = True
        with self.assertRaisesRegex(ValueError, "final native score"):
            self.audit()

    def test_simple_diagnostic_rejected(self):
        self.fixture("simple_humanoid")
        self.result["metrics"]["diagnostic_only"] = True
        with self.assertRaisesRegex(ValueError, "not a capability"):
            self.audit()

    def test_simple_opaque_episode_id_not_used_as_filesystem_path(self):
        self.fixture("simple_humanoid")
        self.result["episode"]["id"] = "fixture/dr0/ep0"
        self.assertEqual(self.audit()["episode_id"], "fixture/dr0/ep0")

    def test_simple_native_png_wrong_dimensions_rejected(self):
        self.fixture("simple_humanoid")
        Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(self.simple_base / "rgb/head_stereo_left_000000.png")
        with self.assertRaisesRegex(ValueError, "PNG dimensions"):
            self.audit()

    def test_simple_observation_step_float_or_bool_rejected(self):
        self.fixture("simple_humanoid")
        control = next(event for event in self.events if event["event"] == "environment_step")
        for value in (1.0, True):
            with self.subTest(value=repr(value)):
                control["observation"]["step"] = value
                with self.assertRaisesRegex(ValueError, "chronological native control"):
                    self.audit()

    def test_simple_swapped_observation_identities_rejected(self):
        self.fixture("simple_humanoid")
        for event in self.events:
            if event["event"] in ("observation", "environment_step"):
                event["observation"]["step"] = 1 - event["observation"]["step"]
        for path in self.mailbox.glob("*/observation.json"):
            public = json.loads(path.read_text())
            public["step"] = 1 - public["step"]
            self.save(path, public)
        with self.assertRaisesRegex(ValueError, "chronological native control"):
            self.audit()

    def test_simple_public_step_float_or_bool_rejected(self):
        self.fixture("simple_humanoid")
        for value in (0.0, False):
            with self.subTest(value=repr(value)):
                self.change_public(lambda public: public.update(step=value))
                with self.assertRaisesRegex(ValueError, "public step must"):
                    self.audit()

    def test_simple_zero_control_dangling_tick_symlink_rejected(self):
        self.test_simple_zero_control_stop_without_tick_file()
        (self.simple_base / "private_native_ticks.jsonl").symlink_to(self.root / "missing.jsonl")
        with self.assertRaisesRegex(ValueError, "symlink in SIMPLE optional tick"):
            self.audit()

    def test_active_mailbox_rejected(self):
        self.fixture()
        self.save(self.mailbox / "ready.json", {"status": "pending"})
        with self.assertRaisesRegex(ValueError, "not closed"):
            self.audit()

    def test_error_not_reclassified_or_excluded(self):
        self.fixture()
        self.result["status"] = "error"
        with self.assertRaisesRegex(ValueError, "retain errors separately"):
            self.audit()

    def test_public_extra_private_field_rejected(self):
        self.fixture()
        self.change_public(lambda value: value.update(seed=0))
        with self.assertRaisesRegex(ValueError, "unexpected public"):
            self.audit()

    def test_mailbox_schema_not_runner_schema(self):
        self.fixture()
        self.change_public(lambda value: value.update(schema_version="starvla-rsi.eval/v1"))
        with self.assertRaisesRegex(ValueError, "schema drift"):
            self.audit()

    def test_changed_pixels_with_updated_hash_rejected(self):
        self.fixture()
        path = self.mailbox / "opaque-request-0/frame-000.png"
        Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.change_public(lambda value: value["images"]["overhead_camera"].update(sha256=digest))
        with self.assertRaisesRegex(ValueError, "pixel mismatch"):
            self.audit()

    def test_public_step_or_state_mismatch(self):
        self.fixture()
        self.change_public(lambda value: value.update(step=1, state=[0]))
        with self.assertRaisesRegex(ValueError, "scheduled native input"):
            self.audit()

    def test_prompt_drift(self):
        self.fixture()
        self.change_public(lambda value: value.update(prompt="extra hint"))
        with self.assertRaisesRegex(ValueError, "prompt drift"):
            self.audit()

    def test_public_image_other_turn_rejected(self):
        self.fixture()
        self.change_public(lambda value: value["images"]["overhead_camera"].update(path="opaque-request-1/frame-000.png"))
        with self.assertRaisesRegex(ValueError, "outside current request"):
            self.audit()

    def test_changed_png_rejected(self):
        self.fixture()
        path = self.run / "overhead_camera-0.png"
        path.write_bytes(path.read_bytes() + b"drift")
        with self.assertRaisesRegex(ValueError, "PNG digest"):
            self.audit()

    def test_native_frame_gap(self):
        self.fixture()
        path = self.run / "frames.jsonl"
        path.write_text(path.read_text().splitlines()[0] + "\n")
        with self.assertRaisesRegex(ValueError, "coverage gap"):
            self.audit()

    def test_changed_accepted_response(self):
        self.fixture()
        self.save(self.mailbox / "opaque-request-0/accepted_response.json", {"request_id": "different"})
        with self.assertRaisesRegex(ValueError, "accepted response differs"):
            self.audit()

    def test_unauthorized_mailbox_reference(self):
        self.fixture()
        self.events[2]["metadata"]["observation_path"] = str(self.root / "outside.json")
        with self.assertRaisesRegex(ValueError, "outside authorized root"):
            self.audit()

    def test_symlink_native_frame(self):
        self.fixture()
        path = self.run / "overhead_camera-0.png"
        outside = self.root / "outside.png"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.audit()

    def test_short_video(self):
        self.fixture()
        self.video(self.run / "overhead_camera.mp4", np.zeros((32, 32, 3), dtype=np.uint8), 1)
        with self.assertRaisesRegex(ValueError, "video frame count"):
            self.audit()


if __name__ == "__main__":
    unittest.main()
