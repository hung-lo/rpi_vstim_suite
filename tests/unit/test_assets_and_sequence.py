from pathlib import Path

import pytest

from rpi_vstim.core.assets import AssetDecodeError, AssetNotFoundError, AssetPreparer, AssetResolver
from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets
from rpi_vstim.display.renderer import ProductionFrameRenderer
from rpi_vstim.display.sequence import (
    BoundedFrameTransport,
    FrameTransportBackpressure,
    NaturalImageFrameSource,
    PreparedSequenceFrame,
)

Image = pytest.importorskip("PIL.Image")


def write_image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (4, 2), color).save(path)


def test_asset_resolver_and_preparer_are_deterministic_and_bounded(tmp_path):
    write_image(tmp_path / "b.png", (20, 30, 40))
    write_image(tmp_path / "a.png", (200, 100, 50))
    resolver = AssetResolver(tmp_path)
    assert resolver.discover() == ("a.png", "b.png")
    metadata = resolver.verify()
    assert [item.relative_path for item in metadata] == ["a.png", "b.png"]
    preparer = AssetPreparer(resolver, 3, 3, cache_size=1)
    first = preparer.prepare("a.png")
    assert len(first.rgb888) == 3 * 3 * 3
    assert first.asset_key.startswith("sha256:")
    assert preparer.prepare("a.png") is first
    preparer.prepare("b.png")
    assert preparer.metrics()["evictions"] == 1
    assert preparer.metrics()["memory_bytes"] == 3 * 3 * 3


def test_asset_errors_are_explicit(tmp_path):
    resolver = AssetResolver(tmp_path)
    with pytest.raises(AssetNotFoundError, match="missing"):
        resolver.metadata("missing.png")
    (tmp_path / "broken.png").write_bytes(b"not an image")
    with pytest.raises(AssetDecodeError, match="cannot decode"):
        resolver.metadata("broken.png")
    with pytest.raises(ValueError, match="transform"):
        AssetPreparer(resolver, 2, 2, transform="unknown")


def test_natural_image_source_maps_plan_frames_and_prevents_stale_pixels(tmp_path):
    write_image(tmp_path / "image.png", (255, 0, 0))
    resolver = AssetResolver(tmp_path)
    preparer = AssetPreparer(resolver, 2, 2, cache_size=2)
    renderer = ProductionFrameRenderer(2, 2, "RGB565", cache_size=2)
    source = NaturalImageFrameSource(preparer, renderer, gray_value=127)
    plan = SessionPlan(
        "natural-images",
        7,
        with_frame_offsets(
            (
                PlannedEvent("pre", "gray", 1, phase="PRE"),
                PlannedEvent(
                    "image-1",
                    "image",
                    2,
                    sequence_id="image-1",
                    photodiode="on",
                    metadata={"image": "image.png"},
                ),
                PlannedEvent("post", "gray", 1, phase="POST"),
            )
        ),
    )
    frames = list(source.prepared_frames(plan))
    assert [frame.frame_index for frame in frames] == [0, 1, 2, 3]
    assert [frame.photodiode_state for frame in frames] == ["off", "on", "on", "off"]
    assert frames[1].asset_key == frames[2].asset_key
    assert frames[1].packed == frames[2].packed
    assert frames[0].packed != frames[1].packed
    assert source.metrics()["renderer_cache"]["hits"] == 2


def test_frame_transport_is_ordered_bounded_and_abortable():
    transport = BoundedFrameTransport(1)
    frame = PreparedSequenceFrame(0, "event", "sequence", "a.png", "asset", "on", b"a")
    second = PreparedSequenceFrame(1, "event", "sequence", "b.png", "asset2", "off", b"b")
    transport.put(frame)
    with pytest.raises(FrameTransportBackpressure):
        transport.put(second, timeout_s=0)
    assert transport.get(timeout_s=0) == frame
    transport.put(second)
    transport.finish()
    assert list(transport.iter_frames()) == [second]
    assert transport.get(timeout_s=0) is None

    aborted = BoundedFrameTransport(1)
    aborted.abort("producer stopped")
    with pytest.raises(RuntimeError, match="producer stopped"):
        aborted.put(frame)
