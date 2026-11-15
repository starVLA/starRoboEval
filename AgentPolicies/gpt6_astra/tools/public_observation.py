"""Generic public sensor encoding; no benchmark files, metadata or robot assumptions."""
from __future__ import annotations

import hashlib
import io
import math
from numbers import Real

def image_edge(value):
    """Check image_max_edge: the longest attached side in pixels; 0 keeps originals."""
    if type(value) is not int or not 0 <= value <= 4096:
        raise ValueError("image_max_edge must be an integer in [0,4096]")
    return value


def image_attachment(original_png, max_edge):
    """Return attachment bytes and dimensions; never change the source bytes.

    Zero disables resizing. Smaller originals pass through byte-for-byte. Pillow
    LANCZOS thumbnailing matches the reference's aspect-preserving preview rule.
    The caller records original and preview paths/digests independently.
    """
    from PIL import Image

    edge = image_edge(max_edge)
    if not isinstance(original_png, bytes):
        raise TypeError("original PNG must be bytes")
    with Image.open(io.BytesIO(original_png)) as original:
        if original.format != "PNG" or original.mode != "RGB":
            raise ValueError("expected an original RGB PNG")
        size = list(original.size)
        if not edge or max(size) <= edge:
            return original_png, {"size": size, "original_size": size,
                                  "resized": False, "resampling": None}
        preview = original.copy()
        preview.thumbnail((edge, edge), Image.Resampling.LANCZOS)  # shrinks in place, keeping the aspect ratio
        encoded = io.BytesIO()
        preview.save(encoded, format="PNG")
        return encoded.getvalue(), {"size": list(preview.size), "original_size": size,
                                   "resized": True, "resampling": "LANCZOS"}


# PersistentRuntime.compatibility_errors: run.py and the runner check it before the run,
# and start_episode checks it again for each episode.
def compatibility_errors(observation_spec, action_spec):
    errors = []
    if observation_spec.privileged:
        errors.append("persistent method rejects privileged observations")
    for names in (observation_spec.cameras, observation_spec.state_names):
        if (len(set(names)) != len(names)
                or any(not isinstance(name, str) or not name.strip() for name in names)):
            errors.append("public sensor names must be unique nonempty strings")
    if type(action_spec.size) is not int or not 1 <= action_spec.size <= 256:
        errors.append("persistent method supports 1..256 declared numeric components")
    return errors


def public_state(observation, spec):
    """Keep missing sensors missing; state names never imply all values measured."""
    # Called for every observation; the result becomes the packet's "state".
    if spec.state_names:
        if (observation.state is None or len(observation.state) != len(spec.state_names)
                or any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
                       for value in observation.state)):
            raise ValueError("declared robot state must be finite and match its names")
        return [float(value) for value in observation.state]
    if observation.state is not None:
        raise ValueError("undeclared robot state")
    return None


def public_images(observation, cameras, directory, *, config, remember):
    """Write only declared RGB using index filenames; arbitrary labels are data."""
    import numpy as np
    from PIL import Image
    attachments, descriptors, pixels = [], [], 0
    for index, name in enumerate(cameras):
        rgb = observation.images[name]
        if (not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3
                or not rgb.shape[0] or not rgb.shape[1]):
            raise ValueError("expected original RGB pixels")
        pixels += rgb.shape[0] * rgb.shape[1]  # summed over all cameras of this observation
        if pixels > config["max_image_pixels"]:
            raise ValueError("image size outside declared bounds")
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format="PNG")
        payload = buffer.getvalue()
        path = directory / f"camera-{index:03d}.png"  # full-resolution original; the model may read this folder
        with path.open("xb") as stream:
            stream.write(payload)
        remember(path, payload)  # records size and hash for the exported public manifest
        attachment, dimensions = image_attachment(payload, config["image_max_edge"])  # the image the model gets
        descriptor = {"camera": name, "path": str(path), "sha256": hashlib.sha256(payload).hexdigest(),
                      "size": dimensions["original_size"]}
        if dimensions["resized"]:  # also save the downscaled copy; the descriptor points to both files
            preview = directory / f"camera-{index:03d}-preview.png"
            with preview.open("xb") as stream:
                stream.write(attachment)
            remember(preview, attachment)
            descriptor["codex_preview"] = {"path": str(preview),
                "sha256": hashlib.sha256(attachment).hexdigest(), **dimensions}
        attachments.append(attachment)
        descriptors.append(descriptor)
    return attachments, descriptors  # both in camera order
