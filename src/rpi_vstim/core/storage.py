"""Explicit storage-path inspection; this module never mounts anything."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
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


@dataclass(frozen=True)
class StorageSession:
    production_root: Path
    session_root: Path
    marker_path: Path
    preflight: StoragePreflight
    free_bytes_at_start: int

    def as_dict(self) -> dict[str, object]:
        return {
            "production_root": str(self.production_root),
            "session_root": str(self.session_root),
            "marker_path": str(self.marker_path),
            "preflight": self.preflight.as_dict(),
            "free_bytes_at_start": self.free_bytes_at_start,
        }


@dataclass(frozen=True)
class StorageFinalizeResult:
    complete: bool
    missing_required_files: tuple[str, ...]
    free_bytes_at_end: int
    marker_retained: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "missing_required_files": list(self.missing_required_files),
            "free_bytes_at_end": self.free_bytes_at_end,
            "marker_retained": self.marker_retained,
        }


class StorageMonitor:
    def __init__(self, root: Path | str, *, minimum_free_bytes: int) -> None:
        if minimum_free_bytes < 0:
            raise ValueError("minimum_free_bytes must be non-negative")
        self.root = Path(root).resolve()
        self.minimum_free_bytes = minimum_free_bytes

    def check(self) -> dict[str, object]:
        free_bytes = shutil.disk_usage(self.root).free
        return {
            "passed": free_bytes >= self.minimum_free_bytes,
            "free_bytes": free_bytes,
            "minimum_free_bytes": self.minimum_free_bytes,
        }


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


def open_storage_session(preflight: StoragePreflight, session_id: str) -> StorageSession:
    if not preflight.passed:
        raise ValueError(f"storage preflight failed: {preflight.status}")
    if not session_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in session_id):
        raise ValueError("session_id contains unsupported characters")
    session_root = preflight.path / session_id
    session_root.mkdir()
    marker = session_root / ".session-incomplete"
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, b"incomplete\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return StorageSession(
        preflight.path,
        session_root,
        marker,
        preflight,
        shutil.disk_usage(preflight.path).free,
    )


def finalize_storage_session(
    session: StorageSession,
    *,
    required_files: Iterable[Path | str],
    success: bool,
) -> StorageFinalizeResult:
    missing = tuple(
        str(path)
        for path in required_files
        if not (session.session_root / path).is_file()
    )
    for path in session.session_root.rglob("*"):
        if path.is_file():
            try:
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError:
                pass
    complete = bool(success and not missing)
    if complete:
        session.marker_path.unlink(missing_ok=True)
    return StorageFinalizeResult(
        complete,
        missing,
        shutil.disk_usage(session.production_root).free,
        session.marker_path.exists(),
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
