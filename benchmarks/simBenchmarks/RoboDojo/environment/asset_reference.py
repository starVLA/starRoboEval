"""Evaluator-private, explicit user-reference asset acceptance; never a blanket bypass."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA = "starvla-rsi.robodojo-asset-reference/v1"
KNOWN_UNRESOLVED = (
    "/home/kaslensu/Desktop/textures/Image_0.png",
    "https://omniverse-content-production.s3.us-west-2.amazonaws.com/Materials/2023_1/Base/Metals/Aluminum_Anodized.mdl",
    "https://omniverse-content-production.s3.us-west-2.amazonaws.com/Materials/2023_1/Base/Metals/Aluminum_Cast.mdl",
    "https://omniverse-content-production.s3.us-west-2.amazonaws.com/Materials/2023_1/Base/Plastics/Plastic_ABS.mdl",
)
_GRASP_DIRS = ["Geometry/t_cushion/00000", "Rigid/t/00000", "Rigid/t/00001"] + [
    f"Rigid/bowl/{index:05d}" for index in (1, 2, 3, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15)]
KNOWN_ANCILLARY = {f"Object/RoboDojo/{directory}/grasps/{name}.json"
    for directory in _GRASP_DIRS for name in ("UMI", "XOne", "aloha", "panda", "piper_v1", "proposal")}
KNOWN_ANCILLARY.add("Robots/x5/.ipynb_checkpoints/curobo-checkpoint.yml")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    before = path.stat()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("asset changed during hashing")
    return digest.hexdigest()


def load_reference(path: Path, expected_sha256: str) -> dict:
    path = Path(path).absolute()
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "")
            or path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024):
        raise ValueError("invalid asset-reference file/hash")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("asset-reference digest changed")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate asset-reference JSON key")
            obj[key] = value
        return obj
    document = json.loads(payload, object_pairs_hook=unique)
    return validate_reference_document(document)


def validate_reference_document(document: dict) -> dict:
    """Validate pinned inventory and provenance before any asset access."""
    if (not isinstance(document, dict) or document.get("schema_version") != SCHEMA
            or document.get("ready_for_user_reference_track") is not True
            or document.get("allowed_unresolved") != list(KNOWN_UNRESOLVED)):
        raise ValueError("unapproved asset reference/schema/unresolved set")
    reference_root = document.get("reference_root")
    if (not isinstance(reference_root, str) or not reference_root
            or "\\" in reference_root or "\x00" in reference_root
            or not PurePosixPath(reference_root).is_absolute()
            or ".." in PurePosixPath(reference_root).parts
            or PurePosixPath(reference_root).as_posix() != reference_root):
        raise ValueError("reference provenance root must be an absolute normalized path")
    rows = document.get("files")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError("invalid reference file inventory")
    names = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid reference file fields")
        name = row["path"]
        if (not isinstance(name, str) or not name or name == "." or "\\" in name
                or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name
                or type(row["bytes"]) is not int or row["bytes"] < 0
                or not isinstance(row["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise ValueError("unsafe reference path/size/hash")
        names.append(name)
    if names != sorted(set(names)):
        raise ValueError("reference inventory must be sorted and unique")
    required = {"Robots/x5/X5A.urdf", "Robots/x5/curobo.yml"}
    required.update(f"Eval_Layout/RoboDojo/arx_x5/0/{task}_0.json" for task in ("stack_bowls", "push_T"))
    if not required.issubset(names):
        raise ValueError("reference inventory lacks required robot/layout files")
    reference_rows = document.get("reference_files")
    absent = document.get("reference_absent")
    crlf_paths = document.get("crlf_equivalent_paths")
    if (not isinstance(reference_rows, list) or not reference_rows
            or not isinstance(absent, list) or len(absent) > 100
            or any(not isinstance(name, str) for name in absent)
            or absent != sorted(set(absent))
            or crlf_paths not in ([], ["Robots/x5/X5A.urdf"])):
        raise ValueError("invalid reference comparison partition")
    own = {row["path"]: row for row in rows}
    referenced = []
    for row in reference_rows:
        if (not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}
                or not isinstance(row["path"], str) or row["path"] not in own
                or type(row["bytes"]) is not int or row["bytes"] < 0
                or not isinstance(row["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise ValueError("invalid counterpart record")
        if row["path"] not in crlf_paths and row != own[row["path"]]:
            raise ValueError("non-URDF reference mismatch is not accepted")
        referenced.append(row["path"])
    if (referenced != sorted(set(referenced)) or set(referenced) & set(absent)
            or set(referenced) | set(absent) != set(names)
            or not required.issubset(referenced)
            or not set(crlf_paths).issubset(referenced)):
        raise ValueError("reference partition is incomplete or overlapping")
    # Missing counterparts are kept as named, byte-pinned own ancillary files;
    # they are not certified reference matches or allowed arbitrary missing geometry.
    for name in absent:
        if name not in KNOWN_ANCILLARY:
            raise ValueError("unapproved reference-absent asset category")
    return document


def verify_reference(path: Path, expected_sha256: str, runtime_assets: Path,
                     *, reference_assets: Path | None = None) -> dict:
    document = load_reference(path, expected_sha256)
    return _verify_reference_assets(document, runtime_assets, reference_assets=reference_assets)


def verify_reference_document(document: dict, runtime_assets: Path,
                              *, reference_assets: Path | None = None) -> dict:
    """Verify assets without rewriting the document's original provenance path."""
    return _verify_reference_assets(validate_reference_document(document), runtime_assets,
                                    reference_assets=reference_assets)


def _verify_reference_assets(document: dict, runtime_assets: Path,
                             *, reference_assets: Path | None = None) -> dict:
    """Check materialized assets for an already validated/constructed document.

    Normal consumers must use verify_reference for schema/digest validation.
    Preparation may check its in-memory document before publishing a ready file.
    """
    runtime_assets = Path(runtime_assets).resolve()
    # A relocated counterpart keeps the historical manifest bytes and digest.
    # Without an override, retain the manifest-directed comparison behavior.
    reference = Path(document["reference_root"] if reference_assets is None else reference_assets).absolute()
    if reference.is_symlink():
        raise ValueError("asset root is not a regular directory")
    reference = reference.resolve()
    names = []
    for item in runtime_assets.rglob("*"):
        if item.is_symlink():
            raise ValueError("runtime asset symlink is outside frozen reference")
        if item.is_file():
            names.append(item.relative_to(runtime_assets).as_posix())
        elif not item.is_dir():
            raise ValueError("nonregular runtime asset")
    if sorted(names) != [row["path"] for row in document["files"]]:
        raise ValueError("runtime asset set differs from reference inventory")
    for root, rows in ((runtime_assets, document["files"]), (reference, document["reference_files"])):
        if not root.is_dir() or root.is_symlink():
            raise ValueError("asset root is not a regular directory")
        for row in rows:
            item = root / row["path"]
            if (item.is_symlink() or not item.is_file() or item.resolve() != item
                    or item.stat().st_size != row["bytes"] or file_hash(item) != row["sha256"]):
                raise ValueError(f"asset differs from user reference: {root}/{row['path']}")
    for name in document["reference_absent"]:
        file = reference / name
        if file.exists() or file.is_symlink():
            raise ValueError("reference-absent counterpart now exists; refreeze comparison")
    for name in document["crlf_equivalent_paths"]:
        if (runtime_assets / name).read_bytes().replace(b"\r\n", b"\n") != (reference / name).read_bytes():
            raise ValueError("URDF difference is not solely the declared CRLF-to-LF conversion")
    return document


def accept_unresolved(unresolved, reference: dict | None) -> None:
    if unresolved and reference is None:
        raise ValueError("unresolved assets require an explicit user-reference track")
    if reference is not None and set(unresolved) - set(reference["allowed_unresolved"]):
        raise ValueError("new unresolved assets are not in the accepted user reference")


def verify_runtime_records(records: list[dict], reference: dict) -> None:
    if any(not row["path"].startswith("Assets/") for row in records):
        raise ValueError("asset record escaped Assets")
    actual = [{"path": row["path"].removeprefix("Assets/"),
               "bytes": row["bytes"], "sha256": row["sha256"]} for row in records]
    actual.sort(key=lambda row: row["path"])
    if actual != reference["files"]:
        raise ValueError("runtime assets changed after reference verification")
