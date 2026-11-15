"""Strict JSON helpers shared by the active model methods."""
import json
import os
from pathlib import Path


def compact_json(value):
    # No spaces; NaN or Infinity raises ValueError. Packets for the model are encoded with this.
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def write_json(path, value):
    """Create an owner-only file with the compact JSON; return the bytes written."""
    payload = compact_json(value).encode()
    with Path(path).open("xb") as stream:  # "x": fails if the file exists, so nothing is overwritten
        os.chmod(path, 0o600)  # owner-only before any byte is written
        stream.write(payload)
    return payload


def strict_object(pairs):
    """object_pairs_hook for json.loads: reject a repeated key instead of keeping the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


def reject_constant(value):
    """parse_constant hook for json.loads: reject NaN, Infinity and -Infinity."""
    raise ValueError("non-finite JSON")
