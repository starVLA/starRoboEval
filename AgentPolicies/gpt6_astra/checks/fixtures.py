"""Offline public robot contracts and ACK fixtures; no model or simulator."""
from copy import deepcopy
from dataclasses import replace

from benchkit.contracts import (ActionSpec, BenchmarkDescriptor, ControlAcknowledgement,
    EpisodeContext, ExecutionFeedback, ObservationSpec, PolicyEpisodeSpec)
# Test-only historical EEF declarations, not an active method dependency.
POSE_FIELDS = ("x_m", "y_m", "z_m", "qw", "qx", "qy", "qz")
STATE_NAMES = tuple(name for side in ("left", "right") for name in (
    *(f"{side}_joint{i}_rad" for i in range(1, 7)), f"{side}_gripper_open_01")) + tuple(
    f"{side}_eef_{field}" for side in ("left", "right") for field in POSE_FIELDS)
ACTION_NAMES = tuple(name for side in ("left", "right") for name in (
    *(f"{side}_eef_{field}" for field in POSE_FIELDS), f"{side}_gripper_open_01"))
FEEDBACK_SCHEMA = "robodojo.robot-control-feedback/v1"

def context(**overrides):
    return replace(EpisodeContext(
        benchmark=BenchmarkDescriptor("fixture", "test", "test", "private-source-do-not-send"),
        episode=PolicyEpisodeSpec("opaque", "fixture-task", "Move to the target"),
        observation_spec=ObservationSpec(),
        action_spec=ActionSpec("native-test", 2, names=("x", "grip"), low=(-1, -1), high=(1, 1)),
        max_steps=10, max_policy_calls=10, replan_interval=2), **overrides)


def eef_context():
    return EpisodeContext(BenchmarkDescriptor("private-benchmark", "v", "private-protocol", "private-source"),
        PolicyEpisodeSpec("private-opaque-marker", "private-task-marker", "Sort objects then return the arms"),
        ObservationSpec(cameras=("cam_head", "cam_left_wrist", "cam_right_wrist"), state_names=STATE_NAMES,
                        modalities=("rgb", "language", "proprioception")),
        ActionSpec("robodojo_dual_x5_world_eef_target_16", 16, names=ACTION_NAMES, control_hz=25.0,
                   frame="world-frame measured ARX X5 link6 poses, not a gripper-tip offset",
                   rotation="absolute unit quaternion wxyz for each arm",
                   gripper="absolute continuous [0,1], 0 closed / 1 open; pinned native conversion"),
        max_steps=1100, max_policy_calls=None, replan_interval=5)


STATE = [0.0] * 14 + [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0] * 2


def robot_payload(step, state=None):
    diagnostic = {"target_position_error_m": .03, "target_rotation_error_rad": .2,
        "proposed_joint_delta": [.001] * 6, "bounded_task_delta": [.001] * 6,
        "measured_fk_check": {"position_error_m": .0001, "rotation_error_rad": .001, "passed": True}}
    return {"schema": FEEDBACK_SCHEMA, "control_target": step, "diagnostic_phase": "pre_control",
            "executed_joint_command": [.001] * 6 + [1.0] + [.001] * 6 + [0.0],
            "post_robot_state": list(STATE if state is None else state),
            "ik_diagnostics": {"left": deepcopy(diagnostic), "right": deepcopy(diagnostic)}}


def acks(start, count, state=None):
    return tuple(ControlAcknowledgement(step, step, robot_payload(step, state))
                 for step in range(start + 1, start + count + 1))



def execution_feedback(policy_calls, action_decisions, environment_steps, executed_steps):
    return ExecutionFeedback(policy_calls, action_decisions, environment_steps, executed_steps,
                             acks(environment_steps - executed_steps, executed_steps))
