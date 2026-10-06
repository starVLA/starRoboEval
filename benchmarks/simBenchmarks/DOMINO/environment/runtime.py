"""Private lazy native binding; no task search or policy code."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

from benchkit.errors import CompatibilityError
from benchmarks.simBenchmarks.DOMINO.bench_server.protocol import (
    CAMERAS, CUROBO_REVISION, INSTRUCTION, JOINT_NAMES, NATIVE_HORIZON,
    NATIVE_REVISION, RUNTIME_VERSIONS, TASK, TASK_CONFIG,
)
from benchmarks.simBenchmarks.DOMINO.environment.deployment import digest, inventory, verify_rows, verify_curobo_asset_paths


@contextmanager
def native_directory(root: Path, cache: Path):
    if not cache.is_absolute() or cache.resolve().is_relative_to(root.resolve()):
        raise CompatibilityError("JIT cache must be outside the verified native deployment")
    previous, previous_cache = Path.cwd(), os.environ.get("TORCH_EXTENSIONS_DIR")
    try:
        os.chdir(root)
        os.environ["TORCH_EXTENSIONS_DIR"] = str(cache)
        yield
    finally:
        os.chdir(previous)
        if previous_cache is None:
            os.environ.pop("TORCH_EXTENSIONS_DIR", None)
        else:
            os.environ["TORCH_EXTENSIONS_DIR"] = previous_cache


def readiness(root: Path, expected_digest: str) -> dict:
    path = root / "deployment.json"
    if digest(path) != expected_digest:
        raise CompatibilityError("DOMINO deployment manifest hash differs")
    record = json.loads(path.read_text())
    if (record["schema"] != "domino.owned-deployment/v1"
            or record["native_source"]["revision"] != NATIVE_REVISION
            or record["curobo_source"]["revision"] != CUROBO_REVISION):
        raise CompatibilityError("DOMINO native/CuRobo identity differs")
    verify_rows(root, record["files"], exact=False)
    if [r["path"] for r in inventory(root) if r["path"] != "deployment.json"] != [r["path"] for r in record["files"]]:
        raise CompatibilityError("DOMINO deployment contains unrecorded files")
    runtime = record["runtime"]
    if sys.version.split()[0] != runtime["python"] or runtime["versions"] != RUNTIME_VERSIONS:
        raise CompatibilityError("DOMINO compatibility runtime declaration differs")
    for name, version in RUNTIME_VERSIONS.items():
        dist = importlib.metadata.distribution(name)
        if dist.version != version:
            raise CompatibilityError(f"DOMINO runtime version differs: {name}")
        if name in runtime["packages"]:
            item = runtime["packages"][name]
            package = Path(dist.locate_file(name)).resolve()
            if package != Path(item["root"]):
                raise CompatibilityError(f"DOMINO package location differs: {name}")
            verify_rows(package, item["files"])
    return {"schema": record["schema"], "deployment_manifest_sha256": expected_digest,
            "native_revision": NATIVE_REVISION, "curobo_revision": CUROBO_REVISION,
            "runtime": runtime, "native_resets": 0,
            "track": "SM120 compatibility; not upstream Torch2.4.1 runtime parity"}


def import_native(root: Path):
    if not sys.dont_write_bytecode:
        raise CompatibilityError("launch with python -B to preserve native source")
    roots = {"envs": root / "envs", "curobo": root / "envs/curobo/src/curobo",
             "eval_metrics": root / "script", "episode_manifest": root / "script"}
    for prefix, directory in roots.items():
        for name, module in tuple(sys.modules.items()):
            if name == prefix or name.startswith(prefix + "."):
                filename = getattr(module, "__file__", None)
                if filename and not Path(filename).resolve().is_relative_to(directory):
                    raise CompatibilityError(f"native module already loaded from another root: {name}")
    for directory in (root / "script", root / "envs/curobo/src", root):
        sys.path.insert(0, str(directory))
    task_class = getattr(importlib.import_module(f"envs.{TASK}"), TASK)
    tracker_class = importlib.import_module("eval_metrics").EvalMetricsTracker
    manifest_class = importlib.import_module("episode_manifest").EpisodeManifest
    for prefix, directory in roots.items():
        module = sys.modules.get(prefix)
        if module is None or not Path(module.__file__).resolve().is_relative_to(directory):
            raise CompatibilityError(f"native import origin differs: {prefix}")
    return task_class, tracker_class, manifest_class


def resolved_config(root: Path) -> dict:
    import yaml
    for side in ("left", "right"):
        path = root / f"assets/embodiments/aloha-agilex/curobo_{side}.yml"
        verify_curobo_asset_paths(root, yaml.safe_load(path.read_text()))
    config = yaml.safe_load((root / f"task_config/{TASK_CONFIG}.yml").read_text())
    embodiment = yaml.safe_load((root / "assets/embodiments/aloha-agilex/config.yml").read_text())
    cameras = yaml.safe_load((root / "task_config/_camera_config.yml").read_text())
    horizon = yaml.safe_load((root / "task_config/_eval_step_limit.yml").read_text())[TASK]
    instruction = json.loads((root / f"description/task_instruction/{TASK}.json").read_text())["full_description"]
    if (config["embodiment"] != ["aloha-agilex"] or not config["use_dynamic"]
            or config["dynamic_level"] != 1 or config["dynamic_coefficient"] != 0.1
            or config["domain_randomization"]["random_background"]
            or config["domain_randomization"]["cluttered_table"]
            or cameras["D435"]["w"] != 320 or cameras["D435"]["h"] != 240
            or horizon != NATIVE_HORIZON or instruction != INSTRUCTION
            or embodiment["arm_joints_name"] != [list(JOINT_NAMES[:6]), list(JOINT_NAMES[6:])]
            or embodiment["gripper_scale"] != [-0.01, 0.045]):
        raise CompatibilityError("native task/config/controller differs from declared track")
    robot = str(root / "assets/embodiments/aloha-agilex")
    config.update(task_name=TASK, task_config=TASK_CONFIG, eval_mode=True,
                  left_robot_file=robot, right_robot_file=robot,
                  left_embodiment_config=embodiment, right_embodiment_config=embodiment,
                  dual_arm_embodied=True, head_camera_h=240, head_camera_w=320,
                  save_data=False, eval_video_save_dir=None, eval_video_log=False)
    return config


def load_entry(path: Path, expected_hash: str, native_seed: int, config: dict, manifest_class):
    # Administrative local file only, never a client upload. Hash before pickle.
    if path.is_symlink() or not path.is_file() or digest(path) != expected_hash:
        raise CompatibilityError("trusted fixed-episode manifest identity differs")
    manifest = manifest_class.load(str(path))
    manifest.validate_against(config)
    if manifest.metadata.get("git_commit") != NATIVE_REVISION:
        raise CompatibilityError("manifest must be generated at pinned DOMINO revision")
    matches = [entry for entry in manifest.entries if type(entry.get("seed")) is int and entry["seed"] == native_seed]
    if len(matches) != 1 or matches[0].get("dynamic_motion_info") is None:
        raise CompatibilityError("exactly one declared seed with dynamic motion is required")
    return deepcopy(matches[0])


def verify_compiled(env) -> dict:
    names = tuple(j.get_name() for j in (*env.robot.left_arm_joints, *env.robot.right_arm_joints))
    timestep = 1 / 250
    # SAPIEN stores the native timestep in binary32 (24 significant bits).
    # Permit only its rounding error: half an ULP at 1/250, not a changed rate.
    half_float32_ulp = math.ldexp(1.0, math.frexp(timestep)[1] - 25)
    if (names != JOINT_NAMES or env.step_lim != NATIVE_HORIZON or env.take_action_cnt != 0
            or not math.isclose(env.scene.get_timestep(), timestep, rel_tol=0.0, abs_tol=half_float32_ulp)):
        raise CompatibilityError("compiled DOMINO action order/horizon/physics differs")
    return {"joint_names": list(names), "physics_timestep_s": timestep,
            "action_type": "qpos", "native_horizon": NATIVE_HORIZON,
            "ticks_per_control": "variable native TOPP interpolation"}


def verify_loaded_renderer(provenance: dict) -> list[str]:
    """Linux loaded-file check, not an attestation of GPU identity or memory."""
    root = Path(provenance["runtime"]["packages"]["sapien"]["root"])
    paths = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        if "libOpenImageDenoise" in line:
            filename = line.split()[-1]
            path = Path(filename)
            if not path.is_absolute() or not path.resolve().is_relative_to(root):
                raise CompatibilityError("unrecorded OIDN library loaded")
            paths.add(filename)
    if not any(".so.2.3.3" in path for path in paths) or not any("device_cuda" in path for path in paths):
        raise CompatibilityError("declared OIDN2.3.3 CUDA renderer is not loaded")
    return sorted(paths)


class SceneStepCounter:
    def __init__(self, scene):
        self.scene, self.steps = scene, 0

    def step(self):
        result = self.scene.step()
        self.steps += 1
        return result

    def __getattr__(self, name):
        return getattr(self.scene, name)
