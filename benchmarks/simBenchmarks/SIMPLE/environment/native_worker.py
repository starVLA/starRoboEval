"""Evaluator-private native SIMPLE process. Never an actor/policy entry point.

Only fixed native AMO/SONIC locomotion controllers are loaded. Source/state/
score artifacts are private to the evaluator. stdout is a dedicated JSON RPC
pipe; native Python/C++ output is redirected to the separate stderr log.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import random
import subprocess
import sys
import time
import traceback
from pathlib import Path, PurePosixPath


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def fingerprint(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "size": path.stat().st_size, "sha256": digest.hexdigest()}


def require_hash(path, expected):
    record = fingerprint(path)
    if record["sha256"] != expected:
        raise ValueError(f"frozen native input changed: {path}")
    return record


def check_pinned_hash(path, expected):
    """Compare when pinned; a missing pin records the observed hash and continues."""
    record = fingerprint(path)
    if expected is not None and record["sha256"] != expected:
        raise ValueError(f"frozen native input changed: {path}")
    record["pin"] = "unpinned" if expected is None else "matched"
    return record


def native_python_inventory(root):
    """Pin the same native source bytes independently of the installation path."""
    root = Path(root).resolve()
    records = []
    for relative in ("src/simple", "third_party/decoupled_wbc", "third_party/gear_sonic"):
        for path in (root / relative).rglob("*.py"):
            record = fingerprint(path)
            # Reject source symlinks escaping the selected native repository.
            record["path"] = path.resolve().relative_to(root).as_posix()
            records.append(record)
    records.sort(key=lambda row: row["path"])
    if len({row["path"] for row in records}) != len(records):
        raise ValueError("duplicate native source inventory path")
    return records


def repaired_layer_hashes(repair):
    """Resolve identities inside a hash-verified repair manifest, not its host."""
    original_root = PurePosixPath(repair["hssd_root"])
    if not original_root.is_absolute() or ".." in original_root.parts:
        raise ValueError("invalid repair manifest HSSD root")
    records = {}
    for row in repair["layers"]:
        relative = PurePosixPath(row["layer"]).relative_to(original_root)
        if not relative.parts or ".." in relative.parts or relative.as_posix() in records:
            raise ValueError("invalid or duplicate repair layer path")
        records[relative.as_posix()] = row["after_sha256"]
    return records


def check_initial_state(success, stabilized=None):
    if type(success) is not bool or success:
        raise ValueError("native initial state is already successful or has an invalid success flag")
    if stabilized is not None and stabilized is not True:
        raise ValueError("SONIC did not stabilize within its native warmup cap")


def verify_scene_alias(root, pins, original_uid):
    """Validate native alias metadata and existing repair hashes, without a sim."""
    import yaml
    config_path = root / "src/simple/resources/hssd-scenes/config.yaml"
    repair_path = root / "data/.archives/hssd_reference_repair_v1.json"
    config_record = require_hash(config_path, pins["hssd_scene_config_sha256"])
    repair_record = require_hash(repair_path, pins["hssd_repair_manifest_sha256"])
    scenes = {row["uid"]: row for row in yaml.safe_load(config_path.read_text())}
    if scenes["scene3"]["name"] != "102344280":
        raise ValueError("native legacy scene3 alias no longer points to HSSD 102344280")
    mapped_uid = original_uid.replace("102344280", "scene3")
    selected = scenes[mapped_uid.split(":", 1)[-1]]
    repair = json.loads(repair_path.read_text())
    records = repaired_layer_hashes(repair)
    checked = []
    for name in sorted({selected["name"], "102344280"}):
        relative = PurePosixPath(name) / (name + ".usd")
        path = root / "data/scenes/hssd" / relative
        expected = records[relative.as_posix()]
        checked.append(require_hash(path, expected))
    return mapped_uid, {"before": original_uid, "after": mapped_uid, "applied": original_uid != mapped_uid,
        "native_loader_rule": "src/simple/datasets/lerobot.py:21: 102344280 -> scene3",
        "asset_identity": selected["name"], "scene_config": config_record,
        "repair_manifest": repair_record, "verified_repaired_layers": checked}


class RGBVideoWriter:
    """Explicit installed PyAV backend; never rely on imageio's backend guess."""
    def __init__(self, path, width, height):
        import av
        self.container = av.open(str(path), mode="w")
        self.stream = self.container.add_stream("libx264", rate=50)
        self.stream.width, self.stream.height = width, height
        self.stream.pix_fmt = "yuv420p"

    def append_data(self, frame):
        import av
        for packet in self.stream.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
            self.container.mux(packet)

    def close(self):
        for packet in self.stream.encode():
            self.container.mux(packet)
        self.container.close()


class NativeRuntime:
    def __init__(self):
        self.env = None
        self.agent = None
        self.writers = {}
        self.frame_count = 0
        self.steps = 0
        self.success = False
        self.finished = False
        self.artifact_dir = None
        self.finalized = False

    def reset(self, request):
        from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import (
            SIMPLE_REVISION, HORIZONS, SEED, INVENTORY_PATH, DR_LEVELS, RELEASED_EPISODES,
            NATIVE_SUCCESS_THRESHOLDS, task_config,
        )
        self.artifact_dir = Path(request["artifact_dir"]).resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.root = Path(request["simple_root"]).resolve()
        os.environ["GIT_OPTIONAL_LOCKS"] = "0"
        self.task_id = request["task"]
        self.diagnostic = bool(request["diagnostic"])
        self.proprioception = bool(request["proprioception"])
        self.horizon = self.environment_step_cap = HORIZONS[self.task_id]
        if request["environment_step_cap"] != self.environment_step_cap:
            raise ValueError("worker and runner environment step cap differ")
        config = task_config(self.task_id, request["proprioception"])
        self.backend = config["backend"]
        if request["seed"] != SEED:
            raise ValueError("seed outside the frozen SIMPLE manifest")
        self.dr_level = request["dr_level"]
        if type(self.dr_level) is not int or self.dr_level not in DR_LEVELS:
            raise ValueError("dr_level outside the released DR0-DR2 levels")
        self.episode_index = request["episode_index"]
        if type(self.episode_index) is not int or not 0 <= self.episode_index < RELEASED_EPISODES:
            raise ValueError("episode_index outside the ten released episodes of a DR level")
        if self.env is not None:
            raise RuntimeError("one native environment per process")
        actual_root = Path(subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "--show-toplevel"], text=True).strip()).resolve()
        revision = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        if actual_root != self.root or revision != SIMPLE_REVISION:
            raise ValueError("SIMPLE actual Git root or commit differs from the pin")
        source_dir = self.artifact_dir / "source"
        source_dir.mkdir(exist_ok=True)
        import benchmarks.simBenchmarks.SIMPLE.bench_server.adapter as codec
        for path in (Path(__file__), Path(codec.__file__), Path(__file__).with_name("upstream.json"), INVENTORY_PATH):
            (source_dir / path.name).write_bytes(path.read_bytes())
        pins = json.loads(Path(__file__).with_name("upstream.json").read_text())
        require_hash(INVENTORY_PATH, pins["released_task_inventory_sha256"])
        # Existing local compatibility patches are retained, never modified.
        patch = subprocess.check_output(["git", "-C", str(self.root), "diff", "HEAD", "--", "*.py"])
        (source_dir / "native-existing.patch").write_bytes(patch)
        require_hash(source_dir / "native-existing.patch", pins["existing_native_python_patch_sha256"])
        dirty = subprocess.check_output(["git", "-C", str(self.root), "status", "--porcelain",
            "--untracked-files=no"], text=True)
        source_hashes = native_python_inventory(self.root)
        if (pins["native_python_inventory_format"] != "relative-path-v1"
                or len(source_hashes) != pins["native_python_inventory_file_count"]):
            raise ValueError("native source inventory format or file count differs")
        write_json(source_dir / "native-python-hashes.json", source_hashes)
        require_hash(source_dir / "native-python-hashes.json", pins["native_python_relative_inventory_sha256"])
        level_dir = f"dr-level-{self.dr_level}"
        data = Path(request["eval_root"]) / "simple-eval" / self.task_id / level_dir / "meta"
        reset_metadata = check_pinned_hash(data / "episodes.jsonl",
            pins["reset_metadata_sha256"][self.task_id].get(level_dir))  # DR1/DR2: no pin yet
        if self.dr_level == 0:  # the inventory binds DR0 only
            require_hash(data / "episodes.jsonl", config["reset_metadata_sha256"])
        require_hash(self.root / config["native_source"], config["native_source_sha256"])
        rows = [json.loads(line) for line in (data / "episodes.jsonl").read_text().splitlines() if line.strip()]
        if [row["episode_index"] for row in rows] != list(range(RELEASED_EPISODES)):
            raise ValueError(f"expected ten ordered released {level_dir} episodes")
        # Only released reset metadata is read: no demonstration frames/actions.
        if (self.dr_level == 0 and hashlib.sha256(rows[0]["environment_config"].encode()).hexdigest()
                != config["environment_config_sha256"]):
            raise ValueError("released episode-0 reset hash mismatch")
        conf = json.loads(rows[self.episode_index]["environment_config"])
        if conf["uid"] != config["task_uid"] or conf["robot_cfg"]["uid"] != config["robot_uid"]:
            raise ValueError("released reset task UID mismatch")
        if conf["dr_state_dict"]["scene"]["uid"] != config["scene_uid"]:  # every level keeps the task scene
            raise ValueError("released episode scene UID differs from the task scene")
        mapped_uid, scene_alias = verify_scene_alias(self.root, pins, conf["dr_state_dict"]["scene"]["uid"])
        conf["dr_state_dict"]["scene"]["uid"] = mapped_uid
        write_json(self.artifact_dir / "private_reset.json", conf)
        weights = list((self.root / "src/simple/robots/policy").glob("*.pt"))
        weights += list((self.root / "third_party/decoupled_wbc/sim2mujoco/resources/robots/g1/policy").glob("*.onnx"))
        for controller in pins["controllers"].values():
            for relative, expected in controller.items():
                if fingerprint(self.root / relative)["sha256"] != expected:
                    raise ValueError(f"fixed native controller weight changed: {relative}")
        self.provenance = {"track": request["protocol_version"], "actual_git_root": str(actual_root), "git_revision": revision,
            "git_tracked_status": dirty, "existing_patch": fingerprint(source_dir / "native-existing.patch"),
            "native_python_manifest": fingerprint(source_dir / "native-python-hashes.json"),
            "native_python_manifest_format": pins["native_python_inventory_format"],
            "reset_metadata": reset_metadata,  # carries pin: matched/unpinned
            "selected_reset": fingerprint(self.artifact_dir / "private_reset.json"),
            "task_inventory": fingerprint(INVENTORY_PATH),
            "selected_task_configuration": config,
            "scene_alias": scene_alias,
            "controller_weight_files": [fingerprint(path) for path in sorted(weights)],
            "task": self.task_id, "dr_level": self.dr_level, "episode_index": self.episode_index, "seed": SEED,
            "reference_native_horizon": self.horizon, "environment_step_cap": self.environment_step_cap,
            "diagnostic_only": self.diagnostic, "native_task_metadata_horizon_unchanged": True,
            "time_limit_wrapper_extension": self.environment_step_cap > self.horizon,
            "time_limit_wrapper_reduction": self.environment_step_cap < self.horizon,
            "success_criteria_override": None,  # native constructor/metadata threshold stays in force
            "native_success_threshold": NATIVE_SUCCESS_THRESHOLDS[self.task_id],
            "fixed_controller": "AMO" if self.backend == "amo" else "SONIC-decoupled-WBC",
            "source_worker": fingerprint(Path(__file__)),
            "source_codec": fingerprint(Path(codec.__file__)),
            "versions": {name: importlib.metadata.version(name) for name in ("numpy", "torch", "mujoco", "isaacsim")},
            "python_executable": sys.executable,
            "python_executable_resolved": str(Path(sys.executable).resolve()),
            "python_prefix": sys.prefix,
            "cuda_home": os.environ.get("CUDA_HOME"),
            "gpu_id": os.environ["SIMPLE_ISAAC_GPU_ID"],
            "policy_observation": "native head_stereo_left RGB 360x640, native instruction; " +
                ("31 named measured robot joint encoders; no task metadata" if self.proprioception else "no state/metadata"),
            "extra_score_calls": 0}
        asset_files = [self.root / "data/.archives/hssd_reference_repair_v1.json"]
        for folder, pattern in (("robots/g1", "*.xml"), ("robots/g1_sonic", "*.xml"),
            ("scenes/hssd", "*.usd")):
            asset_files += list((self.root / "data" / folder).glob(pattern))
        self.provenance["asset_entrypoints"] = [fingerprint(path) for path in sorted(asset_files) if path.is_file()]
        write_json(self.artifact_dir / "native_provenance.json", self.provenance)
        import numpy as np
        import torch
        import gymnasium as gym
        import simple.envs  # noqa: F401

        random.seed(SEED)
        np.random.seed(SEED)
        torch.manual_seed(SEED)
        kwargs = dict(render_hz=50, sim_mode="mujoco_isaac", headless=True)
        if self.backend == "sonic":
            import tyro
            from gear_sonic.utils.mujoco_sim.configs import SimLoopConfig
            sim_loop_config = tyro.cli(SimLoopConfig, config=(tyro.conf.ConsolidateSubcommandArgs,), args=[])
            sonic_config = sim_loop_config.load_wbc_yaml()
            sonic_config["ENV_NAME"] = "simple"
            kwargs["sonic_config"] = sonic_config
        raw = gym.make("simple/" + self.task_id, **kwargs).unwrapped
        self.raw = raw
        # Native constructors define horizons/scorers. Reject drift before reset.
        if (type(raw).__module__ + ":" + type(raw).__name__ != config["env_entry_point"]
            or raw.task.uid != config["task_uid"] or raw.task.robot_cfg["uid"] != config["robot_uid"]):
            raise ValueError("native task environment/robot backend drift")
        if raw.task.metadata["max_episode_steps"] != self.horizon:
            raise ValueError("native horizon drift")
        if self.backend == "amo":
            from simple.envs.wrappers.stand_stabilization import StandStabilizationWrapper
            self.env = gym.wrappers.TimeLimit(StandStabilizationWrapper(raw), max_episode_steps=self.environment_step_cap)
            self.obs, _ = self.env.reset(seed=SEED, options={"state_dict": conf})
            check_initial_state(bool(raw._success))
            self.warmup_steps = 60
            self.robot = self.raw.task.robot
            native_cmd = np.asarray(self.robot.amo_policy.obs_command, dtype=np.float32)
            if native_cmd.shape != (9,) or not np.isfinite(native_cmd).all():
                raise ValueError("invalid post-warmup AMO command")
            self.amo_torso_ypr = native_cmd[3:6].copy()
        else:
            from simple.agents.sonic_decoupled_wbc_agent import SonicDecoupledWbcAgent
            self.env = gym.wrappers.TimeLimit(raw, max_episode_steps=self.environment_step_cap)
            self.robot = raw.task.robot
            self.agent = SonicDecoupledWbcAgent(self.robot, sonic_config)
            self.obs, _ = self.env.reset(seed=SEED, options={"state_dict": conf})
            check_initial_state(bool(raw._success))
            self.agent.reset()
            self.agent._wbc_policy.lower_body_policy.use_policy_action = True
            self.warmup_steps = 0
            while not self.robot.stabilized and self.warmup_steps < 300:
                started = time.monotonic()
                action = self.agent.get_stabilize_action(self.obs)
                self.obs, _, _, _, _ = raw.step(action)
                raw.update_viewer()
                raw.update_reward()  # native last_reward bookkeeping, NOT a scorer invocation
                self.warmup_steps += 1
                time.sleep(max(0, self.agent._control_dt - (time.monotonic() - started)))
            self.agent._wbc_policy.lower_body_policy.gait_indices = torch.zeros((1), dtype=torch.float32)
            model = self.agent._dwbc_robot_model
            indices = model.get_joint_group_indices("upper_body")
            self.sonic_names = [name for name, idx in model.joint_to_dof_index.items() if idx in indices]
            self.provenance["sonic_upper_joint_names"] = self.sonic_names
            # The native .stabilized property increments its access counter;
            # telemetry must not make an additional state-changing access.
            self.provenance["sonic_robot_stabilized"] = bool(self.robot._stabilized)
        self.instruction = self.raw.task.instruction
        if self.instruction != config["instruction"]:
            raise ValueError("native instruction differs from frozen released reset")
        if raw.task.metadata["max_episode_steps"] != self.horizon or raw.task.render_hz != 50:
            raise ValueError("native horizon/render frequency changed during reset")
        self.provenance.update({"warmup_native_steps": self.warmup_steps,
            "instruction": self.instruction, "post_warmup_native_step_count": int(self.raw.step_count),
            "joint_limits": {key: [float(x) for x in value] for key, value in self.robot.joint_limits.items()}})
        self.provenance["public_state_names"] = list(codec.ACTION_NAMES[:31]) if self.proprioception else []
        self.provenance["action_slot_34"] = "turning_flag" if self.agent is None else "turning_gate"
        self.provenance["MODIFIED_POLICY_SWITCH_BEHAVIOR"] = os.environ.get("MODIFIED_POLICY_SWITCH_BEHAVIOR", "0")
        # USD layer provenance is evaluator-only; do not export object transforms.
        import omni.usd
        used_layers = omni.usd.get_context().get_stage().GetUsedLayers()
        used_asset_files = sorted({Path(layer.realPath).resolve() for layer in used_layers
            if layer.realPath and Path(layer.realPath).is_file()
            and str(Path(layer.realPath).resolve()).startswith(str(self.root / "data") + "/")})
        self.provenance["used_usd_asset_layers"] = [fingerprint(path) for path in used_asset_files]
        self.provenance["asset_fingerprint_scope"] = "used local USD layers, robot XML entrypoints and HSSD repair manifest; not a recursive texture/payload audit"
        write_json(self.artifact_dir / "native_provenance.json", self.provenance)
        # Diagnostic evidence includes all native RGB views; policy gets only head-left.
        result = self.capture()
        check_initial_state(bool(self.raw._success), bool(self.robot._stabilized) if self.agent is not None else None)
        result["native_horizon"] = self.horizon
        result["artifacts"] = {"native_provenance": "native_provenance.json", "native_log": "native_worker.log"}
        return result

    def _native_action(self, values):
        import numpy as np
        from simple.core.action import ActionCmd
        from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import decode_action, amo_payload

        command = decode_action(values)
        # v2 passes finite physical targets to the pinned native controller.
        # MuJoCo joint ranges constrain physics, not this command interface:
        # even measured encoders can cross them slightly during soft contact.
        # Do not add target clipping/range rejection ahead of native execution.
        if self.agent is None:
            return ActionCmd("eval_move_actuators", **amo_payload(values, self.amo_torso_ypr))
        agent, model = self.agent, self.agent._dwbc_robot_model
        missing = set(self.sonic_names) - command["joint_positions"].keys()
        if missing:
            raise ValueError(f"SONIC upper body names missing from aligned codec: {sorted(missing)}")
        proprio = self.robot.prepare_obs()
        agent._wbc_policy.set_observation(agent._build_wbc_observation(proprio))
        now = time.monotonic()
        freq = agent._control_frequency
        agent._wbc_policy.set_goal({
            "target_upper_body_pose": np.asarray([command["joint_positions"][name] for name in self.sonic_names]),
            "navigate_cmd": np.asarray(command["navigate_cmd"]),
            "base_height_command": np.asarray([command["base_height"]]),
            "target_time": now + 1 / freq, "interpolation_garbage_collection_time": now - 2 / freq,
            "timestamp": now,
        })
        action = agent._wbc_policy.get_action(time=now)
        return ActionCmd("decoupled_wbc", target_q=model.get_body_actuated_joints(action["q"]),
            left_hand_q=model.get_hand_actuated_joints(action["q"], side="left"),
            right_hand_q=model.get_hand_actuated_joints(action["q"], side="right"))

    def step(self, values):
        if self.finished:
            raise ValueError("cannot advance a completed native episode")
        started = time.monotonic()
        action = self._native_action(values)
        self.obs, reward, terminated, truncated, _ = self.env.step(action)
        self.steps += 1
        self.success = bool(self.raw._success)
        self.finished = bool(terminated or truncated)
        result = self.capture()
        result.update({"reward": float(reward), "success": self.success, "terminated": bool(terminated),
            "truncated": bool(truncated), "native_steps": self.steps, "step_wall_seconds": time.monotonic() - started})
        with (self.artifact_dir / "private_native_ticks.jsonl").open("a") as stream:
            stream.write(json.dumps({key: value for key, value in result.items() if key not in ("frame", "instruction")}) + "\n")
        return result

    def capture(self):
        import numpy as np
        from PIL import Image
        from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import public_observation

        public = public_observation(self.obs, self.steps, self.instruction)
        folder = self.artifact_dir / "rgb"
        folder.mkdir(exist_ok=True)
        frame_path = folder / f"head_stereo_left_{self.steps:06d}.png"
        Image.fromarray(public.images["head_stereo_left"]).save(frame_path)
        if self.finalized:
            raise RuntimeError("cannot capture after video finalization")
        for name in ("head_stereo_left", "head_stereo_right", "front_stereo_left", "front_stereo_right"):
            if name not in self.obs:
                continue
            frame = np.asarray(self.obs[name])
            if frame.ndim != 3 or frame.shape[-1] != 3 or frame.dtype != np.uint8:
                raise ValueError(f"native RGB camera {name} malformed")
            if name not in self.writers:
                self.writers[name] = RGBVideoWriter(self.artifact_dir / f"{name}.mp4", frame.shape[1], frame.shape[0])
            self.writers[name].append_data(frame)
        self.frame_count += 1
        result = {"frame": str(frame_path.relative_to(self.artifact_dir)), "instruction": self.instruction}
        if self.proprioception:
            from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import ACTION_NAMES
            encoders = self.raw.mujoco.get_robot_qpos()
            result["joint_positions"] = {name: float(encoders[name]) for name in ACTION_NAMES[:31]}
            public_observation({"head_stereo_left": self.obs["head_stereo_left"],
                "joint_positions": result["joint_positions"]}, self.steps, self.instruction, True)
        return result

    def finalize(self):
        if not self.finalized:
            for writer in self.writers.values():
                writer.close()
            self.finalized = True
        artifacts = {"native_provenance": "native_provenance.json", "native_log": "native_worker.log"}
        videos = []
        for name in self.writers:
            path = self.artifact_dir / f"{name}.mp4"
            videos.append({**fingerprint(path), "frames": self.frame_count, "fps": 50})
            artifacts[f"video_{name}"] = path.name
        write_json(self.artifact_dir / "video_manifest.json", videos)
        artifacts["video_manifest"] = "video_manifest.json"
        return artifacts

    def close(self):
        result = self.finalize() if self.artifact_dir else {}
        if self.env is not None:
            self.env.close()
        return result


def main():
    output = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    runtime = NativeRuntime()
    for line in sys.stdin:
        request = json.loads(line)
        try:
            op = request["op"]
            if op == "reset":
                result = runtime.reset(request)
            elif op == "step":
                result = runtime.step(request["action"])
            elif op == "finalize":
                result = runtime.finalize()
            elif op == "close":
                result = runtime.close()
            else:
                raise ValueError("unknown private worker operation")
            output.write(json.dumps({"ok": True, "result": result}, allow_nan=False) + "\n")
            if op == "close":
                break
        except BaseException as exc:
            error = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            traceback.print_exc()
            if runtime.artifact_dir:
                write_json(runtime.artifact_dir / "native_error.json", error)
                try:
                    runtime.finalize()
                except Exception:
                    traceback.print_exc()
            output.write(json.dumps({"ok": False, **error}) + "\n")
    output.close()


if __name__ == "__main__":
    main()
