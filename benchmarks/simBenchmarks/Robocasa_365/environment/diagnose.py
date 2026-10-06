"""One reset plus one neutral native action; no actor or capability score."""

from __future__ import annotations

import argparse
import hashlib
import os
import traceback
from pathlib import Path

from benchkit.artifacts import append_jsonl, atomic_write_json
from .native_boundary import (ACTION_SPEC, CAMERAS, NEUTRAL_ACTION, OBSERVATION_SPEC,
                              PILOT_SEED, PILOT_TASKS, NativeBoundary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", choices=PILOT_TASKS, default="OpenDrawer")
    parser.add_argument("--seed", type=int, default=PILOT_SEED)
    parser.add_argument("--gpu", type=int, default=3)
    parser.add_argument("--render-track", choices=("native-v1", "egl-owner-restore-v1", "egl-owner-material-clamp-v1"), default="native-v1")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["MUJOCO_GL"] = "egl"
    os.environ["PYOPENGL_PLATFORM"] = "egl"
    status_path = args.output / "status.json"
    atomic_write_json(status_path, {"status": "running", "kind": "infrastructure_diagnostic"})
    session = NativeBoundary(args.task, args.seed, args.gpu, render_track=args.render_track)
    session.bind_artifact_dir(args.output / "native")
    videos = {}
    result = {"kind": "infrastructure_diagnostic", "capability_attempt": False,
              "policy_decisions": 0, "diagnostic_action_calls": 0,
              "native_steps": 0, "task": args.task, "seed": args.seed, "render_track": args.render_track,
              "action_spec": ACTION_SPEC.to_dict(), "observation_spec": OBSERVATION_SPEC.to_dict(),
              "diagnostic_action": list(NEUTRAL_ACTION), "frames": [], "videos": {}}
    failed = False
    try:
        import av
        from PIL import Image

        for camera in CAMERAS:
            container = av.open(str(args.output / (camera + ".mp4")), mode="w")
            stream = container.add_stream("libx264", rate=20)
            stream.width, stream.height, stream.pix_fmt = 256, 256, "yuv420p"
            videos[camera] = (container, stream)
        observation = session.reset()
        atomic_write_json(args.output / "native_provenance.json", session.provenance)
        for phase in ("reset", "step"):
            if phase == "step":
                result["diagnostic_action_calls"] += 1
                transition = session.step(NEUTRAL_ACTION)
                observation = transition.observation
                append_jsonl(args.output / "events.jsonl", {
                    "event": "native_transition", "step": observation.step,
                    "reward": transition.reward, "native_info": dict(transition.info),
                    "terminated": transition.terminated, "truncated": transition.truncated,
                })
            append_jsonl(args.output / "events.jsonl", {
                "event": "policy_boundary_observation", "phase": phase,
                "observation": observation.log_view(),
            })
            for camera, pixels in observation.images.items():
                path = args.output / f"{camera}-{observation.step:06d}.png"
                Image.fromarray(pixels).save(path)
                frame = {"camera": camera, "step": observation.step, "path": path.name,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                result["frames"].append(frame)
                append_jsonl(args.output / "frames.jsonl", frame)
                container, stream = videos[camera]
                for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                    container.mux(packet)
        result.update(session.metrics())
    except Exception as exc:
        failed = True
        result["error"] = {"type": type(exc).__name__, "message": str(exc),
                           "traceback": traceback.format_exc()}
    finally:
        for camera, (container, stream) in videos.items():
            try:
                for packet in stream.encode():
                    container.mux(packet)
                container.close()
            except Exception as exc:
                failed = True
                result.setdefault("close_errors", []).append(f"{camera}: {exc}")
        try:
            session.close()
        except Exception as exc:
            failed = True
            result.setdefault("close_errors", []).append(str(exc))
        result["native_steps"] = session.step_count
    if not failed:
        try:
            for frame in result["frames"]:
                with Image.open(args.output / frame["path"]) as decoded:
                    decoded.load()
                    if decoded.size != (256, 256) or decoded.mode != "RGB":
                        raise ValueError("invalid PNG")
            for camera in CAMERAS:
                path = args.output / (camera + ".mp4")
                with av.open(str(path)) as decoded:
                    frames = list(decoded.decode(video=0))
                    if len(frames) != 2 or any((f.width, f.height) != (256, 256) for f in frames):
                        raise ValueError("video must fully decode to two 256x256 frames")
                    result["videos"][camera] = {"path": path.name, "decoded_frames": len(frames),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            result["validation"] = {"png_count": len(result["frames"]), "video_count": 3,
                                     "all_fully_decoded": True}
        except Exception as exc:
            failed = True
            result["validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
    result["status"] = "failed" if failed else "passed"
    atomic_write_json(args.output / "result.json", result)
    atomic_write_json(status_path, {"status": result["status"], "kind": result["kind"],
                                    "native_steps": session.step_count, "policy_decisions": 0})
    print(str(args.output), result["status"], flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
