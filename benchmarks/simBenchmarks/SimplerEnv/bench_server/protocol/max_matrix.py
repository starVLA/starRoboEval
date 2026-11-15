"""Pinned SimplerEnv reference matrices, transcribed from the upstream scripts.

Each `max` episode reproduces one `run_maniskill2_eval_single_episode` call made
by the pinned `scripts/rt1_*.sh` / `scripts/rt1x_bridge.sh` for one checkpoint:
explicit environment build kwargs, robot pose and object pose/episode id instead
of `prepackaged_config`. Visual Matching and Variant Aggregation stay separate
matrices: one `max` service run schedules one matrix, as upstream runs one
script, and results are reported per matrix, never pooled.
"""

from __future__ import annotations

import copy
from typing import Any

VISUAL_MATCHING = "visual_matching"
VARIANT_AGGREGATION = "variant_aggregation"
MATRIX_TAGS = {VISUAL_MATCHING: "vm", VARIANT_AGGREGATION: "va"}  # short form used in episode IDs

INPAINTING = "ManiSkill2_real2sim/data/real_inpainting/"  # script-relative overlay directory
QUAT_CENTER = [0.0, 0.0, 0.0, 1.0]  # every script passes --robot-init-rot-quat-center 0 0 0 1
# Robot-family settings of the scripts and of `get_robot_control_mode`.
GOOGLE = {"robot": "google_robot_static", "control_freq": 3, "sim_freq": 513, "control_mode":
          "arm_pd_ee_delta_pose_align_interpolate_by_planner_gripper_pd_joint_target_delta_pos_interpolate_by_planner"}
WIDOWX = {"control_freq": 5, "sim_freq": 500, "control_mode": "arm_pd_ee_target_delta_pose_align2_gripper_pd_joint_pos"}

# Script order differs per family; keep it so variant indices follow the script.
URDF_PICK_MOVE = [None, "recolor_tabletop_visual_matching_1", "recolor_tabletop_visual_matching_2",
                  "recolor_cabinet_visual_matching_1"]
URDF_DRAWER = ["recolor_cabinet_visual_matching_1", "recolor_tabletop_visual_matching_1",
               "recolor_tabletop_visual_matching_2", None]
URDF_SLUG = {None: "default", "recolor_tabletop_visual_matching_1": "tabletop_1",
             "recolor_tabletop_visual_matching_2": "tabletop_2", "recolor_cabinet_visual_matching_1": "cabinet_1"}

# rt1_drawer_visual_matching.sh EvalOverlay: paired robot pose (x, y, yaw) and real overlay.
DRAWER_OVERLAY_POSES = [
    ("a0", 0.644, -0.179, -0.03), ("a1", 0.765, -0.182, -0.02), ("a2", 0.889, -0.203, -0.06),
    ("b0", 0.652, 0.009, 0.0), ("b1", 0.752, 0.009, 0.0), ("b2", 0.851, 0.035, 0.0),
    ("c0", 0.665, 0.224, 0.0), ("c1", 0.765, 0.222, -0.025), ("c2", 0.865, 0.222, -0.025),
]
APPLE_OVERLAY_POSES = [pose for pose in DRAWER_OVERLAY_POSES if pose[0] in ("a0", "b0", "c0")]

PICK_OPTIONS = {"google_robot_pick_horizontal_coke_can": "lr_switch",
                "google_robot_pick_vertical_coke_can": "laid_vertically",
                "google_robot_pick_standing_coke_can": "upright"}
DRAWER_ENVS = {
    "google_robot_open_top_drawer": "OpenTopDrawerCustomInScene-v0",
    "google_robot_open_middle_drawer": "OpenMiddleDrawerCustomInScene-v0",
    "google_robot_open_bottom_drawer": "OpenBottomDrawerCustomInScene-v0",
    "google_robot_close_top_drawer": "CloseTopDrawerCustomInScene-v0",
    "google_robot_close_middle_drawer": "CloseMiddleDrawerCustomInScene-v0",
    "google_robot_close_bottom_drawer": "CloseBottomDrawerCustomInScene-v0",
}
BRIDGE = {  # rt1x_bridge.sh: one overlay setup per task, object episodes 0..23
    "widowx_carrot_on_plate": ("PutCarrotOnPlateInScene-v0", "widowx", "bridge_table_1_v1",
                               "bridge_real_eval_1.png", 0.147, 0.028, 60),
    "widowx_stack_cube": ("StackGreenCubeOnYellowCubeBakedTexInScene-v0", "widowx", "bridge_table_1_v1",
                          "bridge_real_eval_1.png", 0.147, 0.028, 60),
    "widowx_spoon_on_towel": ("PutSpoonOnTableClothInScene-v0", "widowx", "bridge_table_1_v1",
                              "bridge_real_eval_1.png", 0.147, 0.028, 60),
    "widowx_put_eggplant_in_basket": ("PutEggplantInBasketScene-v0", "widowx_sink_camera_setup",
                                      "bridge_table_1_v2", "bridge_sink.png", 0.127, 0.06, 120),
}


def linspace(start: float, stop: float, num: int) -> list[float]:
    """`numpy.linspace` as used by the upstream argparse `parse_range_tuple`."""
    if num == 1:
        return [float(start)]
    step = (stop - start) / (num - 1)
    values = [start + i * step for i in range(num)] if step != 0 else [float(start)] * num
    values[-1] = float(stop)  # numpy pins the endpoint exactly
    return values


def _grid(robot_x, robot_y, yaw, *, obj_x=None, obj_y=None, obj_episodes=None):
    """Expand one script call in `maniskill2_evaluator` loop order."""
    cells = []
    for x in linspace(*robot_x):
        for y in linspace(*robot_y):
            for rz in linspace(*yaw):  # roll and pitch ranges are 0 0 1 in every script
                pose = {"robot_init_xy": [x, y], "robot_init_rpy": [0.0, 0.0, rz],
                        "robot_init_rot_quat_center": list(QUAT_CENTER)}
                if obj_episodes is not None:
                    cells += [{**pose, "obj_init_xy": None, "obj_episode_id": e} for e in range(*obj_episodes)]
                else:
                    cells += [{**pose, "obj_init_xy": [ox, oy], "obj_episode_id": None}
                              for ox in linspace(*obj_x) for oy in linspace(*obj_y)]
    return cells


def _call(env_id: str, scene: str, overlay: str | None, kwargs: dict[str, Any], steps: int, *,
          raytracing: bool = False, robot: dict[str, Any] = GOOGLE, label: str | None = None) -> dict[str, Any]:
    if raytracing:  # --enable-raytracing prepends shader_dir=rt to the build kwargs
        kwargs = {"shader_dir": "rt", **kwargs}
    return {"env_id": env_id, "scene_name": scene, **robot,
            "rgb_overlay_path": None if overlay is None else INPAINTING + overlay,
            "env_build_kwargs": kwargs, "enable_raytracing": raytracing,
            "max_episode_steps": steps, "overlay_pose": label}


def _pick(task: str):
    option = {PICK_OPTIONS[task]: True}
    grid = lambda: _grid((0.35, 0.35, 1), (0.20, 0.20, 1), (0, 0, 1),
                         obj_x=(-0.35, -0.12, 5), obj_y=(-0.02, 0.42, 5))
    base_env, base_scene = "GraspSingleOpenedCokeCanInScene-v0", "google_pick_coke_can_1_v4"
    vm = [(f"urdf_{URDF_SLUG[u]}", "urdf_version", u,
           [(_call(base_env, base_scene, "google_coke_can_real_eval_1.png", {**option, "urdf_version": u}, 80), grid())])
          for u in URDF_PICK_MOVE]
    distractor = "GraspSingleOpenedCokeCanDistractorInScene-v0"
    settings = [  # rt1_pick_coke_can_variant_agg.sh block order
        ("base", "base", None, base_env, base_scene, {}),
        ("table_cabinet1", "table_texture", "Baked_sc1_staging_objaverse_cabinet1_h870", base_env,
         "Baked_sc1_staging_objaverse_cabinet1_h870", {}),
        ("table_cabinet2", "table_texture", "Baked_sc1_staging_objaverse_cabinet2_h870", base_env,
         "Baked_sc1_staging_objaverse_cabinet2_h870", {}),
        ("distractor_less", "distractor", "less (native default)", distractor, base_scene, {}),
        ("distractor_more", "distractor", "more", distractor, base_scene, {"distractor_config": "more"}),
        ("background_alt1", "background", "google_pick_coke_can_1_v4_alt_background", base_env,
         "google_pick_coke_can_1_v4_alt_background", {}),
        ("background_alt2", "background", "google_pick_coke_can_1_v4_alt_background_2", base_env,
         "google_pick_coke_can_1_v4_alt_background_2", {}),
        ("lighting_darker", "lighting", "slightly_darker_lighting", base_env, base_scene,
         {"slightly_darker_lighting": True}),
        ("lighting_brighter", "lighting", "slightly_brighter_lighting", base_env, base_scene,
         {"slightly_brighter_lighting": True}),
        ("camera_alt1", "camera", "GraspSingleOpenedCokeCanAltGoogleCameraInScene-v0",
         "GraspSingleOpenedCokeCanAltGoogleCameraInScene-v0", base_scene, {}),
        ("camera_alt2", "camera", "GraspSingleOpenedCokeCanAltGoogleCamera2InScene-v0",
         "GraspSingleOpenedCokeCanAltGoogleCamera2InScene-v0", base_scene, {}),
    ]
    va = [(name, axis, value, [(_call(env, scene, None, {**option, **extra}, 80), grid())])
          for name, axis, value, env, scene, extra in settings]
    return {VISUAL_MATCHING: ("scripts/rt1_pick_coke_can_visual_matching.sh", vm),
            VARIANT_AGGREGATION: ("scripts/rt1_pick_coke_can_variant_agg.sh", va)}


def _move_near(task: str):
    grid = lambda: _grid((0.35, 0.35, 1), (0.21, 0.21, 1), (-0.09, -0.09, 1), obj_episodes=(0, 60))
    scene = "google_pick_coke_can_1_v4"
    vm = [(f"urdf_{URDF_SLUG[u]}", "urdf_version", u,
           [(_call("MoveNearGoogleBakedTexInScene-v0", scene, "google_move_near_real_eval_1.png",
                   {"urdf_version": u}, 80), grid())])
          for u in URDF_PICK_MOVE]
    env = "MoveNearGoogleInScene-v0"  # VA uses the non-baked environment, unlike VM
    settings = [  # rt1_move_near_variant_agg.sh block order
        ("base", "base", None, env, scene, {}),
        ("no_distractor", "distractor", "no_distractor", env, scene, {"no_distractor": True}),
        ("background_alt1", "background", "google_pick_coke_can_1_v4_alt_background", env,
         "google_pick_coke_can_1_v4_alt_background", {}),
        ("background_alt2", "background", "google_pick_coke_can_1_v4_alt_background_2", env,
         "google_pick_coke_can_1_v4_alt_background_2", {}),
        ("lighting_darker", "lighting", "slightly_darker_lighting", env, scene, {"slightly_darker_lighting": True}),
        ("lighting_brighter", "lighting", "slightly_brighter_lighting", env, scene,
         {"slightly_brighter_lighting": True}),
        ("table_cabinet1", "table_texture", "Baked_sc1_staging_objaverse_cabinet1_h870", env,
         "Baked_sc1_staging_objaverse_cabinet1_h870", {}),
        ("table_cabinet2", "table_texture", "Baked_sc1_staging_objaverse_cabinet2_h870", env,
         "Baked_sc1_staging_objaverse_cabinet2_h870", {}),
        ("camera_alt1", "camera", "MoveNearAltGoogleCameraInScene-v0", "MoveNearAltGoogleCameraInScene-v0", scene, {}),
        ("camera_alt2", "camera", "MoveNearAltGoogleCamera2InScene-v0", "MoveNearAltGoogleCamera2InScene-v0", scene, {}),
    ]
    va = [(name, axis, value, [(_call(env_id, scene_name, None, extra, 80), grid())])
          for name, axis, value, env_id, scene_name, extra in settings]
    return {VISUAL_MATCHING: ("scripts/rt1_move_near_visual_matching.sh", vm),
            VARIANT_AGGREGATION: ("scripts/rt1_move_near_variant_agg.sh", va)}


def _drawer_va_settings(model: dict[str, Any]):
    """Shared block order of rt1_drawer_variant_agg.sh and rt1_put_in_drawer_variant_agg.sh."""
    frl = "frl_apartment_stage_simple"
    rt = {"shader_dir": "rt"}  # later blocks pass shader_dir=rt directly instead of --enable-raytracing
    return [
        ("base", "base", None, frl, dict(model), True),
        ("background_bedroom", "background", "modern_bedroom_no_roof", "modern_bedroom_no_roof", {**rt, **model}, False),
        ("background_office", "background", "modern_office_no_roof", "modern_office_no_roof", {**rt, **model}, False),
        ("lighting_brighter", "lighting", "brighter", frl, {**rt, "light_mode": "brighter", **model}, False),
        ("lighting_darker", "lighting", "darker", frl, {**rt, "light_mode": "darker", **model}, False),
        ("cabinet_station2", "cabinet", "mk_station2", frl, {**rt, "station_name": "mk_station2", **model}, False),
        ("cabinet_station3", "cabinet", "mk_station3", frl, {**rt, "station_name": "mk_station3", **model}, False),
    ]


def _drawer(task: str):
    env = DRAWER_ENVS[task]
    vm = []
    for u in URDF_DRAWER:
        kwargs = {"station_name": "mk_station_recolor", "light_mode": "simple", "disable_bad_material": True,
                  "urdf_version": u}
        calls = [(_call(env, "dummy_drawer", f"open_drawer_{label}.png", kwargs, 113, raytracing=True, label=label),
                  _grid((x, x, 1), (y, y, 1), (yaw, yaw, 1), obj_x=(0, 0, 1), obj_y=(0, 0, 1)))
                 for label, x, y, yaw in DRAWER_OVERLAY_POSES]
        vm.append((f"urdf_{URDF_SLUG[u]}", "urdf_version", u, calls))
    va = [(name, axis, value,
           [(_call(env, scene, None, kwargs, 113, raytracing=raytracing),
             _grid((0.65, 0.85, 3), (-0.2, 0.2, 3), (0.0, 0.0, 1), obj_x=(0, 0, 1), obj_y=(0, 0, 1)))])
          for name, axis, value, scene, kwargs, raytracing in _drawer_va_settings({})]
    return {VISUAL_MATCHING: ("scripts/rt1_drawer_visual_matching.sh", vm),
            VARIANT_AGGREGATION: ("scripts/rt1_drawer_variant_agg.sh", va)}


def _apple(task: str):
    env = "PlaceIntoClosedTopDrawerCustomInScene-v0"
    obj = {"obj_x": (-0.08, -0.02, 3), "obj_y": (-0.02, 0.08, 3)}
    vm = []
    for u in URDF_DRAWER:
        kwargs = {"station_name": "mk_station_recolor", "light_mode": "simple", "disable_bad_material": True,
                  "urdf_version": u, "model_ids": "baked_apple_v2"}
        calls = [(_call(env, "dummy_drawer", f"open_drawer_{label}.png", kwargs, 200, raytracing=True, label=label),
                  _grid((x, x, 1), (y, y, 1), (yaw, yaw, 1), **obj))
                 for label, x, y, yaw in APPLE_OVERLAY_POSES]
        vm.append((f"urdf_{URDF_SLUG[u]}", "urdf_version", u, calls))
    va = [(name, axis, value,  # VA uses model_ids=apple, VM baked_apple_v2
           [(_call(env, scene, None, kwargs, 200, raytracing=raytracing),
             _grid((0.65, 0.65, 1), (-0.2, 0.2, 3), (0.0, 0.0, 1), **obj))])
          for name, axis, value, scene, kwargs, raytracing in _drawer_va_settings({"model_ids": "apple"})]
    return {VISUAL_MATCHING: ("scripts/rt1_put_in_drawer_visual_matching.sh", vm),
            VARIANT_AGGREGATION: ("scripts/rt1_put_in_drawer_variant_agg.sh", va)}


def _bridge(task: str):
    env, robot, scene, overlay, x, y, steps = BRIDGE[task]
    call = _call(env, scene, overlay, {}, steps, robot={"robot": robot, **WIDOWX})
    vm = [("base", "base", None, [(call, _grid((x, x, 1), (y, y, 1), (0, 0, 1), obj_episodes=(0, 24)))])]
    return {VISUAL_MATCHING: ("scripts/rt1x_bridge.sh", vm)}  # upstream has no Bridge VA script


FAMILIES = {**{task: _pick for task in PICK_OPTIONS}, "google_robot_move_near_v0": _move_near,
            **{task: _drawer for task in DRAWER_ENVS},
            "google_robot_place_apple_in_closed_top_drawer": _apple, **{task: _bridge for task in BRIDGE}}


def available_matrices(task: str) -> tuple[str, ...]:
    """Matrices the pinned scripts define for `task`; Bridge tasks have Visual Matching only."""
    return tuple(FAMILIES[task](task))


def reference_matrix(task: str, matrix: str) -> list[dict[str, Any]]:
    """Ordered rows of one matrix: variant, then episode within the variant."""
    families = FAMILIES[task](task)
    if matrix not in families:
        raise ValueError(f"{task} has no {matrix!r} reference matrix; available: {', '.join(families)}")
    script, variants = families[matrix]
    rows = []
    for variant_index, (name, axis, value, calls) in enumerate(variants):
        episode_index = 0
        for call, cells in calls:
            for cell in cells:
                rows.append({
                    "id": f"{task}-{MATRIX_TAGS[matrix]}-{variant_index:02d}_{name}-{episode_index:03d}",
                    "matrix": matrix, "upstream_script": script,
                    "variant": {"index": variant_index, "name": name, "axis": axis, "value": value},
                    "episode_index": episode_index,
                    "native": copy.deepcopy({**call, **cell}),  # calls share build-kwargs dicts across cells
                })
                episode_index += 1
    return rows
