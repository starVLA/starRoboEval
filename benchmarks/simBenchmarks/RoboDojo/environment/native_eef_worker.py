"""Private one-attempt reference EEF worker; no model, oracle or task policy.

Inherited code is limited to correlated lifecycle artifacts, native joint-target
execution and the exact pinned evaluator-method loader. The native reset,
six-task source pins and observation contract are not modified.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import traceback

from benchmarks.simBenchmarks.RoboDojo.bench_server.native_worker_client import RPC_PROTOCOL
from benchmarks.simBenchmarks.RoboDojo.bench_server.adapter import (
    CONTROL_ALIGNMENT, HORIZON, INSTRUCTION, NATIVE_INSTRUCTION, TASK, TASK_SPEC,
    mode_layouts, public_state, validate_action,
)
from benchmarks.simBenchmarks.RoboDojo.environment.asset_reference import KNOWN_UNRESOLVED
from benchmarks.simBenchmarks.RoboDojo.environment.worker_runtime import (
    NATIVE_METHODS, ResetNotificationOnly, Worker, native_control_class, sha, write_json,
)
from benchmarks.simBenchmarks.RoboDojo.environment.reference_eef_runtime import (
    VERSIONS, pins, verify_layouts, verify_runtime,
)
from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.robot_feedback import SCHEMA as ROBOT_FEEDBACK_SCHEMA, make_robot_feedback


def register_native_checks(env) -> dict:
    """Run native registration once and fail closed on vacuous completion."""
    env.run_reward()
    if hasattr(env, "get_score"):
        env.get_score()
    names = ("check_list", "final_check_list", "trigger_check_list")
    counts = {name: [len(group) for group in getattr(env.reward_manager, name)] for name in names}
    if (env.num_envs != 1 or any(len(rows) != env.num_envs for rows in counts.values())
            or any(sum(counts[name][i] for name in names) == 0 for i in range(env.num_envs))):
        raise RuntimeError("native completion conditions are empty or incorrectly registered")
    return {"registered": True, "condition_group_counts": counts,
            "source": "pinned native run_reward/get_score preamble", "scorer_calls": 0}


def validate_native_configuration(config, native_eval_num, output: Path, *, expected_eval_num: int = 50,
                                  allow_missing_stabilization: bool = False) -> dict:
    """Audit allowlisted scalar settings before enforcing the native binding.

    The task index's common eval_nums=50 applies to classify_objects; the
    25-episode overrides of several other tasks do not apply to this task.
    This guard records configuration only and never edits the native config.
    """
    observed = {"upstream_configured_eval_num": native_eval_num,
        "effective_native_eval_num": config.eval_cfg.eval_num,
        "sim_dt": config.sim.dt, "sim_decimation": config.sim.decimation,
        "sim_render_interval": config.sim.render_interval,
        "sim_num_envs": config.sim.scene.num_envs,
        "teleop_enable_stabilization": (getattr(getattr(config.sim, "physx", None), "enable_stabilization", None)
            if allow_missing_stabilization else config.sim.physx.enable_stabilization),
        "camera_collect_freq": config.camera.default_frequency}
    expected = {"upstream_configured_eval_num": expected_eval_num, "sim_dt": 0.004, "sim_decimation": 1}
    mismatches = [name for name, value in expected.items()
        if type(observed[name]) is not type(value) or observed[name] != value]
    receipt = {"source": "pinned process_config and declared single-case overrides",
        "observed": observed, "observed_types": {k: type(v).__name__ for k, v in observed.items()},
        "expected_native_fields": expected, "mismatches": mismatches,
        "validated": not mismatches, "native_reset_started": False}
    write_json(output / "native_config_validation.json", receipt)
    if mismatches:
        raise RuntimeError("native configuration drift: " + json.dumps(
            {"mismatches": mismatches, "observed": observed}, sort_keys=True))
    return receipt


def validate_native_layout_manager(manager, source: Path, layout_rows: list[dict], output: Path,
                                   *, task: str = TASK, candidate_count: int = 55) -> dict:
    """Check the unadvanced native manager without reading layout contents.

    Native ASSETS_PATH contains env/../Assets. Match canonical paths, as the
    reference server does, and bind every candidate to its already pinned hash.
    The original mapping strings and the native manager are never rewritten.
    """
    expected_ids = list(range(candidate_count))
    observed = {"seed_list": manager.seed_list, "idx": manager.idx,
        "current_batch": manager._current_batch_seeds, "st_idx": manager.st_idx,
        "ed_idx": manager.ed_idx, "num_envs": manager.num_envs,
        "eval_seed": manager.eval_seed, "type": manager.type}
    expected_state = {"seed_list": expected_ids, "idx": 0, "current_batch": None,
        "st_idx": 0, "ed_idx": candidate_count, "num_envs": 1, "eval_seed": 0, "type": "eval"}
    mismatches = ["manager." + key for key, value in expected_state.items()
        if type(observed[key]) is not type(value) or observed[key] != value]
    if (not isinstance(manager.seed_info, dict) or set(manager.seed_info) != set(expected_ids)
            or any(type(key) is not int for key in manager.seed_info)):
        mismatches.append("manager.mapping_ids")
    if (len(layout_rows) != candidate_count or [row.get("name") for row in layout_rows]
            != [f"{task}_{i}.json" for i in expected_ids]):
        mismatches.append("candidate_inventory")
    entries = []
    directory = source.resolve() / "Assets/Eval_Layout/RoboDojo/arx_x5/0"
    for i, row in enumerate(layout_rows):
        info = manager.seed_info.get(i) if isinstance(manager.seed_info, dict) else None
        raw = info.get("scene_layout") if isinstance(info, dict) else None
        item = {"layout_id": i, "expected_filename": row["name"],
            "keys_match": isinstance(info, dict) and set(info) == {"scene_layout"},
            "path_string_sha256": hashlib.sha256(raw.encode()).hexdigest() if isinstance(raw, str) else None,
            "actual_filename": Path(raw).name if isinstance(raw, str) else None,
            "canonical_path_matches": False, "sha256": None, "hash_matches": False}
        if isinstance(raw, str) and Path(raw).is_absolute():
            try:
                actual = Path(raw).resolve(strict=True)
                expected = (directory / row["name"]).resolve(strict=True)
                item["canonical_path_matches"] = actual == expected
                # Never inspect a different file just because a mapping names it.
                if actual == expected and actual.is_file() and not Path(raw).is_symlink():
                    item["sha256"] = sha(actual)
                    item["hash_matches"] = item["sha256"] == row["sha256"]
            except (OSError, RuntimeError, ValueError) as exc:
                item["path_error_type"] = type(exc).__name__
        for check in ("keys_match", "canonical_path_matches", "hash_matches"):
            if not item[check]:
                mismatches.append(f"layout{i}.{check}")
        entries.append(item)
    receipt = {"observed_manager": observed, "expected_candidate_count": candidate_count,
        "entries": entries, "mismatches": mismatches, "validated": not mismatches,
        "native_manager_modified": False, "layout_contents_exposed": False,
        "native_reset_started": False}
    write_json(output / "native_layout_validation.json", receipt)
    if mismatches:
        raise RuntimeError("native seed-to-layout mapping changed: " + ", ".join(mismatches))
    return receipt


class ReferenceEEFWorker(Worker):
    task_name = TASK
    native_horizon = HORIZON
    native_instruction = NATIVE_INSTRUCTION
    public_instruction = INSTRUCTION
    candidate_count = TASK_SPEC["layout_binding"]["inventory_count"]
    upstream_eval_num = TASK_SPEC["upstream_configured_episodes"]
    native_eval_seed = TASK_SPEC["native_eval_seed"]
    simulator_initial_seed = TASK_SPEC["simulator_initial_seed"]
    allow_missing_stabilization = False
    asset_scope = "qualified historical base plus exact classify reference additions"

    @staticmethod
    def verify_deployment(manifest, digest):
        return verify_runtime(manifest, digest)

    @staticmethod
    def pinned_snapshot():
        return pins()

    @staticmethod
    def pinned_layouts(source):
        return verify_layouts(source)

    def __init__(self):
        super().__init__()
        self.state_frames = []
        self.asset_reference = None
        self.robot_bindings = None
        self.reset_started = False
        self.reset_completed = False
        self.robot_feedback = ROBOT_FEEDBACK_SCHEMA

    def reset(self, request: dict) -> dict:
        if self.output is not None:
            raise RuntimeError("reset is permitted once only")
        if ("protocol_track" in request or "robot_feedback" in request
                or request["task"] != self.task_name or type(request["layout_id"]) is not int
                or type(request["gpu_id"]) is not int or request["gpu_id"] < 0):
            raise ValueError("reset does not match the declared reference task layouts")
        # Only the requested mode's own layouts; max re-reads its manifest at the startup digest.
        allowed_layout_ids, _ = mode_layouts(request["evaluation_mode"], self.task_name,
            stability_manifest=request.get("stability_manifest"),
            stability_manifest_sha256=request.get("stability_manifest_sha256"))
        if request["layout_id"] not in allowed_layout_ids:
            raise ValueError(f"layout {request['layout_id']} is outside evaluation_mode {request['evaluation_mode']}")
        self.output = Path(request["artifact_dir"]).resolve()
        self.task = self.task_name
        self.layout_id = request["layout_id"]
        self.event("verifying_reference_runtime")
        manifest = Path(request["runtime_manifest"])
        self.runtime = self.verify_deployment(manifest, request["runtime_manifest_sha256"])
        self.root = manifest.parent.resolve() / "RoboDojo"
        versions = {name: importlib.metadata.version(name) for name in VERSIONS}
        if versions != VERSIONS or Path(sys.executable).resolve() != Path(self.runtime["python"]):
            raise RuntimeError("native interpreter or dependency versions differ from deployment")
        payload = manifest.read_bytes()
        if hashlib.sha256(payload).hexdigest() != request["runtime_manifest_sha256"]:
            raise RuntimeError("runtime manifest changed after verification")
        (self.output / "runtime_manifest.json").write_bytes(payload)
        expected = self.pinned_snapshot()
        write_json(self.output / "source_provenance.json", {
            "native_root": str(self.root), "revision": expected["native_revision"],
            "source_files": expected["source_files"], "versions": versions,
            "runtime_manifest_sha256": request["runtime_manifest_sha256"],
            "native_evaluator_sha256": sha(self.root / "src/eval_client/eval_env.py"),
            "native_methods_allowlist": NATIVE_METHODS, "xpolicylab_imported": False,
            "control_conversion": "robot_only_numerical_jacobian_dls", "planner_actions": 0,
            "robot_feedback_schema": self.robot_feedback,
            "control_alignment": CONTROL_ALIGNMENT,
                "target_quaternion_tolerance": 1e-4, "native_command_dtype": "float32",
                "public_robot_state_dtype": "float32", "float32_rounding": "upstream_cast_no_inward_ulp",
                "joint_limit_check": "nonempty_intersection_of_soft_limits_and_measured_q_plus_minus_0.05",
                "terminal_flags": "native_horizon_failure_is_truncated"})
        for source, name in ((Path(__file__), "native_eef_worker.py"),
                (Path(__file__).with_name("eef_kinematics.py"), "eef_kinematics.py"),
                (self.root / "src/eval_client/eval_env.py", "pinned_eval_env.py")):
            (self.output / name).write_bytes(source.read_bytes())
        subclass_source = Path(sys.modules[type(self).__module__].__file__)
        if subclass_source != Path(__file__):
            (self.output / subclass_source.name).write_bytes(subclass_source.read_bytes())
        self.event("launching_isaac", gpu_id=request["gpu_id"])
        from isaaclab.app import AppLauncher
        self.app = AppLauncher(headless=True, enable_cameras=True,
            device=f"cuda:{request['gpu_id']}", multi_gpu=False).app
        import numpy as np
        from omegaconf import OmegaConf
        from env.observation_manager.obs_manager import ObsManager
        from env.seed_manager.seed_manager import SeedManager
        from task.RoboDojo.task_registry import load_task_class, task_config_path
        from utils.load_file import load_yaml
        from utils.pipeline_utils import process_config, process_randomization, get_robot_action_dim_info
        import env.global_configs as native_paths
        if Path(native_paths.ASSETS_PATH).resolve() != self.root / "Assets":
            raise RuntimeError("loaded native package resolved a different asset root")
        urdf = self.root / "Assets/Robots/x5/X5A.urdf"
        write_json(self.output / "runtime_relocation.json", {"gpu_id": request["gpu_id"],
            "urdf": str(urdf), "urdf_sha256": sha(urdf), "action_planner_calls": 0,
            "native_planner_initialization": "disabled_by_reference_direct_config",
            "changes_native_physics_or_scoring": False})
        cfg_dir = self.root / "env_cfg"
        eval_cfg = load_yaml(str(cfg_dir / "arx_x5.yml"))
        eval_cfg.update(task_name=self.task_name, num_envs=1, device_id=request["gpu_id"], eval_batch=False,
            policy_name="rsi_reference_eef_no_legacy_policy", additional_info="single_attempt",
            seed=self.simulator_initial_seed, physx_monitor_enabled=False)
        config = OmegaConf.create({
            **{name: load_yaml(str(cfg_dir / name / (eval_cfg["config"][name] + ".yml")))
                for name in ("sim", "scene", "camera", "robot")},
            "task_env": load_yaml(task_config_path(str(self.root / "task/RoboDojo/config"), self.task_name)),
            "eval_cfg": eval_cfg, "deploy_cfg": {}})
        config.sim.scene.num_envs = 1
        config.sim.seed = [self.simulator_initial_seed]
        config = process_randomization(config)
        config, native_eval_num = process_config(config, self.task_name)
        # The reference direct server requests one selected reset per process;
        # The upstream count is provenance, not a retry count. The complete
        # native task's candidate inventory stays intact.
        config.eval_cfg.eval_num = 1
        config.camera.default_frequency = eval_cfg["observation"]["collect_freq"]
        validate_native_configuration(config, native_eval_num, self.output, expected_eval_num=self.upstream_eval_num,
            allow_missing_stabilization=self.allow_missing_stabilization)
        # Same reference direct-control config; no cuRobo planners are built or
        # used. DLS below is fixed robot-only low-level conversion.
        for robot in config.robot.robots:
            robot.need_planner = False
        write_json(self.output / "native_config.json", OmegaConf.to_container(config, resolve=True))
        _, task_class = load_task_class(self.task_name)
        control_class = native_control_class(self.root, task_class)
        env = control_class.__new__(control_class)
        self.env = env
        self.event("constructing_native_task", task=self.task_name)
        task_class.__init__(env, config, self.app)
        if env.robot_manager.planner or env.robot_manager.ik_solver:
            raise RuntimeError("direct-control runtime unexpectedly constructed a planner")
        if env.step_lim != self.native_horizon:
            raise RuntimeError(f"native{self.native_horizon} horizon changed")
        env.eval_cfg, env.physx_monitor_enabled = config.eval_cfg, False
        env.success, env.end_flag, env.take_action_cnt = [True], [False], [0]
        env.episode_nums, env.unstable_nums, env.unstable_envs = 1, 0, set()
        env.video_writers = {}
        env._abort_video_writers = lambda *args, **kwargs: None
        env._stream_vision = lambda *args, **kwargs: None
        env.model_client = ResetNotificationOnly()
        env.obs_manager = ObsManager(deepcopy(eval_cfg["observation"]), 1, env.dt, self.task_name, {}, env.env_seed_list)
        env.robot_action_dim_info = get_robot_action_dim_info(eval_cfg)
        env.seed_manager = SeedManager(config.eval_cfg)
        env.seed_manager.init_eval()
        layout_rows = self.pinned_layouts(self.root)
        validate_native_layout_manager(env.seed_manager, self.root, layout_rows, self.output,
            task=self.task_name, candidate_count=self.candidate_count)
        write_json(self.output / "layout_inventory.json", {"candidate_count": self.candidate_count,
            "upstream_configured_eval_num": native_eval_num, "effective_native_eval_num": 1,
            "native_eval_seed": 0, "simulator_initial_seed": 0,
            "selected_layout_id": self.layout_id, "entries": layout_rows})
        env.scene_manager.layout_manager.replay = True
        self.event("native_reset_started", native_eval_seed=self.native_eval_seed, layout_id=self.layout_id)
        self.reset_started = True
        env.reset(seed=[self.layout_id])
        if env.end_flag[0] or not env.success[0] or env.episode_nums != 1 or env.unstable_envs:
            raise RuntimeError("unstable initial layout; no replacement or retry")
        if env.step_lim != self.native_horizon or env.obs_manager.collect_interval != 10:
            raise RuntimeError("native horizon or interpolation changed")
        if not np.array_equal(env.robot_manager.scene.env_origins[0].cpu().numpy(), [0, 0, 0]):
            raise RuntimeError("single-environment world origin is not the declared reference origin")
        write_json(self.output / "native_evaluation.json", register_native_checks(env))
        original_reward = env.reward_manager.get_reward
        def observe_reward(*args, **kwargs):
            value = original_reward(*args, **kwargs)
            self.reward_evaluations += 1
            self.latest_reward = float(value[0])
            return value
        env.reward_manager.get_reward = observe_reward
        self.initial_ticks = int(env.sim.unwrapped._sim_step_counter)
        self._bind_robot_kinematics()
        message = self.capture()
        self.asset_manifest()
        self.reset_completed = True
        message["metrics"] = self.metrics()
        self.event("native_reset_completed", initial_physics_ticks=self.initial_ticks,
                   initial_task_success_evaluated=False, native_alive_flag=bool(env.success[0]))
        return message

    def _bind_robot_kinematics(self):
        from benchmarks.simBenchmarks.RoboDojo.environment.eef_kinematics import ArmFK
        manager = self.env.robot_manager
        bindings = {}
        for robot in manager.robot_list:
            side = robot.arm_name.split("_")[0]
            if (robot.type != "target" or side not in ("left", "right") or side in bindings
                    or tuple(robot.arm_joints_name) != tuple(f"joint{i}" for i in range(1, 7))
                    or robot.base_link != "base_link" or robot.ee_link_name != "link6"
                    or Path(robot.urdf_path).resolve() != self.root / "Assets/Robots/x5/X5A.urdf"):
                raise RuntimeError("robot is not the two declared independent X5 chains")
            bindings[side] = {"robot": robot, "fk": ArmFK(robot.urdf_path, robot.arm_joints_name),
                "key": manager.robot_key[manager.robot_list.index(robot)]}
        if set(bindings) != {"left", "right"}:
            raise RuntimeError("expected exactly two target arms, no autonomous support arm")
        self.robot_bindings = bindings
        write_json(self.output / "robot_kinematics.json", {side: binding["fk"].to_calibration()
            for side, binding in bindings.items()})

    def measured_robot(self):
        """Measured joints/EEF plus native last commanded opening; no oracle."""
        import numpy as np
        from scipy.spatial.transform import Rotation
        from benchmarks.simBenchmarks.RoboDojo.environment.eef_kinematics import pose_matrix, validate_pose7
        manager = self.env.robot_manager
        result = {}
        for side in ("left", "right"):
            binding = self.robot_bindings[side]
            robot, key, fk = binding["robot"], binding["key"], binding["fk"]
            q = manager.get_joint(robot, env_idx_list=[0])[0]
            eef = validate_pose7(manager.get_real_endpose(robot, env_idx_list=[0], is_relative=False)[0])
            base = validate_pose7(manager.get_link_pose(robot, robot.base_link, env_idx_list=[0], is_relative=False)[0])
            root = pose_matrix(base[:3], base[3:])
            predicted = root @ fk.matrix(q)
            measured = pose_matrix(eef[:3], eef[3:])
            position_error = float(np.linalg.norm(predicted[:3, 3] - measured[:3, 3]))
            angle = float(Rotation.from_matrix(predicted[:3, :3] @ measured[:3, :3].T).magnitude())
            if position_error >= .002 or angle >= .01:
                raise RuntimeError("robot-only FK differs from measured native link6")
            limits = key.data.soft_joint_pos_limits[0, robot.arm_joint_indices].cpu().numpy()
            # Match native ObsManager and the reference public contract exactly.
            # This is last controller opening, not a measured finger gap/contact.
            command_key = manager.process_name(robot.gripper_name)
            commanded_gripper = float(manager.control_manager.prev_control[0][command_key]["position"][0])
            lo, hi = robot.gripper_scale
            opening = (commanded_gripper - lo) / (hi - lo)
            if robot.gripper_move["sign"] != 1:
                opening = 1 - opening
            result[side] = {"q": q, "eef": eef, "root": root, "limits": limits, "opening": opening,
                "fk_check": {"position_error_m": position_error, "rotation_error_rad": angle, "passed": True}}
        return result

    def capture(self):
        message = super().capture()
        if message["instruction"] != self.native_instruction:
            raise RuntimeError("native task language changed")
        robot = self.measured_robot()
        state = []
        for side in ("left", "right"):
            state.extend(float(v) for v in robot[side]["q"])
            state.append(float(robot[side]["opening"]))
        for side in ("left", "right"):
            state.extend(float(v) for v in robot[side]["eef"])
        # Reference session._observe casts qpos14 and EEF14 to float32.
        # Do not clip commanded opening or substitute sensed finger gaps.
        import numpy as np
        state = np.asarray(state, dtype=np.float32).tolist()
        state = list(public_state(state))
        relative = f"state/{self.targets:06d}.json"
        path = self.output / relative
        path.parent.mkdir(exist_ok=True)
        write_json(path, {"control_target": self.targets, "state": state,
            "source": "measured_joints_and_eef_plus_native_last_opening_command",
            "fk_checks": {s: robot[s]["fk_check"] for s in robot}})
        self.state_frames.append({"control_target": self.targets, "path": relative, "sha256": sha(path)})
        write_json(self.output / "proprioception_manifest.json", self.state_frames)
        message["state"] = state
        message["instruction"] = self.public_instruction
        self.last_message = message
        return message

    def step(self, action):
        if not self.reset_completed:
            raise RuntimeError("cannot execute a target before a completed sensor reset")
        if self.finished or self.finalized or self.env is None:
            raise RuntimeError("control outside the live attempt")
        measured = self.measured_robot()
        target = validate_action(action)
        joints, diagnostics = [], {}
        for side, offset in (("left", 0), ("right", 8)):
            m = measured[side]
            q, info = self.robot_bindings[side]["fk"].bounded_target(m["q"], m["limits"], m["root"],
                {"position": list(target[offset:offset + 3]), "quaternion_wxyz": list(target[offset + 3:offset + 7])})
            joints.extend([*q.tolist(), target[offset + 7]])
            diagnostics[side] = {**info, "measured_fk_check": m["fk_check"]}
        import numpy as np
        # Reference client and session cast the complete joint14 command,
        # including continuous openings, before native take_action.
        joints = np.asarray(joints, dtype=np.float32).tolist()
        self.event("eef_target_conversion", eef_target=list(target), joint_target=joints,
            conversion=diagnostics, physical_steps=0, planner_calls=0)
        # The pinned native joint branch executes exactly ten physics ticks and
        # its own single terminal/reward check. No autonomous action while idle.
        message = self._reference_joint_step(joints)
        # Native control, physics and reward counters were verified before this
        # receipt. No extra measurement, scorer query, planner or control occurs.
        message["control_feedback"] = make_robot_feedback(self.targets, joints, message["state"], diagnostics)
        self.event("robot_control_feedback", control_feedback=message["control_feedback"])
        return message

    def _reference_joint_step(self, joints):
        """One reference float32 native command, never a joint14 actor API.

        Called only with this control's robot-only DLS result. The reference
        clips to native soft limits before float32 casting; reapplying the
        RGB/joint14 decimal bounds afterward would spuriously reject
        e.g. float32(3.14). No additional controller, clipping or replay occurs.
        """
        if (not self.reset_completed or self.finished or self.finalized or self.env is None):
            raise RuntimeError("reference joint conversion outside the live direct attempt")
        import numpy as np
        row = np.asarray(joints, dtype=np.float32)
        if row.shape != (14,) or not np.isfinite(row).all() or np.any((row[[6, 13]] < 0) | (row[[6, 13]] > 1)):
            raise RuntimeError("invalid internal reference joint command")
        decoded = {key: value for side, offset in (("left", 0), ("right", 7))
            for key, value in ((f"{side}_arm_joint_state", row[offset:offset + 6]),
                               (f"{side}_ee_joint_state", row[offset + 6:offset + 7]))}
        before = int(self.env.sim.unwrapped._sim_step_counter)
        native_before = int(self.env.take_action_cnt[0])
        if native_before != self.targets:
            raise RuntimeError("native control counter drift before reference command")
        self.attempted_targets += 1
        self.event("control_target_started", action=row.tolist(),
            decoded_action={key: value.tolist() for key, value in decoded.items()}, physics_counter=before)
        self.env.take_action(decoded)
        self.targets += 1
        if self.env.unstable_envs:  # native in-episode instability: infrastructure error, no spare layout
            raise RuntimeError("native marked the layout unstable during the episode; no replacement")
        after = int(self.env.sim.unwrapped._sim_step_counter)
        if int(self.env.take_action_cnt[0]) != native_before + 1 or self.reward_evaluations != self.targets:
            raise RuntimeError("native action/scorer call counts disagree")
        if after - before != 10:
            raise RuntimeError(f"native interpolation expected 10 physics ticks, got {after-before}")
        ended = bool(self.env.end_flag[0])
        success = bool(ended and self.env.success[0])
        if success and self.first_success is None:
            self.first_success = self.targets
        truncated = bool(ended and not success and self.targets >= self.env.step_lim)
        terminated = bool(ended and not truncated)
        self.finished = terminated or truncated
        message = self.capture()
        message.update(terminated=terminated, truncated=truncated)
        self.event("control_target_completed", physics_tick_delta=after-before, **self.metrics())
        write_json(self.output / "native_result.json", self.metrics())
        return message

    def metrics(self):
        if not self.reset_completed:
            return {"success": False, "control_targets": self.targets,
                "attempted_control_targets": self.attempted_targets,
                "native_reward": None, "native_reward_evaluations": self.reward_evaluations,
                "native_process_score": None, "native_benchmark_score": None,
                "native_reset_started": self.reset_started, "native_reset_completed": False}
        success = bool(self.env.end_flag[0] and self.env.success[0])
        cached = self.env.reward_manager._gated_score_lst
        score = None if cached is None else float(cached[0])
        return {"success": success, "native_end_flag": bool(self.env.end_flag[0]),
            "native_alive_flag": bool(self.env.success[0]),
            "native_reward": self.latest_reward if self.reward_evaluations else None,
            "native_reward_evaluations": self.reward_evaluations, "native_process_score": score,
            "native_benchmark_score": None if not self.reward_evaluations else 100.0 if success else (score or 0.0),
            "native_benchmark_score_scale": "0..100", "first_native_success_control_target": self.first_success,
            "control_targets": self.targets, "attempted_control_targets": self.attempted_targets,
            "native_take_action_count": int(self.env.take_action_cnt[0]),
            "physics_ticks": None if self.initial_ticks is None else int(self.env.sim.unwrapped._sim_step_counter) - self.initial_ticks,
            "native_physics_counter": int(self.env.sim.unwrapped._sim_step_counter), "reset_physics_ticks": self.initial_ticks,
            "control_target_hz": 25.0, "physics_hz": 250.0,
            "native_horizon": int(self.env.step_lim),
            "native_reset_started": self.reset_started, "native_reset_completed": True}

    def finalize(self):
        result = super().finalize()
        if self.reset_completed:
            # A valid reset promises the standard artifacts. Do not conceal a
            # missing frame/asset manifest or recording error in this branch.
            return result
        candidates = {**result["artifacts"],
            **{name: name + ".json" for name in ("native_error_reset", "native_config_validation",
                "native_layout_validation", "runtime_manifest", "video_finalization")}}
        result["artifacts"] = {name: relative for name, relative in candidates.items()
            if self.output is not None and not (self.output / relative).is_symlink()
            and (self.output / relative).is_file()}
        result["reset_completed"] = False
        return result

    def asset_manifest(self):
        """Used USD dependency audit with unchanged exact material exceptions."""
        from pxr import Sdf, UsdUtils
        stage = self.env.stage
        stage.GetRootLayer().Export(str(self.output / "initial_stage.usda"))
        inputs = {Path(layer.realPath).resolve() for layer in stage.GetUsedLayers() if layer.realPath}
        missing, dependencies = set(), set()
        for path in inputs:
            if path.suffix.lower() in (".usd", ".usda", ".usdc", ".usdz"):
                layers, assets, unresolved = UsdUtils.ComputeAllDependencies(Sdf.AssetPath(str(path)))
                missing.update(map(str, unresolved))
                dependencies.update(layer.realPath for layer in layers if layer.realPath)
                dependencies.update(map(str, assets))
        for value in dependencies:
            outer = value.split("[", 1)[0]
            if "://" in outer or (outer and not Path(outer).is_file()):
                missing.add(value)
        # Reverify runtime bytes after native setup, before returning the reset.
        from benchmarks.simBenchmarks.RoboDojo.environment.reference_eef_runtime import verify_rows
        verify_rows(self.root / "Assets", self.runtime["asset_files"])
        record = {"scope": self.asset_scope,
            "files": self.runtime["asset_files"], "usd_dependencies": sorted(dependencies),
            "unresolved": sorted(missing), "complete": not missing, "all_benchmark_assets": False,
            "allowed_inherited_unresolved": list(KNOWN_UNRESOLVED),
            "new_unresolved": sorted(missing - set(KNOWN_UNRESOLVED)),
            "renderer_parity_verified": False}
        write_json(self.output / "asset_manifest.json", record)
        if record["new_unresolved"]:
            raise RuntimeError("new unresolved asset dependencies; no exception expansion")


def main(worker_type=ReferenceEEFWorker):
    rpc_out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    worker = worker_type()
    for line in sys.stdin:
        request = json.loads(line)
        operation = request.get("op")
        try:
            if request.get("rpc_protocol") != RPC_PROTOCOL or re.fullmatch(r"[0-9a-f]{32}", request.get("rpc_id", "")) is None:
                raise ValueError("invalid private RPC envelope")
            if operation == "reset":
                result = worker.reset(request)
            elif operation == "step":
                result = worker.step(request["action"])
            elif operation == "finalize":
                result = worker.finalize()
            elif operation == "close":
                result = worker.close()
            else:
                raise ValueError("unsupported private operation")
            rpc_out.write(json.dumps({"rpc_protocol": RPC_PROTOCOL, "rpc_id": request["rpc_id"], "ok": True,
                                     "result": result}, allow_nan=False) + "\n")
            if operation == "close":
                rpc_out.flush()
                try:
                    worker.shutdown_app()
                except Exception:
                    traceback.print_exc()
                    raise SystemExit(1)
                break
        except Exception as exc:
            error = {"operation": operation, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            if worker.output is not None:
                write_json(worker.output / f"native_error_{operation}.json", error)
            traceback.print_exc()
            rpc_out.write(json.dumps({"rpc_protocol": RPC_PROTOCOL, "rpc_id": request.get("rpc_id"), "ok": False, **error}) + "\n")
            worker.finished = True
            if operation == "close":
                rpc_out.flush()
                try:
                    worker.shutdown_app()
                finally:
                    raise SystemExit(1)


if __name__ == "__main__":
    main()
