"""Lazy native construction and passive instrumentation for the clean qpos track.

No simulator is imported by the adapter factory or readiness command. The
native task owns scene generation, control interpolation and success checks.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import importlib.metadata
import json
import math
from numbers import Real
import os
from pathlib import Path
import sys

from benchkit.errors import CompatibilityError, ProtocolError
from benchmarks.simBenchmarks.Robotwin.environment.deployment import digest, reference_snapshot, verify

NATIVE_INVENTORY_SHA256 = "ab5a73b0482d50d9c83e8702b37e7e7eb10bf7033e03a8fec59b60b708bef08c"
RUNTIME_SNAPSHOT = Path(__file__).with_name("runtime_snapshot.json")
RUNTIME_SNAPSHOT_SHA256 = "b1b7ecba4723d9fecdcdf79e0323817ccd05cc58cb12cd7af56ad2e4fefd4d28"
BUNDLED_RENDERER = "bundled_oidn_2_0_1"
COMPAT_RENDERER = "oidn_2_3_3_cuda_v1"
RENDERER_RUNTIMES = (BUNDLED_RENDERER, COMPAT_RENDERER)
TASK_INSTRUCTIONS = {
    "lift_pot": "use BOTH!!! arms to lift the pot",
    "click_bell": "click the <bell's top center> on the table",
}
JOINT_NAMES = tuple(f"f{side}_joint{i}" for side in ("l", "r") for i in range(1, 7))
STATE_NAMES = tuple(name for side, prefix in (("left", "fl"), ("right", "fr"))
                    for name in (*(f"measured_{prefix}_joint{i}_rad" for i in range(1, 7)),
                                 f"commanded_{side}_gripper_01"))


def validate_robot_state(state) -> tuple[float, ...]:
    """Validate the public mixed-provenance vector without clipping encoders."""
    if not isinstance(state, (tuple, list)) or len(state) != len(STATE_NAMES):
        raise ProtocolError("RoboTwin robot state must contain 14 values in the declared order")
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in state):
        raise ProtocolError("RoboTwin robot state must contain finite real numbers, not booleans")
    try:
        values = tuple(float(value) for value in state)
    except (OverflowError, ValueError) as exc:
        raise ProtocolError("RoboTwin robot state must contain finite real numbers") from exc
    if any(not math.isfinite(value) for value in values):
        raise ProtocolError("RoboTwin robot state must contain finite real numbers")
    if any(not 0 <= values[index] <= 1 for index in (6, 13)):
        raise ProtocolError("RoboTwin cached gripper commands must be in [0,1]")
    # Arm encoders are measurements, not accepted action targets. In particular,
    # do not apply the action specification's authored joint limits here.
    return values


def robot_state(env) -> tuple[float, ...]:
    """Read the pinned native encoder APIs once per side; never use drive targets.

    Each native getter returns six measured articulation qpos entries followed
    by the last normalized set_gripper command, NOT a measured finger position.
    These getters read robot state only and do not advance native physics.
    """
    values = []
    for side in ("left", "right"):
        try:
            getter = getattr(env.robot, f"get_{side}_arm_real_jointState")
            row = getter()
        except Exception as exc:
            raise CompatibilityError(f"RoboTwin native {side} measured-state getter failed") from exc
        if not isinstance(row, (tuple, list)) or len(row) != 7:
            raise CompatibilityError(f"RoboTwin native {side} measured-state getter must return 7 values")
        values.extend(row)
    try:
        return validate_robot_state(values)
    except ProtocolError as exc:
        raise CompatibilityError("RoboTwin native robot-state values differ from the declared contract") from exc


def state_provenance() -> dict:
    """Static sensor declaration; safe for provenance without native calls."""
    return {
        "names": list(STATE_NAMES),
        "sources": ["robot.get_left_arm_real_jointState()", "robot.get_right_arm_real_jointState()"],
        "measured_arm_joint_indices": [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12],
        "measured_arm_joint_source": "left/right_entity.get_qpos(), indexed by left/right_arm_joints",
        "measured_arm_joint_units": "radians",
        "commanded_gripper_indices": [6, 13],
        "commanded_gripper_source": "get_left/right_gripper_val(): cached left/right_gripper_val from native set_gripper",
        "commanded_gripper_semantics": "last normalized command in [0,1], 0 closed / 1 open; not measured finger position",
        "sampling": "after setup_demo and each take_action; getter reads only, no added control or physics",
        "raw_joint_action_vector_used": False,
        "measured_arm_joint_clipping": False,
    }


@contextmanager
def native_directory(root: Path, jit_cache: Path | None = None):
    """The native archive uses relative asset paths; service calls are serial."""
    previous = Path.cwd()
    previous_cache = os.environ.get("TORCH_EXTENSIONS_DIR")
    if jit_cache is not None and (not jit_cache.is_absolute() or jit_cache.resolve().is_relative_to(root.resolve())):
        raise CompatibilityError("native JIT cache must be an owned absolute directory outside the deployment")
    try:
        os.chdir(root)
        if jit_cache is not None:
            os.environ["TORCH_EXTENSIONS_DIR"] = str(jit_cache)
        yield
    finally:
        os.chdir(previous)
        if jit_cache is not None:
            if previous_cache is None:
                os.environ.pop("TORCH_EXTENSIONS_DIR", None)
            else:
                os.environ["TORCH_EXTENSIONS_DIR"] = previous_cache


def verify_runtime(renderer_runtime: str = BUNDLED_RENDERER) -> dict:
    """Read files/metadata only, including the actual native TOPP implementation.

    This pins SAPIEN/MPLib/TOPPRA package files and dependency versions. It does
    not attest a GPU driver, loaded memory, every transitive package or CUDA JIT
    output. The receipt reports those limits instead of claiming a full lockfile.
    """
    if renderer_runtime not in RENDERER_RUNTIMES:
        raise CompatibilityError("unknown RoboTwin renderer runtime track")
    if digest(RUNTIME_SNAPSHOT) != RUNTIME_SNAPSHOT_SHA256:
        raise CompatibilityError("packaged RoboTwin runtime snapshot changed")
    expected = json.loads(RUNTIME_SNAPSHOT.read_text())
    original_sapien_rows = expected["packages"]["sapien"]["files"]
    if renderer_runtime == COMPAT_RENDERER:
        from benchmarks.simBenchmarks.Robotwin.environment import oidn_compat
        expected["packages"]["sapien"]["files"] = oidn_compat.package_rows(original_sapien_rows)
    if sys.version.split()[0] != expected["python"]:
        raise CompatibilityError(f"RoboTwin requires the inspected Python {expected['python']} runtime")
    versions = {}
    file_counts = {}
    compatibility = None
    for name, requirement in expected["packages"].items():
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise CompatibilityError(f"missing RoboTwin dependency: {name}") from exc
        if distribution.version != requirement["version"]:
            raise CompatibilityError(f"RoboTwin {name} version differs from the inspected runtime")
        versions[name] = distribution.version
        if "files" not in requirement:
            continue
        actual = {str(path) for path in (distribution.files or ())
                  if str(path).split("/")[0] == name and "__pycache__" not in str(path)
                  and not str(path).endswith((".pyc", ".pyo"))}
        if actual != {row["path"] for row in requirement["files"]}:
            raise CompatibilityError(f"RoboTwin {name} package inventory differs")
        for row in requirement["files"]:
            path = Path(distribution.locate_file(row["path"]))
            if (not path.is_file() or path.is_symlink() or path.stat().st_size != row["size_bytes"]
                    or digest(path) != row["sha256"]):
                raise CompatibilityError(f"RoboTwin native dependency content differs: {name}/{row['path']}")
        # Detect unrecorded source overrides as well as changed distribution rows.
        package = Path(distribution.locate_file(name))
        disk = {path.relative_to(package.parent).as_posix() for path in package.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
                and path.suffix not in (".pyc", ".pyo")}
        if disk != actual:
            raise CompatibilityError(f"unrecorded RoboTwin native package files: {name}")
        file_counts[name] = len(actual)
        if name == "sapien" and renderer_runtime == COMPAT_RENDERER:
            compatibility = oidn_compat.verify_overlay(distribution, original_sapien_rows)
    report = {"python": sys.version.split()[0], "executable": sys.executable,
            "package_versions": versions, "content_pinned_package_files": file_counts,
            "runtime_snapshot_sha256": RUNTIME_SNAPSHOT_SHA256,
            "runtime_scope": "SAPIEN/MPLib/TOPPRA file content plus listed dependency versions; not a complete environment/driver/JIT attestation"}
    if compatibility is not None:
        report["renderer_compatibility"] = compatibility
    return report


def readiness(root: Path, manifest_sha256: str, renderer_runtime: str = BUNDLED_RENDERER) -> dict:
    if reference_snapshot()["inventory_sha256"] != NATIVE_INVENTORY_SHA256:
        raise CompatibilityError("packaged RoboTwin native content identity changed")
    try:
        deployment = verify(root, manifest_sha256)
    except (OSError, ValueError) as exc:
        raise CompatibilityError("RoboTwin deployment verification failed") from exc
    return {"deployment": deployment, "runtime": verify_runtime(renderer_runtime), "native_resets": 0,
            "status": "files_verified_not_native_validated"}


def verify_loaded_renderer(provenance: dict, *, require_cuda_plugin: bool) -> dict:
    compatibility = provenance.get("runtime", {}).get("renderer_compatibility")
    if compatibility is None:
        return {}
    from benchmarks.simBenchmarks.Robotwin.environment import oidn_compat
    return oidn_compat.verify_loaded(Path(compatibility["overlay_root"]), require_cuda_plugin=require_cuda_plugin)


def resolved_native_config(root: Path, task: str) -> dict:
    import yaml
    with (root / "task_config/demo_clean.yml").open() as stream:
        config = yaml.safe_load(stream)
    with (root / "assets/embodiments/aloha-agilex/config.yml").open() as stream:
        embodiment = yaml.safe_load(stream)
    with (root / "task_config/_camera_config.yml").open() as stream:
        cameras = yaml.safe_load(stream)
    with (root / "task_config/_eval_step_limit.yml").open() as stream:
        horizons = yaml.safe_load(stream)
    description = json.loads((root / f"description/task_instruction/{task}.json").read_text())
    if (description["full_description"] != TASK_INSTRUCTIONS[task]
            or config["embodiment"] != ["aloha-agilex"]
            or horizons[task] != 400
            or cameras["D435"]["h"] != 240 or cameras["D435"]["w"] != 320
            or embodiment["arm_joints_name"] != [list(JOINT_NAMES[:6]), list(JOINT_NAMES[6:])]
            or embodiment["gripper_scale"] != [-0.01, 0.045]
            or embodiment["planner"] != "curobo"):
        raise CompatibilityError("native task/language/camera/controller configuration differs")
    robot_file = str(root / "assets/embodiments/aloha-agilex")
    # Preserve demo_clean's semantic fields. These are the native evaluator's
    # resolved construction fields; there is no model checkpoint or policy hook.
    config.update({"task_name": task, "task_config": "demo_clean", "eval_mode": True,
                   "left_robot_file": robot_file, "right_robot_file": robot_file,
                   "left_embodiment_config": embodiment, "right_embodiment_config": embodiment,
                   "dual_arm_embodied": True, "head_camera_h": 240, "head_camera_w": 320,
                   "save_data": False, "eval_video_save_dir": None})
    return config


SEED_MANIFEST_SCHEMA = "starvla-rsi.robotwin.accepted-seeds/v1"
MAX_ACCEPTED_COUNT = 100  # native eval_policy.py test_num
MAX_START_SEED = 100000  # native st_seed = 100000 * (1 + eval seed 0)
MAX_INSTRUCTION_TYPE = "unseen"  # native deploy_policy.yml default
REJECTION_REASONS = frozenset({"unstable", "exception", "expert_check_fail"})  # native screen branches
SEED_MANIFEST_KEYS = {"schema", "task", "task_config", "embodiment", "native_inventory_sha256", "eval_seed",
                      "start_seed", "accepted_count", "instruction_type", "accepted", "rejected", "preparation"}
PREPARATION_KEYS = frozenset({"deployment_manifest_sha256", "renderer_runtime", "created_at", "procedure"})
MAX_PREPARATION = "prepare it offline as described in environment/README.md (accepted-seed preparation)"


def _strict_json(data: bytes):
    def pairs(items):
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate JSON key")
        return dict(items)

    def constant(name):
        raise ValueError(f"non-finite JSON number {name}")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def load_accepted_seeds(path: Path, expected_hash: str | None, task: str,
                        deployment_hash: str | None = None) -> dict:
    """Startup gate for `max`: the complete offline screening record, or refuse.

    The service never screens; it replays the recorded accepted seeds and the
    native instruction drawn for each one during preparation.
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"RoboTwin max mode needs the accepted-seed manifest file; {MAX_PREPARATION}")
    data = path.read_bytes()
    actual_hash = hashlib.sha256(data).hexdigest()
    if expected_hash is not None and actual_hash != expected_hash:  # a supplied pin must match
        raise ValueError("RoboTwin seed manifest SHA256 differs from seed_manifest_sha256")
    identity = {"sha256": actual_hash, "pinned": expected_hash is not None}  # unpinned: observed hash recorded only
    try:
        record = _strict_json(data)
    except ValueError as exc:
        raise ValueError(f"RoboTwin seed manifest is not strict JSON: {exc}") from exc
    if not isinstance(record, dict) or set(record) != SEED_MANIFEST_KEYS or record["schema"] != SEED_MANIFEST_SCHEMA:
        raise ValueError(f"RoboTwin seed manifest must be {SEED_MANIFEST_SCHEMA} with exactly its declared fields")
    expected = {"task": task, "task_config": "demo_clean", "embodiment": ["aloha-agilex"],
                "native_inventory_sha256": NATIVE_INVENTORY_SHA256, "eval_seed": 0,
                "start_seed": MAX_START_SEED, "accepted_count": MAX_ACCEPTED_COUNT,
                "instruction_type": MAX_INSTRUCTION_TYPE}
    differs = sorted(key for key, value in expected.items()  # strict: False/0 and 100000.0/100000 differ
                     if not (type(record[key]) is type(value) and record[key] == value))
    if differs:
        raise ValueError(f"RoboTwin seed manifest was not prepared for this max track ({', '.join(differs)} differ); "
                         + MAX_PREPARATION)
    accepted, rejected, preparation = record["accepted"], record["rejected"], record["preparation"]
    if (not isinstance(accepted, list) or len(accepted) != MAX_ACCEPTED_COUNT
            or any(not isinstance(row, dict) or set(row) != {"seed", "instruction"} for row in accepted)):
        raise ValueError(f"RoboTwin max mode needs exactly {MAX_ACCEPTED_COUNT} accepted "
                         f"{{seed, instruction}} rows; {MAX_PREPARATION}")
    seeds = [row["seed"] for row in accepted]
    if any(type(seed) is not int for seed in seeds) or seeds != sorted(set(seeds)):
        raise ValueError("RoboTwin accepted seeds must be unique ascending integers")
    for row in accepted:  # native template output: placeholders already filled in
        text = row["instruction"]
        if (not isinstance(text, str) or not text.strip() or len(text) > 1000 or not text.isprintable()
                or "{" in text or "}" in text):
            raise ValueError(f"RoboTwin seed {row['seed']} needs its recorded native instruction text")
    if (not isinstance(rejected, list)
            or any(not isinstance(row, dict) or set(row) != {"seed", "reason"} or type(row["seed"]) is not int
                   or not isinstance(row["reason"], str) or row["reason"] not in REJECTION_REASONS
                   for row in rejected)):
        raise ValueError("RoboTwin rejections need an integer seed and reason unstable, exception or expert_check_fail")
    # A contiguous walk from start_seed to the 100th acceptance proves no seed was skipped or hidden.
    if sorted(seeds + [row["seed"] for row in rejected]) != list(range(MAX_START_SEED, seeds[-1] + 1)):
        raise ValueError("RoboTwin seed manifest is not one contiguous screening walk from seed 100000; "
                         + MAX_PREPARATION)
    if (not isinstance(preparation, dict) or not PREPARATION_KEYS <= set(preparation)
            or any(not isinstance(preparation[key], str) or not preparation[key].strip() for key in PREPARATION_KEYS)):
        raise ValueError("RoboTwin seed manifest needs non-empty preparation provenance strings: "
                         "deployment_manifest_sha256, renderer_runtime, created_at and procedure")
    if deployment_hash is not None and preparation["deployment_manifest_sha256"] != deployment_hash:
        raise ValueError("RoboTwin seed manifest was prepared on a different deployment_manifest_sha256; "
                         + MAX_PREPARATION)
    reasons = {}
    for row in rejected:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    # Rejections are preparation provenance, never policy results.
    return {"accepted": [(row["seed"], row["instruction"]) for row in accepted], "identity": identity,
            "screening": {"accepted": len(accepted), "rejected": len(rejected),
                          "rejection_reasons": dict(sorted(reasons.items())),
                          "last_accepted_seed": seeds[-1], "preparation": preparation}}


def create_native(root: Path, task: str):
    if not sys.dont_write_bytecode:
        raise CompatibilityError("start RoboTwin server with python -B; native source must not gain bytecode caches")
    roots = {"envs": root / "envs", "curobo": root / "envs/curobo/src/curobo"}
    for prefix, directory in roots.items():
        for name, module in tuple(sys.modules.items()):
            if name == prefix or name.startswith(prefix + "."):
                filename = getattr(module, "__file__", None)
                if filename is not None and not Path(filename).resolve().is_relative_to(directory):
                    raise CompatibilityError(f"native module already imported from another root: {name}")
    for path in (root / "envs/curobo/src", root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    with native_directory(root):
        module = importlib.import_module(f"envs.{task}")
        for prefix, directory in roots.items():
            loaded = sys.modules.get(prefix)
            if loaded is None or not Path(loaded.__file__).resolve().is_relative_to(directory):
                raise CompatibilityError(f"native module origin differs: {prefix}")
        return getattr(module, task)()


def verify_compiled_control(env) -> dict:
    """Fail before model control if the authored 14-D contract did not compile."""
    import numpy as np
    robot = env.robot
    joints = tuple(robot.left_arm_joints) + tuple(robot.right_arm_joints)
    names = tuple(joint.get_name() for joint in joints)
    limits = [np.asarray(joint.get_limits(), dtype=float) for joint in joints]
    if (names != JOINT_NAMES or any(row.shape != (1, 2) or not np.array_equal(row, [[-10., 10.]]) for row in limits)
            or list(robot.left_gripper_scale) != [-0.01, 0.045]
            or list(robot.right_gripper_scale) != [-0.01, 0.045]
            or not robot.is_dual_arm or robot.communication_flag
            or env.step_lim != 400 or env.take_action_cnt != 0
            or not math.isclose(float(env.scene.get_timestep()), 1 / 250, rel_tol=0, abs_tol=1e-9)):
        raise CompatibilityError("compiled RoboTwin joint bounds, gripper, horizon or physics timestep differ")
    return {"joint_names": list(names), "arm_joint_bounds_radians": [-10.0, 10.0],
            "gripper_command_range": [0.0, 1.0], "gripper_native_scale_m": [-0.01, 0.045],
            "native_horizon": env.step_lim, "physics_timestep_s": float(env.scene.get_timestep()),
            "native_planners_initialized": True, "expert_play_once_called": False,
            "model_action_type": "qpos", "physics_ticks_per_control": "variable native TOPP duration"}


class SceneStepCounter:
    """Delegating view installed after native reset; counts completed scene.step.

    Initialization retains the original SAPIEN scene object. Robot/planner/camera
    native handles are not replaced. Only the task's subsequent scene.step calls
    pass through this view; no clock or extra physics action is introduced.
    """
    def __init__(self, scene):
        self.scene, self.steps = scene, 0

    def step(self):
        result = self.scene.step()
        self.steps += 1
        return result

    def __getattr__(self, name):
        return getattr(self.scene, name)


class TOPPRecorder:
    """Observe native TOPP's existing failures; never replace its result/path."""
    def __init__(self, planner, side, events):
        self.planner, self.side, self.events = planner, side, events

    def TOPP(self, *args, **kwargs):
        try:
            result = self.planner.TOPP(*args, **kwargs)
        except Exception as exc:
            self.events.append({"side": self.side, "status": "native_exception",
                                "error_type": type(exc).__name__, "native_fallback_ticks": 50})
            raise  # The pinned native controller catches this, unchanged.
        samples = int(result[1].shape[0])
        self.events.append({"side": self.side, "status": "native_zero_samples" if samples == 0 else "native_path",
                            "samples": samples, "native_fallback_ticks": 50 if samples == 0 else 0})
        return result

    def __getattr__(self, name):
        return getattr(self.planner, name)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Read-only RoboTwin file/runtime readiness; no native imports/reset")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--renderer-runtime", choices=RENDERER_RUNTIMES, default=BUNDLED_RENDERER)
    args = parser.parse_args(argv)
    print(json.dumps(readiness(args.root, args.manifest_sha256, args.renderer_runtime), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
