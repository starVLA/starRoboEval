"""One predeclared fixed-manifest dynamic task, not a full-suite preset."""

NATIVE_REVISION = "9c94f2d3a700fff3b65f041df4038d497139ed1f"
CUROBO_REVISION = "d64c4b005459db10c5dd867d8b30a87d5bda9bdb"
PROTOCOL = "domino-9c94f2d/click-bell-fixed-manifest/qpos14-rgb-commanded-state/sm120-agent-grouping-v2"
TASK = "click_bell"
TASK_CONFIG = "demo_clean_dynamic"
INSTRUCTION = "click the <bell's top center> on the table"
NATIVE_HORIZON = 400
CAMERAS = ("head_camera", "left_camera", "right_camera")
IMAGE_SHAPE = (240, 320, 3)
JOINT_NAMES = tuple(f"f{side}_joint{i}" for side in ("l", "r") for i in range(1, 7))
ACTION_NAMES = (*JOINT_NAMES[:6], "left_gripper", *JOINT_NAMES[6:], "right_gripper")
STATE_NAMES = tuple("commanded_target_" + name for name in ACTION_NAMES)

# Deliberate compatibility track, NOT upstream requirements.txt parity.
RUNTIME_VERSIONS = {
    "torch": "2.7.1+cu128", "torchvision": "0.22.1+cu128",
    "sapien": "3.0.0b1", "scipy": "1.15.3", "mplib": "0.2.1",
    "gymnasium": "1.3.0", "trimesh": "4.4.3", "open3d": "0.18.0",
    "imageio": "2.34.2", "transforms3d": "0.4.2", "toppra": "0.6.3",
}
