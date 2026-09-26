"""Explicit storage-path inspection; this module never mounts anything."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class StorageInspection:
    configured_path: Path
    exists: bool
    is_directory: bool
    mounted: bool
    writable: bool
    free_bytes: int | None
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "configured_path": str(self.configured_path),
            "exists": self.exists,
            "is_directory": self.is_directory,
            "mounted": self.mounted,
            "writable": self.writable,
            "free_bytes": self.free_bytes,
            "status": self.status,
        }


@dataclass(frozen=True)
class StoragePreflight:
    path: Path
    passed: bool
    estimated_required_bytes: int
    checks: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "passed": self.passed,
            "estimated_required_bytes": self.estimated_required_bytes,
            "checks": list(self.checks),
            "status": self.status,
        }

    @property
    def status(self) -> str:
        failed = next((check["name"] for check in self.checks if not check["passed"]), None)
        return "ready" if failed is None and self.passed else f"failed:{failed}"


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


def preflight_storage(
    path: Path | str,
    *,
    minimum_free_bytes: int = 0,
    estimated_required_bytes: int = 0,
    require_mount: bool = True,
    expected_device: str | None = None,
    identity_reader: Callable[[Path], str] | None = None,
    allow_test_path: bool = False,
    write_probe: bool = False,
) -> StoragePreflight:
    """Fail closed before production writes; never mounts or selects a fallback.

    `allow_test_path` is for temporary-directory tests only. Production callers
    should leave it false so `/`, the home directory, and temporary storage
    cannot silently become the recording root.
    """
    root = Path(path).resolve()
    checks: list[dict[str, object]] = []

    unsafe = _unsafe_fallback(root)
    checks.append({
        "name": "safe_production_root",
        "passed": allow_test_path or not unsafe,
        "detail": "temporary/test override" if allow_test_path and unsafe else str(root),
    })
    inspection = inspect_storage(root, minimum_free_bytes=minimum_free_bytes)
    checks.extend(
        (
            {"name": "exists", "passed": inspection.exists, "detail": inspection.status},
            {"name": "directory", "passed": inspection.is_directory, "detail": inspection.status},
            {
                "name": "mounted",
                "passed": inspection.mounted or not require_mount,
                "detail": "mounted" if inspection.mounted else "mount required",
            },
            {"name": "writable", "passed": inspection.writable, "detail": inspection.status},
            {
                "name": "minimum_free_bytes",
                "passed": inspection.free_bytes is not None
                and inspection.free_bytes >= minimum_free_bytes,
                "detail": str(inspection.free_bytes),
            },
            {
                "name": "estimated_required_bytes",
                "passed": inspection.free_bytes is not None
                and inspection.free_bytes >= estimated_required_bytes,
                "detail": str(estimated_required_bytes),
            },
        )
    )
    if expected_device is not None:
        identity = identity_reader(root) if identity_reader is not None and root.is_dir() else None
        checks.append(
            {
                "name": "expected_device",
                "passed": identity == expected_device,
                "detail": f"expected={expected_device!r}, observed={identity!r}",
            }
        )
    if write_probe:
        passed, detail = _write_probe(root)
        checks.append({"name": "write_probe", "passed": passed, "detail": detail})
    return StoragePreflight(
        root,
        all(bool(check["passed"]) for check in checks),
        estimated_required_bytes,
        tuple(checks),
    )


def _unsafe_fallback(path: Path) -> bool:
    resolved = path.resolve()
    unsafe_roots = {
        Path("/").resolve(),
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }
    if os.name == "posix":
        unsafe_roots.add(Path("/var/tmp").resolve())
    return any(resolved == root or root in resolved.parents for root in unsafe_roots)


def _write_probe(root: Path) -> tuple[bool, str]:
    if not root.is_dir():
        return False, "root is not a directory"
    path = root / f".rpi-vstim-preflight-{uuid.uuid4().hex}"
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, b"rpi-vstim-preflight\n")
        os.fsync(descriptor)
        return True, "write/fsync/delete probe passed"
    except OSError as exc:
        return False, str(exc)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        path.unlink(missing_ok=True)
