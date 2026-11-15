"""Hash-pinned D validation resets for independent single-task CALVIN cases."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from benchkit.errors import CompatibilityError

PANEL_SHA256 = "9fd6df51f86fadf0fcdcca927bd9af6b5b0905bbb448c7001e937ab93bc105a4"
TRIALS_PER_TASK = 4  # Pinned reset vectors per task in single_task_panel.json.
TASKS = (
    "close_drawer",
    "lift_blue_block_drawer", "lift_blue_block_slider", "lift_blue_block_table",
    "lift_pink_block_drawer", "lift_pink_block_slider", "lift_pink_block_table",
    "lift_red_block_drawer", "lift_red_block_slider", "lift_red_block_table",
    "move_slider_left", "move_slider_right", "open_drawer",
    "place_in_drawer", "place_in_slider",
    "push_blue_block_left", "push_blue_block_right", "push_into_drawer",
    "push_pink_block_left", "push_pink_block_right",
    "push_red_block_left", "push_red_block_right",
    "rotate_blue_block_left", "rotate_blue_block_right",
    "rotate_pink_block_left", "rotate_pink_block_right",
    "rotate_red_block_left", "rotate_red_block_right",
    "stack_block", "turn_off_led", "turn_off_lightbulb",
    "turn_on_led", "turn_on_lightbulb", "unstack_block",
)


def panel_record():
    """Fresh validated copy; no native imports, state search or overrides."""
    raw = Path(__file__).with_name("single_task_panel.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != PANEL_SHA256:
        raise CompatibilityError("CALVIN single-task panel bytes differ")
    record = json.loads(raw)
    rows = record.get("cases")
    expected = [(task, trial) for task in TASKS for trial in range(TRIALS_PER_TASK)]
    if record.get("schema") != "starvla-rsi.calvin.single-task-panel/v1" or not isinstance(rows, list):
        raise CompatibilityError("CALVIN single-task panel schema differs")
    if [(row.get("task"), row.get("trial")) for row in rows] != expected:
        raise CompatibilityError("CALVIN single-task panel order/identity differs")
    for row in rows:
        if not isinstance(row.get("instruction"), str) or not row["instruction"].strip():
            raise CompatibilityError("CALVIN native task instruction is missing")
        for field in ("reset_frame", "annotation_end_frame", "annotation_index"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise CompatibilityError("CALVIN validation reset provenance is invalid")
        for field, size in (("robot_obs", 15), ("scene_obs", 24)):
            values = row.get(field)
            if (not isinstance(values, list) or len(values) != size
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
                raise CompatibilityError("CALVIN validation reset vector is invalid")
    for task in TASKS:
        selected = [row for row in rows if row["task"] == task]
        if any(later["reset_frame"] <= earlier["annotation_end_frame"]
               for earlier, later in zip(selected, selected[1:])):
            raise CompatibilityError("CALVIN trials of one task must use ordered non-overlapping segments")
    return record
