"""Pinned RoboCasa365 PandaOmron development adapter, with no simulator imports at load time."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import (
    ActionSpec, BenchmarkDescriptor, EpisodeSpec, JsonValue, Observation, ObservationSpec, Transition,
)
from benchkit.errors import CompatibilityError, InfrastructureError, ProtocolError
from benchkit.registry import register_benchmark

ROBOCASA_REVISION = "b4684e6ee37d377cc392e98302a6b916d588b415"
ROBOSUITE_REVISION = "85abee228d1c43ab1939bce33028099945d453b4"
CAMERAS = ("robot0_agentview_left", "robot0_agentview_right", "robot0_eye_in_hand")
PILOT_TASKS = ("OpenDrawer", "NavigateKitchen")
NATIVE_HORIZONS = {"OpenDrawer": 750, "NavigateKitchen": 450}
PILOT_SEED = 20260907
NEUTRAL_ACTION = (0.0,) * 12
OBSERVATION_SPEC = ObservationSpec(cameras=CAMERAS, modalities=("language", "rgb"))


def target50_inventory() -> dict[str, Any]:
    """Read the bundled, source-derived target set without importing a simulator."""
    path = Path(__file__).parent / "protocol" / "robocasa365_target50.json"
    inventory = json.loads(path.read_text(encoding="utf-8"))
    groups = {"atomic_seen": 18, "composite_seen": 16, "composite_unseen": 16}
    if (inventory.get("schema_version") != "starvla-rsi.robocasa365-target50/v1"
            or inventory.get("native_revision") != ROBOCASA_REVISION
            or inventory.get("counts") != groups):
        raise CompatibilityError("invalid bundled target50 inventory identity")
    rows = inventory.get("tasks", [])
    expected_groups = [group for group, count in groups.items() for _ in range(count)]
    if (len(rows) != 50 or [r.get("index") for r in rows] != list(range(50))
            or [r.get("task_set") for r in rows] != expected_groups
            or len({r.get("task") for r in rows}) != 50):
        raise CompatibilityError("target50 must retain 18/16/16 distinct tasks in native order")
    for row in rows:
        if (not isinstance(row.get("task"), str) or not row["task"].isidentifier()
                or type(row.get("native_horizon")) is not int or row["native_horizon"] <= 0
                or not isinstance(row.get("module"), str)
                or not row["module"].startswith("robocasa.environments.kitchen.")
                or row.get("source") != row["module"].replace(".", "/") + ".py"):
            raise CompatibilityError("invalid native target50 task metadata")
    return inventory


def verify_target50_sources(root: Path) -> dict[str, Any]:
    """File-only binding of the selected task definitions and native registries.

    This verifies source identity, not reset/render, transitive assets or parity.
    The caller separately requires a clean pinned native Git tree.
    """
    inventory = target50_inventory()
    expected = dict(inventory["source_files"])
    for row in inventory["tasks"]:
        prior = expected.setdefault(row["source"], row["source_sha256"])
        if prior != row["source_sha256"]:
            raise CompatibilityError("conflicting task source hashes")
    root = root.resolve(strict=True)
    for relative, sha256 in expected.items():
        path = root / relative
        if (Path(relative).is_absolute() or ".." in Path(relative).parts
                or path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(root)
                or hashlib.sha256(path.read_bytes()).hexdigest() != sha256):
            raise CompatibilityError(f"native target50 source changed: {relative}")
    inventory_path = Path(__file__).parent / "protocol" / "robocasa365_target50.json"
    return {"task_scope": "target50", "task_count": 50,
            "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
            "source_files": expected, "native_execution_verified": False}


def verify_target50_registry(groups: Mapping[str, Any], atomic: Mapping[str, Any],
                             composite: Mapping[str, Any]) -> None:
    """Compare imported native metadata before environment construction; no scorer."""
    inventory = target50_inventory()
    for group in inventory["counts"]:
        expected = [row["task"] for row in inventory["tasks"] if row["task_set"] == group]
        if groups.get(group) != expected:
            raise CompatibilityError(f"native target50 task order changed: {group}")
    for row in inventory["tasks"]:
        registry = atomic if row["task_set"] == "atomic_seen" else composite
        if registry.get(row["task"], {}).get("horizon") != row["native_horizon"]:
            raise CompatibilityError(f"native target50 horizon changed: {row['task']}")


class PandaOmronActionSpec(ActionSpec):
    def validate(self, values: Sequence[float]) -> tuple[float, ...]:
        action = super().validate(values)
        if action[6] not in (0.0, 1.0) or action[11] not in (0.0, 1.0):
            raise ValueError("gripper_close and base_mode must be exactly 0 or 1")
        return action


ACTION_SPEC = PandaOmronActionSpec(
    mode="robocasa365.pandaomron.hybrid_mobile_base.native12/v1", size=12,
    names=("eef_dx", "eef_dy", "eef_dz", "eef_drx", "eef_dry", "eef_drz",
           "gripper_close", "base_forward", "base_side", "base_yaw", "torso_delta", "base_mode"),
    low=(-1.0,) * 6 + (0.0,) + (-1.0,) * 4 + (0.0,), high=(1.0,) * 12,
    control_hz=20,
    frame="EEF delta: robot base frame, unit=0.05m; base forward/side: current base frame, unit=1m/s; yaw unit=1.5rad/s; torso delta unit=0.05m",
    rotation="base-frame axis-angle delta, unit=0.5rad; binary base_mode 0=achieved arm goal, 1=desired arm goal",
    gripper="binary 0=open, 1=close; native -1/+1; no fractional values",
)


def action_dictionary(values: Sequence[float]) -> dict[str, Any]:
    action = ACTION_SPEC.validate(values)
    import numpy as np

    return {name: np.asarray(action[start:end], dtype=np.float64) for name, start, end in (
        ("action.end_effector_position", 0, 3), ("action.end_effector_rotation", 3, 6),
        ("action.gripper_close", 6, 7), ("action.base_motion", 7, 11),
        ("action.control_mode", 11, 12),
    )}


def policy_observation(raw: Mapping[str, Any], step: int) -> Observation:
    images = {}
    for camera in CAMERAS:
        frame = raw.get("video." + camera)
        if (frame is None or str(getattr(frame, "dtype", None)) != "uint8"
                or getattr(frame, "shape", None) != (256, 256, 3)):
            raise ProtocolError(f"{camera} must contain 256x256 uint8 RGB")
        images[camera] = frame.copy()
    instruction = raw.get("annotation.human.task_description")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ProtocolError("native instruction is missing or empty")
    return Observation(step=step, instruction=instruction, images=images)


def verify_git_root(root: Path, revision: str) -> dict[str, Any]:
    root = root.resolve(strict=True)
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", str(root), *args], env=environment,
                check=True, capture_output=True, text=True, timeout=60).stdout.strip()
        top = Path(git("rev-parse", "--show-toplevel")).resolve(strict=True)
        head = git("rev-parse", "HEAD")
        dirty = git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompatibilityError(f"cannot verify native Git root {root}") from exc
    if top != root or head != revision or dirty:
        raise CompatibilityError(f"native source root must be a clean Git checkout at {revision}: {root}")
    return {"root": str(root), "git_toplevel": str(top), "revision": head, "tracked_dirty": False}


def verify_sources() -> dict[str, Any]:
    provenance: dict[str, Any] = {"packages": {}, "sources": {}}
    for package, expected in (("robocasa", "1.0.1"), ("robosuite", "1.5.2"),
                              ("mujoco", "3.3.1"), ("numpy", "2.2.5")):
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise CompatibilityError(f"missing native package {package}") from exc
        if actual != expected:
            raise CompatibilityError(f"{package} must be {expected}, found {actual}")
        provenance["packages"][package] = actual
    for package, revision in (("robocasa", ROBOCASA_REVISION), ("robosuite", ROBOSUITE_REVISION)):
        spec = importlib.util.find_spec(package)
        if spec is None or spec.origin is None:
            raise CompatibilityError(f"missing {package} source")
        root = Path(spec.origin).resolve().parent.parent
        provenance["sources"][package] = verify_git_root(root, revision)
    for package in ("av", "pillow", "gymnasium", "numba", "scipy"):
        provenance["packages"][package] = importlib.metadata.version(package)
    return provenance


def file_digest(path: Path) -> dict[str, Any]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ProtocolError(f"native dependency changed while hashing: {path}")
    return {"path": str(path), "size_bytes": after.st_size, "sha256": digest.hexdigest()}


def asset_dependency_manifest(xml: str, allowed_roots: Sequence[Path],
                              extra_files: Sequence[Path] = ()) -> dict[str, Any]:
    """Hash the actual compiled scene's file dependency closure, never a guessed full asset set.

    Only files referenced by MJCF file attributes (and recursively included XML)
    are followed. The pin uses absolute paths in merged XML. Ambiguous relative
    references, unknown file attributes and missing/outside-root files fail closed.
    """
    roots = tuple(path.resolve(strict=True) for path in allowed_roots)
    files: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    def add(path: Path, base: Path | None, recurse: bool = False) -> None:
        if not path.is_absolute():
            if base is None:
                errors.append(f"unresolved relative dependency: {path}")
                return
            path = base / path
        try:
            path = path.resolve(strict=True)
            if not path.is_file() or not any(path.is_relative_to(root) for root in roots):
                raise ValueError("dependency is not a regular file under a pinned source root")
            if str(path) in files:
                return
            files[str(path)] = file_digest(path)
            if recurse:
                visit(path.read_text(), path.parent)
        except (OSError, ValueError, ET.ParseError) as exc:
            errors.append(f"{path}: {exc}")

    def visit(text: str, base: Path | None) -> None:
        element = ET.fromstring(text)
        compiler = element.find("compiler")
        settings = {} if compiler is None else compiler.attrib
        for node in element.iter():
            for key, reference in node.attrib.items():
                if not key.startswith("file") or not reference:
                    continue
                if key not in {"file", "fileleft", "fileright", "filefront", "fileback", "fileup", "filedown"}:
                    errors.append(f"unsupported dependency attribute: {node.tag}.{key}")
                    continue
                location = Path(reference)
                directory = settings.get("assetdir")
                if node.tag == "mesh":
                    directory = settings.get("meshdir", directory)
                elif node.tag == "texture":
                    directory = settings.get("texturedir", directory)
                if directory and not location.is_absolute() and node.tag != "include":
                    location = Path(directory) / location
                add(location, base, node.tag == "include" or location.suffix.lower() == ".xml")

    visit(xml, None)
    for path in extra_files:
        add(path, None)
    ordered = sorted(files.values(), key=lambda row: row["path"])
    return {"schema_version": "robocasa365.used-assets/v1",
            "scope": "compiled_scene_MJCF_file_dependency_closure_plus_layout_style_and_private_macros",
            "all_benchmark_assets_verified": False, "complete": not errors,
            "model_xml_sha256": hashlib.sha256(xml.encode()).hexdigest(),
            "file_count": len(ordered), "total_bytes": sum(row["size_bytes"] for row in ordered),
            "inventory_sha256": hashlib.sha256(json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "files": ordered, "errors": errors}


class RoboCasa365Episode:
    def __init__(self, benchmark: RoboCasa365BenchmarkAdapter, episode: EpisodeSpec):
        self.benchmark, self.episode = benchmark, episode
        self.env: Any = None
        self.artifact_dir: Path | None = None
        self.writers: dict[str, Any] = {}
        self.step_count = 0
        self.success = False
        self.success_ever = False
        self.first_success_step: int | None = None
        self.first_success_elapsed_s: float | None = None
        self.started_at: float | None = None
        self.finished = False
        self.reset_started = False
        self.provenance: dict[str, Any] = {}
        self.frame_counts = {camera: 0 for camera in CAMERAS}
        self.asset_manifest: dict[str, Any] | None = None
        self.renderer_guard: Any = None
        self.renderer_finalized = False

    def _render_checkpoint(self, phase: str) -> None:
        if self.renderer_guard is not None:
            self.renderer_guard.check(phase, persist=True)

    def bind_artifact_dir(self, path: Path) -> None:
        if self.artifact_dir is not None or self.reset_started:
            raise ProtocolError("artifact directory must be bound once before reset")
        self.artifact_dir = Path(path)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _write_provenance(self) -> None:
        if self.artifact_dir is not None:
            atomic_write_json(self.artifact_dir / "native_provenance.json", self.provenance)

    def reset(self) -> Observation:
        if self.reset_started:
            raise ProtocolError("each episode session permits one explicit reset")
        self.reset_started = True
        if self.artifact_dir is None:
            raise ProtocolError("native episodes require a bound artifact directory")
        self.provenance = {"phase": "checking_sources", **self.benchmark.budget_metadata(self.episode.task)}
        self._write_provenance()
        self.provenance.update(verify_sources())
        if self.benchmark.task_scope == "target50":
            self.provenance["target50_source_binding"] = verify_target50_sources(
                Path(self.provenance["sources"]["robocasa"]["root"]))
        self._write_provenance()
        from ..environment.render_lifecycle import install, require_native_track
        if self.benchmark.render_track == "native-v1":
            require_native_track()
        else:
            self.renderer_guard = install(self.artifact_dir / "render_lifecycle.json",
                Path(self.provenance["sources"]["robosuite"]["root"]), track=self.benchmark.render_track)
            self.provenance["render_compatibility"] = self.renderer_guard.source_receipt
            self._write_provenance()
        import gymnasium as gym
        import numpy as np
        import robocasa
        import robosuite
        from robocasa.models.scenes.scene_registry import get_layout_path, get_style_path
        from robocasa.utils.dataset_registry import ATOMIC_TASK_DATASETS, COMPOSITE_TASK_DATASETS, TARGET_TASKS

        for module in (robocasa, robosuite):
            expected = Path(self.provenance["sources"][module.__name__]["root"])
            if Path(module.__file__).resolve().parent.parent != expected:
                raise CompatibilityError("imported native module differs from verified source")
        if self.benchmark.task_scope == "target50":
            verify_target50_registry(TARGET_TASKS, ATOMIC_TASK_DATASETS, COMPOSITE_TASK_DATASETS)
        elif ATOMIC_TASK_DATASETS[self.episode.task]["horizon"] != NATIVE_HORIZONS[self.episode.task]:
            raise CompatibilityError("native task horizon changed")
        self.provenance["phase"] = "initializing"
        self._write_provenance()
        self.env = gym.make(
            "robocasa/" + self.episode.task, split="target", seed=self.episode.seed,
            enable_render=True, camera_widths=256, camera_heights=256,
            camera_depths=False, randomize_cameras=False, generative_textures=None,
            render_gpu_device_id=self.benchmark.render_gpu_device_id, control_freq=20,
            disable_env_checker=True,
        )
        self._render_checkpoint("after_native_constructor")
        raw, _private_info = self.env.reset(seed=self.episode.seed)
        self._render_checkpoint("after_explicit_reset")
        native = self.env.unwrapped.env
        controller = native.robots[0].composite_controller
        if controller.name != "HYBRID_MOBILE_BASE" or native.control_freq != 20:
            raise CompatibilityError("native controller/frequency changed")
        arm = controller.part_controllers["right"]
        torso = controller.part_controllers["torso"]
        base = controller.part_controllers["base"]
        if (type(base).__name__ != "LegacyMobileBaseJointVelocityController"
                or base._check_forward_joint_reversed()):
            raise CompatibilityError("this PandaOmron track requires the native legacy base controller with X-forward joints")
        if (arm.input_ref_frame != "base" or arm.input_type != "delta"
                or not np.array_equal(arm.output_max, [0.05, 0.05, 0.05, 0.5, 0.5, 0.5])
                or not np.array_equal(arm.output_min, [-0.05, -0.05, -0.05, -0.5, -0.5, -0.5])
                or torso.input_type != "delta" or not np.array_equal(torso.output_max, [0.05])
                or not np.array_equal(torso.output_min, [-0.05])
                or not np.array_equal(base.actuator_min, [-1, -1, -1.5])
                or not np.array_equal(base.actuator_max, [1, 1, 1.5])):
            raise CompatibilityError("native action scale/frame changed")
        low, high = native.action_spec
        if not np.array_equal(low, np.full(12, -1)) or not np.array_equal(high, np.full(12, 1)):
            raise CompatibilityError("native action dimensions/bounds changed")
        expected_parts = {"right": (0, 6), "right_gripper": (6, 7), "base": (7, 10), "torso": (10, 11)}
        if {k: tuple(v) for k, v in controller._action_split_indexes.items()} != expected_parts:
            raise CompatibilityError("native action part ordering changed")
        initial_success = bool(native._check_success())
        xml = native.sim.model.get_xml()
        (self.artifact_dir / "initial_scene.xml").write_text(xml)
        native_state = native.sim.get_state().flatten()
        np.save(self.artifact_dir / "initial_state.npy", native_state, allow_pickle=False)
        roots = [Path(item["root"]) for item in self.provenance["sources"].values()]
        extras = [Path(get_layout_path(native.layout_id)), Path(get_style_path(native.style_id))]
        extras += [root / package / "macros_private.py" for package, root in
                   (("robocasa", roots[0]), ("robosuite", roots[1])) if (root / package / "macros_private.py").is_file()]
        self.asset_manifest = asset_dependency_manifest(xml, roots, extras)
        atomic_write_json(self.artifact_dir / "used_assets.json", self.asset_manifest)
        self.provenance.update({
            "phase": "initialized", "task": self.episode.task, "split": "target", "seed": self.episode.seed,
            "layout_id": int(native.layout_id), "style_id": int(native.style_id),
            "native_engine_horizon": native.horizon, "native_ignore_done": native.ignore_done,
            "native_control_hz": native.control_freq, "render_gpu_device_id": self.benchmark.render_gpu_device_id,
            "explicit_resets": 1,
            "constructor_initialization": "upstream initializes/resets before explicit seeded reset; no policy actions",
            "action_split_indexes": {k: list(v) for k, v in expected_parts.items()},
            "controller": {"composite": controller.name, "arm": type(arm).__name__,
                           "torso": type(torso).__name__, "base": type(base).__name__},
            "initial_native_success": initial_success,
            "initial_model_xml_sha256": hashlib.sha256(xml.encode()).hexdigest(),
            "initial_state_sha256": hashlib.sha256(native_state.tobytes()).hexdigest(),
            "used_assets_inventory_sha256": self.asset_manifest["inventory_sha256"],
            "used_assets_complete": self.asset_manifest["complete"],
            "image_transform": "native gym vertical flip; copied RGB; no crop/resize",
            "policy_state": None, "policy_metadata": {},
        })
        self._write_provenance()
        if not self.asset_manifest["complete"]:
            self._observe(raw)
            raise CompatibilityError("used native asset dependency manifest is incomplete")
        return self._finish_reset(raw, initial_success)

    def _finish_reset(self, raw: Mapping[str, Any], initial_success: bool) -> Observation:
        observation = self._observe(raw)
        if initial_success:
            raise ProtocolError("native task already succeeded at reset before any policy action")
        self.started_at = time.monotonic()
        return observation

    def _observe(self, raw: Mapping[str, Any]) -> Observation:
        self._render_checkpoint("before_observation_encoding")
        observation = policy_observation(raw, self.step_count)
        if self.artifact_dir is not None:
            import av
            from PIL import Image
            for camera, pixels in observation.images.items():
                path = self.artifact_dir / f"{camera}-{self.step_count:06d}.png"
                Image.fromarray(pixels).save(path)
                append_jsonl(self.artifact_dir / "frames.jsonl", {
                    "camera": camera, "step": self.step_count, "path": path.name,
                    "sha256": file_digest(path)["sha256"], "instruction": observation.instruction,
                })
                if camera not in self.writers:
                    container = av.open(str(self.artifact_dir / f"{camera}.mp4"), mode="w")
                    self.writers[camera] = (container, None)
                    stream = container.add_stream("libx264", rate=20)
                    stream.width, stream.height, stream.pix_fmt = 256, 256, "yuv420p"
                    self.writers[camera] = (container, stream)
                container, stream = self.writers[camera]
                for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                    container.mux(packet)
                self.frame_counts[camera] += 1
        self._render_checkpoint("before_observation_release")
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.env is None or self.started_at is None or self.finished:
            raise ProtocolError("cannot step an uninitialized or finished RoboCasa365 episode")
        validated = self.benchmark.action_spec.validate(action)
        self._render_checkpoint("before_control")
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_actions.jsonl", {
                "event": "native_action_start", "step": self.step_count + 1, "action": validated,
            })
        raw, reward, done, native_truncated, info = self.env.step(action_dictionary(validated))
        self.step_count += 1
        self._render_checkpoint("after_control")
        if type(info.get("success")) is not bool or float(reward) != float(info["success"]):
            raise ProtocolError("native sparse reward/success contract changed")
        self.success = info["success"]
        self.success_ever = self.success_ever or self.success
        if self.success and self.first_success_step is None:
            self.first_success_step = self.step_count
            self.first_success_elapsed_s = time.monotonic() - self.started_at
        # Follow the native rollout convention: stop at first native success.
        terminated = bool(done) or self.success
        truncated = bool(native_truncated) or (self.step_count >= self.benchmark.step_cap(self.episode.task) and not terminated)
        self.finished = terminated or truncated
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_actions.jsonl", {
                "event": "native_action_end", "step": self.step_count, "reward": float(reward),
                "native_success": self.success, "native_done": bool(done),
                "native_truncated": bool(native_truncated), "adapter_truncated": truncated,
            })
        return Transition(self._observe(raw), float(reward), terminated, truncated,
                          {"native_success": self.success, "native_steps": self.step_count})

    def metrics(self) -> Mapping[str, JsonValue]:
        self._render_checkpoint("metrics")
        return {"success": self.success, "native_success_final": self.success,
                "success_ever": self.success_ever, "first_success_step": self.first_success_step,
                "first_success_elapsed_s": self.first_success_elapsed_s,
                "native_steps": self.step_count, "explicit_resets": int(self.reset_started),
                "score_semantics": "final_native_success; stop_at_first_native_success",
                **self.benchmark.budget_metadata(self.episode.task)}

    def _close_writers(self) -> None:
        errors = []
        for camera, (container, stream) in tuple(self.writers.items()):
            try:
                if stream is not None:
                    for packet in stream.encode():
                        container.mux(packet)
            except Exception as exc:
                errors.append(f"{camera} flush: {exc}")
            finally:
                try:
                    container.close()
                except Exception as exc:
                    errors.append(f"{camera} close: {exc}")
                del self.writers[camera]
        if errors:
            if self.artifact_dir is not None:
                atomic_write_json(self.artifact_dir / "video_errors.json", {"errors": errors})
            raise InfrastructureError("; ".join(errors))

    def artifacts(self) -> Mapping[str, str]:
        self._close_writers()
        self._render_checkpoint("artifacts")
        if self.artifact_dir is None:
            return {}
        files = {camera + "_video": camera + ".mp4" for camera in CAMERAS}
        files.update(frames="frames.jsonl", native_actions="native_actions.jsonl",
                     native_provenance="native_provenance.json", used_assets="used_assets.json",
                     initial_scene="initial_scene.xml", initial_state="initial_state.npy",
                     render_lifecycle="render_lifecycle.json")
        return {key: str(self.artifact_dir / name) for key, name in files.items()
                if (self.artifact_dir / name).exists()}

    def close(self) -> None:
        try:
            self._close_writers()
        finally:
            try:
                if self.env is not None:
                    env, self.env = self.env, None
                    env.close()
            finally:
                if self.renderer_guard is not None and not self.renderer_finalized:
                    import gc
                    # Finalize retired/partially constructed render cycles while
                    # the process-local guard and private receipt are still live.
                    gc.collect()
                    self.renderer_finalized = True
                    self.renderer_guard.finish()


class RoboCasa365BenchmarkAdapter:
    def __init__(self, task_ids: Sequence[int] = (0, 1), *, render_gpu_device_id: int = 3,
                 budget_mode: str = "horizon", max_policy_calls: int | None = None,
                 replan_interval: int | None = None, task_scope: str = "pilot",
                 render_track: str = "native-v1"):
        if render_track not in ("native-v1", "egl-owner-restore-v1", "egl-owner-material-clamp-v1"):
            raise ValueError("render_track must be native-v1, egl-owner-restore-v1 or egl-owner-material-clamp-v1")
        self.render_track = render_track
        if task_scope not in ("pilot", "target50"):
            raise ValueError("task_scope must be pilot or target50")
        self.task_scope = task_scope
        self.task_rows = (target50_inventory()["tasks"] if task_scope == "target50" else [
            {"task": task, "native_horizon": NATIVE_HORIZONS[task], "task_set": "atomic_seen"}
            for task in PILOT_TASKS])
        self.task_names = tuple(row["task"] for row in self.task_rows)
        self.native_horizons = {row["task"]: row["native_horizon"] for row in self.task_rows}
        if (not isinstance(task_ids, (list, tuple)) or not task_ids
                or any(type(i) is not int or not 0 <= i < len(self.task_rows) for i in task_ids)
                or list(task_ids) != sorted(set(task_ids))):
            raise ValueError(f"task_ids must be a unique increasing subset of 0..{len(self.task_rows)-1} for {task_scope}")
        if type(render_gpu_device_id) is not int or render_gpu_device_id < 0:
            raise ValueError("render_gpu_device_id must be a nonnegative integer")
        if budget_mode not in ("horizon", "decisions"):
            raise ValueError("budget_mode must be horizon or decisions")
        if budget_mode == "decisions":
            if (type(max_policy_calls) is not int or not 1 <= max_policy_calls <= 200
                    or type(replan_interval) is not int or not 1 <= replan_interval <= 5):
                raise ValueError("development decision limits must be 1..200 calls and 1..5 actions")
        elif max_policy_calls is not None or replan_interval is not None:
            raise ValueError("adapter decision limits require budget_mode=decisions")
        self.task_ids = tuple(task_ids)
        self.render_gpu_device_id = render_gpu_device_id
        self.budget_mode, self.max_policy_calls, self.replan_interval = budget_mode, max_policy_calls, replan_interval
        self.environment_step_cap = (max_policy_calls * replan_interval if budget_mode == "decisions"
                                     else max(self.native_horizons[self.task_names[i]] for i in task_ids))
        budget_track = f"decision-{max_policy_calls}-prefix-{replan_interval}" if budget_mode == "decisions" else "native-horizons"
        selection = "target-first2-development" if task_scope == "pilot" else "target50-development"
        render_version = "v3" if render_track == "egl-owner-material-clamp-v1" else "v2"
        protocol = (f"{selection}/rgb/{budget_track}/v1" if render_track == "native-v1" else
                    f"{selection}/rgb/{budget_track}/{render_track}/{render_version}")
        self.descriptor = BenchmarkDescriptor("robocasa365", "1.0.1", protocol, ROBOCASA_REVISION)
        self.action_spec, self.observation_spec = ACTION_SPEC, OBSERVATION_SPEC

    def step_cap(self, task: str) -> int:
        return self.environment_step_cap if self.budget_mode == "decisions" else self.native_horizons[task]

    def budget_metadata(self, task: str) -> dict[str, JsonValue]:
        return {"budget_mode": self.budget_mode, "max_policy_calls": self.max_policy_calls,
                "render_track": self.render_track,
                "replan_interval": self.replan_interval, "environment_step_cap": self.step_cap(task),
                "native_horizon": self.native_horizons[task],
                "native_horizon_source": "pinned_robocasa1.0.1_dataset_registry",
                "evaluation_horizon": self.step_cap(task), "official_leaderboard_protocol": False}

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or seed != PILOT_SEED:
            raise ValueError(f"frozen development seed must be {PILOT_SEED}")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= len(self.task_ids)):
            raise ValueError("limit must select a nonempty prefix without repetitions")
        namespace = "robocasa365" if self.task_scope == "pilot" else "robocasa365-target50"
        return [EpisodeSpec(
            id=f"{namespace}-task{task_id:02d}-attempt01", task=self.task_names[task_id], seed=seed,
            instruction=(("Open the drawer." if task_id == 0 else "Navigate to the target fixture.")
                         if self.task_scope == "pilot" else "Follow the native task instruction provided at reset."),
            metadata={"task_id": task_id, "attempt": 1, "split": "target",
                      "task_set": self.task_rows[task_id]["task_set"],
                      **({"task_scope": "target50"} if self.task_scope == "target50" else {}),
                      "instruction_source": "native language replaces generic instruction at reset",
                      **self.budget_metadata(self.task_names[task_id])},
        ) for task_id in self.task_ids[:limit]]

    def open_episode(self, episode: EpisodeSpec) -> RoboCasa365Episode:
        if episode not in self.episodes(PILOT_SEED):
            raise ProtocolError("episode differs from the frozen RoboCasa365 manifest")
        return RoboCasa365Episode(self, episode)


@register_benchmark("robocasa365")
def make_robocasa365(parameters: Mapping[str, JsonValue]) -> RoboCasa365BenchmarkAdapter:
    unknown = set(parameters) - {"task_ids", "task_scope", "render_gpu_device_id", "budget_mode", "max_policy_calls", "replan_interval", "render_track"}
    if unknown:
        raise ValueError(f"unknown RoboCasa365 parameters: {sorted(unknown)}")
    return RoboCasa365BenchmarkAdapter(**parameters)
