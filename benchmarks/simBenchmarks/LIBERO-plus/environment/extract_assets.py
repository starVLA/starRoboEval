"""Verify the pinned public ZIP and extract into a new owned asset directory.

The official release retains a long upstream build-path prefix. Strip only that
exact prefix; never extract arbitrary archive paths or merge existing assets.
No simulator, model, reset, pickle or task action is loaded by this utility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

DATASET_REVISION = "dd2bd61b7d9a6fef1abc52d606e983b41886a149"
ARCHIVE_SHA256 = "96764a4bfbdaea98d4411598caeab235458318fe0f549611b93d1a323027b3cf"
ARCHIVE_SIZE = 6395849578
ARCHIVE_PREFIX = PurePosixPath("inspire/hdd/project/embodied-multimodality/public/syfei/libero_new/release/dataset/LIBERO-plus-0/assets")
ARCHIVE_URL = f"https://huggingface.co/datasets/Sylvest/LIBERO-plus/resolve/{DATASET_REVISION}/assets.zip"
MAX_ENTRIES = 500000
MAX_TOTAL_BYTES = 10 * 1024**3
MAX_FILE_BYTES = 512 * 1024**2


def inspect_entries(entries: list[zipfile.ZipInfo]) -> list[tuple[zipfile.ZipInfo, Path]]:
    if not 1 <= len(entries) <= MAX_ENTRIES or sum(row.file_size for row in entries) > MAX_TOTAL_BYTES:
        raise ValueError("archive expansion exceeds the reviewed file/byte bounds")
    names, files = set(), set()
    selected = []
    for entry in entries:
        name = entry.filename[:-1] if entry.filename.endswith("/") else entry.filename
        path = PurePosixPath(name)
        if (not name or "\\" in name or "\x00" in name or ":" in name or path.is_absolute()
                or any(part in ("", ".", "..") for part in name.split("/"))):
            raise ValueError("unsafe archive path")
        if not path.is_relative_to(ARCHIVE_PREFIX):
            raise ValueError("archive does not have the exact reviewed release prefix")
        relative = path.relative_to(ARCHIVE_PREFIX)
        if relative == PurePosixPath(".") and not entry.is_dir():
            raise ValueError("archive root must be a directory")
        if path in names:
            raise ValueError("duplicate archive path")
        names.add(path)
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError("archive symlinks/devices are not allowed")
        if ((kind == stat.S_IFDIR and not entry.is_dir()) or (kind == stat.S_IFREG and entry.is_dir())
                or entry.flag_bits & 1 or entry.file_size < 0 or entry.file_size > MAX_FILE_BYTES):
            raise ValueError("invalid directory, encrypted entry or oversized asset")
        if not entry.is_dir():
            files.add(path)
        selected.append((entry, Path(relative)))
    if any(parent in files for path in names for parent in path.parents):
        raise ValueError("archive path has a file as its parent")
    return selected


def extract(archive: Path, destination: Path, receipt_path: Path, progress=None) -> dict:
    archive = archive.resolve(strict=True)
    target, receipt_path = destination.absolute(), receipt_path.absolute()
    if target != target.resolve() or target.exists() or target.is_symlink():
        raise ValueError("destination must be a new canonical directory; existing assets are never merged")
    if (receipt_path != receipt_path.resolve() or receipt_path.exists() or receipt_path.is_symlink()
            or receipt_path.is_relative_to(target)):
        raise ValueError("receipt must be a new external canonical file")
    identity = archive.stat()
    if identity.st_size != ARCHIVE_SIZE:
        raise ValueError("archive size differs from the pinned official release")
    digest = hashlib.sha256()
    with archive.open("rb") as reader:
        for block in iter(lambda: reader.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise ValueError("archive SHA-256 differs from the pinned official release")
    with zipfile.ZipFile(archive) as container:
        entries = container.infolist()
        selected = inspect_entries(entries)
        if progress:
            progress({"phase": "archive_verified", "entries": len(entries),
                      "uncompressed_bytes": sum(row.file_size for row in entries)})
        target.mkdir(parents=True, exist_ok=False)
        inventory = hashlib.sha256()
        completed = 0
        for entry, relative in selected:
            path = target / relative
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            file_digest, size = hashlib.sha256(), 0
            with container.open(entry) as reader, path.open("xb") as writer:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    size += len(block)
                    file_digest.update(block)
                    writer.write(block)
            if size != entry.file_size:
                raise ValueError("asset size differs after extraction")
            inventory.update(json.dumps([relative.as_posix(), size, file_digest.hexdigest()],
                                        separators=(",", ":")).encode() + b"\n")
            completed += 1
            if progress and completed % 25000 == 0:
                progress({"phase": "extracting", "files_completed": completed})
    after = archive.stat()
    if (identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("archive changed during extraction; preserve partial output for inspection")
    receipt = {"schema_version": "starvla-rsi.libero_plus.asset-extraction/v1",
               "dataset_revision": DATASET_REVISION, "archive_url": ARCHIVE_URL,
               "archive_path": str(archive), "archive_sha256": ARCHIVE_SHA256,
               "archive_size_bytes": ARCHIVE_SIZE, "archive_entries": len(entries),
               "archive_prefix_removed": str(ARCHIVE_PREFIX), "regular_files": completed,
               "uncompressed_bytes": sum(row.file_size for row in entries),
               "ordered_path_size_sha256_inventory_digest": inventory.hexdigest(),
               "destination": str(target), "scope": "verified ZIP and extracted bytes; not persistent storage or runtime rendering attestation",
               "native_environments_constructed": 0, "native_resets": 0, "native_controls": 0}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("x") as writer:
        writer.write(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    emit = lambda value: print(json.dumps(value, sort_keys=True), flush=True)
    emit(extract(args.archive, args.destination, args.receipt, progress=emit))


if __name__ == "__main__":
    main()
