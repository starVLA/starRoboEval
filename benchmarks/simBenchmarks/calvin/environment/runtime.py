"""Lazy, private CALVIN native loader. This module itself is stdlib-only."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from benchkit.errors import CompatibilityError, ProtocolError

NATIVE_REVISION = "fa03f01f19c65920e18cf37398a9ce859274af76"
SNAPSHOT_SHA256 = "d2d62ee402ef61b2b6f93cbd1cc37640c9a6ad1f58b538fb25ebb877d6f25343"
TASK_CONFIG = "calvin_models/conf/callbacks/rollout/tasks/new_playtable_tasks.yaml"
LANGUAGE_CONFIG = "calvin_models/conf/annotations/new_playtable_validation.yaml"
DATASET_CONFIG = "validation/.hydra/merged_config.yaml"
SCENE = "calvin_scene_D"  # Native D table, as declared by the D->D validation config.


def _pinned_json(path, digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise CompatibilityError(f"CALVIN pinned input differs: {path.name}")
    return json.loads(raw)


def dataset_scene(dataset_root: Path):
    """Stdlib read of the setup config's top-level `scene.name`; None if absent."""
    in_scene = False
    for line in (dataset_root / DATASET_CONFIG).read_text().splitlines():
        if line and not line[0].isspace():
            in_scene = line.rstrip() == "scene:"
        elif in_scene and line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
    return None


def _git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments], stderr=subprocess.PIPE, timeout=120)


def verify_tree(root: Path, revision: str, expected_count: int):
    if (Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root.resolve()
            or _git(root, "rev-parse", "HEAD").decode().strip() != revision):
        raise CompatibilityError(f"CALVIN own Git root/revision differs: {root}")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise CompatibilityError(f"CALVIN native Git tree/index is not clean: {root}")
    rows = []
    for entry in _git(root, "ls-tree", "-rz", "HEAD").split(b"\0"):
        if not entry:
            continue
        header, relative = entry.split(b"\t", 1)
        mode, kind, blob = header.split()
        if kind == b"commit":
            continue  # Each pinned nested repository is checked independently.
        name = relative.decode("utf-8")
        path = root / name
        if mode not in (b"100644", b"100755") or path.is_symlink() or not path.is_file():
            raise CompatibilityError(f"CALVIN source must be an original regular file: {name}")
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != blob.decode() or data.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise CompatibilityError(f"CALVIN actual source/asset bytes differ: {name}")
        rows.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    if len(rows) != expected_count:
        raise CompatibilityError("CALVIN native regular-file inventory differs")
    # Ignored bytecode is harmless only because launch requires -B and the
    # loader below rejects every pre-existing .pyc in the imported package.
    return {"root": str(root), "revision": revision, "regular_files": rows}


def readiness(source_root: Path, dataset_root: Path):
    snapshot = _pinned_json(Path(__file__).with_name("runtime_snapshot.json"), SNAPSHOT_SHA256)
    if (list(sys.version_info[:2]) != snapshot["python"] or platform.system() != "Linux"
            or platform.machine() != "x86_64" or not sys.dont_write_bytecode):
        raise CompatibilityError("CALVIN debug runtime requires Linux x86_64 Python 3.10 launched with -B")
    sources = [verify_tree(source_root / relative, revision,
                           snapshot["native_regular_file_counts"][relative])
               for relative, revision in snapshot["native_revisions"].items()]
    for relative, digest in snapshot["native_files"].items():
        if hashlib.sha256((source_root / relative).read_bytes()).hexdigest() != digest:
            raise CompatibilityError(f"CALVIN native evaluator/config identity differs: {relative}")
    config = dataset_root / snapshot["debug_config"]["path"]
    data = config.read_bytes()
    if (config.is_symlink() or len(data) != snapshot["debug_config"]["bytes"]
            or hashlib.sha256(data).hexdigest() != snapshot["debug_config"]["sha256"]):
        raise CompatibilityError("only the unchanged official debug configuration is implemented")
    packages = {}
    for line in Path(__file__).with_name("requirements-rgb-setup.txt").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, version = line.split("==")
        if importlib.metadata.version(name) != version:
            raise CompatibilityError(f"CALVIN dependency version differs: {name}")
        packages[name] = version
    for package, files in snapshot["package_binary_sha256"].items():
        distribution = importlib.metadata.distribution(package)
        for name, digest in files.items():
            if hashlib.sha256(Path(distribution.locate_file(name)).read_bytes()).hexdigest() != digest:
                raise CompatibilityError(f"CALVIN runtime binary differs: {package}/{name}")
    return {"source_trees": sources, "native_source_revision": NATIVE_REVISION,
            "runtime_snapshot_sha256": SNAPSHOT_SHA256, "runtime_scope": snapshot["scope"],
            "dependency_versions": packages, "debug_config": {**snapshot["debug_config"], "root": str(dataset_root)},
            "original_debug_archive": snapshot["original_debug_archive"],
            "runtime_environment": {key: os.environ.get(key) for key in
                                    ("CUDA_VISIBLE_DEVICES", "EGL_VISIBLE_DEVICES", "PYOPENGL_PLATFORM")}}


def verify_loaded_native_modules(package_root):
    for name, module in tuple(sys.modules.items()):
        if name == "calvin_env" or name.startswith("calvin_env."):
            origin = getattr(module, "__file__", None)
            if origin:
                valid = Path(origin).resolve().is_relative_to(package_root)
            else:
                # The pinned source has PEP 420 namespace subdirectories (envs,
                # robot, camera). Verify their actual search roots, not a
                # fabricated __init__.py requirement.
                paths = list(getattr(module, "__path__", ()))
                expected = package_root.joinpath(*name.split(".")[1:])
                valid = len(paths) == 1 and Path(paths[0]).resolve() == expected
            if not valid:
                raise CompatibilityError(f"CALVIN loaded module outside the pinned source: {name}")


def _native_imports(source_root):
    package_root = (source_root / "calvin_env" / "calvin_env").resolve()
    # Do not run stale bytecode or ignored/untracked Python import overrides.
    known = {row.split(b"\t", 1)[1].decode() for row in
             _git(source_root / "calvin_env", "ls-tree", "-rz", "HEAD").split(b"\0") if row}
    for path in package_root.rglob("*"):
        if path.is_symlink():
            raise CompatibilityError(f"native CALVIN import tree must not contain symlinks: {path}")
        if path.is_file() and (path.suffix in (".pyc", ".pyo", ".so")
                               or path.suffix == ".py" and str(path.relative_to(package_root.parent)) not in known):
            raise CompatibilityError(f"unexpected native CALVIN executable file: {path}")
    for name in sys.modules:
        if name == "torch" or name.startswith(("torch.", "calvin_agent.")) or name == "calvin_agent":
            raise CompatibilityError("CALVIN RGB service must not import learned-model evaluation helpers")
    verify_loaded_native_modules(package_root)
    expected_path = str(package_root.parent)
    if expected_path in sys.path:
        sys.path.remove(expected_path)
    sys.path.insert(0, expected_path)
    env_module = importlib.import_module("calvin_env.envs.play_table_env")
    importlib.import_module("calvin_env.envs.tasks")
    verify_loaded_native_modules(package_root)
    return env_module


def resolved_config(source_root, dataset_root, language=None):
    from omegaconf import OmegaConf
    cfg = OmegaConf.load(dataset_root / DATASET_CONFIG)
    if (cfg.scene.name != SCENE or cfg.env._target_ != "calvin_env.envs.play_table_env.PlayTableSimEnv"
            or cfg.env.seed != 0 or cfg.env.bullet_time_step != 240.0 or cfg.env.control_freq != 30
            or not cfg.env.use_egl or list(cfg.env.cameras) != ["static", "gripper", "tactile"]
            or cfg.env.robot_cfg.use_ik_fast or cfg.env.robot_cfg.filename != "franka_panda/panda_longer_finger.urdf"):
        raise CompatibilityError("CALVIN original debug configuration semantics differ")
    del cfg.env.cameras.tactile  # Same RGB-only omission as the retained evaluator.
    cfg.env.show_gui, cfg.env.use_vr, cfg.env.use_scene_info = False, False, True
    annotation = OmegaConf.load(source_root / LANGUAGE_CONFIG)
    # Every selected {task: instruction} must be the native annotation [task][0].
    if language is not None and any(annotation[task][0] != text for task, text in language.items()):
        raise CompatibilityError("CALVIN selected native language differs")
    return cfg


class PhysicsTrace:
    """Passive ticks; reject alien/nested clients before native default-client APIs."""
    def __init__(self, bullet):
        self.bullet = bullet
        self.original_connect, self.original_step = bullet.connect, bullet.stepSimulation
        self.clients = []
        self.phase = "construction"
        self.completed_ticks = {"construction": 0, "reset": 0, "control": 0}
        self.started_ticks = {"construction": 0, "reset": 0, "control": 0}
        self.installed = False

    def connect(self, *args, **kwargs):
        result = self.original_connect(*args, **kwargs)
        if isinstance(result, int) and result >= 0:
            self.clients.append(result)
            if result != 0 or len(self.clients) != 1:
                raise CompatibilityError("CALVIN native construction requires its sole owned Bullet client 0")
        return result

    def step(self, *args, **kwargs):
        self.started_ticks[self.phase] += 1
        result = self.original_step(*args, **kwargs)
        self.completed_ticks[self.phase] += 1
        return result

    def install(self):
        if self.installed or getattr(self.bullet, "_rsi_calvin_trace_owner", None) is not None:
            raise ProtocolError("CALVIN supports one physics trace owner, never nested/shared runtimes")
        self.bullet.connect, self.bullet.stepSimulation = self.connect, self.step
        self.bullet._rsi_calvin_trace_owner = self
        self.installed = True

    def restore(self):
        if self.installed:
            self.bullet.connect, self.bullet.stepSimulation = self.original_connect, self.original_step
            del self.bullet._rsi_calvin_trace_owner
            self.installed = False


class NativeRuntime:
    """Own even a partially initialized native object; construction is explicit."""
    def __init__(self, module, cfg, oracle):
        self.env = module.PlayTableSimEnv.__new__(module.PlayTableSimEnv)
        self.env.p, self.env.cid, self.env.ownsPhysicsClient = module.p, -1, False
        self.trace = PhysicsTrace(module.p)
        self.cfg, self.oracle = cfg, oracle
        self.constructed = False
        self.previous_opengl = os.environ.get("PYOPENGL_PLATFORM")

    def construct(self):
        if self.env.p.isConnected(physicsClientId=0):
            raise CompatibilityError("CALVIN needs a fresh dedicated process with no existing Bullet client 0")
        self.trace.install()
        kwargs = {key: self.cfg.env[key] for key in self.cfg.env if not key.startswith("_")}
        self.env.__init__(**kwargs)
        self.constructed = True
        robot = self.env.robot
        if (self.env.cid != 0 or self.env.use_vr or self.env.show_gui or not self.env.use_egl or self.env.action_repeat != 8
                or self.env.control_freq != 30 or not self.env.use_scene_info
                or robot.use_ik_fast or not robot.use_target_pose or not robot.euler_obs
                or robot.max_rel_pos != 0.02 or robot.max_rel_orn != 0.05
                or robot.magic_scaling_factor_pos != 1 or robot.magic_scaling_factor_orn != 1
                or list(robot.gripper_joint_limits) != [0, 0.04]
                or [camera.name for camera in self.env.cameras] != ["static", "gripper"]):
            raise CompatibilityError("CALVIN compiled native control/camera contract differs")

    def close(self):
        receipt = {"constructed": self.constructed, "native_close_returned": False,
                   "clients": list(self.trace.clients), "orphan_disconnects": [],
                   "disconnected": [], "error_types": []}
        errors = []
        try:
            self.env.close()
            receipt["native_close_returned"] = True
        except BaseException as exc:
            errors.append(exc)
        for cid in self.trace.clients:
            try:
                # Native assigns self.cid only after EGL plugin loading. A
                # failure before that point needs cleanup of its recorded ID;
                # this is not a second attempt at an errored disconnect.
                if cid != self.env.cid and self.env.p.isConnected(physicsClientId=cid):
                    self.env.p.disconnect(physicsClientId=cid)
                    receipt["orphan_disconnects"].append(cid)
                if self.env.p.isConnected(physicsClientId=cid):
                    raise ProtocolError("native CALVIN physics client remains connected")
                receipt["disconnected"].append(cid)
            except BaseException as exc:
                errors.append(exc)
        # Native __del__ calls close again. Ownership is bookkeeping, not a
        # simulator operation; disarm it after this explicit cleanup attempt.
        self.env.ownsPhysicsClient = False
        self.trace.restore()
        if self.previous_opengl is None:
            os.environ.pop("PYOPENGL_PLATFORM", None)
        else:
            os.environ["PYOPENGL_PLATFORM"] = self.previous_opengl
        receipt["error_types"] = [type(exc).__name__ for exc in errors]
        return receipt, errors


def prepare_native(source_root, dataset_root, language):
    module = _native_imports(source_root)
    import hydra
    from omegaconf import OmegaConf
    cfg = resolved_config(source_root, dataset_root, language)
    oracle = hydra.utils.instantiate(OmegaConf.load(source_root / TASK_CONFIG))
    if oracle.num_tasks != 34:
        raise CompatibilityError("CALVIN native oracle must expose 34 configured predicates")
    return NativeRuntime(module, cfg, oracle)


def import_preflight(source_root, dataset_root):
    """Readiness plus module/config imports only: no native object allocated."""
    receipt = readiness(source_root, dataset_root)
    _native_imports(source_root)
    cfg = resolved_config(source_root, dataset_root)
    from omegaconf import OmegaConf
    receipt["resolved_environment_config"] = OmegaConf.to_container(cfg.env, resolve=True)
    receipt["native_constructions"] = receipt["native_resets"] = receipt["native_controls"] = 0
    return receipt
