import pytest

from rpi_vstim.display.photodiode import PhotodiodePatch
from rpi_vstim.display.renderer import (
    BoundedFrameCache,
    ProductionFrameRenderer,
    convert_rgb888_frame,
    photodiode_state_for_frame,
)


def test_bounded_cache_evicts_oldest_entry_and_tracks_hits():
    cache = BoundedFrameCache(2)
    cache.put("a", b"a")
    cache.put("b", b"b")
    assert cache.get("a") == b"a"
    cache.put("c", b"c")
    assert len(cache) == 2
    assert cache.get("b") is None
    assert cache.hits == 1
    assert cache.misses == 1


def test_rgb888_conversion_supports_both_scanout_formats():
    source = bytes((255, 0, 0, 0, 255, 0))
    assert convert_rgb888_frame(source, 2, 1, "RGB565") == bytes((0, 248, 0xE0, 0x07))
    assert convert_rgb888_frame(source, 2, 1, "XRGB8888") == bytes(
        (0, 0, 255, 0, 0, 255, 0, 0)
    )


def test_renderer_reuses_two_buffers_and_keeps_patch_state_with_frame():
    renderer = ProductionFrameRenderer(
        4,
        4,
        "RGB565",
        photodiode=PhotodiodePatch("top_left", 2, 255, 0),
        cache_size=2,
    )
    source = bytes((32, 64, 128)) * 16
    first = renderer.prepare(0, source)
    second = renderer.prepare(1, source)
    assert first.photodiode_state == "on"
    assert second.photodiode_state == "off"
    assert bytes(first.data[:4]) == bytes((0xFF, 0xFF, 0xFF, 0xFF))
    assert bytes(second.data[:4]) == bytes((0, 0, 0, 0))
    assert renderer.scanout_buffer_bytes == 4 * 4 * 2 * 2
    renderer.prepare(0, source)
    assert renderer.cache.hits == 1


def test_photodiode_state_sequence_and_pair_are_deterministic():
    assert [photodiode_state_for_frame(index) for index in range(4)] == [
        "on",
        "off",
        "on",
        "off",
    ]
    renderer = ProductionFrameRenderer(2, 2, "XRGB8888", cache_size=1)
    source = bytes((100, 110, 120)) * 4
    first, second = renderer.prepare_pair(source, source)
    assert first.photodiode_state == "on"
    assert second.photodiode_state == "off"
    assert len(renderer.packed_pair(source, source)) == 2 * 2 * 2 * 4
    assert len(renderer.cache) == 1


def test_photodiode_always_dark_light_and_boundary_states_are_explicit():
    source = bytes((100, 110, 120)) * 4
    dark = ProductionFrameRenderer(
        2, 2, "RGB565", photodiode=PhotodiodePatch("bottom_right", 1, 0, 0)
    )
    light = ProductionFrameRenderer(
        2, 2, "RGB565", photodiode=PhotodiodePatch("bottom_right", 1, 255, 255)
    )
    assert dark.prepare(0, source, photodiode_state="on").photodiode_state == "on"
    assert dark.prepare(1, source, photodiode_state="off").photodiode_state == "off"
    assert light.prepare(0, source, photodiode_state="on").photodiode_state == "on"
    assert light.prepare(1, source, photodiode_state="off").photodiode_state == "off"
    assert ProductionFrameRenderer(2, 2, "RGB565").prepare(
        10, source, photodiode_state="off"
    ).photodiode_state == "off"
    assert ProductionFrameRenderer(2, 2, "RGB565").prepare(
        11, source, photodiode_state="on"
    ).photodiode_state == "on"


def test_renderer_rejects_bad_dimensions_stride_format_and_source():
    with pytest.raises(ValueError, match="unsupported pixel format"):
        ProductionFrameRenderer(2, 2, "ARGB8888")
    with pytest.raises(ValueError, match="source stride"):
        convert_rgb888_frame(bytes(12), 2, 2, "RGB565", source_stride=5)
    with pytest.raises(ValueError, match="shorter"):
        convert_rgb888_frame(bytes(5), 2, 2, "RGB565")
    renderer = ProductionFrameRenderer(2, 2, "RGB565")
    with pytest.raises(ValueError, match="shorter"):
        renderer.prepare(0, bytes(5))


def test_cache_is_bounded_when_many_frames_are_prepared():
    renderer = ProductionFrameRenderer(2, 2, "RGB565", cache_size=3)
    source = bytes((1, 2, 3)) * 4
    for frame_index in range(20):
        renderer.prepare(frame_index, source)
    assert len(renderer.cache) == 3
    assert renderer.cache.memory_bytes == 3 * 2 * 2 * 2
