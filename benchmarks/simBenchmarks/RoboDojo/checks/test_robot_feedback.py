"""CPU-only checks for mandatory robot-only Direct v2 acknowledgements."""
from copy import deepcopy
import unittest

from benchkit.errors import ProtocolError
from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.robot_feedback import (
    SCHEMA, make_robot_feedback, validate_robot_feedback,
)


def state():
    value = [0.0] * 6 + [1.0] + [0.0] * 6 + [1.0]
    return value + [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0] * 2


def diagnostics():
    return {side: {"target_position_error_m": 0.03, "target_rotation_error_rad": 0.2,
        "proposed_joint_delta": [0.01] * 6,
        "bounded_task_delta": [0.02, 0.0, 0.0, 0.1, 0.0, 0.0],
        "method": "private-field-must-not-leak",
        "measured_fk_check": {"position_error_m": 1e-7,
            "rotation_error_rad": 1e-6, "passed": True}}
        for side in ("left", "right")}


def receipt():
    return make_robot_feedback(1, [0.0] * 6 + [1.0] + [0.0] * 6 + [1.0],
                               state(), diagnostics())


class RobotFeedbackChecks(unittest.TestCase):
    def test_projection_is_closed_and_bound_to_control_and_state(self):
        value = receipt()
        self.assertEqual(value["schema"], SCHEMA)
        self.assertNotIn("method", str(value))
        self.assertEqual(validate_robot_feedback(value, expected_control_target=1,
            expected_robot_state=state()), value)
        with self.assertRaises(ProtocolError):
            validate_robot_feedback(value, expected_control_target=2)
        changed = state()
        changed[0] = 0.5
        with self.assertRaises(ProtocolError):
            validate_robot_feedback(value, expected_robot_state=changed)

    def test_unknown_or_invalid_fields_fail_closed(self):
        transforms = (
            lambda value: value.update(hidden_score=100),
            lambda value: value.update(schema="robodojo.robot-control-feedback/v2"),
            lambda value: value.update(control_target=True),
            lambda value: value["executed_joint_command"].__setitem__(6, -0.1),
            lambda value: value["post_robot_state"].__setitem__(17, 0.0),
            lambda value: value["ik_diagnostics"]["left"]["measured_fk_check"].update(passed=False),
        )
        for transform in transforms:
            value = deepcopy(receipt())
            transform(value)
            with self.subTest(transform=transform), self.assertRaises(ProtocolError):
                validate_robot_feedback(value)

    def test_missing_private_conversion_fields_cannot_be_fabricated(self):
        broken = diagnostics()
        del broken["left"]["proposed_joint_delta"]
        with self.assertRaises(ProtocolError):
            make_robot_feedback(1, [0.0] * 14, state(), broken)


if __name__ == "__main__":
    unittest.main()
