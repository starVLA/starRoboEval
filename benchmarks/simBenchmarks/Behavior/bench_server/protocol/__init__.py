"""One fixed 2026 DefaultWrapper debugging case; not full RGBD challenge parity."""
from benchkit.contracts import ActionSpec, ObservationSpec

REVISION = "b1979916ec1549b10a4e65e630bc6504a9af1b00"
PROTOCOL = "behavior-2026-default-rgb-proprio-debug/v1"
TASK = "turning_on_radio"
INSTRUCTION = "Turn on the radio."
INSTANCE = 301
NATIVE_SEED = 0
HUMAN_LENGTH = 2149.64
HORIZON = int(HUMAN_LENGTH * 1.5)
TASK_METADATA_SHA256 = "7dbb5f7f00a2e06c693dfbb3045e5c28e627b6179e775f1ad93ca4b61f08e6dc"
CAMERA_KEYS = {
    "head": "robot_r1::robot_r1:zed_link:Camera:0::rgb",
    "left_wrist": "robot_r1::robot_r1:left_realsense_link:Camera:0::rgb",
    "right_wrist": "robot_r1::robot_r1:right_realsense_link:Camera:0::rgb",
}
PROPRIO_FIELDS = ("base_qvel", "arm_left_qpos", "arm_left_qvel", "eef_left_pos",
    "eef_left_quat", "gripper_left_qpos", "gripper_left_qvel", "arm_right_qpos",
    "arm_right_qvel", "eef_right_pos", "eef_right_quat", "gripper_right_qpos",
    "gripper_right_qvel", "trunk_qpos", "trunk_qvel")
FIELD_SIZES = (3, 7, 7, 3, 4, 2, 2, 7, 7, 3, 4, 2, 2, 4, 4)
STATE_NAMES = tuple(f"{field}_{i}" for field, size in zip(PROPRIO_FIELDS, FIELD_SIZES) for i in range(size))
ACTION_NAMES = ("base_vx_normalized", "base_vy_normalized", "base_wz_normalized",
    *(f"torso_joint{i}_rad" for i in range(1, 5)),
    *(f"left_arm_joint{i}_rad" for i in range(1, 8)), "left_gripper_normalized",
    *(f"right_arm_joint{i}_rad" for i in range(1, 8)), "right_gripper_normalized")
CONTROLLER_INDICES = {"base": list(range(3)), "trunk": list(range(3, 7)),
    "arm_left": list(range(7, 14)), "gripper_left": [14],
    "arm_right": list(range(15, 22)), "gripper_right": [22]}
ACTION_SPEC = ActionSpec("behavior_r1pro_native23", 23, ACTION_NAMES, control_hz=30.0,
    frame="base body-frame velocity; absolute native torso/arm joint angles in radians",
    rotation="base yaw velocity input; arm/trunk joint coordinates, not EEF targets",
    gripper="smooth native normalized scalar: -1 closed, +1 open; native acceptance/scaling retained")
OBSERVATION_SPEC = ObservationSpec(cameras=tuple(CAMERA_KEYS), state_names=STATE_NAMES,
    modalities=("language", "rgb", "proprioception"), privileged=False)
