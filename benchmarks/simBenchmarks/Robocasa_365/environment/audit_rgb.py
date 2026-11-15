"""Offline RGB integrity warnings, not scoring or a renderer diagnosis.

Defaults use mean absolute channel differences on the 0..255 scale: camera
collapse <= 1.0 (direct OR vertically flipped); alternating orientation requires
flipped difference <= 1.0 AND direct difference >= 10.0, for >= 3 consecutive
steps. Distinct stationary cameras do not trigger either condition. Warnings
are heuristic evidence, not proof of stale buffers, incorrect physics or cause.
No simulator, extra rendering, image repair or score modification is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

CAMERAS = ("robot0_agentview_left", "robot0_agentview_right", "robot0_eye_in_hand")
MAX_MANIFEST_BYTES = 16 * 1024 ** 2
MAX_PNG_BYTES = 1024 ** 2
MAX_TOTAL_PNG_BYTES = 4 * 1024 ** 3
MAX_FRAMES = 30000


def _read(root, relative, limit):
    if (not isinstance(relative, str) or len(relative) > 4096 or "\\" in relative
            or "\x00" in relative or any(p in ("", ".", "..") for p in relative.split("/"))):
        raise ValueError("unsafe artifact path")
    parts = relative.split("/")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError("artifact is not bounded regular data")
        payload = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (len(payload) != before.st_size or len(payload) > limit
                or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("artifact changed while reading")
    return payload


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json(payload):
    def nonfinite(value):
        raise ValueError("nonfinite JSON value")
    return json.loads(payload, object_pairs_hook=_object, parse_constant=nonfinite)


def _receipt_bytes(root):
    try:
        return _read(root, "sim_server_session.json", MAX_MANIFEST_BYTES)
    except FileNotFoundError:
        return None


def audit(artifact_dir, *, similarity_mae=1.0, orientation_difference_mae=10.0, min_run=3):
    """Read explicit closed artifacts; return warnings without changing inputs."""
    import numpy as np
    import PIL
    from PIL import Image

    source = Path(__file__).resolve()
    source_bytes = _read(source.parent, source.name, MAX_MANIFEST_BYTES)
    if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in (similarity_mae, orientation_difference_mae))
            or not 0 <= similarity_mae < orientation_difference_mae <= 255
            or type(min_run) is not int or min_run < 2):
        raise ValueError("invalid RGB warning thresholds")
    root = Path(artifact_dir).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact directory must be an existing non-symlink directory")
    closure = "caller-declared closed; no server receipt present"
    receipt_bytes = _receipt_bytes(root)
    expected_steps = None
    completeness = {"status": "unknown", "reason": "no server receipt", "expected_steps": None}
    if receipt_bytes is not None:
        receipt = _json(receipt_bytes)
        if not isinstance(receipt, dict) or receipt.get("state") != "closed":
            raise ValueError("SIM server session is not closed")
        closure = "server session receipt declares closed"
        fields = {"acknowledged_controls", "error_code", "cleanup_error"}
        if receipt.get("protocol") != "starvla-rsi.sim-server/v1" or not fields <= set(receipt):
            completeness["reason"] = "unsupported server receipt"
        elif receipt["error_code"] is not None or receipt["cleanup_error"] is not None:
            # Interrupted native calls may execute without a valid transition;
            # their counters cannot establish an exact frame denominator.
            completeness["reason"] = "faulted or cleanup-error server receipt"
        else:
            controls = receipt["acknowledged_controls"]
            if type(controls) is not int or controls < 0:
                raise ValueError("invalid clean server control count")
            expected_steps = controls + 1  # One reset frame plus every control.
            completeness = {"status": "matches_clean_server_receipt",
                            "reason": "reset plus acknowledged controls", "expected_steps": expected_steps}
    manifest = _read(root, "frames.jsonl", MAX_MANIFEST_BYTES)
    lines = manifest.splitlines()
    if not lines or len(lines) > MAX_FRAMES:
        raise ValueError("invalid frame inventory size")
    selected, paths = {}, set()
    for line in lines:
        row = _json(line)
        if (not isinstance(row, dict) or set(row) != {"camera", "step", "path", "sha256", "instruction"}
                or row["camera"] not in CAMERAS or type(row["step"]) is not int or row["step"] < 0
                or not isinstance(row["instruction"], str) or not isinstance(row["path"], str)
                or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise ValueError("invalid native RGB manifest row")
        key = (row["step"], row["camera"])
        if key in selected or row["path"] in paths:
            raise ValueError("duplicate frame identity/path")
        selected[key] = row
        paths.add(row["path"])
    steps = sorted({step for step, _ in selected})
    if steps != list(range(len(steps))) or len(selected) != len(steps) * len(CAMERAS):
        raise ValueError("frames must cover all three cameras at contiguous steps starting at zero")
    if expected_steps is not None and len(steps) != expected_steps:
        raise ValueError("frame coverage differs from clean closed server control count")
    previous, metrics, warnings = {}, [], []
    runs = {"multicamera_collapse": 0, **{camera: 0 for camera in CAMERAS}}
    total_bytes = 0
    for step in steps:
        images = {}
        for camera in CAMERAS:
            row = selected[(step, camera)]
            payload = _read(root, row["path"], MAX_PNG_BYTES)
            total_bytes += len(payload)
            if total_bytes > MAX_TOTAL_PNG_BYTES or hashlib.sha256(payload).hexdigest() != row["sha256"]:
                raise ValueError("PNG inventory byte bound or digest mismatch")
            with Image.open(io.BytesIO(payload)) as image:
                if (image.format != "PNG" or image.mode != "RGB" or image.size != (256, 256)
                        or getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1):
                    raise ValueError("expected native single-frame 256x256 RGB PNG")
                try:
                    image.verify()  # Check PNG chunks/CRCs before decoding.
                except (OSError, SyntaxError) as exc:
                    raise ValueError("invalid PNG integrity") from exc
            # verify() consumes the decoder; reopen the same hash-bound bytes.
            with Image.open(io.BytesIO(payload)) as image:
                images[camera] = np.asarray(image).astype(np.int16)
        def differences(a, b):
            return {"direct_mae": float(np.abs(a - b).mean()),
                    "vertical_flip_mae": float(np.abs(a[::-1] - b).mean())}
        cross = {a + ":" + b: differences(images[a], images[b])
                 for i, a in enumerate(CAMERAS) for b in CAMERAS[i + 1:]}
        temporal = {camera: differences(previous[camera], images[camera]) for camera in previous}
        conditions = {"multicamera_collapse": all(min(d.values()) <= similarity_mae for d in cross.values()),
                      **{camera: camera in temporal and temporal[camera]["vertical_flip_mae"] <= similarity_mae
                         and temporal[camera]["direct_mae"] >= orientation_difference_mae for camera in CAMERAS}}
        for key, condition in conditions.items():
            runs[key] = runs[key] + 1 if condition else 0
            if runs[key] == min_run:
                warnings.append({"kind": "multicamera_collapse" if key == "multicamera_collapse" else "alternating_vertical_orientation",
                                 "camera": None if key == "multicamera_collapse" else key,
                                 "first_step": step - min_run + 1, "detected_step": step})
        metrics.append({"step": step, "camera_pairs": cross, "consecutive_frames": temporal})
        previous = images
    if _read(root, "frames.jsonl", MAX_MANIFEST_BYTES) != manifest:
        raise ValueError("frame inventory changed during audit")
    if _receipt_bytes(root) != receipt_bytes:
        raise ValueError("server closure receipt changed during audit")
    if _read(source.parent, source.name, MAX_MANIFEST_BYTES) != source_bytes:
        raise ValueError("auditor source file changed during audit")
    return {"schema_version": "starvla-rsi.robocasa365.rgb-audit/v1", "scope": "offline heuristic RGB integrity only",
            "artifact_dir": str(root), "closure_evidence": closure, "status": "warnings" if warnings else "no_warnings",
            "server_receipt_sha256": None if receipt_bytes is None else hashlib.sha256(receipt_bytes).hexdigest(),
            "frame_completeness": completeness,
            "auditor": {"source_file": source.name, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                        "source_scope": "stable source-file bytes during audit; not runtime attestation",
                        "dependencies": {"numpy": np.__version__, "pillow": PIL.__version__,
                                         "python": sys.version.split()[0]}},
            "frames_manifest_sha256": hashlib.sha256(manifest).hexdigest(), "frame_count": len(selected),
            "steps": len(steps), "png_bytes": total_bytes, "cameras": list(CAMERAS),
            "thresholds": {"similarity_mae": similarity_mae, "orientation_difference_mae": orientation_difference_mae,
                           "min_consecutive_steps": min_run, "pixel_scale": "0..255"},
            "warnings": warnings, "metrics": metrics,
            "warning_step_semantics": "first_step is the first qualifying image step for camera collapse, or the destination step of the first qualifying consecutive-frame comparison for alternating orientation (its source frame is first_step - 1). detected_step completes the required run.",
            "limitations": "No source-of-corruption diagnosis, raw renderer capture, physics verification, transport audit or score change. No warnings does not prove rendering correctness."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new JSON outside the input artifact directory")
    parser.add_argument("--similarity-mae", type=float, default=1.0)
    parser.add_argument("--orientation-difference-mae", type=float, default=10.0)
    parser.add_argument("--min-run", type=int, default=3)
    args = parser.parse_args(argv)
    output = args.output.absolute()
    resolved = output.parent.resolve() / output.name
    if resolved == args.artifact_dir.resolve() or args.artifact_dir.resolve() in resolved.parents:
        parser.error("output must be outside the original artifact directory")
    if output.exists() or output.is_symlink():
        parser.error("output must not already exist")
    report = audit(args.artifact_dir, similarity_mae=args.similarity_mae,
                   orientation_difference_mae=args.orientation_difference_mae, min_run=args.min_run)
    from benchkit.artifacts import atomic_write_json
    atomic_write_json(output, report, overwrite=False)
    print(json.dumps({"status": report["status"], "warnings": len(report["warnings"]), "output": str(output)}))
    return 0  # Warnings are evidence, not a score or execution failure.


if __name__ == "__main__":
    raise SystemExit(main())
