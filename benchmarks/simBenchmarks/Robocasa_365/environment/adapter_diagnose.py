"""Fixed infrastructure-only action schedule through the unified runner; never a capability pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import traceback
from dataclasses import replace
from pathlib import Path

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import (
    ACTION_SPEC, PILOT_SEED, RoboCasa365BenchmarkAdapter, RoboCasa365Episode,
    action_dictionary,
)
from benchkit.contracts import ActionChunk, PolicyDecision, PolicyDescriptor
from AgentPolicies.gpt6_astra.tools.runner import EvaluationRunner, RunRequest


def diagnostic_actions():
    actions = [(0.,) * 12]
    for index in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10):
        action = [0.] * 12
        action[index] = 0.02
        action[11] = float(index in (7, 8, 9))
        actions.append(tuple(action))
    actions.append((0.,) * 11 + (1.,))
    return tuple(actions)


class DiagnosticPolicy:
    descriptor = PolicyDescriptor("fixed-small-motion-diagnostic", "infrastructure_diagnostic", version="1",
        parameters={"capability_attempt": False, "schedule": [list(a) for a in diagnostic_actions()],
                    "provider_requests": 0, "adaptive_policy": False})

    def compatibility_errors(self, observation_spec, action_spec):
        for action in diagnostic_actions():
            action_spec.validate(action)
        return []

    def start_episode(self, context):
        pass

    def act(self, observation):
        return PolicyDecision(action=ActionChunk.from_steps([diagnostic_actions()[observation.step]]))

    def end_episode(self):
        pass


class InstrumentedSession(RoboCasa365Episode):
    """Records controller inputs/goals on the evaluator side; never gives them to policy."""

    def reset(self):
        observation = super().reset()
        import numpy as np
        import robosuite.utils.transform_utils as transforms
        native = self.env.unwrapped.env
        controllers = native.robots[0].composite_controller.part_controllers
        self.direction_records = []
        self.current_action = (0.,) * 12

        def record(part, fields, checks):
            item = {"step": self.step_count + 1, "part": part, **fields,
                    "checks": {key: bool(value) for key, value in checks.items()}}
            append_jsonl(self.artifact_dir / "direction_checks.jsonl", item)
            self.direction_records.append(item)
            if not all(checks.values()):
                raise AssertionError(f"native controller direction/scale mismatch: {item}")

        arm = controllers["right"]
        original_arm = arm.set_goal

        def arm_goal(action, *args, **kwargs):
            command = np.array(action, copy=True)
            old_pos = None if arm.goal_pos is None else arm.goal_pos.copy()
            old_rot = None if arm.goal_ori is None else arm.goal_ori.copy()
            result = original_arm(action, *args, **kwargs)
            pose = arm.goal_origin_to_eef_pose()
            desired = arm._goal_update_mode == "desired"
            baseline_pos = old_pos if desired and old_pos is not None else pose[:3, 3]
            baseline_rot = old_rot if desired and old_rot is not None else pose[:3, :3]
            position_change = arm.goal_pos - baseline_pos
            rotation_change = arm.goal_ori @ baseline_rot.T
            expected_rotation = transforms.quat2mat(transforms.axisangle2quat(command[3:] * .5))
            record("arm", {"command": command.tolist(), "position_goal_change": position_change.tolist(),
                           "rotation_goal_change": rotation_change.tolist(), "goal_update_mode": arm._goal_update_mode},
                   {"position_scale_frame": np.allclose(position_change, command[:3] * .05, atol=1e-7),
                    "rotation_scale_frame": np.allclose(rotation_change, expected_rotation, atol=1e-7),
                    "binary_mode_mapping": desired == bool(self.current_action[11])})
            return result

        arm.set_goal = arm_goal
        base = controllers["base"]
        original_base = base.set_goal
        original_base_pose = base.get_base_pose
        sampled_base_pose = []

        def base_pose():
            pose = original_base_pose()
            sampled_base_pose.append((pose[0].copy(), pose[1].copy()))
            return pose

        base.get_base_pose = base_pose

        def base_goal(action, *args, **kwargs):
            command = np.array(action, copy=True)
            sampled_base_pose.clear()
            result = original_base(action, *args, **kwargs)
            # Native update() can forward physics before this pose is read.
            # Observe the exact read made by native set_goal, without a second
            # call or a stale observation from before its update().
            _, orientation = sampled_base_pose[-1]
            theta = transforms.mat2euler(orientation)[2] - transforms.mat2euler(base.init_ori)[2]
            expected = command.copy()
            # RoboCasa's kitchen constructor replaces the JSON base type with
            # JOINT_VELOCITY_LEGACY. For this pin's X-forward Omron joints its
            # native branch applies +theta, unlike the nonlegacy controller.
            expected[:2] = [command[0] * np.cos(theta) - command[1] * np.sin(theta),
                            command[0] * np.sin(theta) + command[1] * np.cos(theta)]
            record("base", {"command": command.tolist(), "initial_frame_velocity": base.goal_qvel.tolist(),
                            "expected_initial_frame_velocity": expected.tolist()},
                   {"current_to_initial_frame": np.allclose(base.goal_qvel, expected, atol=1e-7),
                    "actuator_scale": np.allclose(base.actuator_max, [1., 1., 1.5])})
            return result

        base.set_goal = base_goal
        torso = controllers["torso"]
        original_torso = torso.set_goal

        def torso_goal(action, *args, **kwargs):
            command = np.array(action, copy=True)
            result = original_torso(action, *args, **kwargs)
            change = torso.goal_qpos - torso.joint_pos
            record("torso", {"command": command.tolist(), "position_goal_change": change.tolist()},
                   {"delta_scale": np.allclose(change, command * .05, atol=1e-7)})
            return result

        torso.set_goal = torso_goal
        for binary in (0., 1.):
            action = [0.] * 12
            action[6] = action[11] = binary
            mapped = self.env.unwrapped.key_converter.unmap_action(action_dictionary(action))
            expected = -1. if binary == 0. else 1.
            if mapped["robot0_right_gripper"] != expected or mapped["robot0_base_mode"] != expected:
                raise AssertionError("native binary key conversion changed")
        return observation

    def step(self, action):
        self.current_action = tuple(action)
        native = self.env.unwrapped.env
        before = native.sim.get_state().flatten().copy()
        transition = super().step(action)
        after = native.sim.get_state().flatten()
        import numpy as np
        append_jsonl(self.artifact_dir / "diagnostic_physics.jsonl", {
            "step": self.step_count, "state_l2_change": float(np.linalg.norm(after - before)),
            "note": "physics response is recorded; controller target scales determine the contract",
        })
        return transition

    def artifacts(self):
        files = dict(super().artifacts())
        if self.artifact_dir is not None:
            for name in ("direction_checks.jsonl", "diagnostic_physics.jsonl"):
                if (self.artifact_dir / name).exists():
                    files[name] = str(self.artifact_dir / name)
        return files


class DiagnosticAdapter(RoboCasa365BenchmarkAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.descriptor = replace(self.descriptor,
            protocol_version=self.descriptor.protocol_version + "/infrastructure-direction-diagnostic")

    def open_episode(self, episode):
        if episode not in self.episodes(PILOT_SEED):
            raise ValueError("unexpected diagnostic episode")
        return InstrumentedSession(self, episode)


def validate_artifacts(run):
    import av
    from PIL import Image
    episodes = []
    for result_path in sorted((run / "episodes").glob("*/result.json")):
        result = json.loads(result_path.read_text())
        artifacts = result_path.parent / "artifacts"
        if result["status"] != "completed" or result["environment_steps"] != len(diagnostic_actions()):
            raise AssertionError(f"diagnostic episode did not complete its fixed action schedule: {result_path}")
        frame_rows = [json.loads(line) for line in (artifacts / "frames.jsonl").read_text().splitlines()]
        for row in frame_rows:
            path = artifacts / row["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise AssertionError("PNG hash mismatch")
            with Image.open(path) as image:
                image.load()
                if image.size != (256, 256) or image.mode != "RGB":
                    raise AssertionError("PNG shape/mode mismatch")
        videos = []
        for path in sorted(artifacts.glob("*.mp4")):
            with av.open(str(path)) as video:
                decoded = list(video.decode(video=0))
                if len(decoded) != len(diagnostic_actions()) + 1:
                    raise AssertionError("video frame count mismatch")
            videos.append({"path": path.name, "frames": len(decoded),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        directions = [json.loads(line) for line in (artifacts / "direction_checks.jsonl").read_text().splitlines()]
        if len(directions) != 3 * len(diagnostic_actions()) or not all(all(row["checks"].values()) for row in directions):
            raise AssertionError("direction checks incomplete")
        assets = json.loads((artifacts / "used_assets.json").read_text())
        if not assets["complete"]:
            raise AssertionError("asset closure incomplete")
        episodes.append({"episode": result["episode"]["id"], "native_steps": result["environment_steps"],
                         "diagnostic_decisions": result["policy_calls"], "png_count": len(frame_rows),
                         "videos": videos, "direction_records": len(directions),
                         "used_asset_files": assets["file_count"], "used_asset_bytes": assets["total_bytes"]})
    return episodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=3)
    parser.add_argument("--render-track", choices=("native-v1", "egl-owner-restore-v1", "egl-owner-material-clamp-v1"), default="native-v1")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    status = args.output / "diagnostic_status.json"
    atomic_write_json(status, {"status": "running", "capability_attempt": False})
    source = Path(__file__).read_bytes()
    (args.output / "diagnostic_source.py").write_bytes(source)
    os.environ["MUJOCO_GL"] = "egl"
    os.environ["PYOPENGL_PLATFORM"] = "egl"
    try:
        benchmark = DiagnosticAdapter(render_gpu_device_id=args.gpu, render_track=args.render_track, budget_mode="decisions",
            max_policy_calls=len(diagnostic_actions()), replan_interval=1)
        run = EvaluationRunner().run(benchmark, DiagnosticPolicy(), RunRequest(
            args.output, seed=PILOT_SEED, run_id="unified-native-direction-diagnostic",
            max_steps=len(diagnostic_actions()), max_policy_calls=len(diagnostic_actions()),
            replan_interval=1, budget_mode="decisions", fail_fast=True,
        ))
        episodes = validate_artifacts(run)
        if len(episodes) != 2:
            raise AssertionError("both preselected diagnostic tasks must be checked")
        atomic_write_json(args.output / "diagnostic_result.json", {"status": "passed",
            "capability_attempt": False, "episodes": episodes,
            "diagnostic_source_sha256": hashlib.sha256(source).hexdigest()})
        atomic_write_json(status, {"status": "passed", "capability_attempt": False})
        print(args.output, "passed", flush=True)
    except Exception as exc:
        atomic_write_json(args.output / "diagnostic_result.json", {"status": "failed", "capability_attempt": False,
            "error": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}})
        atomic_write_json(status, {"status": "failed", "capability_attempt": False})
        raise


if __name__ == "__main__":
    main()
