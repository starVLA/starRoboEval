"""LIBERO-Plus native direct-control adapter, with no simulator import at startup."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from benchkit.artifacts import append_jsonl, atomic_write_json
from benchkit.contracts import ActionSpec, BenchmarkDescriptor, EpisodeSpec, JsonValue, Observation, ObservationSpec, Transition
from benchkit.errors import CompatibilityError, ProtocolError
from benchkit.registry import register_benchmark

from .protocol.catalog import COUNTS, HORIZONS, REVISION, file_sha256, native_files, task_catalog

CAMERAS = ("agentview", "robot0_eye_in_hand")
SETTLE_STEPS = 10
PACKAGE_PINS = {"robosuite": "1.4.0", "mujoco": "3.2.3", "numpy": "1.24.4", "torch": "2.5.1+cpu",
                "Wand": "0.6.13", "scikit-image": "0.24.0"}
IMPORT_SUFFIXES = (".py", ".pyc", ".pyo", ".so", ".pyd", ".dll")


def verify_native_import_inventory(root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Reject source/extension/cache overrides in the executed native package.

    Released assets and BDDL/reset data are checked by separate receipts. They
    are not recursively scanned as import code, nor is unused lifelong code.
    This is a filesystem inventory, not attestation of loaded Python memory.
    """
    namespace, package = root / "libero", root / "libero/libero"
    for directory in (namespace, package):
        if directory.is_symlink() or not directory.is_dir():
            raise CompatibilityError("native package must be a regular directory")
    # This pin intentionally has a namespace package at the outer libero level.
    # A new __init__.py or extension there would execute before origin checks.
    if any(path.name.endswith(IMPORT_SUFFIXES) for path in namespace.iterdir() if not path.is_dir()):
        raise CompatibilityError("unrecorded native namespace import file")
    expected = {row["path"] for row in rows if row["path"].endswith(".py")}
    actual = set()
    count = 0
    for directory, children, filenames in os.walk(package, followlinks=False):
        if Path(directory) == package:
            children[:] = [name for name in children if name not in {"assets", "bddl_files", "init_files"}]
        for name in children:
            if (Path(directory) / name).is_symlink():
                raise CompatibilityError("native import directory symlink is not pinned")
        count += len(children) + len(filenames)
        if count > 1000:
            raise CompatibilityError("native import inventory exceeds its bound")
        for name in filenames:
            if not name.endswith(IMPORT_SUFFIXES):
                continue
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file() or relative not in expected:
                raise CompatibilityError("unrecorded native source, bytecode or extension import file")
            actual.add(relative)
    if actual != expected:
        raise CompatibilityError("native Python import inventory differs from the frozen source manifest")


def image_magick_receipt() -> dict:
    """Actual native sensor-noise backend, not just the Python Wand version."""
    from wand import version
    return {"version": version.MAGICK_VERSION, "features": version.MAGICK_VERSION_FEATURES,
            "quantum_depth": version.QUANTUM_DEPTH, "hdri": version.MAGICK_HDRI,
            "scope": "loaded library reports; not binary or library-dependency attestation"}


def policy_observation(raw: Mapping[str, Any], step: int, instruction: str) -> Observation:
    """Two independent RGB copies only; preserve upstream perturbations exactly."""
    import numpy as np

    images = {}
    for camera in CAMERAS:
        frame = np.asarray(raw.get(camera + "_image"))
        if frame.dtype != np.uint8 or frame.shape != (256, 256, 3):
            raise ProtocolError("LIBERO-Plus requires two 256x256 uint8 RGB observations")
        images[camera] = np.ascontiguousarray(frame[::-1, ::-1]).copy()
    return Observation(step=step, instruction=instruction, images=images)


def verify_native_source(root: Path) -> dict:
    """Verify bounded native source inputs before loading torch or the simulator."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True, timeout=20, env=env).stdout.strip()
        revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True, timeout=20, env=env).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompatibilityError("cannot verify the LIBERO-Plus native checkout") from exc
    if Path(top).resolve() != root or revision != REVISION:
        raise CompatibilityError(f"LIBERO-Plus requires its own native checkout at {REVISION}")
    manifest_path = Path(__file__).parents[1] / "environment" / "native_source_manifest.json"
    payload = json.loads(manifest_path.read_text())
    if (payload.get("schema_version") != "starvla-rsi.libero-plus-native-source/v1"
            or payload.get("upstream_revision") != REVISION or not payload.get("files")
            or len(payload["files"]) > 200):
        raise CompatibilityError("native source inventory differs")
    verify_native_import_inventory(root, payload["files"])
    for item in payload["files"]:
        path = (root / item["path"]).resolve()
        if (not path.is_relative_to(root) or path.stat().st_size != item["size_bytes"]
                or file_sha256(path, max_bytes=4 * 1024 * 1024) != item["sha256"]):
            raise CompatibilityError("native source differs from the frozen source inventory")
    return {"manifest_sha256": file_sha256(manifest_path), "files": payload["files"], "scope": payload["scope"]}


def prepare_native_import(root: Path) -> dict:
    # Native imports must not leave bytecode caches that the next session's
    # source inventory would reject; pre-existing caches still fail it.
    sys.dont_write_bytecode = True
    source = verify_native_source(root)
    for package, expected in PACKAGE_PINS.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise CompatibilityError(f"missing required LIBERO-Plus package {package}") from exc
        if actual != expected:
            raise CompatibilityError(f"LIBERO-Plus requires {package}=={expected}, got {actual}")
    config = os.environ.get("LIBERO_CONFIG_PATH")
    if not config or not (Path(config) / "config.yaml").is_file():
        raise CompatibilityError("set LIBERO_CONFIG_PATH to an isolated, pre-created config directory")
    # Namespace packages are used by this pin. Never silently reuse a different
    # installed standard-LIBERO namespace or alter an already imported runtime.
    if "libero" in sys.modules:
        locations = tuple(Path(path).resolve() for path in getattr(sys.modules["libero"], "__path__", ()))
        if locations != (root / "libero",):
            raise CompatibilityError("another LIBERO namespace is already loaded in this process")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    native = importlib.import_module("libero.libero")
    if Path(native.__file__).resolve() != root / "libero/libero/__init__.py":
        raise CompatibilityError("imported LIBERO namespace differs from the selected Plus checkout")
    for field, suffix in (("benchmark_root", ""), ("bddl_files", "bddl_files"),
                          ("init_states", "init_files"), ("assets", "assets")):
        expected = root / "libero/libero" / suffix
        if Path(native.get_libero_path(field)).resolve() != expected or not expected.is_dir():
            raise CompatibilityError(f"LIBERO-Plus {field} must resolve inside the pinned native checkout")
    return source


def selected_asset_receipt(native_env: Any, root: Path, robosuite_root: Path) -> dict:
    """Hash only files explicitly referenced by the constructed native XML.

    This is not an attestation of all 16 GB of released assets or loaded GPU
    memory. The receipt never crosses the policy observation boundary.
    """
    text = native_env.model.get_xml()
    if not isinstance(text, str) or len(text.encode()) > 8 * 1024 * 1024:
        raise CompatibilityError("native XML exceeds the asset-receipt bound")
    document = ET.fromstring(text)
    allowed = {"libero_plus_assets": root / "libero/libero/assets",
               "robosuite_assets": robosuite_root / "models/assets"}
    paths = {}
    unresolved = []
    compiler = document.find("compiler")
    compiler = {} if compiler is None else compiler.attrib
    for element in document.findall(".//asset/*"):
        filename = element.get("file")
        if not filename:
            continue
        path = Path(filename)
        if not path.is_absolute():
            directory = compiler.get("meshdir" if element.tag == "mesh" else "texturedir", "")
            path = Path(directory) / path
        if not path.is_absolute():
            unresolved.append({"tag": element.tag, "file": filename})
            continue
        path = path.resolve()
        match = next(((label, base) for label, base in allowed.items() if path.is_relative_to(base.resolve())), None)
        if match is None:
            raise CompatibilityError("native asset reference leaves the declared source/package asset roots")
        label, base = match
        key = label + "/" + path.relative_to(base.resolve()).as_posix()
        paths[key] = path
    if len(paths) > 2048 or sum(path.stat().st_size for path in paths.values()) > 2 * 1024**3:
        raise CompatibilityError("selected native asset receipt exceeds its declared bound")
    return {"scope": "constructed XML mesh/texture file references, not complete asset or GPU-memory attestation",
            "native_model_xml_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "files": [{"path": name, "size_bytes": path.stat().st_size,
                       "sha256": file_sha256(path, max_bytes=256 * 1024**2)} for name, path in sorted(paths.items())],
            "unresolved_relative_references": unresolved}


class LiberoPlusEpisode:
    def __init__(self, adapter: LiberoPlusBenchmarkAdapter, episode: EpisodeSpec):
        self.benchmark, self.episode = adapter, episode
        self.env = None
        self.artifact_dir: Path | None = None
        self.writers: dict[str, Any] = {}
        self.step_count = 0
        self.control_attempts = 0
        self.settle_count = 0
        self.settle_attempts = 0
        self.uncertain_controls = 0
        self.success = False
        self.finished = False
        self.reset_claimed = False
        self.initialized = False
        self.closed = False
        self.finalized = False
        self.close_error: Exception | None = None
        self.provenance: dict[str, Any] | None = None

    def bind_artifact_dir(self, path: Path) -> None:
        if self.artifact_dir is not None or self.reset_claimed or self.finalized or self.closed:
            raise ProtocolError("artifact directory must be bound once before reset")
        self.artifact_dir = path
        path.mkdir(parents=True, exist_ok=True)

    def reset(self) -> Observation:
        if self.reset_claimed or self.closed or self.finalized:
            raise ProtocolError("LIBERO-Plus session permits exactly one reset attempt")
        self.reset_claimed = True
        try:
            return self._reset_once()
        except Exception:
            self.finished = True
            raise

    def _reset_once(self) -> Observation:
        root = self.benchmark.upstream
        source = prepare_native_import(root)
        import numpy as np
        import robosuite
        from libero.libero import benchmark as native_benchmark
        from libero.libero.envs import OffScreenRenderEnv

        suite = native_benchmark.get_benchmark_dict()[self.benchmark.suite](task_order_index=0)
        task_id = self.episode.metadata["native_id"]
        task = suite.get_task(task_id)
        row = self.benchmark.catalog["tasks"][task_id]
        if (suite.n_tasks != COUNTS[self.benchmark.suite] or task.name != row["native_name"]
                or task.language != row["native_instruction"] or task.problem_folder != self.benchmark.suite
                or task.bddl_file != task.name + ".bddl" or task.init_states_file != task.name + ".pruned_init"):
            raise CompatibilityError("native LIBERO-Plus identity/order differs from frozen selection")
        paths = native_files(self.benchmark.suite, task.name)
        bddl = root / "libero/libero/bddl_files" / paths["bddl"]
        virtual_bddl = root / "libero/libero/bddl_files" / paths["virtual_bddl"]
        initial_file = root / "libero/libero/init_files" / row["initial_file"]
        if file_sha256(bddl) != row["bddl_sha256"] or file_sha256(initial_file) != row["initial_file_sha256"]:
            raise CompatibilityError("selected BDDL/reset file differs from the frozen catalog")
        initial_states = suite.get_task_init_states(task_id)
        if file_sha256(initial_file) != row["initial_file_sha256"]:
            raise CompatibilityError("reset file changed while the native loader read it")
        states = np.asarray(initial_states)
        if states.ndim != 2 or not 1 <= len(states) <= 1000 or not 1 <= states.shape[1] <= 10000 or not np.isfinite(states).all():
            raise CompatibilityError("native initial states must be a finite bounded matrix")
        controller = robosuite.load_controller_config(default_controller="OSC_POSE")
        if (controller["input_min"] != -1 or controller["input_max"] != 1
                or controller["output_max"] != [0.05, 0.05, 0.05, 0.5, 0.5, 0.5]
                or controller["output_min"] != [-0.05, -0.05, -0.05, -0.5, -0.5, -0.5]
                or controller["control_delta"] is not True):
            raise CompatibilityError("native OSC_POSE controller differs from declared normalized control")
        self.provenance = {"upstream_revision": REVISION, "native_source": source,
            "suite": self.benchmark.suite, "task_order_index": 0, "native_id": task_id,
            "native_name": task.name, "category": row["category"], "difficulty_level": row["difficulty_level"],
            "native_filename_instruction": task.language, "public_instruction_source": "backing BDDL :language",
            "initial_state_index": 0, "available_initial_states": len(states), "reset_seed": self.episode.seed,
            "bddl_file": paths["bddl"], "virtual_bddl_file": paths["virtual_bddl"],
            "bddl_sha256": row["bddl_sha256"], "initial_file": row["initial_file"],
            "initial_file_sha256": row["initial_file_sha256"],
            "selected_state_sha256": hashlib.sha256(states[0].tobytes()).hexdigest(),
            "declared_settle_steps": SETTLE_STEPS, "controller": controller,
            "native_engine_horizon": self.benchmark.native_engine_horizon,
            "image_transform": "native RGB[::-1,::-1] copied; native sensor perturbations untouched",
            "image_magick": image_magick_receipt(),
            "versions": {name: importlib.metadata.version(name) for name in (*PACKAGE_PINS, "Pillow", "imageio", "imageio-ffmpeg", "PyOpenGL")},
            **self.benchmark.budget_metadata()}
        self._write_provenance()
        np.random.seed(self.episode.seed)
        self._event("native_construct_start")
        self.env = OffScreenRenderEnv(bddl_file_name=str(virtual_bddl), camera_heights=256, camera_widths=256,
            camera_names=list(CAMERAS), camera_depths=False, camera_segmentations=None, control_freq=20,
            horizon=self.benchmark.native_engine_horizon, render_gpu_device_id=self.benchmark.render_gpu_device_id)
        self._event("native_construct_end")
        low, high = self.env.env.action_spec
        if not np.array_equal(low, np.full(7, -1.0)) or not np.array_equal(high, np.full(7, 1.0)):
            raise CompatibilityError("native action bounds must be 7D [-1, 1]")
        self.env.seed(self.episode.seed)
        self._event("native_reset_start")
        self.env.reset()
        self._event("native_reset_end")
        self._event("native_initial_state_start")
        raw = self.env.set_init_state(initial_states[0])
        self._event("native_initial_state_end")
        self.provenance["selected_assets"] = selected_asset_receipt(self.env.env, root, Path(robosuite.__file__).resolve().parent)
        self._write_provenance()
        for _ in range(SETTLE_STEPS):
            raw, _reward, done, _info = self._native_control([0.0] * 6 + [-1.0], settle=True)
            if bool(done):
                raise ProtocolError("native success occurred during initialization before a policy action")
        observation = self._observe(raw)
        self.initialized = True
        return observation

    def _event(self, event: str, **fields) -> None:
        if self.artifact_dir is not None:
            append_jsonl(self.artifact_dir / "native_events.jsonl", {"event": event, **fields})

    def _native_control(self, action, *, settle=False):
        phase = "settle" if settle else "policy"
        index = (self.settle_attempts if settle else self.control_attempts) + 1
        self._event("native_control_start", phase=phase, attempt=index, action=list(action))
        if settle:
            self.settle_attempts += 1
        else:
            self.control_attempts += 1
        try:
            returned = self.env.step(list(action))
        except Exception:
            # The native call may have partly advanced before raising. Do not
            # guess how much or permit the same action to be replayed.
            self.uncertain_controls += 1
            self.finished = True
            raise
        if settle:
            self.settle_count += 1
        else:
            self.step_count += 1
        self._event("native_control_end", phase=phase, attempt=index,
                    completed_controls=self.settle_count if settle else self.step_count)
        return returned

    def _write_provenance(self) -> None:
        if self.artifact_dir is not None and self.provenance is not None:
            atomic_write_json(self.artifact_dir / "native_provenance.json", self.provenance)

    def _observe(self, raw: Mapping[str, Any]) -> Observation:
        observation = policy_observation(raw, self.step_count, self.episode.instruction)
        if self.artifact_dir is not None:
            import imageio.v2 as imageio
            from PIL import Image
            for camera, frame in observation.images.items():
                path = self.artifact_dir / f"{camera}-{self.step_count:06d}.png"
                Image.fromarray(frame).save(path)
                if camera not in self.writers:
                    self.writers[camera] = imageio.get_writer(str(self.artifact_dir / f"{camera}.mp4"),
                        fps=20, codec="libx264", macro_block_size=1)
                self.writers[camera].append_data(frame)
                append_jsonl(self.artifact_dir / "frames.jsonl", {"camera": camera, "step": self.step_count,
                    "path": path.name, "sha256": file_sha256(path), "instruction": self.episode.instruction})
        return observation

    def step(self, action: tuple[float, ...]) -> Transition:
        if self.env is None or not self.initialized or self.finished or self.closed or self.finalized:
            raise ProtocolError("cannot step an uninitialized/finished LIBERO-Plus session")
        action = self.benchmark.action_spec.validate(action)
        try:
            raw, reward, done, _private_info = self._native_control(action)
            # BDDLBaseDomain.step already assigns done = _check_success(). No
            # extra scorer query or privileged field is used.
            self.success = bool(done)
            truncated = self.step_count >= self.benchmark.environment_step_cap and not self.success
            self.finished = self.success or truncated
            return Transition(observation=self._observe(raw), reward=float(reward), terminated=self.success,
                              truncated=truncated, info={"native_success": self.success, "native_steps": self.step_count})
        except Exception:
            self.finished = True
            raise

    def metrics(self) -> Mapping[str, JsonValue]:
        return {"success": self.success, "native_steps": self.step_count, "settle_steps": self.settle_count,
                "declared_settle_steps": SETTLE_STEPS, "native_control_attempts": self.control_attempts,
                "settle_control_attempts": self.settle_attempts, "uncertain_native_controls": self.uncertain_controls,
                **self.benchmark.budget_metadata()}

    def _close_writers(self) -> None:
        errors = []
        for camera, writer in list(self.writers.items()):
            try:
                writer.close()
            except Exception as exc:
                errors.append(exc)
            finally:
                del self.writers[camera]
        if errors:
            raise errors[0]

    def artifacts(self) -> Mapping[str, str]:
        self.finalized = True
        self._close_writers()
        if self.artifact_dir is None:
            return {}
        names = {camera + "_video": camera + ".mp4" for camera in CAMERAS}
        names.update(frames="frames.jsonl", native_provenance="native_provenance.json", native_events="native_events.jsonl")
        return {key: str(self.artifact_dir / name) for key, name in names.items() if (self.artifact_dir / name).is_file()}

    def close(self) -> None:
        if self.closed:
            if self.close_error is not None:
                raise self.close_error
            return
        self.closed = True
        self.finalized = True
        self.finished = True
        errors = []
        try:
            self._close_writers()
        except Exception as exc:
            errors.append(exc)
        if self.env is not None:
            native, self.env = self.env, None
            try:
                native.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            self.close_error = errors[0]
            raise self.close_error


class LiberoPlusBenchmarkAdapter:
    """One explicit fast subset, native order, state 0, one attempt per task."""
    def __init__(self, *, upstream: str, suite: str = "libero_spatial", task_ids: Sequence[int] = (0,),
                 evaluation_mode: str = "fast", render_gpu_device_id: int = 0,
                 budget_mode: str = "horizon", max_policy_calls: int | None = None,
                 replan_interval: int | None = None):
        if not isinstance(upstream, str) or not Path(upstream).is_absolute():
            raise ValueError("upstream must be an absolute server-local native checkout path")
        if evaluation_mode != "fast":
            raise ValueError("only explicit fast selections are supported; full native parity is not validated")
        self.catalog = task_catalog(suite)
        if (not isinstance(task_ids, (list, tuple)) or not task_ids
                or any(type(index) is not int or not 0 <= index < COUNTS[suite] for index in task_ids)
                or list(task_ids) != sorted(set(task_ids))):
            raise ValueError("task_ids must be a nonempty unique increasing subset of native indices")
        if type(render_gpu_device_id) is not int or render_gpu_device_id < 0:
            raise ValueError("render_gpu_device_id must be a nonnegative integer")
        if budget_mode not in ("horizon", "decisions"):
            raise ValueError("budget_mode must be horizon or decisions")
        if budget_mode == "decisions":
            if any(type(value) is not int or not 1 <= value <= 10000 for value in (max_policy_calls, replan_interval)):
                raise ValueError("decision budgets require positive bounded max_policy_calls and replan_interval")
            cap = max_policy_calls * replan_interval
            if cap > 10000:
                raise ValueError("maximum declared environment controls is 10000")
        else:
            if max_policy_calls is not None or replan_interval is not None:
                raise ValueError("adapter decision parameters require budget_mode=decisions")
            cap = HORIZONS[suite]
        self.upstream = Path(upstream).resolve()
        self.suite, self.task_ids = suite, tuple(task_ids)
        self.render_gpu_device_id = render_gpu_device_id
        self.budget_mode, self.max_policy_calls, self.replan_interval = budget_mode, max_policy_calls, replan_interval
        self.environment_step_cap = self.evaluation_horizon = cap
        self.native_engine_horizon = max(1000, cap + SETTLE_STEPS)
        self.opened: set[tuple[str, int]] = set()
        budget = f"decision-{max_policy_calls}-prefix-{replan_interval}" if budget_mode == "decisions" else "reference-horizon"
        self.descriptor = BenchmarkDescriptor(name="libero_plus", version="0.1.0",
            protocol_version=f"libero-plus-fast/{suite}/rgb/{budget}/v1", source_revision=REVISION)
        self.observation_spec = ObservationSpec(cameras=CAMERAS, modalities=("language", "rgb"))
        self.action_spec = ActionSpec(mode="normalized_osc_delta_pose", size=7,
            names=("dx_scaled", "dy_scaled", "dz_scaled", "rx_scaled", "ry_scaled", "rz_scaled", "gripper"),
            low=(-1.0,) * 7, high=(1.0,) * 7, control_hz=20.0,
            frame="world: translation component 1 means +0.05 m",
            rotation="world axis-angle delta: rotation component 1 means +0.5 rad",
            gripper="-1 open; +1 close; 0 hold native gripper target")

    def budget_metadata(self) -> dict[str, JsonValue]:
        return {"evaluation_mode": "fast", "budget_mode": self.budget_mode,
                "max_policy_calls": self.max_policy_calls, "replan_interval": self.replan_interval,
                "environment_step_cap": self.environment_step_cap, "native_horizon": HORIZONS[self.suite],
                "native_horizon_source": "retained_starvla_libero_plus_evaluator_reference",
                "evaluation_horizon": self.evaluation_horizon}

    def episodes(self, seed: int, limit: int | None = None) -> Sequence[EpisodeSpec]:
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("seed must be a predeclared uint32 integer")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= len(self.task_ids)):
            raise ValueError("limit must select a nonempty prefix without repeats")
        rows = [self.catalog["tasks"][index] for index in self.task_ids[:limit]]
        return [EpisodeSpec(id=f"{self.suite}-task{row['native_id']:04d}-init00", seed=seed,
            task=f"{self.suite}/task-{row['native_id']}", instruction=row["instruction"],
            metadata={"suite": self.suite, "native_id": row["native_id"], "native_name": row["native_name"],
                      "category": row["category"], "difficulty_level": row["difficulty_level"],
                      "task_order_index": 0, "initial_state_index": 0, "attempt": 1,
                      "settle_steps": SETTLE_STEPS, **self.budget_metadata()}) for row in rows]

    def open_episode(self, episode: EpisodeSpec) -> LiberoPlusEpisode:
        key = (episode.id, episode.seed)
        if episode not in self.episodes(episode.seed) or key in self.opened:
            raise ProtocolError("episode differs from selection or was already attempted")
        self.opened.add(key)
        return LiberoPlusEpisode(self, episode)


@register_benchmark("libero_plus")
def make_libero_plus(parameters: Mapping[str, JsonValue]) -> LiberoPlusBenchmarkAdapter:
    allowed = {"upstream", "suite", "task_ids", "evaluation_mode", "render_gpu_device_id",
               "budget_mode", "max_policy_calls", "replan_interval"}
    if not isinstance(parameters, Mapping) or set(parameters) - allowed:
        raise ValueError("unknown LIBERO-Plus adapter parameters")
    return LiberoPlusBenchmarkAdapter(**parameters)
