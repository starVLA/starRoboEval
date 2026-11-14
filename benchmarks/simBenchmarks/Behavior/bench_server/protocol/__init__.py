"""Pinned selected 2026 DefaultWrapper cases; not full RGBD challenge parity."""
from dataclasses import dataclass
from types import MappingProxyType
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
EXPANDED_PROTOCOL = "behavior-2026-default-rgb-proprio-debug/v3"


@dataclass(frozen=True)
class TaskDefinition:
    name: str
    human_length: float
    instruction: str
    scene: str
    instance_sha256: str
    instruction_source: str

    @property
    def native_timeout_steps(self):
        return int(self.human_length * 1.5)

    @property
    def control_cap(self):
        # Pinned Timeout checks the zero-based counter before _post_step
        # increments it. Preserve radio v1's historical cap, not timeout parity.
        return self.native_timeout_steps + (self.name != TASK)

    @property
    def instance_path(self):
        return (f"2026-challenge-task-instances/scene_test/public/{self.scene}/json/"
                f"{self.scene}_task_{self.name}_instances/"
                f"{self.scene}_task_{self.name}_0_{INSTANCE}_template-tro_state.json")


TASKS = MappingProxyType({item.name: item for item in (
    TaskDefinition(TASK, HUMAN_LENGTH, INSTRUCTION, "house_double_floor_lower",
        "30a0fe101da1cbf6eb3683d3f9da716399ccd7409974b459dc12a580d2c8ad13", "legacy-radio-v1"),
    TaskDefinition("picking_up_trash", 5267.75,
        "Put the three cans of soda from the living room inside the trash can in the kitchen.",
        "house_double_floor_lower", "df18de75e8c96e9f517f3d3aa524149c2e6c7454f659e2fc91e6e7d5d22dc348",
        "pinned docs/challenge/task_data.json"),
    TaskDefinition("clean_up_your_desk", 21417.875,
        "In the child's room, clean up the desk: put both folders and both paperback books into the bookcase; "
        "put the pencil and both pens into the pencil case and leave the case on the desk; take the stapler "
        "out of the bookcase and place it on the desk; move the laptop from the bed onto the desk and close it.",
        "house_single_floor", "6d5e6a43f060d5fc1f7c45f6597eb21cea502a383546896d688e9a1888a4e509",
        "pinned docs/challenge/task_data.json"),
    TaskDefinition("store_honey", 6766.84, "Place the jar of honey inside the cabinet.",
        "Rs_int", "956f10508fe2914c66bcecfb64df5364dcd119751edc42b3433c8a91ade5b1cb",
        "benchmark-authored goal-only language from pinned bddl3/bddl/activity_definitions/store_honey/problem0.bddl"),
    TaskDefinition("cook_a_brisket", 7334.995,
        "Cook the brisket and place it on the chopping board. Leave the frying pan on the countertop.",
        "house_double_floor_lower", "5e78fa57c8015376b64f0743ba5b2b56efb19d194be759b1dce9be6a4bf849d3",
        "benchmark-authored goal-only language from pinned bddl3/bddl/activity_definitions/cook_a_brisket/problem0.bddl"),
    TaskDefinition("putting_shoes_on_rack", 7726.145,
        "Pick up the two gym shoes and the two sandals from the corridor floor and place them onto the "
        "hallstand (shoe rack) in the corridor, making sure they are on the rack and not on the floor. "
        "Arrange them so the two gym shoes are next to each other and the two sandals are next to each other.",
        "house_double_floor_lower", "f0a34d059c2d6bdddb53119f54df05524572d71f24367d0de492a95425e5df1c",
        "pinned docs/challenge/task_data.json"),
    TaskDefinition("hanging_pictures", 2387.415,
        "Pick up the poster from the kitchen countertop and hang it on one of the wall nails in the kitchen.",
        "house_double_floor_lower", "8bd992e57e159378aa4734578c496f7c6585071eccb467ac98d397534ba41df1",
        "pinned docs/challenge/task_data.json"),
)})


def task_definition(name=TASK):
    if type(name) is not str or name not in TASKS:
        raise ValueError("unsupported BEHAVIOR debug task")
    return TASKS[name]

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
