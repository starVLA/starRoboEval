"""CPU-only robot math/validation; these are not simulator or capability tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from benchmarks.simBenchmarks.RoboDojo.environment.eef_kinematics import (
    ArmFK, matrix_pose, pose_matrix, validate_pose7, validate_target,
)


NAMES = [f"joint{index}" for index in range(1, 7)]


def fixture_xml():
    """Six coplanar unit links; analytically known zero and quarter-turn FK."""
    links = "".join(f'<link name="{name}"/>' for name in ("base_link", *(f"link{i}" for i in range(1, 7))))
    joints = []
    for index, name in enumerate(NAMES, 1):
        parent = "base_link" if index == 1 else f"link{index - 1}"
        joints.append(f'<joint name="{name}" type="revolute"><parent link="{parent}"/>'
                      f'<child link="link{index}"/><origin xyz="1 0 0" rpy="0 0 0"/>'
                      '<axis xyz="0 0 1"/></joint>')
    return '<robot name="synthetic-six-joint-arm">' + links + "".join(joints) + '</robot>'


class EEFKinematicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "robot.urdf"
        self.path.write_text(fixture_xml())
        self.fk = ArmFK(self.path, NAMES)
        self.q = np.zeros(6)
        self.limits = np.tile([-3.14, 3.14], (6, 1))

    def read_bad(self, document, names=None):
        self.path.write_text(document)
        with self.assertRaises(ValueError):
            ArmFK(self.path, NAMES if names is None else names)

    def test_known_zero_fk(self):
        expected = np.eye(4)
        expected[0, 3] = 6
        np.testing.assert_allclose(self.fk.matrix(self.q), expected, atol=1e-14)

    def test_known_first_joint_quarter_turn(self):
        self.q[0] = np.pi / 2
        result = self.fk.matrix(self.q)
        np.testing.assert_allclose(result[:3, 3], [1, 5, 0], atol=1e-14)
        np.testing.assert_allclose(result[:3, :3], Rotation.from_euler("z", np.pi / 2).as_matrix(), atol=1e-14)

    def test_supplied_root_left_multiplies_fk(self):
        root = pose_matrix([0, 2, 3], [np.sqrt(0.5), 0, 0, np.sqrt(0.5)])
        np.testing.assert_allclose((root @ self.fk.matrix(self.q))[:3, 3], [0, 8, 3], atol=1e-14)

    def test_fixed_joint_chain_is_preserved(self):
        document = fixture_xml().replace('<link name="base_link"/>', '<link name="base_link"/><link name="mount"/>')
        document = document.replace('<parent link="base_link"/>', '<parent link="mount"/>')
        document = document.replace('</robot>', '<joint name="mount_joint" type="fixed"><parent link="base_link"/>'
                                    '<child link="mount"/><origin xyz="0 0 0.25"/></joint></robot>')
        self.path.write_text(document)
        np.testing.assert_allclose(ArmFK(self.path, NAMES).matrix(self.q)[:3, 3], [6, 0, 0.25])

    def test_continuous_joint_is_supported(self):
        self.path.write_text(fixture_xml().replace('type="revolute"', 'type="continuous"', 1))
        np.testing.assert_array_equal(ArmFK(self.path, NAMES).matrix(self.q), self.fk.matrix(self.q))

    def test_json_calibration_round_trip(self):
        calibration = json.loads(json.dumps(self.fk.to_calibration(), allow_nan=False))
        recovered = ArmFK.from_calibration(calibration)
        q = np.linspace(-0.3, 0.3, 6)
        np.testing.assert_array_equal(self.fk.matrix(q), recovered.matrix(q))
        self.assertEqual(calibration, recovered.to_calibration())

    def test_calibration_mutation_does_not_mutate_fk(self):
        calibration = self.fk.to_calibration()
        calibration["chain"][0]["origin"][0][3] = 100
        np.testing.assert_allclose(self.fk.matrix(self.q)[:3, 3], [6, 0, 0])
        with self.assertRaises(ValueError):
            self.fk.chain[0].origin[0, 3] = 100

    def test_calibration_extra_missing_and_wrong_schema(self):
        for change in ({"schema": "other"}, {"scene_objects": []}, {"chain": []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ArmFK.from_calibration({**self.fk.to_calibration(), **change})
        data = self.fk.to_calibration()
        del data["base"]
        with self.assertRaises(ValueError):
            ArmFK.from_calibration(data)

    def test_calibration_rejects_malformed_chain(self):
        changes = [{"kind": "prismatic"}, {"parent": "disconnected"}, {"axis": [0, 0, 0]},
                   {"child": "base_link"}, {"origin": np.zeros((4, 4)).tolist()}, {"name": "joint2"}]
        for change in changes:
            data = self.fk.to_calibration()
            data["chain"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                ArmFK.from_calibration(data)

    def test_pose_conversion_wxyz(self):
        transform = pose_matrix([1, 2, 3], [np.sqrt(0.5), 0, 0, np.sqrt(0.5)])
        np.testing.assert_allclose(transform[:3, :3] @ [1, 0, 0], [0, 1, 0], atol=1e-14)
        result = matrix_pose(transform)
        np.testing.assert_allclose(pose_matrix(**result), transform, atol=1e-14)

    def test_pose7_strict_validation(self):
        malformed = [np.zeros(7), [0, 0, 0, 2, 0, 0, 0], [0, 0, 0, 1, 0, 0],
                     [0, 0, 0, 1, 0, 0, np.nan], [0, 0, 0, 1, 0, 0, np.inf],
                     [False, 0, 0, 1, 0, 0, 0], ["0", 0, 0, 1, 0, 0, 0], np.ones(7, complex)]
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_pose7(value)
        validate_pose7([0, 0, 0, 1 + 0.5e-4, 0, 0, 0])
        with self.assertRaises(ValueError):
            validate_pose7([0, 0, 0, 1 + 2e-4, 0, 0, 0])

    def test_matrix_pose_rejects_nonrigid(self):
        matrices = [np.ones((4, 4)), np.eye(3), np.eye(4) * 2]
        reflection = np.eye(4)
        reflection[0, 0] = -1
        matrices.append(reflection)
        for value in matrices:
            with self.subTest(value=value), self.assertRaises(ValueError):
                matrix_pose(value)

    def test_decision_target_bound_is_euclidean(self):
        origin = [0, 0, 0, 1, 0, 0, 0]
        validate_target(origin, [0.05, 0, 0, 1, 0, 0, 0])
        with self.assertRaises(ValueError):
            validate_target(origin, [0.04, 0.04, 0, 1, 0, 0, 0])
        with self.assertRaises(ValueError):
            validate_target(origin, [0.050001, 0, 0, 1, 0, 0, 0])

    def test_decision_orientation_bound_and_quaternion_sign(self):
        origin = [0, 0, 0, 1, 0, 0, 0]
        validate_target(origin, [0, 0, 0, -1, 0, 0, 0])
        for angle, valid in ((0.35, True), (0.3501, False)):
            pose = [0, 0, 0, np.cos(angle / 2), 0, 0, np.sin(angle / 2)]
            if valid:
                validate_target(origin, pose)
            else:
                with self.assertRaises(ValueError):
                    validate_target(origin, pose)

    def test_zero_error_holds_measured_float32_joints(self):
        q = np.linspace(-0.2, 0.2, 6, dtype=np.float32)
        target = matrix_pose(self.fk.matrix(q))
        result, diagnostic = self.fk.bounded_target(q, self.limits, np.eye(4), target)
        self.assertEqual(result.dtype, np.float32)
        np.testing.assert_array_equal(result, q)
        self.assertLess(np.linalg.norm(diagnostic["bounded_task_delta"]), 1e-14)
        self.assertFalse(diagnostic["physical_tracking_verified"])
        json.dumps(diagnostic, allow_nan=False)

    def test_translation_and_rotation_caps(self):
        target = matrix_pose(pose_matrix([6, 1, 0], [np.cos(0.4), 0, 0, np.sin(0.4)]))
        result, diagnostic = self.fk.bounded_target(self.q, self.limits, np.eye(4), target)
        np.testing.assert_allclose(np.linalg.norm(diagnostic["bounded_task_delta"][:3]), 0.02)
        np.testing.assert_allclose(np.linalg.norm(diagnostic["bounded_task_delta"][3:]), 0.1)
        self.assertTrue(np.all(np.abs(result.astype(float) - self.q) <= 0.05))

    def test_reference_numeric_fixture(self):
        # Independent algebra for six collinear revolute z axes at q=0.
        # The reference uses finite differences, not the exact analytic Jacobian.
        epsilon = 1e-5
        jacobian = np.zeros((6, 6))
        for i in range(6):
            remaining = 5 - i
            jacobian[0, i] = remaining * (np.cos(epsilon) - 1) / epsilon
            jacobian[1, i] = remaining * np.sin(epsilon) / epsilon
            jacobian[5, i] = 1
        error = np.array([0, 0.01, 0, 0, 0, 0.02])
        expected = jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + 0.05**2 * np.eye(6), error)
        target = {"position": [6, 0.01, 0], "quaternion_wxyz": [np.cos(0.01), 0, 0, np.sin(0.01)]}
        result, diagnostic = self.fk.bounded_target(self.q, self.limits, np.eye(4), target)
        np.testing.assert_allclose(result, expected.astype(np.float32), rtol=1e-6, atol=1e-9)
        np.testing.assert_allclose(diagnostic["bounded_task_delta"], error, atol=1e-14)

    def test_joint_limits_are_projected_without_violating_delta(self):
        self.limits[:, 0], self.limits[:, 1] = -1e-4, 1e-4
        result, _ = self.fk.bounded_target(self.q, self.limits, np.eye(4),
                                         {"position": [6, 0.02, 0], "quaternion_wxyz": [1, 0, 0, 0]})
        self.assertTrue(np.all(result >= self.limits[:, 0]))
        self.assertTrue(np.all(result <= self.limits[:, 1]))

    def test_outward_float32_rounding_stays_inside_limits(self):
        self.limits[:, 1] = 0.0001000000001
        result, _ = self.fk.bounded_target(self.q, self.limits, np.eye(4),
                                         {"position": [6, 0.05, 0], "quaternion_wxyz": [1, 0, 0, 0]})
        self.assertTrue(np.all(result.astype(float) <= self.limits[:, 1]))

    def test_invalid_current_state_limits_and_root(self):
        target = matrix_pose(self.fk.matrix(self.q))
        calls = [(np.ones(5), self.limits, np.eye(4)), (np.full(6, np.nan), self.limits, np.eye(4)),
                 (np.ones(6) * 4, self.limits, np.eye(4)), (self.q, self.limits[:, ::-1], np.eye(4)),
                 (self.q, np.ones((6, 3)), np.eye(4)), (self.q, np.full((6, 2), np.inf), np.eye(4)),
                 (self.q, self.limits, np.zeros((4, 4)))]
        for q, limits, root in calls:
            with self.subTest(q=q, limits=limits, root=root), self.assertRaises(ValueError):
                self.fk.bounded_target(q, limits, root, target)

    def test_target_has_no_extra_action_fields(self):
        target = matrix_pose(self.fk.matrix(self.q))
        for bad in ({**target, "gripper_closed": True}, {"position": [0, 0, 0]}, None):
            with self.subTest(target=bad), self.assertRaises(ValueError):
                self.fk.bounded_target(self.q, self.limits, np.eye(4), bad)

    def test_dls_does_not_mutate_inputs(self):
        q, limits, root = self.q.copy(), self.limits.copy(), np.eye(4)
        target = {"position": [6, 0.01, 0], "quaternion_wxyz": [1, 0, 0, 0]}
        before = deepcopy(target)
        self.fk.bounded_target(q, limits, root, target)
        np.testing.assert_array_equal(q, self.q)
        np.testing.assert_array_equal(limits, self.limits)
        np.testing.assert_array_equal(root, np.eye(4))
        self.assertEqual(before, target)

    def test_rejects_dtd_and_entity(self):
        self.read_bad('<!DOCTYPE robot [<!ENTITY a "hi">]>' + fixture_xml())

    def test_rejects_malformed_xml_and_missing_links(self):
        self.read_bad('<robot>')
        self.read_bad(fixture_xml().replace('<link name="link6"/>', ''))

    def test_rejects_duplicate_name_child_origin_axis(self):
        self.read_bad(fixture_xml().replace('name="joint2"', 'name="joint1"'))
        self.read_bad(fixture_xml().replace('<child link="link2"/>', '<child link="link1"/>'))
        self.read_bad(fixture_xml().replace('<axis xyz="0 0 1"/>', '<axis xyz="0 0 1"/><axis xyz="0 1 0"/>', 1))
        self.read_bad(fixture_xml().replace('<origin xyz="1 0 0" rpy="0 0 0"/>', '<origin/><origin/>', 1))

    def test_rejects_bad_axis_origin_and_mimic(self):
        for axis in ('0 0 0', '0 0 2', '0 nan 1', '0 0 1 2'):
            self.read_bad(fixture_xml().replace('axis xyz="0 0 1"', f'axis xyz="{axis}"', 1))
        self.read_bad(fixture_xml().replace('xyz="1 0 0"', 'xyz="inf 0 0"', 1))
        self.read_bad(fixture_xml().replace('</joint>', '<mimic joint="joint2"/></joint>', 1))

    def test_rejects_cycle_and_disconnected_chain(self):
        self.read_bad(fixture_xml().replace('<parent link="base_link"/>', '<parent link="link6"/>'))
        self.read_bad(fixture_xml().replace('<parent link="link3"/>', '<parent link="base_link"/>'))

    def test_rejects_wrong_joint_order_count_and_type(self):
        self.read_bad(fixture_xml(), list(reversed(NAMES)))
        self.read_bad(fixture_xml(), NAMES[:5])
        self.read_bad(fixture_xml(), NAMES[:5] + [NAMES[0]])
        self.read_bad(fixture_xml().replace('type="revolute"', 'type="prismatic"', 1))

    def test_unrelated_gripper_chain_is_not_included(self):
        document = fixture_xml().replace('</robot>', '<link name="finger"/><joint name="finger_joint" type="prismatic">'
                                          '<parent link="link6"/><child link="finger"/><axis xyz="0 1 0"/></joint></robot>')
        self.path.write_text(document)
        selected = ArmFK(self.path, NAMES)
        self.assertEqual(len(selected.chain), 6)


if __name__ == "__main__":
    unittest.main()
