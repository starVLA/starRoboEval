"""Strict, dependency-light access to declarative RoboDojo evaluation plans."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA = "starvla-rsi.robodojo-task-catalog/v1"
CATALOG_PATH = Path(__file__).with_name("task_catalog.json")
TASK_FIELDS = frozenset({"enabled", "native_instruction", "public_instruction",
    "native_horizon", "native_eval_seed", "simulator_initial_seed",
    "upstream_configured_episodes", "layout_binding", "panels"})


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate RoboDojo task-catalog key: {key}")
        result[key] = value
    return result


def load_catalog() -> dict[str, Any]:
    value = json.loads(CATALOG_PATH.read_text(), object_pairs_hook=_unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(
                           ValueError(f"nonfinite task-catalog value: {value}")))
    if (not isinstance(value, dict) or set(value) != {"schema_version", "interface_protocol", "tasks"}
            or value["schema_version"] != SCHEMA
            or not isinstance(value["interface_protocol"], str)
            or not isinstance(value["tasks"], dict) or not value["tasks"]):
        raise ValueError("invalid RoboDojo task catalog")
    for task_id, task in value["tasks"].items():
        if (not isinstance(task_id, str) or not task_id or not isinstance(task, dict)
                or set(task) != TASK_FIELDS):
            raise ValueError("invalid RoboDojo task declaration")
        panels = task["panels"]
        if not isinstance(panels, Mapping) or set(panels) != {"fast", "full"}:
            raise ValueError("RoboDojo tasks require exactly fast and full panels")
        if task["enabled"] is not True:
            raise ValueError("public RoboDojo catalog may contain only enabled tasks")
        binding = task["layout_binding"]
        if (not isinstance(binding, Mapping)
                or set(binding) != {"inventory_count", "id", "snapshot_sha256"}
                or type(binding["inventory_count"]) is not int or binding["inventory_count"] <= 0
                or not isinstance(binding["id"], str) or not binding["id"]
                or not isinstance(binding["snapshot_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", binding["snapshot_sha256"]) is None
                ):
            raise ValueError("invalid RoboDojo layout binding")
        for panel_name, panel in panels.items():
            layouts = panel.get("layout_ids") if isinstance(panel, Mapping) else None
            if (not isinstance(panel, Mapping)
                    or set(panel) != {"id", "layout_ids", "attempts_per_layout"}
                    or not isinstance(panel["id"], str) or not panel["id"]
                    or not isinstance(layouts, list) or not layouts
                    or any(type(item) is not int or item < 0 or item >= binding["inventory_count"]
                           for item in layouts)
                    or layouts != sorted(set(layouts)) or panel["attempts_per_layout"] != 1):
                raise ValueError(f"invalid RoboDojo {panel_name} panel")
        if (not set(panels["fast"]["layout_ids"]).issubset(panels["full"]["layout_ids"])
                or len(panels["full"]["layout_ids"]) != task["upstream_configured_episodes"]):
            raise ValueError("RoboDojo full panel must match the native configured episode count")
        for name in ("native_horizon", "upstream_configured_episodes"):
            if type(task[name]) is not int or task[name] <= 0:
                raise ValueError(f"invalid RoboDojo task integer: {name}")
        for name in ("native_eval_seed", "simulator_initial_seed"):
            if type(task[name]) is not int or task[name] < 0:
                raise ValueError(f"invalid RoboDojo task seed: {name}")
        for name in ("native_instruction", "public_instruction"):
            if not isinstance(task[name], str) or not task[name]:
                raise ValueError(f"invalid RoboDojo task string: {name}")
    return value


def task_spec(task_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    if not isinstance(task_id, str) or task_id not in catalog["tasks"]:
        raise ValueError(f"unsupported RoboDojo task: {task_id!r}")
    return dict(catalog["tasks"][task_id])
