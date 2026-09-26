"""Deterministic, bounded natural-image discovery and preparation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .cache import BoundedCache
from .timestamps import utc_ns

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"})


class AssetError(ValueError):
    """Raised when an asset cannot be resolved, decoded, or prepared."""


class AssetNotFoundError(AssetError):
    pass


class AssetDecodeError(AssetError):
    pass


@dataclass(frozen=True)
class AssetMetadata:
    relative_path: str
    asset_id: str
    sha256: str
    width_px: int
    height_px: int
    mode: str
    byte_size: int
    mtime_ns: int
    inode: int

    def as_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "asset_id": self.asset_id,
            "sha256": self.sha256,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "mode": self.mode,
            "byte_size": self.byte_size,
            "mtime_ns": self.mtime_ns,
            "inode": self.inode,
        }


@dataclass(frozen=True)
class AssetManifest:
    """Immutable metadata index built once before presentation."""

    schema_version: int
    created_utc_ns: int
    entries: tuple[AssetMetadata, ...]
    manifest_hash: str
    selected_occurrences: tuple[tuple[str, int], ...] = ()
    target_width_px: int | None = None
    target_height_px: int | None = None
    transform: str | None = None
    background_value: int | None = None

    @classmethod
    def build(
        cls,
        entries: tuple[AssetMetadata, ...],
        *,
        selected_occurrences: tuple[tuple[str, int], ...] = (),
        target_width_px: int | None = None,
        target_height_px: int | None = None,
        transform: str | None = None,
        background_value: int | None = None,
    ) -> "AssetManifest":
        occurrence_map = dict(selected_occurrences)
        canonical = json.dumps(
            {
                "entries": [entry.as_dict() for entry in entries],
                "selected_occurrences": occurrence_map,
                "target_width_px": target_width_px,
                "target_height_px": target_height_px,
                "transform": transform,
                "background_value": background_value,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return cls(
            1,
            utc_ns(),
            entries,
            hashlib.sha256(canonical).hexdigest(),
            tuple(sorted(selected_occurrences)),
            target_width_px,
            target_height_px,
            transform,
            background_value,
        )

    def entry(self, relative_path: str) -> AssetMetadata:
        for entry in self.entries:
            if entry.relative_path == str(Path(relative_path)):
                return entry
        raise AssetNotFoundError(f"asset is absent from manifest: {relative_path}")

    def as_dict(self) -> dict[str, object]:
        occurrences = dict(self.selected_occurrences)
        return {
            "schema_version": self.schema_version,
            "created_utc_ns": self.created_utc_ns,
            "manifest_hash": self.manifest_hash,
            "entries": [
                entry.as_dict()
                | {
                    "selected_occurrence_count": occurrences.get(entry.relative_path, 0),
                    "target_width_px": self.target_width_px,
                    "target_height_px": self.target_height_px,
                    "transform": self.transform,
                    "background_value": self.background_value,
                }
                for entry in self.entries
            ],
            "selected_occurrences": occurrences,
            "prepared_memory_bytes": self.prepared_memory_bytes,
            "duplicate_content_groups": self.duplicate_content_groups,
        }

    @property
    def prepared_memory_bytes(self) -> int:
        if self.target_width_px is None or self.target_height_px is None:
            return 0
        unique_hashes = {entry.sha256 for entry in self.entries}
        return len(unique_hashes) * self.target_width_px * self.target_height_px * 3

    @property
    def duplicate_content_groups(self) -> list[list[str]]:
        by_hash: dict[str, list[str]] = {}
        for entry in self.entries:
            by_hash.setdefault(entry.sha256, []).append(entry.relative_path)
        return sorted(group for group in by_hash.values() if len(group) > 1)


@dataclass(frozen=True)
class PreparedAsset:
    metadata: AssetMetadata
    width_px: int
    height_px: int
    rgb888: bytes
    asset_key: str
    transform: str
    background_value: int


class AssetResolver:
    """Resolve only relative assets inside an immutable asset root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.metadata_calls = 0
        self.hash_calculations = 0
        self.source_reads = 0
        if not self.root.is_dir():
            raise AssetNotFoundError(f"asset root is not a directory: {self.root}")

    def discover(self) -> tuple[str, ...]:
        return tuple(
            str(path.relative_to(self.root))
            for path in sorted(self.root.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )

    def resolve(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise AssetError(f"asset path must be relative: {relative_path}")
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise AssetError(f"asset path escapes asset root: {relative_path}") from exc
        if not resolved.is_file():
            raise AssetNotFoundError(f"asset is missing: {relative_path}")
        if resolved.suffix.lower() not in IMAGE_SUFFIXES:
            raise AssetError(f"unsupported image format: {resolved.suffix or '<none>'}")
        return resolved

    def metadata(self, relative_path: str) -> AssetMetadata:
        self.metadata_calls += 1
        path = self.resolve(relative_path)
        stat = path.stat()
        self.hash_calculations += 1
        self.source_reads += 1
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            from PIL import Image

            with Image.open(path) as image:
                width_px, height_px = image.size
                mode = image.mode
        except Exception as exc:
            raise AssetDecodeError(f"cannot decode asset {relative_path}: {exc}") from exc
        return AssetMetadata(
            relative_path=str(Path(relative_path)),
            asset_id=digest,
            sha256=digest,
            width_px=width_px,
            height_px=height_px,
            mode=mode,
            byte_size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            inode=stat.st_ino,
        )

    def verify(self, relative_paths: tuple[str, ...] | None = None) -> tuple[AssetMetadata, ...]:
        paths = self.discover() if relative_paths is None else relative_paths
        return tuple(self.metadata(path) for path in paths)

    def build_manifest(
        self,
        relative_paths: tuple[str, ...],
        *,
        target_width_px: int | None = None,
        target_height_px: int | None = None,
        transform: str | None = None,
        background_value: int | None = None,
    ) -> AssetManifest:
        unique_paths = tuple(dict.fromkeys(relative_paths))
        occurrences = tuple(
            (path, relative_paths.count(path)) for path in unique_paths
        )
        return AssetManifest.build(
            tuple(self.metadata(path) for path in unique_paths),
            selected_occurrences=occurrences,
            target_width_px=target_width_px,
            target_height_px=target_height_px,
            transform=transform,
            background_value=background_value,
        )


def build_selected_asset_manifest(
    plan: object,
    resolver: AssetResolver,
    *,
    target_width_px: int,
    target_height_px: int,
    transform: str = "fit_pad",
    background_value: int = 127,
) -> AssetManifest:
    """Resolve and validate every selected image before TASK starts."""
    paths = tuple(
        str(event.metadata["image"])
        for event in getattr(plan, "events", ())
        if getattr(event, "kind", "") == "image"
    )
    return resolver.build_manifest(
        paths,
        target_width_px=target_width_px,
        target_height_px=target_height_px,
        transform=transform,
        background_value=background_value,
    )


class AssetPreparer:
    """Decode and deterministically transform assets with bounded retention."""

    def __init__(
        self,
        resolver: AssetResolver,
        width_px: int,
        height_px: int,
        *,
        transform: str = "fit_pad",
        background_value: int = 127,
        cache_size: int = 8,
        manifest: AssetManifest | None = None,
    ) -> None:
        if width_px <= 0 or height_px <= 0:
            raise ValueError("prepared asset dimensions must be positive")
        if transform not in {"stretch", "fit_pad", "crop"}:
            raise ValueError("transform must be 'stretch', 'fit_pad', or 'crop'")
        if not 0 <= background_value <= 255:
            raise ValueError("background_value must be between 0 and 255")
        self.resolver = resolver
        self.width_px = width_px
        self.height_px = height_px
        self.transform = transform
        self.background_value = background_value
        self.manifest = manifest
        self.decode_count = 0
        self.source_open_count = 0
        if manifest is not None and (
            manifest.target_width_px not in (None, width_px)
            or manifest.target_height_px not in (None, height_px)
            or manifest.transform not in (None, transform)
            or manifest.background_value not in (None, background_value)
        ):
            raise ValueError("asset manifest preparation policy does not match preparer")
        self.cache = BoundedCache[str, PreparedAsset](
            cache_size,
            size_of=lambda asset: len(asset.rgb888),
        )

    def prepare(self, relative_path: str) -> PreparedAsset:
        metadata = (
            self.manifest.entry(relative_path)
            if self.manifest is not None
            else self.resolver.metadata(relative_path)
        )
        cached = self.cache.get(metadata.sha256)
        if cached is not None:
            return cached
        path = self.resolver.resolve(relative_path)
        self._verify_source_fingerprint(path, metadata)
        try:
            from PIL import Image, ImageOps

            self.decode_count += 1
            self.source_open_count += 1
            with Image.open(path) as source:
                if "A" in source.getbands():
                    background = Image.new(
                        "RGBA", source.size, (self.background_value,) * 3 + (255,)
                    )
                    image = Image.alpha_composite(background, source.convert("RGBA")).convert("RGB")
                else:
                    image = source.convert("RGB")
            target_size = (self.width_px, self.height_px)
            if self.transform == "stretch":
                image = image.resize(target_size, Image.Resampling.LANCZOS)
            elif self.transform == "crop":
                image = ImageOps.fit(
                    image,
                    target_size,
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
            else:
                image = ImageOps.pad(
                    image,
                    target_size,
                    method=Image.Resampling.LANCZOS,
                    color=(self.background_value,) * 3,
                    centering=(0.5, 0.5),
                )
            rgb888 = image.tobytes()
        except Exception as exc:
            raise AssetDecodeError(f"cannot prepare asset {relative_path}: {exc}") from exc
        self._verify_source_fingerprint(path, metadata)
        asset = PreparedAsset(
            metadata=metadata,
            width_px=self.width_px,
            height_px=self.height_px,
            rgb888=rgb888,
            asset_key=(
                f"sha256:{metadata.sha256}:{self.width_px}x{self.height_px}:"
                f"{self.transform}:bg{self.background_value}"
            ),
            transform=self.transform,
            background_value=self.background_value,
        )
        self.cache.put(metadata.sha256, asset)
        return asset

    @staticmethod
    def _verify_source_fingerprint(path: Path, metadata: AssetMetadata) -> None:
        stat = path.stat()
        if (
            stat.st_size != metadata.byte_size
            or stat.st_mtime_ns != metadata.mtime_ns
            or stat.st_ino != metadata.inode
        ):
            raise AssetError(f"asset changed during preparation: {metadata.relative_path}")

    def metrics(self) -> dict[str, int]:
        return self.cache.metrics() | {
            "decode_count": self.decode_count,
            "source_open_count": self.source_open_count,
        }
