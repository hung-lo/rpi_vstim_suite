"""Explicit storage-path inspection; this module never mounts anything."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageInspection:
    configured_path: Path
    exists: bool
    is_directory: bool
    mounted: bool
    writable: bool
    free_bytes: int | None
    status: str


def inspect_storage(path: Path | str, *, minimum_free_bytes: int = 0) -> StorageInspection:
    """Inspect a configured path and reject absent/unmounted production roots."""
    path = Path(path)
    if not path.exists():
        return StorageInspection(path, False, False, False, False, None, "absent")
    is_directory = path.is_dir()
    if not is_directory:
        return StorageInspection(path, True, False, False, False, None, "not_directory")
    mounted = os.path.ismount(path)
    writable = os.access(path, os.W_OK)
    free_bytes = shutil.disk_usage(path).free
    if not mounted:
        status = "not_mounted"
    elif not writable:
        status = "not_writable"
    elif free_bytes < minimum_free_bytes:
        status = "low_space"
    else:
        status = "ready"
    return StorageInspection(path, True, True, mounted, writable, free_bytes, status)
