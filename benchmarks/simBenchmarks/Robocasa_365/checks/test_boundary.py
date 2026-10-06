"""Boundary validation without importing the simulator or NumPy."""

import unittest

from benchmarks.simBenchmarks.Robocasa_365.environment.native_boundary import (
    ACTION_SPEC, CAMERAS, NEUTRAL_ACTION, action_dictionary, policy_observation,
)
from benchkit.errors import ProtocolError


class Frame:
    dtype = "uint8"
    shape = (256, 256, 3)

    def copy(self):
        return Frame()


class BoundaryChecks(unittest.TestCase):
    def test_native_state_and_metadata_cannot_cross_observation_boundary(self):
        raw = {"video." + key: Frame() for key in CAMERAS}
        raw.update({"annotation.human.task_description": "Open the drawer.",
                    "state.base_position": [1, 2, 3], "success": True,
                    "object_pose": [4, 5, 6], "seed": 17})
        observation = policy_observation(raw, 0)
        self.assertEqual(tuple(observation.images), CAMERAS)
        self.assertIsNone(observation.state)
        self.assertEqual(observation.metadata, {})
        self.assertIsNot(observation.images[CAMERAS[0]], raw["video." + CAMERAS[0]])

    def test_fractional_discrete_controls_are_rejected_before_numpy_import(self):
        for index in (6, 11):
            action = list(NEUTRAL_ACTION)
            action[index] = 0.5
            with self.assertRaises(ValueError):
                action_dictionary(action)

    def test_wrong_frame_or_missing_instruction_fails(self):
        raw = {"video." + key: Frame() for key in CAMERAS}
        with self.assertRaises(ProtocolError):
            policy_observation(raw, 0)
        raw["annotation.human.task_description"] = "Open the drawer."
        raw["video." + CAMERAS[0]].shape = (3, 256, 256)
        with self.assertRaises(ProtocolError):
            policy_observation(raw, 0)

    def test_invalid_actions_are_not_clipped(self):
        self.assertEqual(ACTION_SPEC.validate(NEUTRAL_ACTION), NEUTRAL_ACTION)
        for action in ((0,) * 29, (float("nan"),) + (0,) * 11, (2,) + (0,) * 11):
            with self.assertRaises(ValueError):
                ACTION_SPEC.validate(action)


if __name__ == "__main__":
    unittest.main()
