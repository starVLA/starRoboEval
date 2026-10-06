"""Task-neutral lifecycle helpers for the private Direct v2 native worker."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from benchmarks.simBenchmarks.RoboDojo.bench_server.native_worker_client import CAMERAS, CLOSE_PROTOCOL


NATIVE_METHODS = (
    "close", "_post_setup_scene", "reset", "setup_scene", "get_obs", "get_obs_batch",
    "get_action_type", "take_action", "take_action_batch", "process_control_info",
    "validate_action_dict", "step", "_align_layout_success", "is_episode_end",
    "have_empty", "get_control_empty",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def native_control_class(root: Path, task_class: type, unstable_error=None) -> type:
    """Compile only pinned native control methods; never load a model client."""
    import numpy as np
    if unstable_error is None:
        from utils.cluttered_generator import UnStableError
        unstable_error = UnStableError
    source = root / "src/eval_client/eval_env.py"
    tree = ast.parse(source.read_text())
    classes = [node for node in ast.walk(tree)
               if isinstance(node, ast.ClassDef) and node.name == "EvalEnv"]
    if len(classes) != 1:
        raise RuntimeError("unexpected native evaluator AST")
    methods = [node for node in classes[0].body
               if isinstance(node, ast.FunctionDef) and node.name in NATIVE_METHODS]
    if {node.name for node in methods} != set(NATIVE_METHODS):
        raise RuntimeError("missing native method")
    new_class = ast.ClassDef(name="NativeControl", bases=[ast.Name(id="_Task", ctx=ast.Load())],
        keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[new_class], type_ignores=[]))
    namespace = {"_Task": task_class, "np": np, "deepcopy": deepcopy,
                 "UnStableError": unstable_error}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["NativeControl"]


class ResetNotificationOnly:
    def call(self, *, func_name: str) -> None:
        if func_name != "reset":
            raise RuntimeError("model calls are forbidden in the native worker")


class Worker:
    """Recording/finalization base; task reset and action semantics stay above."""

    def __init__(self) -> None:
        self.output: Path | None = None
        self.app = None
        self.env = None
        self.targets = 0
        self.attempted_targets = 0
        self.initial_ticks: int | None = None
        self.latest_reward = 0.0
        self.reward_evaluations = 0
        self.frames = []
        self.videos = {}
        self.finalized = False
        self.finalization_errors: list[str] = []
        self.finished = False
        self.first_success = None
        self.last_message = {}

    def event(self, name: str, **values: Any) -> None:
        assert self.output is not None
        record = {"event": name, "completed_control_targets": self.targets,
            "attempted_control_targets": self.attempted_targets, **values}
        with (self.output / "native_events.jsonl").open("a") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
            stream.flush()
        write_json(self.output / "status.json", record)

    def capture(self) -> dict[str, Any]:
        import av
        import numpy as np
        from PIL import Image

        raw = self.env.get_obs()
        instruction = raw.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise RuntimeError("native observation has no task instruction")
        files = {}
        for camera in CAMERAS:
            rgb = np.asarray(raw["vision"][camera]["color"])
            if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
                raise RuntimeError("native camera is not uint8 HxWx3 RGB")
            relative = f"frames/{camera}/{self.targets:06d}.png"
            path = self.output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb).save(path)
            self.frames.append({"control_target": self.targets, "camera": camera,
                "path": relative, "sha256": sha(path), "shape": list(rgb.shape)})
            files[camera] = relative
            if camera not in self.videos:
                container = av.open(str(self.output / f"{camera}.mp4"), "w")
                stream = container.add_stream("libx264", rate=25)
                stream.width, stream.height = rgb.shape[1], rgb.shape[0]
                stream.pix_fmt = "yuv420p"
                self.videos[camera] = (container, stream)
            container, stream = self.videos[camera]
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                container.mux(packet)
        write_json(self.output / "frame_manifest.json", self.frames)
        self.last_message = {"instruction": instruction, "frames": files,
                             "metrics": self.metrics()}
        return self.last_message

    def finalize(self) -> dict[str, Any]:
        if not self.finalized:
            errors = []
            for camera, (container, stream) in self.videos.items():
                try:
                    for packet in stream.encode():
                        container.mux(packet)
                    container.close()
                except Exception as exc:
                    errors.append(f"{camera}: {exc}")
            self.finalized = True
            self.finalization_errors = errors
            try:
                if self.output is not None:
                    write_json(self.output / "native_result.json", self.metrics())
                    write_json(self.output / "video_finalization.json", {"errors": errors})
            except Exception as exc:
                self.finalization_errors.append(f"finalization receipt: {type(exc).__name__}: {exc}")
        if self.finalization_errors:
            raise RuntimeError("; ".join(self.finalization_errors))
        return {"metrics": self.metrics(), "artifacts": {
            "native_result": "native_result.json", "native_events": "native_events.jsonl",
            "frame_manifest": "frame_manifest.json", "asset_manifest": "asset_manifest.json",
            "source_provenance": "source_provenance.json",
            **{f"video_{camera}": f"{camera}.mp4" for camera in self.videos}}}

    def close(self) -> dict[str, Any]:
        errors = []
        result = {}
        finalization = "failed"
        environment_cleanup = "not_created" if self.env is None else "failed"
        try:
            result = self.finalize()
            finalization = "completed"
        except Exception as exc:
            errors.append(f"finalize: {type(exc).__name__}: {exc}")
        try:
            if self.env is not None:
                self.env.close()
                environment_cleanup = "completed"
        except Exception as exc:
            errors.append(f"environment: {type(exc).__name__}: {exc}")
        prepared = {"protocol": CLOSE_PROTOCOL, "phase": "failed" if errors else "prepared",
            "pid": os.getpid(), "finalization": finalization,
            "environment_cleanup": environment_cleanup, "app_created": self.app is not None,
            "errors": errors}
        if self.output is not None:
            write_json(self.output / "cleanup_prepared.json", prepared)
        if errors:
            raise RuntimeError("; ".join(errors))
        return {**result, "cleanup_prepared": prepared}

    def shutdown_app(self) -> None:
        record = {"protocol": CLOSE_PROTOCOL, "phase": "app_shutdown_started",
            "pid": os.getpid(), "app_created": self.app is not None}
        if self.output is not None:
            write_json(self.output / "app_shutdown_started.json", record)
        try:
            if self.app is not None:
                self.app.close()
        except Exception as exc:
            if self.output is not None:
                write_json(self.output / "app_shutdown_error.json",
                    {**record, "phase": "app_shutdown_failed", "error": f"{type(exc).__name__}: {exc}"})
            raise
        if self.output is not None:
            write_json(self.output / "app_shutdown_returned.json",
                {**record, "phase": "app_shutdown_returned"})
