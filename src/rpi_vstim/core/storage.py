"""Storage inspection and fail-closed NVMe preflight; never mounts anything."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
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
    path = Path(path)
    if not path.exists():
        return StorageInspection(path, False, False, False, False, None, "absent")
    if not path.is_dir():
        return StorageInspection(path, True, False, False, False, None, "not_directory")
    mounted = os.path.ismount(path)
    writable = os.access(path, os.W_OK)
    free_bytes = shutil.disk_usage(path).free
    status = (
        "not_mounted"
        if not mounted
        else "not_writable"
        if not writable
        else "low_space"
        if free_bytes < minimum_free_bytes
        else "ready"
    )
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
    """Fail closed before production writes; never mounts or selects a fallback."""
    root = Path(path).resolve()
    checks: list[dict[str, object]] = [
        {
            "name": "safe_production_root",
            "passed": allow_test_path or not _unsafe_fallback(root),
            "detail": "temporary/test override"
            if allow_test_path and _unsafe_fallback(root)
            else str(root),
        }
    ]
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
    if not session_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for char in session_id
    ):
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
        preflight.path, session_root, marker, preflight, shutil.disk_usage(preflight.path).free
    )


def finalize_storage_session(
    session: StorageSession, *, required_files: Iterable[Path | str], success: bool
) -> StorageFinalizeResult:
    missing = tuple(
        str(path) for path in required_files if not (session.session_root / path).is_file()
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
    roots = {Path("/").resolve(), Path.home().resolve(), Path(tempfile.gettempdir()).resolve()}
    if os.name == "posix":
        roots.add(Path("/var/tmp").resolve())
    return any(resolved == root or root in resolved.parents for root in roots)


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


PRODUCTION_STORAGE_MOUNT = Path("/mnt/behavbox_ssd")
PRODUCTION_SESSION_ROOT = PRODUCTION_STORAGE_MOUNT / "sessions"
PRODUCTION_STORAGE_UUID = "18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99"
PRODUCTION_STORAGE_SOURCE = "/dev/nvme0n1p1"
DEFAULT_MIN_FREE_BYTES = 20 * 1024**3


class StoragePreflightError(RuntimeError):
    """The requested session storage is not safe to use."""


@dataclass(frozen=True)
class StorageSnapshot:
    output_root: str
    filesystem_type: str | None
    mount_source: str | None
    filesystem_uuid: str | None
    total_bytes: int
    free_bytes: int
    production_storage: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_production_root(root: Path) -> bool:
    try:
        root.resolve(strict=False).relative_to(PRODUCTION_STORAGE_MOUNT)
    except ValueError:
        return False
    return True


def _mount_info(path: Path) -> dict[str, str | None]:
    try:
        result = subprocess.run(
            ("findmnt", "--json", "--target", str(path), "--output", "TARGET,SOURCE,FSTYPE,UUID"),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        filesystems = json.loads(result.stdout).get("filesystems", [])
        entry = filesystems[0] if result.returncode == 0 and filesystems else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        entry = {}
    return {"source": entry.get("source"), "fstype": entry.get("fstype"), "uuid": entry.get("uuid")}


def _writable(path: Path) -> bool:
    if not os.access(path, os.W_OK | os.X_OK):
        return False
    try:
        descriptor, probe = tempfile.mkstemp(prefix=".rpi-vstim-storage-", dir=path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"storage preflight\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(probe).unlink()
    except OSError:
        return False
    return True


def storage_snapshot(output_root: Path | str) -> StorageSnapshot:
    root = Path(output_root)
    usage = shutil.disk_usage(root)
    mount = _mount_info(root)
    return StorageSnapshot(
        str(root),
        mount["fstype"],
        mount["source"],
        mount["uuid"],
        usage.total,
        usage.free,
        _is_production_root(root),
    )


def prepare_session_output_root(output_root: Path | str) -> StorageSnapshot:
    """Create and validate the one root from which a session may write."""
    root = Path(output_root)
    production = _is_production_root(root)
    if production:
        if not PRODUCTION_STORAGE_MOUNT.exists() or not os.path.ismount(PRODUCTION_STORAGE_MOUNT):
            raise StoragePreflightError(
                "Production storage unavailable: /mnt/behavbox_ssd is not mounted from the expected filesystem."
            )
        mount = _mount_info(PRODUCTION_STORAGE_MOUNT)
        if (
            mount["source"] != PRODUCTION_STORAGE_SOURCE
            or mount["fstype"] != "ext4"
            or mount["uuid"] != PRODUCTION_STORAGE_UUID
        ):
            raise StoragePreflightError(
                "Production storage unavailable: /mnt/behavbox_ssd is not mounted from the expected filesystem."
            )
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir() or not _writable(root):
        raise StoragePreflightError(f"Session output root is not writable: {root}")
    snapshot = storage_snapshot(root)
    if production and snapshot.free_bytes < DEFAULT_MIN_FREE_BYTES:
        raise StoragePreflightError(
            f"Production storage unavailable: only {snapshot.free_bytes} bytes free; need at least {DEFAULT_MIN_FREE_BYTES}."
        )
    return snapshot
