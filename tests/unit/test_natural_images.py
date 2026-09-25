from pathlib import Path

import pytest

from rpi_vstim.protocols.natural_images import (
    NaturalImageSettings,
    build_plan,
    discover_images,
)


def test_image_discovery_is_sorted_and_does_not_decode_assets(tmp_path):
    (tmp_path / "b.png").write_bytes(b"not decoded")
    (tmp_path / "a.JPG").write_bytes(b"not decoded")
    (tmp_path / "ignore.txt").write_text("ignore")

    assert discover_images(tmp_path) == ("a.JPG", "b.png")


def test_natural_plan_is_reproducible_and_keeps_profile_metadata():
    settings = NaturalImageSettings(
        images=("a.png", "b.png", "c.png"),
        seed=11,
        trial_count=6,
        iti_frames=(2, 4),
        initial_gray_frames=1,
        final_gray_frames=1,
        camera_ids=("face", "behavior"),
    )
    first = build_plan(settings)
    second = build_plan(settings)

    assert first.stable_json() == second.stable_json()
    selected = first.metadata["selected_images"]
    assert all(left != right for left, right in zip(selected, selected[1:]))
    assert first.metadata["camera_ids"] == ["face", "behavior"]
    assert first.total_frames == sum(event.frame_count for event in first.events)


def test_natural_profiles_have_explicit_final_iti_behavior():
    plain = build_plan(
        NaturalImageSettings(images=("a",), iti_frames=(3,), compatibility_profile="natural_legacy_plain")
    )
    camera = build_plan(
        NaturalImageSettings(images=("a",), iti_frames=(3,), compatibility_profile="natural_legacy_camera")
    )

    assert [event.kind for event in plain.events].count("iti") == 1
    assert [event.kind for event in camera.events].count("iti") == 0


def test_discover_images_rejects_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_images(Path(tmp_path / "missing"))
