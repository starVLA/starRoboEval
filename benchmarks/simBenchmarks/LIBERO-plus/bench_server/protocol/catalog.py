"""Dependency-light frozen identities and pinned native file resolution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from benchkit.errors import CompatibilityError

REVISION = "4976dc30028e805ff8094b55501d532c48fec182"
COUNTS = {"libero_spatial": 2402, "libero_object": 2518, "libero_goal": 2591, "libero_10": 2519}
HORIZONS = {"libero_spatial": 220, "libero_object": 280, "libero_goal": 300, "libero_10": 520}
CATEGORIES = ("Background Textures", "Camera Viewpoints", "Language Instructions", "Light Conditions",
              "Objects Layout", "Robot Initial States", "Sensor Noise")
FAST_SELECTION_SEED = 20261026  # ranking salt of the fast variant selection
FAST_SAMPLES = 5  # variants per (base task, category) group
COLUMNS = ("native_id", "native_name", "instruction", "native_instruction", "category", "difficulty_level",
           "bddl_sha256", "initial_file", "initial_file_sha256")


def native_files(suite: str, name: str) -> dict[str, str]:
    """Mirror the pinned wrapper and get_task_init_states routing, not a fallback.

    The virtual BDDL name must still be passed to OffScreenRenderEnv: it encodes
    camera, Panda initial-pose and sensor perturbations interpreted natively.
    Only its backing file is used for integrity checks here.
    """
    if suite not in COUNTS or not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.-]+", name) is None:
        raise ValueError("unsupported suite or unsafe native task name")
    bddl = name.split("_view_")[0] if "_view_" in name and "_initstate_" in name else name
    filename = name + ".pruned_init"
    if "_language_" in filename:
        initial = filename.split("_language_")[0] + ".pruned_init"
    elif "_view_" in filename:
        initial = filename.split("_view_")[0] + ".pruned_init"
    else:
        initial = None
        if "_table_" in filename:
            initial = re.sub(r"_table_\d+", "", filename)
        if "_tb_" in filename:
            initial = re.sub(r"_tb_\d+", "", filename)
        if "_light_" in filename:
            initial = filename.split("_light_")[0] + ".pruned_init"
        if "_add_" in filename or "_level" in filename:
            initial = "libero_newobj/" + suite + "/" + filename
            return {"virtual_bddl": f"{suite}/{name}.bddl", "bddl": f"{suite}/{bddl}.bddl",
                    "initial_file": initial}
        if initial is None:
            raise CompatibilityError("pinned native loader has no initial-state branch for this task")
    return {"virtual_bddl": f"{suite}/{name}.bddl", "bddl": f"{suite}/{bddl}.bddl",
            "initial_file": f"{suite}/{initial}"}


def task_catalog(suite: str) -> dict:
    if suite not in COUNTS:
        raise ValueError("suite must be one of the four LIBERO-Plus suites; libero_90 is excluded")
    payload = json.loads(Path(__file__).with_name("catalogs").joinpath(suite + ".json").read_text())
    if (payload.get("schema_version") != "starvla-rsi.libero_plus.catalog/v1"
            or payload.get("upstream_revision") != REVISION or payload.get("suite") != suite
            or payload.get("task_order_index") != 0 or payload.get("columns") != list(COLUMNS)
            or payload.get("task_count") != COUNTS[suite] or len(payload.get("tasks", [])) != COUNTS[suite]):
        raise CompatibilityError("LIBERO-Plus frozen catalog identity/count differs")
    rows = []
    names = set()
    for index, row in enumerate(payload["tasks"]):
        if len(row) != len(COLUMNS):
            raise CompatibilityError("LIBERO-Plus catalog row shape differs")
        item = dict(zip(COLUMNS, row))
        if (type(item["native_id"]) is not int or item["native_id"] != index
                or item["native_name"] in names or not isinstance(item["instruction"], str)
                or not item["instruction"].strip()
                or not isinstance(item["native_instruction"], str) or not item["native_instruction"].strip()
                or any(re.fullmatch(r"[0-9a-f]{64}", item[field]) is None
                       for field in ("bddl_sha256", "initial_file_sha256"))
                or native_files(suite, item["native_name"])["initial_file"] != item["initial_file"]):
            raise CompatibilityError("LIBERO-Plus frozen task identity or file mapping differs")
        names.add(item["native_name"])
        rows.append(item)
    return {**payload, "tasks": rows}


def fast_selection(suite: str, rows: list[dict]) -> list[tuple[int, dict]]:
    """Return (sample slot, row) pairs of the fast variant selection, in run order.

    Within each (base task, category) group, variants are ranked by ascending
    SHA256("20261026/suite/base_task/category/native_id"), native ID breaking
    ties, and the first five are kept. Order: slot, category, then the ten base
    tasks in order of first appearance among Background Textures variants.
    """
    bases = []
    for row in rows:
        if row["category"] == "Background Textures":
            match = re.fullmatch(r"(.+)_(?:table|tb)_\d+", row["native_name"])
            if match is None:
                raise CompatibilityError("LIBERO-Plus background variant name has no table suffix")
            if match.group(1) not in bases:
                bases.append(match.group(1))
    if len(bases) != 10:
        raise CompatibilityError("LIBERO-Plus suite must contain exactly ten base tasks")
    groups = {(base, category): [] for base in bases for category in CATEGORIES}
    for row in rows:
        matches = [base for base in bases if row["native_name"].startswith(base + "_")]
        if len(matches) != 1 or row["category"] not in CATEGORIES:
            raise CompatibilityError("LIBERO-Plus variant needs exactly one base task and a known category")
        groups[matches[0], row["category"]].append(row)
    selected = {}
    for (base, category), members in groups.items():
        prefix = f"{FAST_SELECTION_SEED}/{suite}/{base}/{category}/"
        selected[base, category] = sorted(members, key=lambda row: (
            hashlib.sha256(f"{prefix}{row['native_id']}".encode("utf-8")).digest(), row["native_id"]))[:FAST_SAMPLES]
    return [(slot, selected[base, category][slot]) for slot in range(FAST_SAMPLES)
            for category in CATEGORIES for base in bases if slot < len(selected[base, category])]


def file_sha256(path: Path, *, max_bytes: int = 64 * 1024 * 1024) -> str:
    """Bounded read for selected native source, BDDL and released reset files."""
    size = path.stat().st_size
    if not path.is_file() or not 0 <= size <= max_bytes:
        raise CompatibilityError("native evidence file is not a bounded regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise CompatibilityError("native evidence file grew beyond its bound")
            digest.update(chunk)
    if total != size or path.stat().st_size != size:
        raise CompatibilityError("native evidence file changed size during read")
    return digest.hexdigest()
