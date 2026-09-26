from pathlib import Path
from threading import Thread

import pytest

from rpi_vstim.core.assets import (
    AssetDecodeError,
    AssetNotFoundError,
    AssetPreparer,
    AssetResolver,
)
from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets
from rpi_vstim.display.renderer import ProductionFrameRenderer
from rpi_vstim.display.sequence import (
    BoundedFrameTransport,
    FrameTransportBackpressure,
    NaturalImageFrameSource,
    PreparedSequenceFrame,
    produce_frames,
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


def test_manifest_avoids_rehashing_and_reopening_cached_assets(tmp_path, monkeypatch):
    write_image(tmp_path / "a.png", (200, 100, 50))
    resolver = AssetResolver(tmp_path)
    manifest = resolver.build_manifest(("a.png",))
    assert manifest.entry("a.png").sha256 == manifest.entries[0].sha256
    preparer = AssetPreparer(resolver, 3, 3, manifest=manifest)
    first = preparer.prepare("a.png")

    monkeypatch.setattr(resolver, "metadata", lambda _path: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(resolver, "resolve", lambda _path: (_ for _ in ()).throw(AssertionError()))
    assert preparer.prepare("a.png") is first
    assert preparer.metrics()["hits"] == 1


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
    assert frames[1].packed is frames[2].packed
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


def test_frame_transport_finish_wakes_blocked_consumer():
    transport = BoundedFrameTransport(1)
    result = []

    def consume():
        result.append(transport.get())

    thread = Thread(target=consume)
    thread.start()
    transport.finish()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert result == [None]


def test_frame_transport_abort_wakes_consumer_and_clears_queued_frames():
    transport = BoundedFrameTransport(1)
    result = []

    def consume():
        try:
            transport.get()
        except Exception as exc:  # asserted below; thread must not hang
            result.append(exc)

    thread = Thread(target=consume)
    thread.start()
    transport.abort("producer failed")
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert len(result) == 1
    assert isinstance(result[0], RuntimeError)
    assert str(result[0]) == "producer failed"
    queued = BoundedFrameTransport(1)
    queued.put(PreparedSequenceFrame(0, "event", "sequence", "a.png", "asset", "on", b"a"))
    queued.abort("discard queued")
    with pytest.raises(RuntimeError, match="discard queued"):
        queued.get(timeout_s=0)


def test_frame_transport_blocked_put_wakes_on_abort():
    transport = BoundedFrameTransport(1)
    frame = PreparedSequenceFrame(0, "event", "sequence", "a.png", "asset", "on", b"a")
    transport.put(frame)
    result = []

    def produce():
        try:
            transport.put(frame)
        except Exception as exc:  # asserted below; thread must not hang
            result.append(exc)

    thread = Thread(target=produce)
    thread.start()
    transport.abort("consumer failed")
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert len(result) == 1
    assert isinstance(result[0], RuntimeError)
    assert str(result[0]) == "consumer failed"


def test_plan_to_transport_replays_deterministically_and_fails_mid_plan(tmp_path):
    write_image(tmp_path / "image.png", (1, 2, 3))
    resolver = AssetResolver(tmp_path)
    plan = SessionPlan(
        "natural-images",
        9,
        with_frame_offsets(
            (
                PlannedEvent(
                    "image-1", "image", 1, photodiode="on", metadata={"image": "image.png"}
                ),
                PlannedEvent("tail", "gray", 1, phase="POST"),
            )
        ),
    )

    def make_source():
        return NaturalImageFrameSource(
            AssetPreparer(resolver, 2, 2),
            ProductionFrameRenderer(2, 2, "RGB565"),
        )

    first_transport = BoundedFrameTransport(2)
    assert produce_frames(make_source().prepared_frames(plan), first_transport) == 2
    first = list(first_transport.iter_frames())
    second_transport = BoundedFrameTransport(2)
    assert produce_frames(make_source().prepared_frames(plan), second_transport) == 2
    second = list(second_transport.iter_frames())
    assert [(frame.frame_index, frame.asset_key, frame.packed) for frame in first] == [
        (frame.frame_index, frame.asset_key, frame.packed) for frame in second
    ]

    bad_plan = SessionPlan(
        "natural-images",
        9,
        with_frame_offsets(
            (
                PlannedEvent("good", "image", 1, metadata={"image": "image.png"}),
                PlannedEvent("bad", "image", 1, metadata={"image": "missing.png"}),
            )
        ),
    )
    with pytest.raises(AssetNotFoundError):
        list(make_source().prepared_frames(bad_plan))
