"""Pinned GR1 Tabletop selections: RGB/encoders to 29 absolute joint targets.

No simulator imports occur at module import or adapter construction. Native
state, scene metadata, source checks and scoring remain evaluator-private.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from importlib import resources
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import (
    ActionSpec, BenchmarkDescriptor, EpisodeSpec, JsonValue, Observation,
    ObservationSpec, Transition,
)
from benchkit.errors import CompatibilityError, InfrastructureError, ProtocolError

SCHEDULE_SEED = 20261020  # launch --seed; sample k resets with SCHEDULE_SEED + k
EVALUATION_MODES = ("fast", "max", "example")  # fast: blog subset; example: first fast episode
MODE_SAMPLES = {"fast": 2, "max": 10, "example": 1}  # seeded samples per task
NATIVE_ENGINE_HORIZON = 1000  # robosuite engine setting; ignore_done=True, so it never ends an episode
EVALUATED_STEP_CAP = 720  # upstream simulation_service --max_episode_steps; one control per service step
CAMERA = "ego_view_bg_crop_pad_res256_freq20"
CAMERA_KEY = "video." + CAMERA
LANGUAGE_KEY = "annotation.human.coarse_action"
PARTS = (("left_arm", "left", 7), ("right_arm", "right", 7),
         ("left_hand", "left_gripper", 6), ("right_hand", "right_gripper", 6),
         ("waist", "torso", 3))
# Distinguish an omitted EGL device from an explicit null.
_UNSET_EGL_DEVICE = object()


def frozen_contract() -> dict[str, Any]:
    payload = json.loads(resources.files("benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.protocol")
                         .joinpath("robocasa_tabletop_contract.json").read_text())
    if (payload["schema_version"] != "starvla-rsi.robocasa_tabletop.contract/v1"
            or payload["action"]["size"] != 29 or payload["state"]["size"] != 29):
        raise CompatibilityError("packaged Tabletop contract identity differs")
    return payload


_FROZEN = frozen_contract()


def task_catalog() -> dict[str, Any]:
    payload = json.loads(resources.files("benchmarks.simBenchmarks.Robocasa_tabletop.bench_server.protocol")
                         .joinpath("task_catalog.json").read_text())
    rows = payload["tasks"]
    if (payload["schema_version"] != "starvla-rsi.robocasa_tabletop.tasks/v1"
            or payload["task_scope"] != "tabletop24-seeded-v1"
            or payload["native_revision"] != _FROZEN["sources"]["robocasa"]["revision"]
            or payload["schedule_order"] != "sample-major/task-minor"
            or payload["official_full_protocol"] is not False
            or payload["candidate_style_ids"] != list(range(12))
            or [row["native_task_index"] for row in rows] != list(range(24))
            or len({row["task"] for row in rows}) != 24
            or [row["candidate_layout_ids"] for row in rows] != [[i] for i in [4, 2, 2, 5, 5, 4] + [0] * 18]
            or any(not row["task"].startswith("gr1_unified/") or not
                   row["task"].endswith("_GR1ArmsAndWaistFourierHands_Env") for row in rows)):
        raise CompatibilityError("packaged Tabletop task catalog identity differs")
    return payload


_CATALOG = task_catalog()
OFFICIAL_TASKS = {row["native_task_index"]: row["task"] for row in _CATALOG["tasks"]}
OFFICIAL_TASK_LAYOUTS = {row["native_task_index"]: row["candidate_layout_ids"][0] for row in _CATALOG["tasks"]}
_COMPONENTS = tuple(component for part in _FROZEN["action"]["parts"] for component in part["components"])
ACTION_SPEC = ActionSpec(
    mode="absolute_joint_position", size=29,
    names=tuple("+".join(component["joint_names"]) for component in _COMPONENTS),
    low=tuple(component["low"] for component in _COMPONENTS),
    high=tuple(component["high"] for component in _COMPONENTS), control_hz=20.,
    frame="robot joint coordinates; absolute position targets in radians; no Cartesian pose action",
    rotation="joint angles in radians; no Euler/axis-angle end-effector command",
    gripper="6 Fourier position commands per hand: pinky, ring, middle, index, thumb pitch, thumb yaw; "
            "native expansion [0,0,1,1,2,2,3,3,4,4,5]; paired limits intersected; no clipping",
)
STATE_NAMES = tuple(name for part in _FROZEN["state"]["parts"] for name in part["joint_names"])


def policy_observation(raw: Mapping[str, Any], step: int) -> Observation:
    """Copy exactly one native crop, its task language, and 29 ordinary encoders."""
    import numpy as np

    if CAMERA_KEY not in raw or LANGUAGE_KEY not in raw:
        raise ProtocolError("native observation omitted the declared RGB/language channels")
    frame = np.asarray(raw[CAMERA_KEY])
    if frame.shape != (256, 256, 3) or frame.dtype != np.uint8:
        raise ProtocolError("Tabletop camera must be native 256x256 uint8 RGB")
    instruction = raw[LANGUAGE_KEY]
    if not isinstance(instruction, str) or not instruction.strip():
        raise ProtocolError("native task language must be nonempty text")
    values = []
    for public, _, size in PARTS:
        key = "state." + public
        if key not in raw:
            raise ProtocolError(f"missing native ordinary encoder channel: {key}")
        part = np.asarray(raw[key])
        if part.shape != (size,) or part.dtype.kind not in "fi" or not np.isfinite(part).all():
            raise ProtocolError(f"invalid native encoder shape/type/values: {key}")
        values.extend(float(value) for value in part)
    # In particular, do not forward another view, raw metadata, reward/success,
    # EEF/object true poses, world root pose, reset parameters or simulator state.
    return Observation(step, instruction, {CAMERA: np.ascontiguousarray(frame).copy()}, tuple(values))


def action_dictionary(action: Sequence[float]) -> dict[str, Any]:
    import numpy as np

    values = ACTION_SPEC.validate(action)
    mapped, offset = {}, 0
    for public, _, size in PARTS:
        mapped["action." + public] = np.asarray(values[offset:offset + size], dtype=np.float64)
        offset += size
    return mapped


def file_digest(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def verify_source(root: Path, package: str) -> dict[str, Any]:
    """Verify the entire non-asset file set, including absence of private overrides."""
    expected = _FROZEN["sources"][package]
    root = root.resolve(strict=True)
    assets = root / package / "models" / "assets"
    if not assets.is_symlink() or not assets.resolve().is_dir():
        raise CompatibilityError("this runtime requires an explicit external asset symlink")
    actual_paths = set()
    for directory, subdirectories, names in os.walk(root, followlinks=False):
        actual_paths.update((Path(directory) / name).relative_to(root).as_posix()
                            for name in subdirectories if (Path(directory) / name).is_symlink()
                            and Path(directory) / name != assets)
        subdirectories[:] = [name for name in subdirectories if name != ".git"
                             and Path(directory) / name != assets]
        actual_paths.update((Path(directory) / name).relative_to(root).as_posix()
                            for name in names if Path(directory) / name != assets)
    if actual_paths != set(expected["files"]):
        raise CompatibilityError("native non-asset file set differs from the complete frozen source manifest")
    for relative, digest in expected["files"].items():
        path = root / relative
        if path.is_symlink() or file_digest(path)["sha256"] != digest:
            raise CompatibilityError(f"native source file differs: {package}/{relative}")
    layout = "complete pinned non-asset archive; SHA256 checked for every file"
    if (root / ".git").exists():
        options = dict(check=True, capture_output=True, text=True, timeout=30,
                       env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], **options).stdout.strip()
        revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], **options).stdout.strip()
        if Path(top).resolve() != root or revision != expected["revision"]:
            raise CompatibilityError("native Git root/revision differs from the pinned source")
        layout = "pinned sparse code checkout plus explicit external asset overlay; not an untouched full checkout"
    return {"root": str(root), "revision": expected["revision"], "layout": layout,
            "code_file_count": len(actual_paths), "code_sha256": expected["files"],
            "asset_overlay": str(assets.resolve())}


def verify_object_inventory(path: Path, root: Path) -> dict[str, Any]:
    """Check provisioned full hashes and live complete names/sizes; do not resample."""
    payload = json.loads(path.read_text())
    canonical = json.dumps(payload["files"], sort_keys=True, separators=(",", ":")).encode()
    if (hashlib.sha256(canonical).hexdigest() != _FROZEN["object_inventory"]["inventory_sha256"]
            or any(payload[key] != value for key, value in _FROZEN["object_inventory"].items())
            or not payload.get("comparison", {}).get("matches")
            or Path(payload["root"]).resolve() != root.resolve()):
        raise CompatibilityError("provisioned full object inventory differs from the frozen reuse snapshot")
    actual = {}
    for registry in ("objaverse", "sketchfab", "lightwheel"):
        base = root / registry
        if not base.is_dir() or base.is_symlink():
            raise CompatibilityError("each complete reused object registry must be a real directory")
        for directory, subdirectories, names in os.walk(base, followlinks=False):
            if any((Path(directory) / name).is_symlink() for name in subdirectories + names):
                raise CompatibilityError("frozen object inventory contains no symlinks")
            for name in names:
                candidate = Path(directory) / name
                actual[candidate.relative_to(root).as_posix()] = candidate.stat().st_size
    if actual != {name: row["size"] for name, row in payload["files"].items()}:
        raise CompatibilityError("live object candidate pool file names/sizes differ; no partial-library fallback")
    return payload


def used_asset_manifest(xml: str, roots: Sequence[Path], extras: Sequence[Path],
                        objects: Path, object_inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Hash merged-MJCF dependencies and compare used object bytes with reuse hashes."""
    allowed = tuple(root.resolve(strict=True) for root in roots)
    objects = objects.resolve()
    files: dict[str, dict[str, Any]] = {}
    errors = []

    def add(path: Path, base: Path | None, recurse: bool = False) -> None:
        if not path.is_absolute():
            if base is None:
                errors.append(f"unresolved relative asset: {path}")
                return
            path = base / path
        try:
            path = path.resolve(strict=True)
            if not path.is_file() or not any(path.is_relative_to(root) for root in allowed):
                raise ValueError("file is outside explicitly declared source/asset roots")
            if str(path) in files:
                return
            row = file_digest(path)
            files[str(path)] = row
            if path.is_relative_to(objects):
                expected = object_inventory["files"].get(path.relative_to(objects).as_posix())
                if expected is None or row["size_bytes"] != expected["size"] or row["sha256"] != expected["sha256"]:
                    raise ValueError("used object content differs from full reused snapshot")
            if recurse:
                visit(path.read_text(), path.parent)
        except (OSError, ValueError, ET.ParseError) as error:
            errors.append(f"{path}: {error}")

    def visit(text: str, base: Path | None) -> None:
        element = ET.fromstring(text)
        compiler = element.find("compiler")
        settings = {} if compiler is None else compiler.attrib
        for node in element.iter():
            for key, reference in node.attrib.items():
                if not key.startswith("file") or not reference:
                    continue
                if key not in {"file", "fileleft", "fileright", "filefront", "fileback", "fileup", "filedown"}:
                    errors.append(f"unsupported file attribute: {node.tag}.{key}")
                    continue
                location = Path(reference)
                directory = settings.get("assetdir")
                if node.tag == "mesh":
                    directory = settings.get("meshdir", directory)
                elif node.tag == "texture":
                    directory = settings.get("texturedir", directory)
                if directory and not location.is_absolute() and node.tag != "include":
                    location = Path(directory) / location
                add(location, base, node.tag == "include")

    visit(xml, None)
    for path in extras:
        # Original object XML is hashed as an extra; its relative assets have
        # already been resolved in the compiled MJCF, avoiding guesses here.
        add(path, None)
    rows = [files[key] for key in sorted(files)]
    return {"schema_version": "starvla-rsi.robocasa_tabletop.used-assets/v1", "complete": not errors,
            "scope": "compiled MJCF file closure plus actual object XML and layout/style files",
            "all_benchmark_assets_verified": False,
            "object_pool_validation": "full provisioning content parity; live full names/sizes; used object content parity",
            "files": rows, "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
            "inventory_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "errors": errors}


def verify_native_contract(native: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    import numpy as np
    from robocasa.models.robots import unformat_gripper_space

    robot = native.robots[0]
    model = native.sim.model
    cc = robot.composite_controller
    if (len(native.robots) != 1 or type(robot.robot_model).__name__ != "GR1ArmsAndWaistFourierHands"
            or cc.name != "BASIC" or native.control_freq != 20 or native.horizon != NATIVE_ENGINE_HORIZON or not native.ignore_done
            or set(cc.part_controllers) != {part for _, part, _ in PARTS}):
        raise CompatibilityError("native embodiment/controller/frequency/termination contract differs")
    for action_part, state_part in zip(_FROZEN["action"]["parts"], _FROZEN["state"]["parts"]):
        part = action_part["native_part"]
        controller = cc.part_controllers[part]
        if type(controller).__name__ != action_part["controller"]:
            raise CompatibilityError("native controller class differs")
        joint_ids = np.asarray(robot._ref_joints_indexes_dict[part], dtype=int)
        if part in cc.grippers:
            if controller.use_action_scaling:
                raise CompatibilityError("hand actions must be unscaled absolute position targets")
            expansion = np.asarray(cc.grippers[part].format_action(np.arange(6)), dtype=int)
            if expansion.tolist() != [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5]:
                raise CompatibilityError("native Fourier hand expansion changed")
            actuator_ids = robot._ref_actuators_indexes_dict[part]
            for component in action_part["components"]:
                ids = [int(aid) for aid, command in zip(actuator_ids, expansion) if command == component["index"]]
                joints = [int(model.actuator_trnid[aid, 0]) for aid in ids]
                limits = [model.jnt_range[jid] for jid in joints] + [model.actuator_ctrlrange[aid] for aid in ids]
                if ([model.joint_id2name(jid) for jid in joints] != component["joint_names"]
                        or [model.actuator_id2name(aid) for aid in ids] != component["actuator_names"]
                        or max(float(pair[0]) for pair in limits) != component["low"]
                        or min(float(pair[1]) for pair in limits) != component["high"]):
                    raise CompatibilityError("native coupled hand targets/limits changed")
            joint_ids = unformat_gripper_space(cc.grippers[part], joint_ids)[::-1].astype(int)
        else:
            if controller.input_type != "absolute":
                raise CompatibilityError("arms/waist must use absolute JOINT_POSITION")
            for jid, component in zip(joint_ids, action_part["components"]):
                if ([model.joint_id2name(int(jid))] != component["joint_names"]
                        or model.jnt_range[jid].tolist() != [component["low"], component["high"]]):
                    raise CompatibilityError("native absolute joint order/limits changed")
        if ([model.joint_id2name(int(jid)) for jid in joint_ids] != state_part["joint_names"]
                or [model.jnt_range[jid].tolist() for jid in joint_ids] != state_part["joint_limits"]):
            raise CompatibilityError("ordinary encoder joint identity/order/limits changed")
        measured = np.asarray([native.sim.data.qpos[model.jnt_qposadr[jid]] for jid in joint_ids], dtype=np.float32)
        if not np.array_equal(measured, raw[state_part["native_key"]]):
            raise CompatibilityError("native encoder preprocessing differs from the frozen contract")
    return {"composite": cc.name, "action_split_indexes": {key: list(value) for key, value in cc._action_split_indexes.items()},
            "action": _FROZEN["action"], "state": _FROZEN["state"]}


class TabletopEpisode:
    def __init__(self, benchmark: TabletopBenchmarkAdapter, episode: EpisodeSpec):
        self.benchmark, self.episode = benchmark, episode
        self.env: Any = None
        self.artifact_dir: Path | None = None
        self.writer: Any = None
        self.stream: Any = None
        self.frame_count = 0
        self.step_count = 0
        self.success = False
        self.success_ever = False
        self.first_success_step: int | None = None
        self.first_success_elapsed_s: float | None = None
        self.started_at: float | None = None
        self.reset_started = False
        self.finished = False
        self.provenance: dict[str, Any] = {}

    def bind_artifact_dir(self, path: Path) -> None:
        if self.artifact_dir is not None or self.reset_started:
            raise ProtocolError("bind a Tabletop artifact directory once, before reset")
        self.artifact_dir = Path(path)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _write_provenance(self) -> None:
        if self.artifact_dir is not None:
            atomic_write_json(self.artifact_dir / "native_provenance.json", self.provenance)

    def reset(self) -> Observation:
        if self.reset_started or self.artifact_dir is None:
            raise ProtocolError("one explicit reset requires a bound artifact directory")
        self.reset_started = True
        self.provenance = {"phase": "preflight", **self.benchmark.budget_metadata(),
                           "render_gpu_device_id": self.benchmark.render_gpu_device_id,
                           "egl_device_id": self.benchmark.egl_device_id}
        self._write_provenance()
        if (os.environ.get("PYTHONHASHSEED") != "0" or hash("starvla-rsi-tabletop-hash-v1") != 3297632180807334493
                or sys.version_info[:3] != (3, 10, 21)):
            raise CompatibilityError("launch Python 3.10.21 with PYTHONHASHSEED=0 before process start")
        # Source attestations must not be bypassed by cached native bytecode.
        # Existing unmanifested caches fail the full file-set check below.
        sys.dont_write_bytecode = True
        for name, version in _FROZEN["versions"].items():
            if importlib.metadata.version(name) != version:
                raise CompatibilityError(f"Tabletop runtime requires {name}=={version}")
        for key, value in {"MUJOCO_GL": "egl", "PYOPENGL_PLATFORM": "egl",
                           "MUJOCO_EGL_DEVICE_ID": str(self.benchmark.egl_device_id)}.items():
            if "mujoco" in sys.modules and os.environ.get(key) != value:
                raise CompatibilityError("an already imported native renderer has incompatible device settings")
            os.environ[key] = value
        os.environ["NUMBA_CACHE_DIR"] = str(self.artifact_dir / "numba_cache")
        sources = {name: verify_source(root, name) for name, root in self.benchmark.sources.items()}
        objects = Path(sources["robocasa"]["asset_overlay"]) / "objects"
        inventory = verify_object_inventory(self.benchmark.object_inventory, objects)
        self.provenance.update(sources=sources, object_inventory={key: value for key, value in inventory.items() if key != "files"})
        self.provenance["phase"] = "initializing"
        self._write_provenance()
        sys.path[:0] = [str(root) for root in self.benchmark.sources.values()]
        import gymnasium as gym
        import numpy as np
        import robocasa
        import robosuite
        from robocasa.utils.gym_utils import GrootRoboCasaEnv  # noqa: F401 - native registration
        from robocasa.models.scenes.scene_registry import get_tabletop_layout_path, get_style_path

        for module in (robocasa, robosuite):
            if Path(module.__file__).resolve().parent.parent != self.benchmark.sources[module.__name__]:
                raise CompatibilityError("native import path is outside the verified source")
        self.env = gym.make(self.episode.task, seed=self.episode.seed, enable_render=True, disable_env_checker=True)
        raw, _private_reset_info = self.env.reset(seed=self.episode.seed)
        native = self.env.unwrapped.env
        contract = verify_native_contract(native, raw)
        atomic_write_json(self.artifact_dir / "native_controller_contract.json", contract)
        expected_layout = OFFICIAL_TASK_LAYOUTS[self.episode.metadata["native_task_index"]]
        pairs = [[int(layout), int(style)] for layout, style in native.layout_and_style_ids]
        if (pairs != [[expected_layout, style] for style in range(12)]
                or tuple(native.obj_registries) != ("objaverse", "sketchfab", "lightwheel")):
            raise CompatibilityError("native candidate layout/style/object registry set changed")
        initial_success = bool(native._check_success())
        metadata = native.get_ep_meta()
        atomic_write_json(self.artifact_dir / "native_episode_metadata.json", metadata)
        state = native.sim.get_state().flatten()
        np.save(self.artifact_dir / "initial_state.npy", state, allow_pickle=False)
        xml = native.sim.model.get_xml()
        (self.artifact_dir / "initial_scene.xml").write_text(xml)
        roots = list(self.benchmark.sources.values()) + [Path(row["asset_overlay"]) for row in sources.values()]
        # Casa's overlay has explicit read-only fixture/texture/scenes links.
        roots += [child.resolve() for child in Path(sources["robocasa"]["asset_overlay"]).iterdir() if child.is_symlink()]
        extras = [Path(get_tabletop_layout_path(native.layout_id)), Path(get_style_path(native.style_id))]
        extras += [Path(row["info"]["mjcf_path"]) for row in metadata["object_cfgs"] if "mjcf_path" in row.get("info", {})]
        assets = used_asset_manifest(xml, roots, extras, objects, inventory)
        atomic_write_json(self.artifact_dir / "used_assets.json", assets)
        self.provenance.update(
            phase="initialized", native_task=self.episode.task, seed=self.episode.seed, python_hash_seed="0",
            layout_id=int(native.layout_id), style_id=int(native.style_id), layout_and_style_candidates=pairs,
            factory_layout_style_parameters="not forwarded by pinned native factory; no overridden candidates",
            explicit_resets=1, constructor_initialization="native constructor initialization followed by one explicit seeded reset",
            initial_state_sha256=hashlib.sha256(state.tobytes()).hexdigest(),
            initial_scene_sha256=hashlib.sha256(xml.encode()).hexdigest(), initial_native_success=initial_success,
            native_engine_horizon=int(native.horizon), native_ignore_done=bool(native.ignore_done),
            used_assets_complete=assets["complete"], used_assets_inventory_sha256=assets["inventory_sha256"],
            runtime_versions=dict(_FROZEN["versions"]), render_gpu_device_id=self.benchmark.render_gpu_device_id,
            egl_device_id=self.benchmark.egl_device_id,
            image_transform="native vertical flip, crop [310:770,110:1130], resize 720x480, pad to square, resize 256x256; copied",
            policy_state="29 ordinary joint encoders in radians; native hand selection/reversal; no sin/cos conversion",
            policy_metadata={},
        )
        self._write_provenance()
        observation = self._observe(raw)
        if not assets["complete"]:
            raise CompatibilityError("actual scene asset dependency parity is incomplete")
        if initial_success:
            raise ProtocolError("task already succeeded at reset; no retry or policy call")
        self.started_at = time.monotonic()
        return observation

    def _observe(self, raw: Mapping[str, Any]) -> Observation:
        observation = policy_observation(raw, self.step_count)
        if self.artifact_dir is not None:
            import av
            from PIL import Image

            frame = observation.images[CAMERA]
            path = self.artifact_dir / f"{CAMERA}-{self.step_count:06d}.png"
            Image.fromarray(frame).save(path)
            append_jsonl(self.artifact_dir / "frames.jsonl", {"step": self.step_count, "camera": CAMERA,
                         "path": path.name, "sha256": file_digest(path)["sha256"]})
            if self.writer is None:
                self.writer = av.open(str(self.artifact_dir / f"{CAMERA}.mp4"), "w")
                self.stream = self.writer.add_stream("libx264", rate=20)
                self.stream.width, self.stream.height, self.stream.pix_fmt = 256, 256, "yuv420p"
            for packet in self.stream.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
                self.writer.mux(packet)
            self.frame_count += 1
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.env is None or self.started_at is None or self.finished:
            raise ProtocolError("cannot step an uninitialized or finished Tabletop episode")
        validated = self.benchmark.action_spec.validate(action)
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_actions.jsonl", {
                "event": "native_action_start", "step": self.step_count + 1, "action": validated,
            })
        raw, reward, done, native_truncated, info = self.env.step(action_dictionary(validated))
        self.step_count += 1
        if type(info.get("success")) is not bool or float(reward) != float(info["success"]):
            raise ProtocolError("native sparse reward/success contract differs")
        # This is the native per-action reward flag. Do not query the oracle
        # again, use model assertions, or keep only a chunk's final observation.
        self.success = info["success"]
        self.success_ever = self.success_ever or self.success
        if self.success and self.first_success_step is None:
            self.first_success_step = self.step_count
            self.first_success_elapsed_s = time.monotonic() - self.started_at
        terminated = bool(done) or self.success
        truncated = bool(native_truncated) or (self.step_count >= self.benchmark.environment_step_cap and not terminated)
        self.finished = terminated or truncated
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_actions.jsonl", {
                "event": "native_action_end", "step": self.step_count, "native_reward": float(reward),
                "native_success": self.success, "native_done": bool(done),
                "native_truncated": bool(native_truncated), "adapter_truncated": truncated,
            })
        return Transition(self._observe(raw), float(reward), terminated, truncated,
                          {"native_success": self.success, "native_steps": self.step_count})

    def metrics(self) -> Mapping[str, JsonValue]:
        return {"success": self.success, "native_success_final": self.success, "success_ever": self.success_ever,
                "first_success_step": self.first_success_step, "first_success_elapsed_s": self.first_success_elapsed_s,
                "native_steps": self.step_count, "score_semantics": "final_native_success; stop_at_first_native_success",
                "explicit_resets": int(self.reset_started), **self.benchmark.budget_metadata()}

    def _close_writer(self) -> None:
        if self.writer is None:
            return
        writer, self.writer = self.writer, None
        try:
            if self.stream is not None:
                for packet in self.stream.encode():
                    writer.mux(packet)
        finally:
            writer.close()

    def artifacts(self) -> Mapping[str, str]:
        self._close_writer()
        if self.artifact_dir is None:
            return {}
        video_path = self.artifact_dir / f"{CAMERA}.mp4"
        if self.frame_count:
            import av
            with av.open(str(video_path)) as container:
                decoded = sum(1 for _ in container.decode(video=0))
            atomic_write_json(self.artifact_dir / "video_validation.json", {"expected_frames": self.frame_count, "decoded_frames": decoded})
            if decoded != self.frame_count:
                raise InfrastructureError("Tabletop video frame count does not match recorded observations")
        names = {"video": video_path.name, "frames": "frames.jsonl", "native_actions": "native_actions.jsonl",
                 "native_provenance": "native_provenance.json", "controller_contract": "native_controller_contract.json",
                 "native_episode_metadata": "native_episode_metadata.json", "initial_state": "initial_state.npy",
                 "initial_scene": "initial_scene.xml", "used_assets": "used_assets.json", "video_validation": "video_validation.json"}
        return {key: str(self.artifact_dir / name) for key, name in names.items() if (self.artifact_dir / name).is_file()}

    def close(self) -> None:
        try:
            self._close_writer()
        finally:
            if self.env is not None:
                self.env.close()
                self.env = None


class TabletopBenchmarkAdapter:
    environment_step_cap = EVALUATED_STEP_CAP

    def __init__(self, *, casa_source: str, suite_source: str, object_inventory: str,
                 evaluation_mode: str = "fast", render_gpu_device_id: int = 0,
                 egl_device_id: Any = _UNSET_EGL_DEVICE):
        if evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"evaluation_mode must be one of {', '.join(EVALUATION_MODES)}; got {evaluation_mode!r}")
        if type(render_gpu_device_id) is not int or render_gpu_device_id < 0:
            raise ValueError("render GPU index must be a nonnegative integer")
        if egl_device_id is _UNSET_EGL_DEVICE:
            egl_device_id = render_gpu_device_id
        if type(egl_device_id) is not int or egl_device_id < 0:
            raise ValueError("EGL device index must be a nonnegative integer")
        self.evaluation_mode = evaluation_mode
        self.tasks = OFFICIAL_TASKS
        # Sample-major: every task with seed SCHEDULE_SEED, then SCHEDULE_SEED + 1, ...
        self.schedule = tuple((sample, index) for sample in range(MODE_SAMPLES[evaluation_mode])
                              for index in self.tasks)
        if evaluation_mode == "example":
            self.schedule = self.schedule[:1]
        self.render_gpu_device_id = render_gpu_device_id
        self.egl_device_id = egl_device_id
        self.sources = {"robocasa": Path(casa_source).resolve(), "robosuite": Path(suite_source).resolve()}
        self.object_inventory = Path(object_inventory).absolute()
        revision = _FROZEN["sources"]["robocasa"]["revision"]
        self.descriptor = BenchmarkDescriptor(
            "robocasa_tabletop", "0.5.0",
            f"robocasa-tabletop-{revision[:7]}/gr1-official24-seeded-control-{EVALUATED_STEP_CAP}/rgb256-qpos29/{evaluation_mode}/v1",
            revision,
        )
        self.action_spec = ACTION_SPEC
        self.observation_spec = ObservationSpec((CAMERA,), STATE_NAMES, ("language", "rgb", "joint_position"))

    def budget_metadata(self) -> dict[str, JsonValue]:
        return {"environment_step_cap": self.environment_step_cap, "native_engine_horizon": NATIVE_ENGINE_HORIZON,
                "native_ignore_done": True, "native_control_hz": 20}

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or seed != SCHEDULE_SEED:
            raise ValueError(f"Tabletop schedule requires seed={SCHEDULE_SEED}")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= len(self.schedule)):
            raise ValueError("episode limit must select a nonempty prefix without repeats")
        return [EpisodeSpec(
            id=f"tabletop-task{index:02d}-seed{seed + sample}-attempt1",
            task=self.tasks[index], seed=seed + sample,
            instruction="Follow the native Tabletop task instruction supplied after reset.",
            metadata={"native_task_index": index, "attempt": 1, "sample_index": sample,
                      "evaluation_mode": self.evaluation_mode,
                      "selection": _CATALOG["task_scope"], "official_full_protocol": False,
                      "schedule_order": "sample-major/task-minor",
                      "candidate_layout_ids": [OFFICIAL_TASK_LAYOUTS[index]],
                      "candidate_style_ids": list(range(12)), **self.budget_metadata()},
        ) for sample, index in self.schedule[:limit]]

    def open_episode(self, episode: EpisodeSpec) -> TabletopEpisode:
        if episode not in self.episodes(SCHEDULE_SEED):
            raise ProtocolError("episode differs from the frozen Tabletop selection")
        return TabletopEpisode(self, episode)


def make_tabletop(parameters: Mapping[str, JsonValue]) -> TabletopBenchmarkAdapter:
    unknown = set(parameters) - {"evaluation_mode", "render_gpu_device_id", "egl_device_id",
                                 "casa_source", "suite_source", "object_inventory"}
    if unknown:
        raise ValueError(f"unknown Tabletop parameters: {sorted(unknown)}")
    missing = [key for key in ("casa_source", "suite_source", "object_inventory") if key not in parameters]
    if missing:
        raise ValueError(f"missing required Tabletop deployment paths: {missing}")
    return TabletopBenchmarkAdapter(**parameters)
