"""Deterministic, bounded natural-image discovery and preparation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .cache import BoundedCache

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
        path = self.resolve(relative_path)
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
            byte_size=path.stat().st_size,
        )

    def verify(self, relative_paths: tuple[str, ...] | None = None) -> tuple[AssetMetadata, ...]:
        paths = self.discover() if relative_paths is None else relative_paths
        return tuple(self.metadata(path) for path in paths)


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
        self.cache = BoundedCache[str, PreparedAsset](
            cache_size,
            size_of=lambda asset: len(asset.rgb888),
        )

    def prepare(self, relative_path: str) -> PreparedAsset:
        metadata = self.resolver.metadata(relative_path)
        cached = self.cache.get(metadata.sha256)
        if cached is not None:
            return cached
        path = self.resolver.resolve(relative_path)
        try:
            from PIL import Image, ImageOps

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

    def metrics(self) -> dict[str, int]:
        return self.cache.metrics()
