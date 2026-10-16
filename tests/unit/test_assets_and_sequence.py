from pathlib import Path
from threading import Thread

import pytest

from rpi_vstim.core.assets import (
    AssetDecodeError,
    AssetNotFoundError,
    AssetPreparer,
    AssetResolver,
    build_selected_asset_manifest,
)
from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets
from rpi_vstim.display.renderer import ProductionFrameRenderer
from rpi_vstim.display.sequence import (
    BoundedFrameTransport,
    FrameTransportBackpressure,
    NaturalImageFrameSource,
    PrefetchCoordinator,
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


def test_selected_manifest_counts_occurrences_and_duplicate_content(tmp_path):
    write_image(tmp_path / "a.png", (1, 2, 3))
    (tmp_path / "b.png").write_bytes((tmp_path / "a.png").read_bytes())
    plan = SessionPlan(
        "natural-images",
        1,
        with_frame_offsets(
            (
                PlannedEvent("a", "image", 1, metadata={"image": "a.png"}),
                PlannedEvent("a2", "image", 1, metadata={"image": "a.png"}),
                PlannedEvent("b", "image", 1, metadata={"image": "b.png"}),
            )
        ),
    )
    manifest = build_selected_asset_manifest(
        plan,
        AssetResolver(tmp_path),
        target_width_px=2,
        target_height_px=2,
        transform="crop",
    )
    assert dict(manifest.selected_occurrences) == {"a.png": 2, "b.png": 1}
    assert manifest.duplicate_content_groups == [["a.png", "b.png"]]
    assert manifest.prepared_memory_bytes == 12
    assert manifest.as_dict()["entries"][0]["transform"] == "crop"


def test_manifest_detects_source_mutation_before_decode(tmp_path):
    write_image(tmp_path / "a.png", (1, 2, 3))
    resolver = AssetResolver(tmp_path)
    manifest = resolver.build_manifest(("a.png",))
    (tmp_path / "a.png").write_bytes(b"changed")
    with pytest.raises(Exception, match="changed during preparation"):
        AssetPreparer(resolver, 2, 2, manifest=manifest).prepare("a.png")


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


def test_prefetch_coordinator_is_bounded_ordered_and_reaps_producer():
    frames = [
        PreparedSequenceFrame(index, "event", "sequence", "a.png", "asset", "on", bytes([index]))
        for index in range(20)
    ]
    coordinator = PrefetchCoordinator(
        frames,
        BoundedFrameTransport(3),
        low_watermark=1,
        high_watermark=2,
    )
    coordinator.start()
    received = []
    while True:
        frame = coordinator.get(timeout_s=1)
        if frame is None:
            break
        received.append(frame.frame_index)
    coordinator.stop()
    assert received == list(range(20))
    assert coordinator.metrics().peak_occupancy <= 3
    assert coordinator.metrics().producer_state == "EOF"


def test_prefetch_consumer_abort_stops_producer():
    frame = PreparedSequenceFrame(0, "event", "sequence", "a.png", "asset", "on", b"a")

    def endless_frames():
        while True:
            yield frame

    coordinator = PrefetchCoordinator(endless_frames(), BoundedFrameTransport(2))
    coordinator.start()
    coordinator.transport.abort("consumer failed")
    with pytest.raises(RuntimeError, match="consumer failed"):
        coordinator.get(timeout_s=1)
    coordinator.stop()
    assert coordinator.producer_state in {"ABORTED", "STOPPED"}


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
