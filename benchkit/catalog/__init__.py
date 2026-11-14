"""Packaged benchmark catalog: declarations, loading and repository validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CatalogEntry:
    """One benchmark's stable identity and adapter migration status.

    `id` equals the adapter descriptor name recorded in run manifests.
    """

    id: str
    display_name: str
    directory: str
    protocol: str
    migration_status: str
    priority: str
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CatalogEntry":
        required = {
            "id",
            "display_name",
            "directory",
            "protocol",
            "migration_status",
            "priority",
            "tags",
        }
        missing = sorted(required - value.keys())
        extra = sorted(value.keys() - required)
        if missing or extra:
            raise ValueError(f"invalid catalog entry keys; missing={missing}, extra={extra}")
        if not isinstance(value["tags"], list) or not all(isinstance(tag, str) for tag in value["tags"]):
            raise TypeError("catalog tags must be a list of strings")
        strings = {key: value[key] for key in required - {"tags"}}
        if not all(isinstance(item, str) and item.strip() for item in strings.values()):
            raise TypeError("catalog fields must be non-empty strings")
        return cls(tags=tuple(value["tags"]), **strings)


def load_catalog() -> tuple[CatalogEntry, ...]:
    """Load the packaged benchmark catalog."""
    catalog_path = resources.files("benchkit.catalog").joinpath("benchmarks.json")
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "starvla-rsi.catalog/v1":
        raise ValueError("unsupported benchmark catalog schema")
    entries = tuple(CatalogEntry.from_dict(value) for value in payload.get("benchmarks", []))
    ids = [entry.id for entry in entries]
    directories = [entry.directory for entry in entries]
    if not entries:
        raise ValueError("benchmark catalog must not be empty")
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark catalog ids must be unique")
    if len(directories) != len(set(directories)):
        raise ValueError("benchmark catalog directories must be unique")
    return entries


def validate_repository_catalog(repository: Path) -> list[str]:
    """Return catalog/file-layout errors without importing simulator stacks."""
    errors: list[str] = []
    for entry in load_catalog():
        benchmark_dir = repository / entry.directory
        if not benchmark_dir.is_dir():
            errors.append(f"{entry.id}: missing directory {entry.directory}")
        protocol_path = repository / entry.protocol
        if not protocol_path.is_file():
            errors.append(f"{entry.id}: missing protocol {entry.protocol}")
        train_dir = benchmark_dir / "train_files"
        if train_dir.exists():
            errors.append(f"{entry.id}: training directory must be removed: {train_dir}")
        eval_dir = benchmark_dir / "eval_files"
        if eval_dir.exists():
            errors.append(f"{entry.id}: historical model evaluators must be removed from the public benchmark tree: {eval_dir}")
        legacy_dir = benchmark_dir / "legacy"
        if legacy_dir.exists():
            errors.append(f"{entry.id}: legacy material belongs in Git history or local barks/: {legacy_dir}")
    return errors
