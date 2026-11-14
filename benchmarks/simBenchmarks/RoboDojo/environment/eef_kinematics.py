"""Protocol-fixed robot-only FK and bounded local DLS; no simulator access.

The caller verifies its pinned robot URDF, supplies measured joints, native soft
joint limits and the robot-base transform, and owns native execution/ACKs. This
module does not inspect objects, plan collisions, advance physics or choose a
task target. Calibration serialization contains only the declared robot chain.

The local DLS mathematics derive from GPT-as-Policy, commit
8f3d362b077d8efb77e2a7274d5b2c20e2243846,
hybrid_rollout/robodojo/robodojo_server/{kinematics,action_edit_kinematics}.py.
Upstream license, retained for this derivative:

MIT License

Copyright (c) 2026 Yu-Mool Shu and Lipxin Zheng

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation


CALIBRATION_SCHEMA = "robodojo.robot-only-six-joint-chain/v1"
STRICT_DLS = "rsi-strict-float32/v1"
REFERENCE_DLS = "gpt-as-policy-float32/v1"
JOINT_COUNT = 6
QUATERNION_TOLERANCE = 1e-4
JACOBIAN_EPSILON = 1e-5
DAMPING = 0.05
MAX_TRANSLATION_STEP = 0.02
MAX_ROTATION_STEP = 0.1
MAX_JOINT_STEP = 0.05
MAX_URDF_BYTES = 8 * 1024 * 1024
MAX_CHAIN_JOINTS = 64


def _finite_array(value, shape, label):
    """Reject coercible strings, booleans, complex/object arrays and non-finite data."""
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "fiu":
            raise ValueError(f"{label} must contain real numeric values")
    else:
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, (list, tuple)):
                pending.extend(item)
            elif isinstance(item, (bool, np.bool_)) or not isinstance(item, Real):
                raise ValueError(f"{label} must contain real numeric values")
    try:
        array = np.array(value, dtype=np.float64, copy=True)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"Invalid {label}") from error
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{label} must have finite shape {shape}")
    return array


def validate_pose7(value):
    """Return a copied finite [x,y,z,w,x,y,z] pose, requiring a unit quaternion."""
    result = _finite_array(value, (7,), "pose")
    norm = float(np.linalg.norm(result[3:]))
    if not np.isfinite(norm) or abs(norm - 1.0) > QUATERNION_TOLERANCE:
        raise ValueError("Pose requires a unit wxyz quaternion")
    return result


def pose_matrix(position, quaternion_wxyz):
    """Convert an explicitly validated wxyz pose to a rigid 4x4 transform."""
    position = _finite_array(position, (3,), "position")
    quaternion = _finite_array(quaternion_wxyz, (4,), "quaternion_wxyz")
    pose = validate_pose7(np.r_[position, quaternion])
    result = np.eye(4)
    result[:3, :3] = Rotation.from_quat(pose[[4, 5, 6, 3]]).as_matrix()
    result[:3, 3] = pose[:3]
    return result


def _rigid_matrix(value, label="transform"):
    result = _finite_array(value, (4, 4), label)
    rotation = result[:3, :3]
    if (not np.array_equal(result[3], [0.0, 0.0, 0.0, 1.0])
        or not np.allclose(rotation.T @ rotation, np.eye(3), rtol=0, atol=1e-6)
        or not np.isclose(np.linalg.det(rotation), 1.0, rtol=0, atol=1e-6)):
        raise ValueError(f"{label} must be a proper rigid transform")
    return result


def _name(value, label):
    if not isinstance(value, str) or not value or len(value) > 256 or any(c.isspace() for c in value):
        raise ValueError(f"Invalid {label}")
    return value


def _joint_names(value):
    if not isinstance(value, (list, tuple)) or len(value) != JOINT_COUNT:
        raise ValueError("Exactly six declared joint names are required")
    result = tuple(_name(name, "joint name") for name in value)
    if len(set(result)) != JOINT_COUNT:
        raise ValueError("Duplicate declared joint names")
    return result


def _vector_attribute(element, key, default):
    text = default if element is None else element.get(key, default)
    fields = text.split()
    if len(fields) != 3:
        raise ValueError(f"URDF {key} requires exactly three numbers")
    try:
        return _finite_array([float(item) for item in fields], (3,), f"URDF {key}")
    except (ValueError, OverflowError) as error:
        raise ValueError(f"Invalid URDF {key}") from error


def _one(element, tag, *, required=False):
    values = element.findall(tag)
    if len(values) > 1 or (required and not values):
        raise ValueError(f"URDF requires {'one' if required else 'at most one'} {tag}")
    return values[0] if values else None


@dataclass(frozen=True)
class _Joint:
    name: str
    kind: str
    parent: str
    child: str
    origin: np.ndarray
    axis: np.ndarray


class ArmFK:
    """Declared six-joint URDF chain. No native runtime or scene dependency."""

    def __init__(self, urdf_path, joint_names, base="base_link", tip="link6"):
        names = _joint_names(joint_names)
        base, tip = _name(base, "base link"), _name(tip, "tip link")
        path = Path(urdf_path)
        with path.open("rb") as stream:
            document = stream.read(MAX_URDF_BYTES + 1)
        if len(document) > MAX_URDF_BYTES:
            raise ValueError("Robot URDF exceeds the bounded parser size")
        # ElementTree does not fetch external entities; also reject DTD/entity
        # declarations explicitly rather than accepting internal expansion.
        upper = document.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper or b"\x00" in document:
            raise ValueError("DTD, entity declarations and UTF-16 URDF are unsupported")
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise ValueError("Malformed robot URDF") from error
        if root.tag != "robot":
            raise ValueError("Expected an unnamespaced URDF robot")
        links = [_name(link.get("name"), "URDF link") for link in root.findall("link")]
        if len(links) != len(set(links)) or base not in links or tip not in links or base == tip:
            raise ValueError("Duplicate/missing URDF base or tip links")
        edges, seen_names = {}, set()
        for element in root.findall("joint"):
            name = _name(element.get("name"), "URDF joint")
            parent = _name(_one(element, "parent", required=True).get("link"), "parent link")
            child = _name(_one(element, "child", required=True).get("link"), "child link")
            if (name in seen_names or child in edges or parent == child
                or parent not in links or child not in links):
                raise ValueError("Duplicate or invalid URDF joint/link edge")
            seen_names.add(name)
            edges[child] = (element, name, parent, child)
        chain, seen_links, current = [], set(), tip
        while current != base:
            if current in seen_links or current not in edges or len(chain) >= MAX_CHAIN_JOINTS:
                raise ValueError("Cyclic, disconnected or oversized URDF chain")
            seen_links.add(current)
            element, name, parent, child = edges[current]
            kind = element.get("type")
            if kind not in ("fixed", "revolute", "continuous") or element.find("mimic") is not None:
                raise ValueError("Arm chain permits only independent fixed/revolute/continuous joints")
            origin_element = _one(element, "origin")
            xyz = _vector_attribute(origin_element, "xyz", "0 0 0")
            rpy = _vector_attribute(origin_element, "rpy", "0 0 0")
            origin = np.eye(4)
            origin[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()
            origin[:3, 3] = xyz
            axis = _vector_attribute(_one(element, "axis"), "xyz", "1 0 0")
            chain.append(_Joint(name, kind, parent, child, origin, axis))
            current = parent
        self._initialize(names, base, tip, tuple(reversed(chain)))

    def _initialize(self, names, base, tip, chain):
        if not 1 <= len(chain) <= MAX_CHAIN_JOINTS:
            raise ValueError("Invalid robot chain length")
        self.names, self.base, self.tip = _joint_names(names), _name(base, "base link"), _name(tip, "tip link")
        moving, joint_names, visited = [], set(), {self.base}
        current = self.base
        checked = []
        for joint in chain:
            name, parent, child = (_name(joint.name, "joint"), _name(joint.parent, "parent"),
                                   _name(joint.child, "child"))
            if name in joint_names or parent != current or child in visited:
                raise ValueError("Robot calibration has duplicate, cyclic or disconnected edges")
            if joint.kind not in ("fixed", "revolute", "continuous"):
                raise ValueError("Unsupported arm joint type")
            origin, axis = _rigid_matrix(joint.origin, "joint origin"), _finite_array(joint.axis, (3,), "joint axis")
            if not np.isclose(np.linalg.norm(axis), 1.0, rtol=0, atol=1e-6):
                raise ValueError("Robot joint axis must be unit length")
            origin.setflags(write=False)
            axis.setflags(write=False)
            checked.append(_Joint(name, joint.kind, parent, child, origin, axis))
            if joint.kind != "fixed":
                moving.append(name)
            joint_names.add(name)
            visited.add(child)
            current = child
        if current != self.tip or tuple(moving) != self.names:
            raise ValueError("Robot chain differs from the ordered six declared joints and tip")
        self.chain = tuple(checked)

    def to_calibration(self):
        """Serialize robot-only geometry, not runtime object state or a source attestation."""
        return {"schema": CALIBRATION_SCHEMA, "base": self.base, "tip": self.tip,
                "joint_names": list(self.names), "chain": [
                    {"name": joint.name, "kind": joint.kind, "parent": joint.parent, "child": joint.child,
                     "origin": joint.origin.tolist(), "axis": joint.axis.tolist()} for joint in self.chain]}

    @classmethod
    def from_calibration(cls, value):
        """Load the exact bounded calibration schema without filesystem access."""
        if (not isinstance(value, dict) or set(value) != {"schema", "base", "tip", "joint_names", "chain"}
            or value["schema"] != CALIBRATION_SCHEMA or not isinstance(value["chain"], list)
            or not 1 <= len(value["chain"]) <= MAX_CHAIN_JOINTS):
            raise ValueError("Invalid robot calibration schema")
        chain = []
        for row in value["chain"]:
            if not isinstance(row, dict) or set(row) != {"name", "kind", "parent", "child", "origin", "axis"}:
                raise ValueError("Invalid robot calibration joint")
            chain.append(_Joint(**row))
        instance = cls.__new__(cls)
        instance._initialize(value["joint_names"], value["base"], value["tip"], chain)
        return instance

    def matrix(self, q):
        """Robot-base to tip FK for the declared joint order, not environment pose."""
        values = dict(zip(self.names, _finite_array(q, (JOINT_COUNT,), "arm joints")))
        result = np.eye(4)
        with np.errstate(over="raise", invalid="raise"):
            try:
                for joint in self.chain:
                    motion = np.eye(4)
                    if joint.kind != "fixed":
                        motion[:3, :3] = Rotation.from_rotvec(joint.axis * values[joint.name]).as_matrix()
                    result = result @ joint.origin @ motion
            except (FloatingPointError, ValueError) as error:
                raise ValueError("Robot FK arithmetic is invalid") from error
        return _rigid_matrix(result, "FK result")

    def bounded_target(self, q, limits, root, target, *, execution_mode=STRICT_DLS):
        """One reference DLS update; target choice and real control stay with caller.

        Recompute after each real ACK. Historical strict mode requires measured
        joints inside native limits and rounds float32 bounds inward. Reference
        mode exactly uses the nonempty limits/inter-step intersection and the
        upstream np.clip(...).astype(np.float32), including its rounding.
        """
        if execution_mode not in (STRICT_DLS, REFERENCE_DLS):
            raise ValueError("Unknown DLS execution mode")
        q = _finite_array(q, (JOINT_COUNT,), "arm joints")
        limits = _finite_array(limits, (JOINT_COUNT, 2), "native joint limits")
        root = _rigid_matrix(root, "robot-base transform")
        if (np.any(limits[:, 0] > limits[:, 1]) or (execution_mode == STRICT_DLS
            and (np.any(q < limits[:, 0]) or np.any(q > limits[:, 1])))):
            raise ValueError("Current joints are outside ordered native limits")
        if not isinstance(target, dict) or set(target) != {"position", "quaternion_wxyz"}:
            raise ValueError("DLS target requires only position and quaternion_wxyz")
        goal = pose_matrix(target["position"], target["quaternion_wxyz"])
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            try:
                now = root @ self.matrix(q)
                translation = goal[:3, 3] - now[:3, 3]
                rotation = Rotation.from_matrix(goal[:3, :3] @ now[:3, :3].T).as_rotvec()

                def bounded(vector, cap):
                    return vector * min(1.0, cap / max(float(np.linalg.norm(vector)), 1e-12))

                error = np.r_[bounded(translation, MAX_TRANSLATION_STEP), bounded(rotation, MAX_ROTATION_STEP)]
                jacobian = np.zeros((6, JOINT_COUNT))
                for index in range(JOINT_COUNT):
                    shifted = q.copy()
                    shifted[index] += JACOBIAN_EPSILON
                    nxt = root @ self.matrix(shifted)
                    jacobian[:3, index] = (nxt[:3, 3] - now[:3, 3]) / JACOBIAN_EPSILON
                    jacobian[3:, index] = Rotation.from_matrix(nxt[:3, :3] @ now[:3, :3].T).as_rotvec() / JACOBIAN_EPSILON
                delta = jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + DAMPING**2 * np.eye(6), error)
                low = np.maximum(limits[:, 0], q - MAX_JOINT_STEP)
                high = np.minimum(limits[:, 1], q + MAX_JOINT_STEP)
                if np.any(low > high):
                    raise ValueError("Joint outside bounded valid interval")
                result = np.clip(q + delta, low, high).astype(np.float32)
            except (FloatingPointError, np.linalg.LinAlgError, ValueError) as problem:
                raise ValueError("Local DLS arithmetic is invalid") from problem
        # Casting to float32 can round an exact bound outward. Move that one ULP
        # inward; do not let serialization violate the declared hard interval.
        if execution_mode == STRICT_DLS:
            for index in range(JOINT_COUNT):
                if float(result[index]) < low[index]:
                    result[index] = np.nextafter(result[index], np.float32(np.inf))
                if float(result[index]) > high[index]:
                    result[index] = np.nextafter(result[index], np.float32(-np.inf))
        if (not np.isfinite(result).all() or (execution_mode == STRICT_DLS
            and (np.any(result.astype(float) < low) or np.any(result.astype(float) > high)))):
            raise ValueError("No finite float32 command exists in the bounded joint interval")
        diagnostics = {"target_position_error_m": float(np.linalg.norm(translation)),
                       "target_rotation_error_rad": float(np.linalg.norm(rotation)),
                       "proposed_joint_delta": (result.astype(float) - q).tolist(),
                       "bounded_task_delta": error.tolist(),
                       "method": "robot_only_numerical_jacobian_dls", "physical_tracking_verified": False}
        return result, diagnostics
