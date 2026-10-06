"""Read-only integrity checks plus a new verification artifact; no simulator."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    import av
    import numpy as np
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()
    root = args.artifact_dir.resolve()
    report = json.loads((root / "diagnostic_result.json").read_text())
    native = json.loads((root / "native_provenance.json").read_text())
    assert report["passed"] is True and report["diagnostic_only"] is True
    assert report["policy_calls"] == 0 and report["metrics"]["native_steps"] == 1
    assert native["extra_score_calls"] == 0
    assert native["warmup_native_steps"] == 60 if native["fixed_controller"] == "AMO" else 0 <= native["warmup_native_steps"] <= 300
    result = {"passed": True, "diagnostic_only": True, "policy_calls": 0, "native_steps": 1,
        "warmup_native_steps": native["warmup_native_steps"], "videos": []}
    for item in json.loads((root / "video_manifest.json").read_text()):
        path = root / Path(item["path"]).name
        assert digest(path) == item["sha256"]
        with av.open(str(path)) as container:
            frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
        assert len(frames) == item["frames"] == 2
        assert all(frame.shape == (360, 640, 3) and frame.dtype == np.uint8 for frame in frames)
        assert all(float(frame.std()) > 1 for frame in frames), "blank RGB render"
        result["videos"].append({"file": path.name, "sha256": item["sha256"], "decoded_frames": len(frames)})
    assert result["videos"]
    for record in native["controller_weight_files"]:
        assert digest(Path(record["path"])) == record["sha256"]
    if native["fixed_controller"] != "AMO":
        assert len(native["sonic_upper_joint_names"]) == 31
        assert native["sonic_robot_stabilized"] is True
    output = root / "diagnostic_verification.json"
    if output.exists():
        raise FileExistsError("verification already exists; do not overwrite evidence")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
