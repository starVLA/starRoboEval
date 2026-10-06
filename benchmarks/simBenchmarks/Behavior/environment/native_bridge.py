"""Pure boundary helpers, independently testable without importing OmniGibson."""
import math
from collections.abc import Mapping
from numbers import Real

from benchkit.contracts import Observation
from benchkit.errors import ProtocolError
from benchmarks.simBenchmarks.Behavior.bench_server.protocol import (
    ACTION_SPEC, CAMERA_KEYS, CONTROLLER_INDICES, HORIZON, HUMAN_LENGTH,
    INSTRUCTION, INSTANCE, PROPRIO_FIELDS, STATE_NAMES,
)


def array(value):
    import numpy as np
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def public_observation(raw, step):
    import numpy as np
    if not isinstance(raw, Mapping):
        raise ProtocolError("BEHAVIOR native observation must be a mapping")
    images = {}
    for name, key in CAMERA_KEYS.items():
        rgb = array(raw.get(key))
        if rgb.shape != (224, 224, 4) or rgb.dtype != np.uint8:
            raise ProtocolError("BEHAVIOR DefaultWrapper requires native 224x224 uint8 RGBA")
        images[name] = np.array(rgb[..., :3], copy=True, order="C")
    state = array(raw.get("robot_r1::proprio"))
    if state.shape != (61,) or not np.issubdtype(state.dtype, np.floating) or not np.isfinite(state).all():
        raise ProtocolError("BEHAVIOR measured proprioception requires 61 finite floats")
    return Observation(step, INSTRUCTION, images, tuple(float(x) for x in state),
        {"state_provenance": "measured robot joints/body velocity and base-relative EEF kinematics"})


def metric_json(value):
    """Preserve nonfinite native ratios explicitly, never replace them with zero."""
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, Real):
        number = float(value)
        if math.isfinite(number):
            return number
        return {"native_nonfinite": "nan" if math.isnan(number) else ("+inf" if number > 0 else "-inf")}
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise ProtocolError("native metric keys must be strings")
        return {k: metric_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [metric_json(x) for x in value]
    if hasattr(value, "tolist"):
        return metric_json(value.tolist())
    raise ProtocolError("unsupported native metric value")


class ExternalAction:
    """One externally selected command; no inference, observation access or fallback."""
    def __init__(self, convert):
        self.convert = convert
        self.pending = None
        self.calls = 0

    def queue(self, values):
        if self.pending is not None:
            raise ProtocolError("unconsumed external action")
        self.pending = ACTION_SPEC.validate(values)

    def forward(self, obs):
        if self.pending is None:
            raise ProtocolError("native evaluator requested an unsupplied action")
        values, self.pending = self.pending, None
        self.calls += 1
        return self.convert(values)

    def reset(self):
        if self.pending is not None:
            raise ProtocolError("reset cannot discard a queued action")


def initialize_evaluator(evaluator):
    """Exactly the native CLI preparation, not one reset per actor action."""
    evaluator.reset()
    evaluator.load_task_instance(INSTANCE)
    evaluator.reset()


def validate_loaded(evaluator, sim):
    robot = evaluator.robot
    indices = {name: array(values).tolist() for name, values in robot.controller_action_idx.items()}
    # A zero-dimensional native camera controller may be present.
    effective = {name: values for name, values in indices.items() if values}
    if robot.action_dim != 23 or effective != CONTROLLER_INDICES:
        raise ProtocolError("loaded native action order differs from R1Pro23")
    if robot.model != "r1pro" or robot._grasping_mode != "assisted" or tuple(robot._proprio_obs) != PROPRIO_FIELDS:
        raise ProtocolError("loaded robot/sensors/grasp mechanism differs")
    if evaluator.human_stats["length"] != HUMAN_LENGTH:
        raise ProtocolError("native task human horizon changed")
    if evaluator.env.task._termination_config["max_steps"] != HORIZON:
        raise ProtocolError("loaded native timeout differs from resolved public cap")
    if not math.isclose(sim.get_physics_dt(), 1 / 120) or not math.isclose(sim.get_sim_step_dt(), 1 / 30):
        raise ProtocolError("native timing differs from declared 120/30 Hz")
    # The evaluator loads the hash-pinned native r1pro YAML. Inspect loaded
    # controller configuration as a second check, without mutating controllers.
    cfg = robot._controller_config
    for name in ("trunk", "arm_left", "arm_right"):
        item = cfg[name]
        if item["name"] != "JointController" or item["use_delta_commands"] or item["use_impedances"]:
            raise ProtocolError("native absolute joint controller mismatch")
    for name in ("gripper_left", "gripper_right"):
        if cfg[name]["name"] != "MultiFingerGripperController" or cfg[name]["mode"] != "smooth":
            raise ProtocolError("native gripper controller mismatch")
    if cfg["base"]["name"] != "HolonomicBaseJointController":
        raise ProtocolError("native base controller mismatch")
    return {"action_indices": indices, "action_dimension": 23, "proprio_dimension": len(STATE_NAMES),
            "native_horizon": HORIZON, "physics_hz": 120, "control_hz": 30,
            "grasping_mode": "assisted", "robot_model": robot.model}
