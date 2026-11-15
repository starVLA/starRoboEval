"""Startup gate for `max`: a complete, hash-bound reset-stability record, or refuse.

The service never screens, searches or edits this record; it only replays the
first stable layouts that an offline reset-only screen recorded. Rejected
layouts are preparation provenance, never policy results.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "starvla-rsi.robodojo.reset-stability/v1"
RESULTS = frozenset({"stable", "unstable", "exception"})  # native reset outcomes upstream skips past
FIELDS = frozenset({"schema", "task", "native_revision", "layout_inventory_sha256",
    "native_eval_seed", "required_stable", "screened", "preparation"})
PREPARATION_FIELDS = frozenset({"runtime_manifest_sha256", "created_at", "procedure"})  # recorded, not compared
PREPARATION = ("screen layouts 0, 1, 2, ... in order with one reset-only native worker process each "
               "and stop at the required stable count; see environment/README.md")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate RoboDojo reset-stability key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"nonfinite RoboDojo reset-stability value: {value}")


def load_stable_layouts(path: Path, expected_hash: str | None, *, task: str, native_revision: str,
                        layout_inventory_sha256: str, native_eval_seed: int,
                        required_stable: int, inventory_count: int) -> tuple[tuple[int, ...], dict[str, Any]]:
    """Return the first `required_stable` stable layout IDs and the manifest provenance.

    A supplied hash must match; without one the observed digest is recorded
    unpinned rather than refused.
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"RoboDojo max mode needs the reset-stability manifest file; {PREPARATION}")
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if expected_hash is not None and digest != expected_hash:  # compared only when pinned
        raise ValueError("RoboDojo reset-stability manifest SHA256 differs from stability_manifest_sha256")
    try:
        record = json.loads(payload, object_pairs_hook=_unique, parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"RoboDojo reset-stability manifest is not JSON: {exc}") from exc
    if not isinstance(record, dict) or set(record) != FIELDS or record["schema"] != SCHEMA:
        raise ValueError(f"RoboDojo reset-stability manifest needs exactly the {SCHEMA} fields")
    expected = {"task": task, "native_revision": native_revision,
                "layout_inventory_sha256": layout_inventory_sha256,
                "native_eval_seed": native_eval_seed, "required_stable": required_stable}
    differs = sorted(key for key, value in expected.items()
                     if type(record[key]) is not type(value) or record[key] != value)
    if differs:
        raise ValueError(f"RoboDojo reset-stability manifest was not screened for this max mode "
                         f"({', '.join(differs)} differ); {PREPARATION}")
    screened = record["screened"]
    if (not isinstance(screened, list) or len(screened) > inventory_count
            or any(not isinstance(row, Mapping) or set(row) != {"layout_id", "result"} for row in screened)
            or [row["layout_id"] for row in screened] != list(range(len(screened)))
            or any(type(row["layout_id"]) is not int or not isinstance(row["result"], str)
                   or row["result"] not in RESULTS for row in screened)):
        raise ValueError("RoboDojo reset-stability rows must be {layout_id, result} for layouts 0, 1, 2, ... "
                         f"in order, within the {inventory_count}-layout inventory, result one of {sorted(RESULTS)}")
    stable = tuple(row["layout_id"] for row in screened if row["result"] == "stable")
    # The screen stops at the required stable count; the last row must be that acceptance.
    if len(stable) != required_stable or screened[-1]["result"] != "stable":
        raise ValueError(f"RoboDojo max mode needs a complete screen ending at its {required_stable}th stable "
                         f"layout; got {len(stable)} stable of {len(screened)} screened; {PREPARATION}")
    preparation = record["preparation"]
    if (not isinstance(preparation, Mapping) or not PREPARATION_FIELDS.issubset(preparation)
            or any(not isinstance(preparation[key], str) or not preparation[key] for key in PREPARATION_FIELDS)):
        raise ValueError(f"RoboDojo reset-stability preparation needs {sorted(PREPARATION_FIELDS)}")
    rejected = {}
    for row in screened:
        if row["result"] != "stable":
            rejected[row["result"]] = rejected.get(row["result"], 0) + 1
    # Preparation provenance only; rejected layouts are never policy results.
    return stable, {"stability_manifest": {"sha256": digest, "pinned": expected_hash is not None},
                    "reset_stability_screening": {"screened_layouts": len(screened), "stable_layouts": len(stable),
                        "rejected_layouts": dict(sorted(rejected.items())),
                        "last_screened_layout_id": screened[-1]["layout_id"],
                        "screening_runtime_manifest_sha256": preparation["runtime_manifest_sha256"],
                        "created_at": preparation["created_at"]}}
