"""Reset/render/one measured-position hold; never a policy capability score.

Simulator and oracle access in this tool is evaluator-private diagnostic access.
The action is fixed infrastructure logic, not an evaluated model decision.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

CASA_REVISION = "4840e671596f93ca03651524b9f72ffb1aadfeff"
SUITE_REVISION = "51cc01785bab80ffeed20da15e67d7dd4140e76a"
OBJECT_INVENTORY_SHA256 = "f5cae285846c2afa55db6909027d8454242e217f54f21856cbf68a91bdcc0c7b"
TASK = "gr1_unified/PnPCupToDrawerClose_GR1ArmsAndWaistFourierHands_Env"
PARTS = (("left_arm", "left", 7), ("right_arm", "right", 7),
         ("left_hand", "left_gripper", 6), ("right_hand", "right_gripper", 6),
         ("waist", "torso", 3))


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def verify_source(root: Path, revision: str, package: str) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).strip()

    expected_blobs = None
    if package == "robosuite":
        manifest = json.loads(Path(__file__).with_name("robosuite-source-manifest.json").read_text())
        if manifest["revision"] != revision:
            raise RuntimeError("archive manifest revision mismatch")
        expected_blobs = manifest["files"]
        relative_paths = list(expected_blobs)
        source_layout = "full non-asset git archive, every file verified against pinned upstream git blob IDs"
    else:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root.resolve():
            raise RuntimeError("native source must have its own Git checkout")
        if git("rev-parse", "HEAD") != revision:
            raise RuntimeError(f"unexpected source revision for {root}")
        if git("diff", "--name-only", "HEAD", "--", ".", f":(exclude){package}/models/assets/**"):
            raise RuntimeError(f"tracked source changes in {root}")
        relative_paths = git("ls-files").splitlines()
        source_layout = "pinned sparse code checkout with explicit external assets overlay"
    assets = root / package / "models" / "assets"
    if not assets.is_symlink() or not assets.resolve().is_dir():
        raise RuntimeError(f"explicit external asset symlink required: {assets}")
    hashes = {}
    for relative in relative_paths:
        if relative.startswith(f"{package}/models/assets/"):
            continue
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"missing tracked source file: {path}")
        data = path.read_bytes()
        if expected_blobs is not None:
            blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if blob != expected_blobs[relative]["git_blob_sha1"]:
                raise RuntimeError(f"source archive differs from pinned git blob: {relative}")
        hashes[relative] = hashlib.sha256(data).hexdigest()
    observed_paths = set()
    for directory, subdirectories, names in os.walk(root, followlinks=False):
        observed_paths.update((Path(directory) / name).relative_to(root).as_posix()
                              for name in subdirectories
                              if (Path(directory) / name).is_symlink()
                              and Path(directory) / name != assets)
        subdirectories[:] = [name for name in subdirectories
                             if name not in (".git", "__pycache__")
                             and Path(directory) / name != assets]
        for name in names:
            path = Path(directory) / name
            if path != assets:
                observed_paths.add(path.relative_to(root).as_posix())
    if observed_paths != set(hashes):
        raise RuntimeError(f"unmanifested or missing non-asset source files: {sorted(observed_paths ^ set(hashes))}")
    return {"root": str(root), "revision": revision, "tracked_code_sha256": hashes,
            "source_layout": source_layout,
            "asset_overlay": str(assets.resolve()),
            "assets_complete": "not established by directory presence"}


def gpu_identity(gpu: int) -> dict:
    identity = subprocess.check_output([
        "nvidia-smi", f"--id={gpu}", "--query-gpu=uuid,name,memory.used",
        "--format=csv,noheader,nounits"], text=True).strip()
    return {"physical_index": gpu, "identity": identity}


def measured_hold_and_contract(native) -> tuple[dict, dict]:
    import numpy as np

    robot = native.robots[0]
    sim = native.sim
    cc = robot.composite_controller
    action, contract = {}, []
    for public, part, size in PARTS:
        controller = cc.part_controllers[part]
        components = []
        if part in cc.grippers:
            if controller.use_action_scaling:
                raise RuntimeError("GR1 hand controller unexpectedly scales actions")
            gripper = cc.grippers[part]
            expansion = np.asarray(gripper.format_action(np.arange(size)), dtype=int)
            actuator_ids = robot._ref_actuators_indexes_dict[part]
            if len(expansion) != len(actuator_ids):
                raise RuntimeError("hand expansion/actuator order mismatch")
            for index in range(size):
                ids = [int(aid) for aid, value in zip(actuator_ids, expansion) if value == index]
                joint_ids = [int(sim.model.actuator_trnid[aid, 0]) for aid in ids]
                limits = [sim.model.jnt_range[jid] for jid in joint_ids]
                limits += [sim.model.actuator_ctrlrange[aid] for aid in ids]
                low = max(float(pair[0]) for pair in limits)
                high = min(float(pair[1]) for pair in limits)
                current = float(np.mean([sim.data.qpos[sim.model.jnt_qposadr[jid]] for jid in joint_ids]))
                components.append({"index": index, "joint_names": [sim.model.joint_id2name(jid) for jid in joint_ids],
                                   "actuator_names": [sim.model.actuator_id2name(aid) for aid in ids],
                                   "low": low, "high": high, "measured": current})
        else:
            if controller.input_type != "absolute":
                raise RuntimeError(f"{part} is not absolute JOINT_POSITION")
            joint_ids = robot._ref_joints_indexes_dict[part]
            if len(joint_ids) != size:
                raise RuntimeError(f"unexpected {part} joint count")
            for index, jid in enumerate(joint_ids):
                jid = int(jid)
                low, high = sim.model.jnt_range[jid]
                components.append({"index": index, "joint_names": [sim.model.joint_id2name(jid)],
                                   "low": float(low), "high": float(high),
                                   "measured": float(sim.data.qpos[sim.model.jnt_qposadr[jid]])})
        values = []
        for item in components:
            if item["low"] > item["high"]:
                raise RuntimeError("coupled joints have incompatible ranges")
            # Infrastructure hold only: soft joint limits can allow slight reset overshoot.
            target = min(item["high"], max(item["low"], item["measured"]))
            item["hold_target"] = target
            item["hold_clamped"] = target != item["measured"]
            values.append(target)
        action["action." + public] = np.array(values, dtype=np.float64)
        contract.append({"name": public, "native_part": part, "size": size,
                         "controller": type(controller).__name__, "components": components})
    if sum(len(value) for value in action.values()) != 29:
        raise RuntimeError("expected exactly 29 native action values")
    return action, {"mode": "absolute_joint_position", "units": "radians", "size": 29,
                    "control_hz": native.control_freq, "parts": contract,
                    "hand_mapping": "native Fourier format_action and compiled actuator order",
                    "bounds": "joint limits; hands intersect coupled joint and actuator position limits",
                    "generic_gym_bounds_are_not_authoritative": True}


def measured_state_contract(native, observation) -> dict:
    """Identify only native ordinary encoders, not object/EEF/root world state."""
    import numpy as np
    from robocasa.models.robots import unformat_gripper_space

    robot = native.robots[0]
    cc = robot.composite_controller
    parts = []
    for public, part, size in PARTS:
        joint_ids = np.asarray(robot._ref_joints_indexes_dict[part], dtype=int)
        if part in cc.grippers:
            joint_ids = unformat_gripper_space(cc.grippers[part], joint_ids)[::-1].astype(int)
        if len(joint_ids) != size:
            raise RuntimeError("unexpected robot encoder dimension")
        expected = np.asarray([native.sim.data.qpos[native.sim.model.jnt_qposadr[jid]]
                               for jid in joint_ids], dtype=np.float32)
        if not np.array_equal(expected, observation["state." + public]):
            raise RuntimeError("native observation encoder order differs from documented mapping")
        parts.append({"name": public, "native_key": "state." + public, "size": size,
                      "joint_names": [native.sim.model.joint_id2name(int(jid)) for jid in joint_ids],
                      "joint_limits": [native.sim.model.jnt_range[jid].tolist() for jid in joint_ids]})
    return {"size": 29, "units": "radians", "parts": parts,
            "semantics": "native robot joint encoders; hands use native unformat then reverse ordering",
            "excluded": ["object state", "EEF pose", "world root pose", "native metadata", "success"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casa-source", type=Path, required=True)
    parser.add_argument("--suite-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--object-inventory", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260907)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {"kind": "environment_diagnostic_not_model_evaluation", "task": TASK,
              "policy_calls": 0, "diagnostic_steps": 0, "status": "initializing", "errors": [],
              "diagnostic_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    env = None
    write_json(output / "diagnostic_result.json", result)
    write_json(output / "diagnostic_status.json", {"status": "initializing"})
    try:
        if os.environ.get("PYTHONHASHSEED") != "0":
            raise RuntimeError("launch with PYTHONHASHSEED=0 before Python starts")
        inventory = json.loads(args.object_inventory.read_text())
        canonical = json.dumps(inventory["files"], sort_keys=True, separators=(",", ":")).encode()
        if (hashlib.sha256(canonical).hexdigest() != OBJECT_INVENTORY_SHA256
                or inventory["inventory_sha256"] != OBJECT_INVENTORY_SHA256
                or not inventory.get("comparison", {}).get("matches")
                or inventory["file_count"] != 42994
                or inventory["total_regular_bytes"] != 6843155836):
            raise RuntimeError("complete object-asset parity inventory is not verified")
        result["object_asset_inventory"] = {key: value for key, value in inventory.items() if key != "files"}
        result["object_asset_inventory"]["artifact_path"] = str(args.object_inventory.resolve())
        result["gpu"] = gpu_identity(args.gpu)
        result["source"] = {
            "robocasa": verify_source(args.casa_source, CASA_REVISION, "robocasa"),
            "robosuite": verify_source(args.suite_source, SUITE_REVISION, "robosuite")}
        write_json(output / "native_source_provenance.json", result.pop("source"))
        expected_objects = args.casa_source / "robocasa" / "models" / "assets" / "objects"
        if expected_objects.resolve() != Path(inventory["root"]).resolve():
            raise RuntimeError("native source asset overlay differs from the verified object inventory root")
        os.environ["MUJOCO_GL"] = "egl"
        os.environ["PYOPENGL_PLATFORM"] = "egl"
        os.environ["MUJOCO_EGL_DEVICE_ID"] = str(args.gpu)
        os.environ["NUMBA_CACHE_DIR"] = str(output / "numba_cache")
        sys.path[:0] = [str(args.casa_source.resolve()), str(args.suite_source.resolve())]
        import av
        import gymnasium as gym
        import numpy as np
        from PIL import Image
        import robocasa
        import robosuite
        from robocasa.utils.gym_utils import GrootRoboCasaEnv  # registers native environments

        result["versions"] = {name: importlib.metadata.version(name) for name in
                              ("mujoco", "gymnasium", "numpy", "numba", "av")}
        result["native_import_paths"] = {"robocasa": robocasa.__file__, "robosuite": robosuite.__file__}
        result["installed_packages"] = dict(sorted(
            (distribution.metadata["Name"], distribution.version)
            for distribution in importlib.metadata.distributions()))
        result["seed"] = args.seed
        result["python_hash_seed"] = "0"
        write_json(output / "diagnostic_status.json", {"status": "creating_native_environment"})
        env = gym.make(TASK, enable_render=True, seed=args.seed)
        observation, _ = env.reset(seed=args.seed)
        native = env.unwrapped.env
        action, contract = measured_hold_and_contract(native)
        write_json(output / "native_action_contract.json", contract)
        write_json(output / "native_state_contract.json", measured_state_contract(native, observation))
        initial_state = native.sim.get_state().flatten()
        np.save(output / "initial_state.npy", initial_state, allow_pickle=False)
        write_json(output / "native_episode_metadata.json", native.get_ep_meta())
        result["initial_state_sha256"] = hashlib.sha256(initial_state.tobytes()).hexdigest()
        result["layout_id"], result["style_id"] = int(native.layout_id), int(native.style_id)
        result["layout_and_style_candidate_pairs"] = [[int(layout), int(style)]
                                                      for layout, style in native.layout_and_style_ids]
        result["explicit_resets"] = 1
        write_json(output / "diagnostic_hold_action.json", {key: value.tolist() for key, value in action.items()})
        camera = "video.ego_view_bg_crop_pad_res256_freq20"
        frames = [np.asarray(observation[camera]).copy()]
        Image.fromarray(frames[0]).save(output / "reset.png")
        result["observation_keys"] = sorted(observation)
        result["native_instruction"] = observation["annotation.human.coarse_action"]
        result["native_success_at_reset"] = bool(native._check_success())
        write_json(output / "diagnostic_status.json", {"status": "executing_one_measured_hold"})
        observation, reward, terminated, truncated, info = env.step(action)
        result["diagnostic_steps"] = 1
        if not np.isfinite(native.sim.data.qpos).all():
            raise RuntimeError("non-finite native qpos after measured hold")
        cc = native.robots[0].composite_controller
        result["controller_goal_matches_hold"] = {}
        result["hand_actuator_controls_match_hold"] = {}
        for public, part, _ in PARTS:
            expected = action["action." + public]
            controller = cc.part_controllers[part]
            if part in cc.grippers:
                expected = cc.grippers[part].format_action(expected)
                actual = controller.goal_qvel
                actuator_ids = native.robots[0]._ref_actuators_indexes_dict[part]
                controls_match = bool(np.array_equal(native.sim.data.ctrl[actuator_ids], expected))
                result["hand_actuator_controls_match_hold"][public] = controls_match
                if not controls_match:
                    raise RuntimeError(f"native position actuators differ from hand hold: {part}")
            else:
                actual = controller.goal_qpos
            matches = bool(np.array_equal(expected, actual))
            result["controller_goal_matches_hold"][public] = matches
            if not matches:
                raise RuntimeError(f"native controller goal differs from declared hold: {part}")
        frames.append(np.asarray(observation[camera]).copy())
        Image.fromarray(frames[1]).save(output / "after_hold.png")
        result.update(native_reward=float(reward), native_success=bool(info["success"]),
                      native_oracle_success=bool(native._check_success()),
                      terminated=bool(terminated), truncated=bool(truncated),
                      frame_shape=list(frames[0].shape),
                      frame_std=[float(frame.std()) for frame in frames])
        if result["native_success"] != result["native_oracle_success"]:
            raise RuntimeError("native Gym success and task oracle disagree")
        if frames[0].shape != (256, 256, 3) or frames[0].dtype != np.uint8 or frames[0].std() < 1:
            raise RuntimeError("native RGB frame failed shape/dtype/nonblank validation")
        with av.open(str(output / "diagnostic.mp4"), "w") as video:
            stream = video.add_stream("libx264", rate=20)
            stream.width, stream.height, stream.pix_fmt = 256, 256, "yuv420p"
            for rgb in frames:
                for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                    video.mux(packet)
            for packet in stream.encode():
                video.mux(packet)
        with av.open(str(output / "diagnostic.mp4")) as video:
            result["decoded_video_frames"] = sum(1 for _ in video.decode(video=0))
        if result["decoded_video_frames"] != 2:
            raise RuntimeError("diagnostic video should decode exactly two frames")
        result["status"] = "completed"
    except Exception as error:
        result["status"] = "failed"
        result["errors"].append({"type": type(error).__name__, "message": str(error),
                                 "traceback": traceback.format_exc()})
    finally:
        if env is not None:
            try:
                env.close()
            except Exception as error:
                result["status"] = "failed"
                result["errors"].append({"type": type(error).__name__, "message": str(error), "phase": "close"})
        write_json(output / "diagnostic_result.json", result)
        write_json(output / "diagnostic_status.json", {"status": result["status"]})
    print(json.dumps(result, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
