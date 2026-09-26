from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan


def test_natural_legacy_plan_matches_frozen_seed_fixture():
    images = tuple(f"stringer_{index:04d}.png" for index in range(14))
    plan = build_plan(
        NaturalImageSettings(
            images=images,
            seed=42,
            image_count=5,
            repeat_count=2,
            selection_seed=777,
            refresh_hz=60.0,
            image_duration_s=0.5,
            iti_frames=(42, 60),
            initial_gray_frames=180,
            final_gray_frames=180,
        )
    )
    expected = [
        ("stringer_0005.png", 43),
        ("stringer_0003.png", 51),
        ("stringer_0012.png", 46),
        ("stringer_0009.png", 56),
        ("stringer_0012.png", 53),
        ("stringer_0003.png", 45),
        ("stringer_0009.png", 56),
        ("stringer_0007.png", 57),
        ("stringer_0005.png", 42),
        ("stringer_0007.png", 58),
    ]
    image_events = [event for event in plan.events if event.kind == "image"]
    iti_events = [event for event in plan.events if event.kind == "iti"]
    actual = [(event.metadata["image"], iti.frame_count) for event, iti in zip(image_events, iti_events)]
    assert actual == expected
    assert plan.metadata["asset_transform"] == "crop"
    assert plan.metadata["background_gray"] == 127


def test_natural_camera_profile_skips_final_iti_like_frozen_runner():
    plan = build_plan(
        NaturalImageSettings(
            images=("a.png", "b.png"),
            seed=4,
            image_count=None,
            repeat_count=1,
            compatibility_profile="natural_legacy_camera",
        )
    )
    assert plan.events[-2].kind == "image"
    assert plan.events[-1].kind == "gray"
