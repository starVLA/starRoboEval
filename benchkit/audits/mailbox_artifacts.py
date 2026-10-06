#!/usr/bin/env python3
"""Closed LIBERO/SimplerEnv/RoboCasa365/SIMPLE artifact audit; never runs a simulator.

The caller explicitly supplies the one closed mailbox. This is evidence checking,
not actor isolation, native scoring, model metering or leaderboard certification.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from fractions import Fraction
from pathlib import Path

from benchkit.audits.closed_run import ClosedFiles, audit_run, require


PUBLIC_FIELDS = {"schema_version", "request_id", "step", "instruction", "images",
                 "state", "observation_spec", "action_spec", "budgets", "prompt", "history"}
PUBLIC_FIELDS_V3 = PUBLIC_FIELDS | {"policy_constraints", "control_feedback"}
IMAGE_FIELDS = {"path", "encoding", "color_space", "width", "height", "sha256"}
ROBOCASA_CAMERAS = ["robot0_agentview_left", "robot0_agentview_right", "robot0_eye_in_hand"]
SIMPLE_HEAD_CAMERAS = {"head_stereo_left", "head_stereo_right"}
SIMPLE_ALL_CAMERAS = SIMPLE_HEAD_CAMERAS | {"front_stereo_left", "front_stereo_right"}


def audit_policy_fields(public: dict, version: str, parameters: dict, protocol: dict,
                        feedback: dict) -> None:
    """Check declared policy-only settings and counter receipts, without media.

    Old v2 keeps its historical field set; it is never relabeled v3. This helper
    checks record consistency only, not trusted enforcement by an external actor.
    """
    require(version in {"starvla-rsi.mailbox/v2", "starvla-rsi.mailbox/v3"},
            "unsupported mailbox schema")
    require(set(public) == (PUBLIC_FIELDS_V3 if version.endswith("/v3") else PUBLIC_FIELDS),
            "unexpected public observation fields")
    require(public["schema_version"] == version, "public policy schema drift")
    if version.endswith("/v2"):
        return
    require(protocol.get("execution_feedback_version") == "starvla-rsi.execution-feedback/v1",
            "mailbox v3 requires declared execution receipts")
    require(not {"min_action_decisions_before_give_up", "stop_constraint_version",
                 "early_policy_stop_exception"} & set(protocol),
            "policy persistence must not be mixed into benchmark protocol")
    rule = parameters.get("policy_stop_rule")
    require(isinstance(rule, dict) and set(rule) == {
        "stop_constraint_version", "min_action_decisions_before_give_up",
        "early_policy_stop_exception", "scope"}, "invalid policy persistence declaration")
    minimum = rule["min_action_decisions_before_give_up"]
    require(type(minimum) is int and minimum >= 0
            and rule["stop_constraint_version"] == "minimum-action-decisions/v2"
            and rule["early_policy_stop_exception"] == "safety_stop_with_nonempty_note"
            and rule["scope"] == "policy", "unknown policy persistence declaration")
    received = public["control_feedback"]
    require(isinstance(received, dict) and set(received) == set(feedback)
            and all(type(value) is int and value >= 0 for value in received.values())
            and received == feedback, "policy execution feedback differs from actual controls")
    expected = {**rule, "voluntary_stop_allowed": feedback["action_decisions"] >= minimum}
    require(public["policy_constraints"] == expected
            and type(public["policy_constraints"].get("voluntary_stop_allowed")) is bool
            and type(public["policy_constraints"].get("min_action_decisions_before_give_up")) is int,
            "public policy persistence configuration drift")


def bound_reference(files: ClosedFiles, reference: str) -> str:
    """Accept only explicit absolute references inside the caller-authorized root."""
    path = Path(reference)
    require(path.is_absolute() and ".." not in path.parts, "unsafe absolute reference")
    require(path.is_relative_to(files.root), "reference outside authorized root")
    relative = path.relative_to(files.root).as_posix()
    files.path(relative)  # Includes symlink and missing-file rejection.
    return relative


def png(files: ClosedFiles, relative: str, expected_hash: str):
    from PIL import Image

    payload = files.raw(relative)
    require(files.hashes[relative] == expected_hash, "PNG digest mismatch")
    with Image.open(io.BytesIO(payload)) as decoded:
        require(decoded.format == "PNG" and decoded.mode == "RGB", "non-RGB PNG")
        decoded.load()
        return decoded.copy()


def stream_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_video(files: ClosedFiles, relative: str, rows: list, frame_base: Path,
                *, expected_hz: int | None = None) -> dict:
    import av
    import numpy as np

    path = files.path(relative)
    digest = stream_hash(path)
    count = flat_frames = 0
    differences = []
    dimensions = None
    with av.open(str(path)) as container:
        require(len(container.streams.video) == 1, "video must have one video stream")
        for frame in container.decode(video=0):
            require(count < len(rows), "video has extra frames")
            if expected_hz is not None:
                require(frame.pts is not None and frame.time_base is not None
                        and frame.pts * frame.time_base == Fraction(count, expected_hz),
                        "video presentation timestamp differs from native control time")
            row = rows[count]
            expected = png(files, (frame_base / row["path"]).as_posix(), row["sha256"])
            rgb = frame.to_ndarray(format="rgb24")
            require(rgb.shape == (expected.height, expected.width, 3), "video dimensions differ from PNG")
            dimensions = [expected.width, expected.height]
            flat_frames += int(rgb.max() == rgb.min())
            differences.append(float(np.abs(rgb.astype(np.int16) - np.asarray(expected).astype(np.int16)).mean()))
            count += 1
    require(count == len(rows), "video frame count differs from native frames")
    require(stream_hash(files.path(relative)) == digest, "video changed during audit")
    return {"path": relative, "sha256": digest, "frames": count,
            **({"presentation_timestamps_verified_hz": expected_hz} if expected_hz is not None else {}),
            "dimensions": dimensions, "flat_frames": flat_frames,
            "maximum_png_pixel_mae_255": max(differences, default=None),
            "mean_png_pixel_mae_255": sum(differences) / count if count else None,
            "comparison": "Lossy-codec differences are reported, not a task score or automatic parity verdict."}


def audit_robocasa_controls(files: ClosedFiles, result: dict, events: list) -> int:
    """Compare retained adapter-side native call records; do not invoke a scorer."""
    rows = files.jsonl(bound_reference(files, result["artifacts"]["native_actions"]))
    controls = [event for event in events if event["event"] == "environment_step"]
    require(len(rows) == 2 * len(controls) == 2 * result["environment_steps"],
            "RoboCasa native action coverage mismatch")
    for index, event in enumerate(controls, 1):
        start, end = rows[2 * index - 2:2 * index]
        for vector in (start.get("action"), event.get("action")):
            require(isinstance(vector, list) and bool(vector)
                    and all(type(value) in (int, float) and math.isfinite(value) for value in vector),
                    "RoboCasa native/runner action must contain finite nonboolean numbers")
        require(set(start) == {"event", "step", "action"}
                and start["event"] == "native_action_start"
                and type(start["step"]) is int and start["step"] == index
                and start["action"] == event["action"], "RoboCasa native action start mismatch")
        require(set(end) == {"event", "step", "reward", "native_success", "native_done",
                             "native_truncated", "adapter_truncated"}
                and end["event"] == "native_action_end"
                and type(end["step"]) is int and end["step"] == index,
                "RoboCasa native action end identity mismatch")
        require(all(type(end[key]) is bool for key in
                    ("native_success", "native_done", "native_truncated", "adapter_truncated")),
                "RoboCasa native flag type mismatch")
        require(type(end["reward"]) in (int, float) and end["reward"] == float(end["native_success"])
                and end["reward"] == event["reward"]
                and type(event["reward"]) in (int, float)
                and end["native_success"] is event["info"]["native_success"]
                and type(event["info"]["native_steps"]) is int
                and event["info"]["native_steps"] == index
                and event["terminated"] is (end["native_done"] or end["native_success"])
                and event["truncated"] is end["adapter_truncated"],
                "RoboCasa native/runner transition mismatch")
        require(not end["native_truncated"] or end["adapter_truncated"],
                "RoboCasa native truncation lost")
    require(result["success"] is (rows[-1]["native_success"] if rows else False),
            "RoboCasa final native score mismatch")
    return len(controls)


def finite_vector(value, size: int) -> bool:
    return (isinstance(value, list) and len(value) == size
            and all(type(item) in (int, float) and math.isfinite(item) for item in value))


def simple_layout(files: ClosedFiles, manifest: dict, result: dict, base: Path | None):
    """Read only retained episode files; no native imports or external fingerprints."""
    require(base is not None, "SIMPLE requires the audited result directory, not a reconstructed episode ID")
    native = files.json((base / result["artifacts"]["native_provenance"]).as_posix())
    spec = manifest["observation_spec"]
    names = spec["state_names"]
    require(spec["cameras"] == ["head_stereo_left"] and len(names) == 31
            and all(isinstance(name, str) and name for name in names)
            and len(set(names)) == 31 and names == manifest["action_spec"]["names"][:31]
            and names == native["public_state_names"], "unsupported SIMPLE camera/state track")
    require(native["diagnostic_only"] is False and result["metrics"]["diagnostic_only"] is False,
            "SIMPLE diagnostic is not a capability attempt")
    raw = native["instruction"]
    require(isinstance(raw, str) and bool(raw.strip())
            and raw.strip() == result["episode"]["instruction"], "SIMPLE episode instruction mismatch")
    require(native["task"] == result["episode"]["task"], "SIMPLE retained task mismatch")
    if "selected_task_configuration" in native:
        require(native["selected_task_configuration"]["instruction"] == raw,
                "SIMPLE retained configuration instruction mismatch")
    rows = []
    for step in range(result["environment_steps"] + 1):
        relative = f"rgb/head_stereo_left_{step:06d}.png"
        path = (base / relative).as_posix()
        files.raw(path)
        rows.append({"step": step, "camera": "head_stereo_left", "path": relative,
                     "sha256": files.hashes[path], "instruction": raw})
    expected = {row["path"] for row in rows}
    actual = set()
    for path in (files.root / base / "rgb").rglob("*"):
        require(not path.is_symlink(), "symlink in SIMPLE PNG directory")
        if path.is_file():
            actual.add(path.relative_to(files.root / base).as_posix())
    require(actual == expected, "SIMPLE PNG directory coverage gap/extra")
    return base, rows, native


def audit_simple_controls(files: ClosedFiles, base: Path, native: dict, spec: dict,
                          result: dict, events: list, observations: dict) -> int:
    names = spec["state_names"]
    for observation in observations.values():
        require(finite_vector(observation["state"], 31), "SIMPLE state must be 31 finite nonboolean numbers")
        require(observation["instruction"] == native["instruction"], "SIMPLE raw native language mismatch")
    controls = [event for event in events if event["event"] == "environment_step"]
    relative = (base / "private_native_ticks.jsonl").as_posix()
    require(not (files.root / relative).is_symlink(), "symlink in SIMPLE optional tick path")
    rows = files.jsonl(relative) if controls or (files.root / relative).exists() else []
    require(len(rows) == len(controls) == result["environment_steps"], "SIMPLE native tick coverage mismatch")
    total = 0.0
    for index, (row, event) in enumerate(zip(rows, controls), 1):
        require(set(row) == {"joint_positions", "reward", "success", "terminated", "truncated",
                             "native_steps", "step_wall_seconds"}, "SIMPLE native tick fields mismatch")
        require(type(row["native_steps"]) is int and row["native_steps"] == index
                and type(event["info"]["native_steps"]) is int and event["info"]["native_steps"] == index,
                "SIMPLE native tick counter mismatch")
        require(all(type(row[key]) is bool for key in ("success", "terminated", "truncated"))
                and row["success"] is event["info"]["native_success"]
                and row["terminated"] is event["terminated"] and row["truncated"] is event["truncated"],
                "SIMPLE native tick flag mismatch")
        require(type(row["reward"]) in (int, float) and math.isfinite(row["reward"])
                and type(event["reward"]) in (int, float) and row["reward"] == event["reward"]
                and type(row["step_wall_seconds"]) in (int, float)
                and math.isfinite(row["step_wall_seconds"]) and row["step_wall_seconds"] >= 0,
                "SIMPLE native tick reward/time mismatch")
        joints = row["joint_positions"]
        require(isinstance(joints, dict) and set(joints) == set(names), "SIMPLE private encoder names mismatch")
        values = [joints[name] for name in names]
        require(finite_vector(values, 31) and values == observations[index]["state"],
                "SIMPLE private/public encoder mismatch")
        total += row["reward"]
    require(result["success"] is (rows[-1]["success"] if rows else False), "SIMPLE final native score mismatch")
    require(type(result["metrics"]["native_steps"]) is int
            and result["metrics"]["native_steps"] == len(rows)
            and type(result["metrics"]["native_return"]) in (int, float)
            and result["metrics"]["native_return"] == total, "SIMPLE native metric mismatch")
    return len(rows)


def audit_private_simple_video(files: ClosedFiles, relative: str, count: int) -> dict:
    """These cameras have no retained PNGs. Decode/timing is not pixel parity."""
    import av

    digest = stream_hash(files.path(relative))
    frames = flat = 0
    dimensions = None
    with av.open(str(files.path(relative))) as container:
        require(len(container.streams.video) == 1, "video must have one video stream")
        for frame in container.decode(video=0):
            require(frames < count, "SIMPLE private video has extra frames")
            require(frame.pts is not None and frame.time_base is not None
                    and frame.pts * frame.time_base == Fraction(frames, 50),
                    "SIMPLE private video presentation timestamp mismatch")
            rgb = frame.to_ndarray(format="rgb24")
            size = [frame.width, frame.height]
            require(frame.width > 0 and frame.height > 0
                    and (dimensions is None or dimensions == size), "SIMPLE private video dimension drift")
            dimensions = size
            flat += int(rgb.max() == rgb.min())
            frames += 1
    require(frames == count, "SIMPLE private video frame count mismatch")
    require(stream_hash(files.path(relative)) == digest, "SIMPLE private video changed during audit")
    return {"path": relative, "sha256": digest, "frames": frames, "dimensions": dimensions,
            "presentation_timestamps_verified_hz": 50, "flat_frames": flat,
            "maximum_png_pixel_mae_255": None, "mean_png_pixel_mae_255": None,
            "comparison": "No retained source PNGs: decode/hash/timestamps only; pixel parity unavailable."}


def audit_simple_videos(files: ClosedFiles, base: Path, result: dict, rows: list) -> list:
    import av

    inventory = files.json((base / result["artifacts"]["video_manifest"]).as_posix())
    indexed = {}
    for row in inventory:
        relative = bound_reference(files, row["path"])
        path = Path(relative)
        camera = path.stem
        require(path.parent == base and path.suffix == ".mp4" and camera not in indexed,
                "SIMPLE video identity/path mismatch")
        require(type(row["frames"]) is int and row["frames"] == len(rows)
                and type(row["fps"]) in (int, float) and row["fps"] == 50
                and type(row["size"]) is int and row["size"] == files.path(relative).stat().st_size
                and row["sha256"] == stream_hash(files.path(relative)), "SIMPLE video manifest mismatch")
        require(result["artifacts"].get(f"video_{camera}") == path.name, "SIMPLE result video reference mismatch")
        with av.open(str(files.path(relative))) as container:
            require(len(container.streams.video) == 1 and container.streams.video[0].average_rate == 50,
                    "SIMPLE video stream rate differs from 50 Hz")
        indexed[camera] = (relative, row["sha256"])
    require(set(indexed) in (SIMPLE_HEAD_CAMERAS, SIMPLE_ALL_CAMERAS), "unsupported SIMPLE private camera set")
    require({key for key in result["artifacts"] if key.startswith("video_") and key != "video_manifest"}
            == {f"video_{camera}" for camera in indexed}, "SIMPLE result video coverage mismatch")
    videos = []
    for camera, (relative, digest) in sorted(indexed.items()):
        checked = (audit_video(files, relative, rows, base, expected_hz=50) if camera == "head_stereo_left"
                   else audit_private_simple_video(files, relative, len(rows)))
        require(checked["sha256"] == digest, "SIMPLE video changed after manifest check")
        videos.append({"camera": camera, **checked})
    return videos


def audit_payload(files: ClosedFiles, mailbox: ClosedFiles, manifest: dict, result: dict,
                  events: list, *, episode_artifact_base: Path | None = None) -> dict:
    require(result["status"] == "completed", "full artifact audit requires a completed episode; retain errors separately")
    benchmark = manifest["benchmark"]["name"]
    require(benchmark in {"libero", "simpler_env", "robocasa365", "simple_humanoid"}, "unsupported native frame layout")
    version = manifest["policy"]["version"]
    require(version in {"starvla-rsi.mailbox/v2", "starvla-rsi.mailbox/v3"}, "unsupported mailbox schema")
    parameters = manifest["policy"]["parameters"]
    require(Path(parameters["directory"]) == mailbox.root, "caller mailbox differs from recorded endpoint")
    ready = mailbox.json("ready.json")
    require(ready["status"] == "episode_closed", "mailbox is not closed")
    require(ready["schema_version"] == manifest["policy"]["version"], "ready schema mismatch")
    spec, action, protocol = (manifest[name] for name in ("observation_spec", "action_spec", "protocol"))
    require(spec["privileged"] is False, "privileged observation track")
    cameras = spec["cameras"]
    require(cameras and len(set(cameras)) == len(cameras), "invalid camera set")
    if benchmark == "robocasa365":
        require(cameras == ROBOCASA_CAMERAS and spec["state_names"] == [],
                "unsupported RoboCasa public camera/state track")
    if benchmark == "simple_humanoid":
        frame_base, rows, simple_native = simple_layout(files, manifest, result, episode_artifact_base)
    else:
        frame_index = bound_reference(files, result["artifacts"]["frames"])
        frame_base = Path(frame_index).parent
        rows = files.jsonl(frame_index)
    steps = result["environment_steps"]
    expected_keys = {(step, camera) for step in range(steps + 1) for camera in cameras}
    indexed = {}
    image_paths = set()
    for row in rows:
        key = (row["step"], row["camera"])
        require(type(row["step"]) is int and key not in indexed, "duplicate/invalid native frame identity")
        relative = (frame_base / row["path"]).as_posix()
        require(not Path(row["path"]).is_absolute() and relative not in image_paths,
                "duplicate/absolute native frame path")
        decoded = png(files, relative, row["sha256"])
        if benchmark == "robocasa365":
            require(decoded.size == (256, 256), "RoboCasa native PNG dimensions changed")
        if benchmark == "simple_humanoid":
            require(decoded.size == (640, 360), "SIMPLE native PNG dimensions changed")
        image_paths.add(relative)
        indexed[key] = row
    require(set(indexed) == expected_keys, "native frame coverage gap/extra")

    observations = {}
    current_step = 0
    scheduled = {}
    scheduled_feedback = {}
    executed_by_call = {}
    active_call = 0
    decisions = []
    for event in events:
        if event["event"] in {"observation", "environment_step"}:
            observation = event["observation"]
            if benchmark == "simple_humanoid":
                expected_step = len(observations)
                require(type(observation["step"]) is int and observation["step"] == expected_step
                        and event["event"] == ("observation" if expected_step == 0 else "environment_step"),
                        "SIMPLE observation step must match chronological native control identity")
            current_step = observation["step"]
            require(current_step not in observations, "duplicate native observation")
            observations[current_step] = observation
            if event["event"] == "environment_step":
                executed_by_call[active_call] = executed_by_call.get(active_call, 0) + 1
        elif event["event"] == "policy_call_start":
            scheduled[event["policy_call"]] = current_step
            scheduled_feedback[event["policy_call"]] = {
                "policy_calls": active_call,
                "action_decisions": len(executed_by_call),
                "environment_steps": sum(executed_by_call.values()),
                "executed_steps": executed_by_call.get(active_call, 0),
            }
            active_call = event["policy_call"]
        elif event["event"] == "policy_decision":
            decisions.append(event)
    require(set(observations) == set(range(steps + 1)), "native observation coverage gap")
    require(len(decisions) == result["policy_calls"], "missing returned decisions")
    require(all(set(row["camera_names"]) == set(cameras) and row["metadata"] == {}
                for row in observations.values()), "native exported observation boundary mismatch")
    simple_controls = (audit_simple_controls(files, frame_base, simple_native, spec, result, events, observations)
                       if benchmark == "simple_humanoid" else None)

    expected_budgets = {
        "budget_mode": protocol["budget_mode"], "primary_budget": protocol["primary_budget"],
        "max_steps": protocol["max_steps"], "max_policy_calls": protocol["max_policy_calls"],
        "replan_interval": protocol["replan_interval"], "max_chunk_length": parameters["max_chunk_length"],
        "response_timeout_s": parameters["timeout_s"], "max_provider_calls_per_decision": 1,
        "provider_call_limit_verified": False,
    }
    request_ids = set()
    public_image_count = 0
    for decision in decisions:
        metadata = decision["metadata"]
        request_id = metadata["request_id"]
        require(request_id not in request_ids, "duplicate request ID")
        request_ids.add(request_id)
        observation_path = bound_reference(mailbox, metadata["observation_path"])
        response_path = bound_reference(mailbox, metadata["response_path"])
        turn = Path(observation_path).parent
        require(turn == Path(response_path).parent and turn.name == request_id,
                "request/response directory mismatch")
        public = mailbox.json(observation_path)
        feedback = scheduled_feedback[decision["policy_call"]]
        audit_policy_fields(public, version, parameters, protocol, feedback)
        if benchmark == "simple_humanoid":
            require(finite_vector(public["state"], 31), "SIMPLE public state must be 31 finite nonboolean numbers")
            require(type(public["step"]) is int, "SIMPLE public step must be a nonboolean integer")
        require(public["schema_version"] == manifest["policy"]["version"] and public["request_id"] == request_id,
                "public request/schema mismatch")
        step = scheduled[decision["policy_call"]]
        native = observations[step]
        require(public["step"] == step and public["instruction"] == native["instruction"]
                and public["state"] == native["state"], "public observation differs from scheduled native input")
        require(public["state"] is None if not spec["state_names"] else
                isinstance(public["state"], list) and len(public["state"]) == len(spec["state_names"]),
                "undeclared public proprioception")
        require(public["observation_spec"] == spec and public["action_spec"] == action,
                "public specification drift")
        turn_budgets = dict(expected_budgets)
        if version.endswith("/v2") and protocol.get("min_action_decisions_before_give_up", 0):
            minimum = protocol["min_action_decisions_before_give_up"]
            turn_budgets.update({key: protocol[key] for key in (
                "stop_constraint_version", "min_action_decisions_before_give_up", "early_policy_stop_exception")})
            turn_budgets.update(completed_action_decisions=feedback["action_decisions"],
                                voluntary_stop_allowed=feedback["action_decisions"] >= minimum)
        require(public["budgets"] == turn_budgets and public["history"] == parameters["history"],
                "public budget/history drift")
        require(hashlib.sha256(public["prompt"].encode()).hexdigest() == parameters["prompt_sha256"],
                "public prompt drift")
        require(mailbox.json(response_path) == metadata["structured_response"], "accepted response differs from event")
        require(set(public["images"]) == set(cameras), "public camera set drift")
        for camera, image in public["images"].items():
            require(set(image) == IMAGE_FIELDS and image["encoding"] == "png"
                    and image["color_space"] == "RGB", "public image schema drift")
            require(Path(image["path"]).parent == turn, "public image outside current request")
            actual = png(mailbox, image["path"], image["sha256"])
            row = indexed[(step, camera)]
            expected = png(files, (frame_base / row["path"]).as_posix(), row["sha256"])
            require(actual.size == expected.size == (image["width"], image["height"])
                    and actual.tobytes() == expected.tobytes(), "public/native pixel mismatch")
            if "instruction" in row:
                require(row["instruction"] == public["instruction"], "frame instruction mismatch")
            public_image_count += 1

    videos = []
    for camera in ([] if benchmark == "simple_humanoid" else cameras):
        key = "video" if benchmark == "simpler_env" else f"{camera}_video"
        relative = bound_reference(files, result["artifacts"][key])
        camera_rows = [indexed[(step, camera)] for step in range(steps + 1)]
        videos.append({"camera": camera, **audit_video(
            files, relative, camera_rows, frame_base,
            expected_hz=20 if benchmark == "robocasa365" else None)})
    native_controls = ({"native_control_pairs_verified": audit_robocasa_controls(files, result, events)}
                       if benchmark == "robocasa365" else {})
    if benchmark == "simple_humanoid":
        videos = audit_simple_videos(files, frame_base, result, rows)
        native_controls = {"native_ticks_verified": simple_controls,
                           "native_instruction_binding": "Exact retained provenance/observation/public text and retained configuration when present; EpisodeSpec alone strips outer whitespace.",
                           "retained_configuration_instruction_verified": "selected_task_configuration" in simple_native,
                           "native_png_hash_origin": "Computed from retained files; SIMPLE does not retain a native frame-hash index."}
    return {"episode_id": result["episode"]["id"], "native_success": result["success"],
            **native_controls,
            "controls": steps, "decisions": result["policy_calls"],
            "native_pngs_verified": len(rows), "public_images_matched": public_image_count,
            "public_observations_verified": len(decisions), "videos": videos}


def audit_artifacts(run: Path, mailbox_dir: Path) -> dict:
    own_path = Path(__file__).resolve()
    own_hash = stream_hash(own_path)
    record_report = audit_run(run)
    require(len(record_report["episodes"]) == 1, "supply a single-case closed run")
    files, mailbox = ClosedFiles(run), ClosedFiles(mailbox_dir)
    manifest = files.json("manifest.json")
    results = files.jsonl("episodes.jsonl")
    result_path = next((files.root / "episodes").glob("*/result.json"))
    result = files.json(result_path.relative_to(files.root).as_posix())
    require(results == [result], "episode changed after record audit")
    event_path = result_path.with_name("events.jsonl").relative_to(files.root).as_posix()
    row = audit_payload(files, mailbox, manifest, result, files.jsonl(event_path),
                        episode_artifact_base=result_path.parent.relative_to(files.root) / "artifacts")
    # Recheck the entire previously audited record inventory, not only image inputs.
    for relative, digest in record_report["read_file_sha256"].items():
        require(stream_hash(files.path(relative)) == digest, "record changed during image audit")
    for video in row["videos"]:
        require(stream_hash(files.path(video["path"])) == video["sha256"], "video changed before audit completed")
    files.verify_unchanged()
    mailbox.verify_unchanged()
    require(stream_hash(own_path) == own_hash, "artifact auditor changed during audit")
    return {"schema_version": "starvla-rsi.closed-mailbox-artifacts/v1",
            "artifact_consistency": "passed", "run_dir": str(files.root),
            "authorized_mailbox": str(mailbox.root), "artifact_auditor_sha256": own_hash,
            "record_audit": record_report, "episode": row,
            "run_files_sha256": files.hashes, "mailbox_files_sha256": mailbox.hashes,
            "limitations": ["No simulator, scorer, external assets or native policy is executed.",
                            "Only complete single-episode LIBERO/SimplerEnv/RoboCasa365 and SIMPLE RGB+qpos31 mailbox-v2/v3 records are supported; failed records use the separate generic record audit.",
                            "SIMPLE checks retained ticks/language/encoders and 50 Hz videos, not native source/reset/campaign/asset closure or runtime warning impact. Private cameras lack PNG pixel parity; reset has no private tick.",
                            "RoboCasa checks retained native call pairs and 20 Hz video timestamps, not actuator traces or native source/reset/asset provenance.",
                            "Accepted responses are compared with events; original action.json files, the frozen response parser and native action-contract validity are not checked here.",
                            "Errors remain attempts; unsupported/error audits do not authorize retries or exclusion.",
                            "No OS sandbox, actor-access attestation or trusted provider/model/usage accounting.",
                            "Pixel differences for lossy videos require interpretation, not automatic native parity."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--mailbox-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.absolute()
    for root in (args.run_dir.resolve(strict=True), args.mailbox_dir.resolve(strict=True)):
        require(not output.resolve().is_relative_to(root), "audit output must be outside both closed inputs")
    require(not output.exists() and not output.is_symlink(), "audit output already exists")
    report = audit_artifacts(args.run_dir, args.mailbox_dir)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(output)


if __name__ == "__main__":
    main()
