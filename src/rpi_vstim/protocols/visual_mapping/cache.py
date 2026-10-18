from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rpi_vstim.core.session import atomic_write_json

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class FrameCacheError(RuntimeError):
    """A rendered-frame cache is missing, corrupt, or incompatible."""


@dataclass(frozen=True)
class FrameSetSpec:
    name: str
    frame_count: int
    render: Callable[[int], bytes]


@dataclass
class FrameCache:
    path: Path
    protocol: str
    cache_key: str
    frame_size_bytes: int
    manifest: dict[str, Any]
    _handles: dict[str, Any] = field(default_factory=dict)

    def read_frame(self, name: str, index: int) -> bytes:
        entry = self.manifest["frame_sets"].get(name)
        if entry is None:
            raise FrameCacheError(f"cache has no frame set {name!r}")
        count = int(entry["frame_count"])
        if not 0 <= index < count:
            raise IndexError(f"frame {index} outside {name!r} cache of {count} frames")
        handle = self._handles.get(name)
        if handle is None:
            handle = (self.path / entry["file"]).open("rb")
            self._handles[name] = handle
        handle.seek(index * self.frame_size_bytes)
        payload = handle.read(self.frame_size_bytes)
        if len(payload) != self.frame_size_bytes:
            raise FrameCacheError(f"short read in cached frame set {name!r} at frame {index}")
        return payload

    def close(self) -> None:
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()


def _digest_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def cache_key_for(protocol: str, render_settings: dict[str, Any], frame_size_bytes: int) -> str:
    return _digest_json({
        "protocol": protocol,
        "render_settings": render_settings,
        "frame_size_bytes": frame_size_bytes,
    })


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _entry(root: Path, path: Path) -> dict[str, Any]:
    digest, size = _file_digest(path)
    return {"file": str(path.relative_to(root)), "sha256": digest, "size_bytes": size}


def _resolve_inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise FrameCacheError("cache manifest path escapes its cache directory")
    return candidate


def open_frame_cache(
    path: Path,
    *,
    protocol: str,
    cache_key: str,
    frame_size_bytes: int,
    render_settings: dict[str, Any],
) -> FrameCache:
    manifest_path = path / "cache_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FrameCacheError(f"cannot read frame cache manifest at {manifest_path}: {exc}") from exc
    if (
        manifest.get("schema_version") != 1
        or manifest.get("protocol") != protocol
        or manifest.get("cache_key") != cache_key
        or manifest.get("render_settings") != render_settings
        or manifest.get("frame_size_bytes") != frame_size_bytes
    ):
        raise FrameCacheError("render cache settings do not match this protocol configuration")
    if _digest_json({"protocol": protocol, "render_settings": render_settings,
                     "frame_size_bytes": frame_size_bytes}) != cache_key:
        raise FrameCacheError("render cache key does not match its settings")
    frame_sets = manifest.get("frame_sets")
    if not isinstance(frame_sets, dict) or not frame_sets:
        raise FrameCacheError("render cache contains no frame sets")
    for name, entry in frame_sets.items():
        if not _SAFE_NAME.fullmatch(name) or not isinstance(entry, dict):
            raise FrameCacheError("render cache has an invalid frame-set entry")
        if type(entry.get("frame_count")) is not int or entry["frame_count"] < 1:
            raise FrameCacheError(f"render cache frame count is invalid for {name}")
        file_path = _resolve_inside(path, str(entry.get("file", "")))
        digest, size = _file_digest(file_path)
        expected_size = entry["frame_count"] * frame_size_bytes
        if size != expected_size or entry.get("size_bytes") != size:
            raise FrameCacheError(f"render cache size mismatch for frame set {name}")
        if digest != entry.get("sha256"):
            raise FrameCacheError(f"render cache checksum mismatch for frame set {name}")
    for entry in manifest.get("artifacts", []):
        if not isinstance(entry, dict):
            raise FrameCacheError("render cache has an invalid artifact entry")
        artifact_path = _resolve_inside(path, str(entry.get("file", "")))
        digest, size = _file_digest(artifact_path)
        if size != entry.get("size_bytes") or digest != entry.get("sha256"):
            raise FrameCacheError(f"render cache artifact failed validation: {entry.get('file')}")
    return FrameCache(path, protocol, cache_key, frame_size_bytes, manifest)


def build_frame_cache(
    cache_root: Path,
    *,
    protocol: str,
    render_settings: dict[str, Any],
    frame_size_bytes: int,
    frame_sets: Iterable[FrameSetSpec],
    write_artifacts: Callable[[Path], Iterable[Path]] | None = None,
) -> FrameCache:
    if not _SAFE_NAME.fullmatch(protocol):
        raise ValueError("protocol cache name must be a safe path component")
    if frame_size_bytes <= 0:
        raise ValueError("frame_size_bytes must be positive")
    sets = tuple(frame_sets)
    if not sets or len({item.name for item in sets}) != len(sets):
        raise ValueError("frame sets must be non-empty and have unique names")
    if any(not _SAFE_NAME.fullmatch(item.name) or item.frame_count < 1 for item in sets):
        raise ValueError("frame set names and counts must be valid")
    cache_key = cache_key_for(protocol, render_settings, frame_size_bytes)
    destination = Path(cache_root) / protocol / cache_key
    if destination.exists():
        return open_frame_cache(
            destination,
            protocol=protocol,
            cache_key=cache_key,
            frame_size_bytes=frame_size_bytes,
            render_settings=render_settings,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{cache_key}.building-", dir=destination.parent))
    try:
        (staging / "frames").mkdir()
        manifest_sets: dict[str, Any] = {}
        for spec in sets:
            relative = Path("frames") / f"{spec.name}.bin"
            path = staging / relative
            digest = hashlib.sha256()
            count = 0
            with path.open("wb") as handle:
                for index, frame in enumerate(spec.render(i) for i in range(spec.frame_count)):
                    payload = bytes(frame)
                    if len(payload) != frame_size_bytes:
                        raise FrameCacheError(
                            f"renderer returned {len(payload)} bytes for {spec.name}[{index}], "
                            f"expected {frame_size_bytes}"
                        )
                    handle.write(payload)
                    digest.update(payload)
                    count += 1
                handle.flush()
                os.fsync(handle.fileno())
            if count != spec.frame_count:
                raise FrameCacheError(f"renderer produced the wrong frame count for {spec.name}")
            manifest_sets[spec.name] = {
                "file": str(relative),
                "frame_count": count,
                "size_bytes": count * frame_size_bytes,
                "sha256": digest.hexdigest(),
            }
        artifact_paths = tuple(write_artifacts(staging)) if write_artifacts else ()
        artifacts = []
        for artifact in artifact_paths:
            resolved = Path(artifact).resolve()
            if not resolved.is_relative_to(staging.resolve()) or not resolved.is_file():
                raise FrameCacheError("cache artifact writer returned a missing/out-of-cache path")
            artifacts.append(_entry(staging, resolved))
        atomic_write_json(staging / "cache_manifest.json", {
            "schema_version": 1,
            "protocol": protocol,
            "cache_key": cache_key,
            "frame_size_bytes": frame_size_bytes,
            "render_settings": render_settings,
            "frame_sets": manifest_sets,
            "artifacts": artifacts,
        })
        # Verify checksums and schema before the cache becomes visible to a run.
        open_frame_cache(
            staging,
            protocol=protocol,
            cache_key=cache_key,
            frame_size_bytes=frame_size_bytes,
            render_settings=render_settings,
        ).close()
        try:
            os.replace(staging, destination)
        except OSError:
            if not destination.exists():
                raise
            shutil.rmtree(staging)
        return open_frame_cache(
            destination,
            protocol=protocol,
            cache_key=cache_key,
            frame_size_bytes=frame_size_bytes,
            render_settings=render_settings,
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
