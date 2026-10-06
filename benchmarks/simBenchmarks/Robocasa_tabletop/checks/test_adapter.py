"""Native-independent contract/accounting tests; NumPy-only observation tests."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dataclasses import replace

from benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter import (
    ACTION_SPEC, CAMERA, CAMERA_KEY, LANGUAGE_KEY, PARTS, PILOT_SEED, PILOT_TASKS,
    STATE_NAMES, TabletopBenchmarkAdapter, TabletopEpisode, action_dictionary,
    policy_observation, used_asset_manifest, verify_native_contract, verify_object_inventory,
)
from benchkit.contracts import ActionChunk, Observation, PolicyDecision, PolicyDescriptor
from benchkit.errors import CompatibilityError, ProtocolError
from AgentPolicies.policy_support.runner import EvaluationRunner, RunRequest

HAS_NUMPY = importlib.util.find_spec("numpy") is not None


class ContractChecks(unittest.TestCase):
    def test_import_and_construction_do_not_import_native_or_numpy(self):
        code = ("import sys; from benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter import TabletopBenchmarkAdapter; "
                "TabletopBenchmarkAdapter(); assert not set(('robocasa','robosuite','mujoco','numpy','av')) & set(sys.modules)")
        subprocess.run([sys.executable, "-B", "-c", code], check=True)

    def test_actual_joint_limits_are_not_generic_gym_boxes(self):
        self.assertEqual(ACTION_SPEC.size, 29)
        self.assertEqual(len(STATE_NAMES), 29)
        self.assertEqual(ACTION_SPEC.control_hz, 20)
        self.assertEqual(ACTION_SPEC.low[0:4], (-3., 0., -3., -3.))
        self.assertEqual(ACTION_SPEC.high[14:20], (1.57, 1.57, 1.57, 1.57, 1.22, 1.74))
        legal = [0.] * 29
        legal[0] = 2.
        self.assertEqual(ACTION_SPEC.validate(legal)[0], 2.)
        for index, value in ((1, -.01), (8, .01), (17, 1.58), (18, 1.23), (27, 1.23)):
            action = [0.] * 29
            action[index] = value
            with self.assertRaises(ValueError):
                ACTION_SPEC.validate(action)

    def test_dimension_nonfinite_and_boolean_actions_fail_closed(self):
        for action in ([0.] * 28, [0.] * 30, [float("nan")] + [0.] * 28,
                       [float("inf")] + [0.] * 28, [True] + [0.] * 28):
            with self.assertRaises((ValueError, TypeError)):
                ACTION_SPEC.validate(action)

    def test_selection_and_budget_are_predeclared(self):
        adapter = TabletopBenchmarkAdapter()
        episodes = adapter.episodes(PILOT_SEED)
        self.assertEqual([ep.task for ep in episodes], list(PILOT_TASKS.values()))
        self.assertEqual(adapter.environment_step_cap, 1000)
        self.assertEqual(episodes[0].metadata["candidate_style_ids"], list(range(12)))
        self.assertEqual(len(adapter.episodes(PILOT_SEED, 1)), 1)
        for other in (replace(episodes[0], seed=1), replace(episodes[0], metadata={})):
            with self.assertRaises(ProtocolError):
                adapter.open_episode(other)
        for selection in ([], [0, 0], [19, 0], [1], [True]):
            with self.assertRaises(ValueError):
                TabletopBenchmarkAdapter(task_ids=selection)
        for seed in (1, True):
            with self.assertRaises(ValueError):
                adapter.episodes(seed)
        for calls, prefix in ((201, 5), (200, 6), (0, 1), (True, 5), (200, 1.)):
            with self.assertRaises(ValueError):
                TabletopBenchmarkAdapter(max_policy_calls=calls, replan_interval=prefix)
        shorter = TabletopBenchmarkAdapter(max_policy_calls=1, replan_interval=1)
        self.assertNotEqual(adapter.descriptor.protocol_version, shorter.descriptor.protocol_version)

    def session(self, native_result):
        adapter = TabletopBenchmarkAdapter()
        session = adapter.open_episode(adapter.episodes(PILOT_SEED)[0])
        session.env = SimpleNamespace(step=lambda _: native_result)
        session.started_at = time.monotonic()
        observer = patch.object(session, "_observe", side_effect=lambda _: Observation(session.step_count, "Native task."))
        observer.start()
        self.addCleanup(observer.stop)
        mapper = patch("benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter.action_dictionary", return_value={})
        mapper.start()
        self.addCleanup(mapper.stop)
        return session

    def test_native_success_is_checked_each_action_and_stops_without_oracle_requery(self):
        session = self.session(({}, 1., False, False, {"success": True, "object_pose": object()}))
        transition = session.step((0.,) * 29)
        self.assertTrue(transition.terminated)
        self.assertFalse(transition.truncated)
        self.assertEqual(session.metrics()["first_success_step"], 1)
        self.assertNotIn("object_pose", transition.info)
        self.assertEqual(transition.observation.metadata, {})
        with self.assertRaises(ProtocolError):
            session.step((0.,) * 29)

    def test_native_reference_720_is_not_provisional_1000_cap(self):
        session = self.session(({}, 0., False, False, {"success": False}))
        session.step_count = 719
        self.assertFalse(session.step((0.,) * 29).truncated)
        session.step_count = 999
        transition = session.step((0.,) * 29)
        self.assertTrue(transition.truncated)
        self.assertFalse(transition.terminated)
        self.assertFalse(session.metrics()["success"])

    def test_native_termination_and_truncation_remain_distinct(self):
        for done, truncated in ((True, False), (False, True)):
            session = self.session(({}, 0., done, truncated, {"success": False}))
            result = session.step((0.,) * 29)
            self.assertEqual((result.terminated, result.truncated), (done, truncated))
            self.assertFalse(session.metrics()["success"])

    def test_reward_success_mismatch_fails_after_recording_executed_action(self):
        session = self.session(({}, 1., False, False, {"success": False}))
        with self.assertRaises(ProtocolError):
            session.step((0.,) * 29)
        self.assertEqual(session.step_count, 1)

    def test_ever_success_is_not_substituted_for_final_native_success(self):
        session = self.session(({}, 0., False, False, {"success": False}))
        session.success_ever = True
        self.assertFalse(session.metrics()["success"])
        self.assertTrue(session.metrics()["success_ever"])

    def test_repeated_reset_and_artifact_rebinding_are_rejected(self):
        adapter = TabletopBenchmarkAdapter()
        session = adapter.open_episode(adapter.episodes(PILOT_SEED)[0])
        session.reset_started = True
        with self.assertRaises(ProtocolError):
            session.reset()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProtocolError):
                session.bind_artifact_dir(Path(directory))

    def test_used_object_content_changes_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            objects = root / "objects"
            objects.mkdir()
            texture = objects / "texture.png"
            texture.write_bytes(b"native texture")
            row = {"size": texture.stat().st_size, "sha256": hashlib.sha256(texture.read_bytes()).hexdigest()}
            inventory = {"files": {"texture.png": row}}
            xml = f'<mujoco><asset><texture file="{texture}"/></asset></mujoco>'
            manifest = used_asset_manifest(xml, [root], [], objects, inventory)
            self.assertTrue(manifest["complete"])
            texture.write_bytes(b"altered image!")
            altered = used_asset_manifest(xml, [root], [], objects, inventory)
            self.assertFalse(altered["complete"])
            self.assertIn("differs", altered["errors"][0])

    def test_live_pool_cannot_be_reduced_after_provisioning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {}
            for name in ("objaverse", "sketchfab", "lightwheel"):
                (root / name).mkdir()
                (root / name / "model.xml").write_bytes(b"model")
                files[name + "/model.xml"] = {"size": 5, "kind": "file", "sha256": hashlib.sha256(b"model").hexdigest()}
            digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            frozen = {"inventory_sha256": digest, "file_count": 3, "total_regular_bytes": 15}
            payload = {**frozen, "files": files, "comparison": {"matches": True}, "root": str(root)}
            path = root / "inventory.json"
            path.write_text(json.dumps(payload))
            with patch.dict("benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter._FROZEN", {"object_inventory": frozen}):
                verify_object_inventory(path, root)
                (root / "objaverse" / "model.xml").rename(root / "objaverse" / "changed.xml")
                with self.assertRaises(CompatibilityError):
                    verify_object_inventory(path, root)


@unittest.skipUnless(HAS_NUMPY, "NumPy observation checks run in the isolated eval runtime")
class ObservationChecks(unittest.TestCase):
    def test_native_horizon_must_match_recorded_engine_horizon(self):
        robot = SimpleNamespace(robot_model=type("GR1ArmsAndWaistFourierHands", (), {})(),
                                composite_controller=SimpleNamespace(name="BASIC", part_controllers={part: None for _, part, _ in PARTS}))
        native = SimpleNamespace(robots=[robot], sim=SimpleNamespace(model=object()),
                                 control_freq=20, horizon=999, ignore_done=True)
        with patch.dict(sys.modules, {"robocasa.models.robots": SimpleNamespace(unformat_gripper_space=lambda *args: None)}):
            with self.assertRaises(CompatibilityError):
                verify_native_contract(native, {})

    def raw(self):
        import numpy as np
        return {CAMERA_KEY: np.zeros((256, 256, 3), dtype=np.uint8), LANGUAGE_KEY: "unlocked_waist: native task",
                **{"state." + part: np.arange(size, dtype=np.float32) for part, _, size in PARTS},
                "object_pose": object(), "eef_pose": object(), "world_root_pose": object(),
                "metadata": {"success": True, "seed": 9}, "video.extra": object(), "sim": object()}

    def test_observation_is_a_copied_allowlist(self):
        raw = self.raw()
        observation = policy_observation(raw, 0)
        self.assertEqual(set(observation.images), {CAMERA})
        self.assertEqual(observation.metadata, {})
        self.assertEqual(len(observation.state), 29)
        self.assertEqual(observation.state[14:20], tuple(float(i) for i in range(6)))
        raw[CAMERA_KEY][:] = 255
        raw["state.left_arm"][:] = -99
        self.assertEqual(int(observation.images[CAMERA].max()), 0)
        self.assertEqual(observation.state[0], 0.)

    def test_bad_shapes_nonfinite_and_missing_channels_are_rejected(self):
        import numpy as np
        for key, value in ((CAMERA_KEY, np.zeros((224, 224, 3), np.uint8)),
                           ("state.left_arm", np.zeros(6)), ("state.left_arm", np.full(7, float("nan"))),
                           (LANGUAGE_KEY, "")):
            raw = self.raw()
            raw[key] = value
            with self.assertRaises(ProtocolError):
                policy_observation(raw, 0)
        raw = self.raw()
        del raw["state.waist"]
        with self.assertRaises(ProtocolError):
            policy_observation(raw, 0)

    def test_action_groups_preserve_exact_values_without_clipping(self):
        import numpy as np
        values = [(low + high) / 2 for low, high in zip(ACTION_SPEC.low, ACTION_SPEC.high)]
        mapped = action_dictionary(values)
        self.assertEqual(list(mapped), ["action." + part for part, _, _ in PARTS])
        np.testing.assert_array_equal(np.concatenate(list(mapped.values())), values)
        values[1] = -1.
        with self.assertRaises(ValueError):
            action_dictionary(values)


class RunnerChecks(unittest.TestCase):
    def test_mid_chunk_success_counts_three_actions_and_one_decision_without_leaks(self):
        class Native:
            calls = 0
            closed = False
            def step(self, action):
                self.calls += 1
                success = self.calls == 3
                return {}, float(success), False, False, {"success": success, "private_oracle": object()}
            def close(self):
                self.closed = True

        class Session(TabletopEpisode):
            def reset(self):
                self.started_at = time.monotonic()
                self.env = Native()
                return self._observe({})
            def _observe(self, raw):
                return Observation(self.step_count, "Visible native task.", {CAMERA: b"fixture"}, (0.,) * 29)

        class Policy:
            descriptor = PolicyDescriptor("boundary-fixture", "scripted", version="1")
            def compatibility_errors(self, observation_spec, action_spec):
                return []
            def start_episode(self, context):
                self.context = context
            def act(self, observation):
                self.observation = observation
                return PolicyDecision(action=ActionChunk.from_steps([[0.] * 29] * 5))
            def end_episode(self):
                pass

        adapter = TabletopBenchmarkAdapter(task_ids=[0], max_policy_calls=5, replan_interval=5)
        session = Session(adapter, adapter.episodes(PILOT_SEED)[0])
        policy = Policy()
        with tempfile.TemporaryDirectory() as directory, patch.object(adapter, "open_episode", return_value=session), \
             patch("benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.adapter.action_dictionary", return_value={}):
            path = EvaluationRunner().run(adapter, policy, RunRequest(
                Path(directory), seed=PILOT_SEED, max_steps=25, max_policy_calls=5, replan_interval=5,
                budget_mode="decisions",
            ))
            result = json.loads((path / "episodes.jsonl").read_text().splitlines()[0])
            self.assertEqual(result["environment_steps"], 3)
            self.assertEqual(result["policy_calls"], 1)
            self.assertEqual(result["metrics"]["first_success_step"], 3)
            self.assertTrue(result["metrics"]["success"])
            self.assertEqual(policy.context.episode.instruction, "Visible native task.")
            self.assertFalse(hasattr(policy.context.episode, "seed"))
            self.assertFalse(hasattr(policy.context.episode, "metadata"))
            self.assertEqual(policy.observation.metadata, {})
            self.assertIsNone(session.env)


if __name__ == "__main__":
    unittest.main()
