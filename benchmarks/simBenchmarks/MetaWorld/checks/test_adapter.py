"""Dependency-light contracts plus mocked-native tests; never reset a real SIM."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.MetaWorld.bench_server import adapter as module
from benchmarks.simBenchmarks.MetaWorld.environment import runtime
from benchkit.errors import CompatibilityError, ProtocolError

try:
    import numpy as np
except ImportError:
    np = None


class Contracts(unittest.TestCase):
    def test_public_service_budget_matches_enforced_cap_without_native_reset(self):
        from benchkit.sim_server.server import BenchmarkService

        for orientation in ("native", "rot180"):
            with self.subTest(orientation=orientation), tempfile.TemporaryDirectory() as temporary:
                adapter = module.make_metaworld({"image_orientation": orientation})
                with patch.object(adapter, "open_episode", side_effect=AssertionError("no native reset")):
                    service = BenchmarkService(adapter, root=Path(temporary) / "server", seed=4042)
                    description = service.dispatch("describe", {})
                self.assertEqual(description["budget"]["environment_step_cap"], 400)
                self.assertEqual(description["episodes"][0]["metadata"]["policy_control_cap"], 400)
                self.assertEqual(service.sessions, {})

    def test_import_and_schedule_are_native_dependency_free(self):
        code = """
import sys
from benchmarks.simBenchmarks.MetaWorld.bench_server.adapter import make_metaworld
a = make_metaworld({'task_names': ['reach-v3']})
a.episodes(4042)
assert not any(n in sys.modules for n in ('metaworld', 'gymnasium', 'mujoco', 'numpy'))
"""
        subprocess.run([sys.executable, "-B", "-c", code], check=True)

    def test_catalog_complete_native_aliases(self):
        rows = module.task_catalog()
        self.assertEqual(len(rows), 50)
        self.assertEqual(rows[0]["name"], "assembly-v3")
        self.assertEqual(rows[12]["name"], "disassemble-v3")
        self.assertEqual(rows[15]["name"], "door-open-v3")
        self.assertEqual(rows[35]["name"], "peg-insert-side-v3")
        self.assertEqual(rows[46]["name"], "sweep-into-v3")
        self.assertEqual([sum(r["bucket"] == b for r in rows) for b in
                          ("easy", "medium", "hard", "very_hard")], [28, 11, 6, 5])

    def test_alias_normalization_and_duplicate_rejection(self):
        a = module.make_metaworld({"task_names": ["door-v3"]})
        self.assertEqual(a.episodes(4042)[0].task, "door-open-v3")
        for names in ([], ["unknown"], "reach-v3", ["door-v3", "door-open-v3"], [5]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                module.make_metaworld({"task_names": names})

    def test_no_full_or_unknown_parameters(self):
        for value in ({"evaluation_mode": "full"}, {"max_steps": 1000}, {"proprioception": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.make_metaworld(value)

    def test_orientation_protocols_are_explicit_and_distinct(self):
        default = module.make_metaworld({})
        native = module.make_metaworld({"image_orientation": "native"})
        self.assertEqual(default.image_orientation, "rot180")
        self.assertEqual(default.descriptor.protocol_version,
                         "metaworld-mt50-3.1.1/rgb480-corner2-rot180/control400/fast-v2")
        self.assertEqual(native.descriptor.protocol_version,
                         "metaworld-mt50-3.1.1/rgb480-corner2/control400/fast-v1")
        self.assertEqual(default.episodes(4042)[0].metadata["image_orientation"], "rot180")
        self.assertEqual(native.episodes(4042)[0].metadata["image_orientation"], "native")
        for value in (None, True, [], "flipud", "rot90", "ROT180"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.make_metaworld({"image_orientation": value})

    def test_schedule_one_attempt_stable(self):
        a = module.make_metaworld({"task_names": ["reach-v3", "door-open-v3"]})
        episodes = a.episodes(4042)
        self.assertEqual(episodes, a.episodes(4042))
        self.assertEqual(len(episodes), 2)
        self.assertEqual(len(a.episodes(4042, limit=1)), 1)
        self.assertEqual([e.metadata["episode_index"] for e in episodes], [0, 0])
        with patch.object(module, "verify_runtime") as verify, patch.object(module, "_create_native") as create:
            a.open_episode(episodes[0])
            verify.assert_not_called()
            create.assert_not_called()
        with self.assertRaises(ProtocolError):
            a.open_episode(episodes[0])
        with self.assertRaises(ProtocolError):
            a.open_episode(replace(episodes[1], instruction="changed"))

    def test_seed_and_limit_validation(self):
        a = module.make_metaworld({})
        for seed in (-1, 2**32, True, 1.5, "4042"):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                a.episodes(seed)
        for limit in (0, -1, False, "1", 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                a.episodes(4042, limit)

    def test_action_contract_exact(self):
        spec = module.make_metaworld({}).action_spec
        self.assertEqual(spec.validate((1, -1, 0, 0.5)), (1.0, -1.0, 0.0, 0.5))
        self.assertEqual(spec.size, 4)
        self.assertEqual(spec.control_hz, 80)
        for action in ((0, 0, 0), (0, 0, 0, 2), (True, 0, 0, 0), (float("nan"), 0, 0, 0),
                       (0, 0, 0, float("inf")), ("0", 0, 0, 0)):
            with self.subTest(action=action), self.assertRaises((ValueError, TypeError)):
                spec.validate(action)

    def test_pin_has_actual_code_and_assets(self):
        pin = runtime.package_pin()
        self.assertEqual(len(pin["files"]), 440)
        self.assertEqual(sum(row["path"].startswith("metaworld/assets/") for row in pin["files"]), 325)
        self.assertEqual(pin["file_inventory_sha256"], runtime.PACKAGE_INVENTORY_SHA256)

    def test_preflight_requires_optional_renderer_packaging_dependency(self):
        self.assertEqual(runtime.VERSIONS["packaging"], "26.2")
        def installed(name):
            if name == "packaging":
                raise runtime.importlib.metadata.PackageNotFoundError(name)
            return runtime.VERSIONS[name]
        with patch.object(runtime.importlib.metadata, "version", side_effect=installed):
            with self.assertRaisesRegex(CompatibilityError, "missing packaging"):
                runtime.verify_runtime()

    def test_package_tree_rejects_mutation_extra_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "__init__.py"
            path.write_bytes(b"native")
            pin = {"files": [{"path": "metaworld/__init__.py", "size_bytes": 6,
                               "sha256": hashlib.sha256(b"native").hexdigest()}]}
            runtime.verify_package_tree(root, pin)
            path.write_bytes(b"change")
            with self.assertRaises(CompatibilityError):
                runtime.verify_package_tree(root, pin)
            path.write_bytes(b"native")
            (root / "extra.py").write_bytes(b"extra")
            with self.assertRaises(CompatibilityError):
                runtime.verify_package_tree(root, pin)
            (root / "extra.py").unlink()
            (root / "alias.py").symlink_to(path)
            with self.assertRaises(CompatibilityError):
                runtime.verify_package_tree(root, pin)

    def test_pin_rejects_escape(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(CompatibilityError):
            runtime.verify_package_tree(Path(directory), {"files": [{"path": "metaworld/../secret"}]})


class FakeNative:
    def __init__(self):
        self.action_space = SimpleNamespace(low=np.full(4, -1.), high=np.full(4, 1.))
        self.unwrapped = self
        self.frame_skip = 5
        self.action_scale = 0.01
        self.max_path_length = 500
        self.model = SimpleNamespace(opt=SimpleNamespace(timestep=0.0025))
        self.actions = []
        self.resets = []
        self.success = 0.0
        self.truncated = False
        self.render_error = False
        self.frame = None

    def reset(self, seed):
        self.resets.append(seed)
        return {"secret_goal": [9, 9, 9]}, {"private": "drop"}

    def step(self, action):
        self.actions.append(action.copy())
        return {"goal": [9, 9, 9]}, 0.5, False, self.truncated, {"success": self.success, "goal": [9, 9, 9]}

    def render(self):
        if self.render_error:
            raise RuntimeError("renderer failed")
        if self.frame is not None:
            return self.frame
        return np.full(module.IMAGE_SHAPE, len(self.actions), dtype=np.uint8)


class FakeVector:
    def __init__(self):
        self.envs = [FakeNative() for _ in range(50)]
        self.closes = 0
        self.close_fails = False

    def close(self):
        self.closes += 1
        if self.close_fails:
            raise RuntimeError("native close failed")


@unittest.skipIf(np is None, "NumPy needed only for mocked RGB/native tests")
class MockedNative(unittest.TestCase):
    def setUp(self):
        self.adapter = module.make_metaworld({})
        self.session = self.adapter.open_episode(self.adapter.episodes(4042)[0])
        self.vector = FakeVector()
        self.native = self.vector.envs[43]
        self.verify_patch = patch.object(module, "verify_runtime", return_value={})
        self.factory_patch = patch.object(module, "_create_native", return_value=self.vector)
        self.verify_patch.start()
        self.factory = self.factory_patch.start()
        self.addCleanup(self.verify_patch.stop)
        self.addCleanup(self.factory_patch.stop)

    def test_reset_once_native_stabilization_separate_public_boundary(self):
        observation = self.session.reset()
        self.factory.assert_called_once_with(4042, self.adapter.catalog)
        self.assertEqual(self.native.resets, [4042])
        np.testing.assert_equal(self.native.actions, [np.zeros(4, dtype=np.float32)])
        self.assertEqual(observation.step, 0)
        self.assertEqual(set(observation.images), {"corner2"})
        self.assertIsNone(observation.state)
        self.assertEqual(observation.metadata, {})
        self.assertEqual(self.session.metrics()["native_steps_including_settle"], 1)
        with self.assertRaises(ProtocolError):
            self.session.reset()
        self.session.close()
        self.session.close()
        self.assertEqual(self.vector.closes, 1)

    def test_frames_copied_and_shape_not_silently_repaired(self):
        frame = np.zeros(module.IMAGE_SHAPE, dtype=np.uint8)
        observation = module.policy_observation(frame, 0, "task")
        frame[:] = 100
        self.assertTrue((observation.images["corner2"] == 0).all())
        for bad in (frame.astype(float), np.zeros((224, 224, 3), dtype=np.uint8), []):
            with self.subTest(type=type(bad)), self.assertRaises(ProtocolError):
                module.policy_observation(bad, 0, "task")

    def test_exact_asymmetric_pixels_for_both_orientations(self):
        frame = (np.arange(np.prod(module.IMAGE_SHAPE), dtype=np.uint32)
                 .reshape(module.IMAGE_SHAPE) % 251).astype(np.uint8)
        original = frame.copy()
        native = module.policy_observation(frame, 2, "task", "native").images["corner2"]
        rotated = module.policy_observation(frame, 2, "task", "rot180").images["corner2"]
        np.testing.assert_array_equal(native, original)
        np.testing.assert_array_equal(rotated, original[::-1, ::-1, :])
        self.assertFalse(np.array_equal(rotated, original))
        self.assertFalse(np.array_equal(rotated, original[::-1, :, :]))
        self.assertTrue(native.flags.c_contiguous and rotated.flags.c_contiguous)
        self.assertFalse(np.shares_memory(native, frame) or np.shares_memory(rotated, frame))
        frame[:] = 0
        np.testing.assert_array_equal(native, original)
        np.testing.assert_array_equal(rotated, original[::-1, ::-1, :])
        for value in (None, True, [], "flipud"):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                module.policy_observation(original, 0, "task", value)

    def test_orientation_routes_through_reset_controls_and_provenance(self):
        frame = np.zeros(module.IMAGE_SHAPE, dtype=np.uint8)
        frame[0, 1] = [17, 29, 43]
        frame[-2, -3] = [101, 127, 251]
        for orientation in ("native", "rot180"):
            with self.subTest(orientation=orientation):
                adapter = module.make_metaworld({"image_orientation": orientation})
                session = adapter.open_episode(adapter.episodes(4042)[0])
                self.native.frame = frame
                expected = frame if orientation == "native" else frame[::-1, ::-1, :]
                with patch.object(module, "atomic_write_json") as write, \
                        patch.object(session, "_log"):
                    # Capture private provenance without requiring media dependencies.
                    session.artifact_dir = Path("/not-written/mock-artifacts")
                    observe = session._observe
                    with patch.object(session, "_observe", return_value=None):
                        session.reset()
                    payload = write.call_args.args[1]
                    self.assertEqual(payload["image_orientation"], orientation)
                    self.assertEqual(payload["image_transform"], module.IMAGE_TRANSFORMS[orientation])
                    self.assertEqual(payload["protocol_version"], adapter.descriptor.protocol_version)
                    session.artifact_dir = None
                    np.testing.assert_array_equal(observe().images["corner2"], expected)
                    transition = session.step((0, 0, 0, 0))
                    np.testing.assert_array_equal(transition.observation.images["corner2"], expected)
                    session.close()

    def test_native_success_ends_once_and_no_scorer_leak(self):
        self.session.reset()
        self.native.success = np.float32(1.0)
        transition = self.session.step((0, 0, 0, 1))
        self.assertTrue(transition.terminated)
        self.assertTrue(self.session.metrics()["success"])
        self.assertEqual(transition.observation.step, 1)
        self.assertIsNone(transition.observation.state)
        self.assertEqual(transition.observation.metadata, {})
        self.assertEqual(self.session.metrics()["native_steps_including_settle"], 2)
        with self.assertRaises(ProtocolError):
            self.session.step((0, 0, 0, 0))

    def test_control_cap_excludes_settle(self):
        self.session.reset()
        self.session.step_count = 399
        transition = self.session.step((0, 0, 0, 0))
        self.assertTrue(transition.truncated)
        self.assertFalse(transition.terminated)
        self.assertEqual(self.session.metrics()["native_steps_including_settle"], 401)

    def test_native_early_truncation_preserved(self):
        self.session.reset()
        self.native.truncated = True
        self.assertTrue(self.session.step((0, 0, 0, 0)).truncated)

    def test_bad_action_never_reaches_native(self):
        self.session.reset()
        with self.assertRaises(ValueError):
            self.session.step((0, 0, 0, 2))
        self.assertEqual(len(self.native.actions), 1)

    def test_bad_native_score_poisoned(self):
        self.session.reset()
        self.native.success = float("nan")
        with self.assertRaises(ProtocolError):
            self.session.step((0, 0, 0, 0))
        with self.assertRaises(ProtocolError):
            self.session.step((0, 0, 0, 0))
        self.assertEqual(len(self.native.actions), 2)

    def test_render_failure_after_native_control_not_replayed(self):
        self.session.reset()
        self.native.render_error = True
        with self.assertRaises(RuntimeError):
            self.session.step((0, 0, 0, 0))
        self.assertEqual(self.session.step_count, 1)
        with self.assertRaises(ProtocolError):
            self.session.step((0, 0, 0, 0))

    def test_controller_drift_closes_entire_vector(self):
        self.native.frame_skip = 6
        with self.assertRaises(CompatibilityError):
            self.session.reset()
        self.assertEqual(self.vector.closes, 1)
        self.assertEqual(self.native.resets, [])

    def test_unexpected_goal_method_not_called(self):
        self.native.iterate_goal_position = lambda: self.fail("must not silently change reset")
        with self.assertRaises(CompatibilityError):
            self.session.reset()
        self.assertEqual(self.native.resets, [])

    def test_init_success_is_not_policy_success(self):
        self.native.success = 1.0
        with self.assertRaises(ProtocolError):
            self.session.reset()
        self.assertFalse(self.session.metrics()["success"])
        self.assertEqual(self.session.metrics()["settle_steps"], 1)
        self.assertEqual(self.vector.closes, 1)

    def test_artifact_finalization_disallows_more_actions(self):
        self.session.reset()
        self.assertEqual(self.session.artifacts(), {})
        with self.assertRaises(ProtocolError):
            self.session.step((0, 0, 0, 0))
        self.session.close()
        self.assertEqual(self.vector.closes, 1)

    def test_finalization_before_reset_prevents_native_creation(self):
        self.assertEqual(self.session.artifacts(), {})
        with self.assertRaises(ProtocolError):
            self.session.reset()
        self.factory.assert_not_called()

    def test_close_failure_stays_visible(self):
        self.session.reset()
        self.vector.close_fails = True
        with self.assertRaises(ProtocolError):
            self.session.close()
        with self.assertRaises(ProtocolError):
            self.session.close()
        self.assertEqual(self.vector.closes, 1)

    def test_malformed_native_success_rejected(self):
        for value in (None, {}, "1", [1], 2.0, float("inf")):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                module._native_success({"success": value})


if __name__ == "__main__":
    unittest.main()
