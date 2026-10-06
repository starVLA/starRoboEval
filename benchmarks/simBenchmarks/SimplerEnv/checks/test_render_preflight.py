"""Synthetic preflight checks; no native simulator, reset or policy attempt."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

try:
    import numpy as np
except ImportError:
    np = None

SCRIPT = Path(__file__).resolve().parents[1] / "environment/verify_environment.py"
SPEC = importlib.util.spec_from_file_location("simpler_render_preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@unittest.skipIf(np is None, "NumPy is available in the native environment")
class CachedRenderPreflightChecks(unittest.TestCase):
    def check(self, color, rgb=None, robot="google_robot_static"):
        calls = []

        def cached_images(*, take_picture):
            self.assertIs(take_picture, False)
            calls.append(take_picture)
            return {"Color": color}

        camera = SimpleNamespace(get_images=cached_images)
        native = SimpleNamespace(robot_uid=robot, _cameras={
            "overhead_camera": camera, "3rd_view_camera": camera,
        })
        # These objects expose no step/reset/render/scorer methods.
        env = SimpleNamespace(unwrapped=native)
        rgb = np.arange(18, dtype=np.uint8).reshape(2, 3, 3) if rgb is None else rgb
        result = MODULE.check_cached_render(env, rgb)
        self.assertEqual(calls, [False])
        return result

    def test_color_passes_through_cached_read_for_both_robots(self):
        for robot, camera in (("google_robot_static", "overhead_camera"),
                              ("widowx", "3rd_view_camera")):
            with self.subTest(robot=robot):
                result = self.check(np.ones((2, 3, 4), dtype=np.float32), robot=robot)
                self.assertEqual(result["camera"], camera)
                self.assertEqual(result["cached_raw_rgb_nonzero_values"], 18)
                self.assertEqual(result["extra_picture_acquisitions"], 0)
                self.assertEqual(result["extra_scorer_requests"], 0)

    def test_nonflat_photo_does_not_hide_black_native_rgb(self):
        raw = np.zeros((2, 3, 4), dtype=np.float32)
        raw[..., 3] = 1  # Alpha must not make a black RGB render look valid.
        with self.assertRaisesRegex(ValueError, "entirely zero"):
            self.check(raw)

    def test_nonfinite_raw_rgb_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            raw = np.ones((2, 3, 4), dtype=np.float32)
            raw[0, 0, 0] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "nonfinite"):
                self.check(raw)

    def test_raw_shape_and_dtype_rejected(self):
        for raw in (np.ones((2, 3, 3)), np.ones((3, 2, 4)),
                    np.full((2, 3, 4), "bad", dtype=object)):
            with self.subTest(shape=raw.shape), self.assertRaises(ValueError):
                self.check(raw)

    def test_invalid_public_rgb_rejected(self):
        for rgb in (np.ones((2, 3, 3)), np.zeros((2, 3, 4), dtype=np.uint8),
                    np.zeros((0, 3, 3), dtype=np.uint8)):
            with self.subTest(shape=rgb.shape), self.assertRaises(ValueError):
                self.check(np.ones((2, 3, 4)), rgb=rgb)

    def test_unknown_robot_mapping_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown native robot"):
            self.check(np.ones((2, 3, 4)), robot="unknown")


if __name__ == "__main__":
    unittest.main()
