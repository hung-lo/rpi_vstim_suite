import csv
import json
import math
import random
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="visual protocol rendering tests require the [visual] extra")
Image = pytest.importorskip("PIL.Image", reason="visual protocol preview tests require the [visual] extra")

from rpi_vstim.core.config import Config, PathsConfig
from rpi_vstim.core.session import inspect_session
from rpi_vstim.protocols.drifting_gratings import (
    DEFAULT_ORIENTATIONS_DEG,
    DriftingGratingSettings,
    RectangularPatchGeometry,
    drift_direction_deg,
)
from rpi_vstim.protocols.drifting_gratings import (
    build_plan as build_grating_plan,
)
from rpi_vstim.protocols.drifting_gratings.cache import build_cache as build_grating_cache
from rpi_vstim.protocols.drifting_gratings.cache import write_preview as write_grating_preview
from rpi_vstim.protocols.drifting_gratings.stimulus import generate_grating_frame
from rpi_vstim.protocols.retinotopy import (
    DIRECTIONS,
    RetinotopySettings,
    refreshes_per_source_frame,
)
from rpi_vstim.protocols.retinotopy import (
    build_plan as build_retinotopy_plan,
)
from rpi_vstim.protocols.retinotopy.cache import build_cache as build_retinotopy_cache
from rpi_vstim.protocols.retinotopy.cache import write_preview as write_retinotopy_preview
from rpi_vstim.protocols.retinotopy.sequence import (
    build_frame_plan_rows,
    update_actual_kms_mapping,
    write_frame_plan,
)
from rpi_vstim.protocols.retinotopy.stimulus import (
    bar_width_px,
    boundary_positions_px,
    generate_retinotopy_frame,
)
from rpi_vstim.protocols.visual_mapping.cache import FrameCacheError
from rpi_vstim.protocols.visual_mapping.config import load_protocol_settings
from rpi_vstim.protocols.visual_mapping.geometry import (
    geometry_snapshot,
    pixel_edge_to_screen_cm,
    pixel_to_screen_cm,
    screen_cm_to_visual_angle_deg,
)
from rpi_vstim.protocols.visual_mapping.runner import run_visual_mapping


def small_config(tmp_path: Path) -> Config:
    return replace(
        Config(),
        paths=replace(
            PathsConfig(),
            output_root=tmp_path / "sessions",
            cache_root=tmp_path / "cache",
        ),
        display=replace(
            Config().display,
            backend="fake",
            width_px=80,
            height_px=60,
            refresh_hz=59.82,
            physical_width_cm=12.0,
            physical_height_cm=9.0,
            eye_distance_cm=16.0,
        ),
        photodiode=replace(Config().photodiode, enabled=True, size_px=4),
    )


def test_grating_frozen_defaults_and_bar_vs_drift_semantics():
    settings = DriftingGratingSettings()
    assert settings.orientations_deg == DEFAULT_ORIENTATIONS_DEG
    assert len(set(settings.orientations_deg)) == 8
    assert [drift_direction_deg(angle) for angle in settings.orientations_deg] == [
        270.0, 292.5, 315.0, 337.5, 0.0, 22.5, 45.0, 67.5
    ]
    assert (settings.trials_per_orientation, settings.stim_duration_s) == (80, 0.5)
    assert (settings.temporal_frequency_hz, settings.spatial_frequency_cycles_per_cm) == (2.0, 0.2)
    assert (settings.contrast, settings.mean_luminance, settings.initial_gray_s, settings.final_gray_s) == (
        1.0, 0.5, 3.0, 3.0
    )


def test_grating_plan_balanced_deterministic_and_frame_quantized_itis():
    settings = DriftingGratingSettings(trials_per_orientation=3, sequence_seed=91, refresh_hz=59.82)
    first = build_grating_plan(settings)
    second = build_grating_plan(settings)
    assert first.stable_json() == second.stable_json()
    trials = [event for event in first.events if event.kind == "drifting-grating"]
    counts = {angle: 0 for angle in settings.orientations_deg}
    for event in trials:
        counts[event.metadata["bar_orientation_deg"]] += 1
        assert event.metadata["drift_direction_deg"] == drift_direction_deg(event.metadata["bar_orientation_deg"])
        assert event.frame_count == round(0.5 * 59.82)
    assert set(counts.values()) == {3}
    itis = [event for event in first.events if event.kind == "iti"]
    assert len(itis) == 24
    ordered = [
        (orientation_id, angle, repeat)
        for orientation_id, angle in enumerate(settings.orientations_deg, start=1)
        for repeat in range(1, settings.trials_per_orientation + 1)
    ]
    rng = random.Random(settings.sequence_seed)
    rng.shuffle(ordered)
    for event in itis:
        requested = settings.iti_base_s + rng.random() * settings.iti_jitter_max_s
        assert 0.7 <= requested < 1.2
        assert event.frame_count == round(requested * settings.refresh_hz)


def test_grating_render_phase_frequency_luminance_and_no_clipping(tmp_path):
    config = small_config(tmp_path)
    settings = DriftingGratingSettings(
        orientations_deg=(0.0,), trials_per_orientation=1, stim_duration_s=0.5,
        refresh_hz=config.display.refresh_hz,
    )
    frame0 = generate_grating_frame(config, settings, bar_orientation_deg=0.0, frame_index=0)
    frame1 = generate_grating_frame(config, settings, bar_orientation_deg=0.0, frame_index=1)
    assert frame0.shape == (60, 80, 3)
    assert frame0.dtype == np.uint8
    assert frame0.min() >= 0 and frame0.max() <= 255
    assert not np.array_equal(frame0, frame1)
    assert settings.stimulus_frame_count == round(0.5 * config.display.refresh_hz)
    row, column = 11, 17
    y_cm = ((config.display.height_px - 1) / 2 - row) * config.display.physical_height_cm / config.display.height_px
    phase = 2 * math.pi * settings.temporal_frequency_hz * 0 / config.display.refresh_hz
    old_formula_luminance = settings.mean_luminance * (
        1 + settings.contrast * math.sin(2 * math.pi * settings.spatial_frequency_cycles_per_cm * y_cm + phase)
    )
    assert frame0[row, column, 0] == round(old_formula_luminance * 255)
    with pytest.raises(ValueError, match="display range"):
        DriftingGratingSettings(mean_luminance=0.8, contrast=1.0)

    patch_settings = replace(
        settings,
        grating_mode="rectangular_patch",
        rectangular_patch_geometry=RectangularPatchGeometry(0, 0, 2, 2),
    )
    patch = generate_grating_frame(config, patch_settings, bar_orientation_deg=0, frame_index=0)
    assert np.all(patch[0, 0] == 127)
    assert np.any(patch[30, 40] != 127)
    out_of_bounds_patch = replace(
        patch_settings,
        rectangular_patch_geometry=RectangularPatchGeometry(0, 0, 100, 100),
    )
    with pytest.raises(ValueError, match="exceeds the configured active screen"):
        generate_grating_frame(
            config, out_of_bounds_patch, bar_orientation_deg=0, frame_index=0
        )


@pytest.mark.parametrize("refresh_hz", [60.0, 59.82])
def test_grating_phase_uses_configured_refresh_for_frame_count_and_duration(tmp_path, refresh_hz):
    config = replace(
        small_config(tmp_path),
        display=replace(small_config(tmp_path).display, refresh_hz=refresh_hz),
    )
    settings = DriftingGratingSettings(
        orientations_deg=(0.0,),
        trials_per_orientation=1,
        stim_duration_s=0.5,
        refresh_hz=refresh_hz,
    )
    assert settings.stimulus_frame_count == 30
    assert settings.stimulus_frame_count / refresh_hz == pytest.approx(0.5 if refresh_hz == 60 else 30 / 59.82)
    row, column = 11, 17
    y_cm = ((config.display.height_px - 1) / 2 - row) * (
        config.display.physical_height_cm / config.display.height_px
    )
    for frame_index in (0, 1, 29):
        frame = generate_grating_frame(
            config, settings, bar_orientation_deg=0.0, frame_index=frame_index
        )
        phase = 2 * math.pi * settings.temporal_frequency_hz * frame_index / refresh_hz
        luminance = settings.mean_luminance * (
            1 + settings.contrast * math.sin(
                2 * math.pi * settings.spatial_frequency_cycles_per_cm * y_cm + phase
            )
        )
        assert frame[row, column, 0] == np.rint(luminance * 255)


def test_grating_cache_contact_sheet_hash_and_corruption_validation(tmp_path):
    config = small_config(tmp_path)
    settings = DriftingGratingSettings(
        orientations_deg=(0.0, 90.0), trials_per_orientation=1,
        stim_duration_s=2 / 59.82, refresh_hz=59.82,
    )
    cache = build_grating_cache(config, settings, tmp_path / "cache")
    frame = cache.read_frame("orientation_01", 0)
    assert len(frame) == 80 * 60 * 2
    preview = cache.path / "orientation_contact_sheet.png"
    assert preview.is_file()
    with Image.open(preview) as image:
        assert image.width > image.height
    key = cache.cache_key
    cache.close()
    changed = replace(settings, contrast=0.5)
    changed_cache = build_grating_cache(config, changed, tmp_path / "cache")
    assert changed_cache.cache_key != key
    changed_cache.close()
    cached_frame = next((tmp_path / "cache" / "drifting-gratings" / key / "frames").glob("*.bin"))
    with cached_frame.open("r+b") as handle:
        handle.seek(0)
        byte = handle.read(1)
        handle.seek(0)
        handle.write(bytes([byte[0] ^ 0x01]))
    with pytest.raises(FrameCacheError, match="checksum"):
        build_grating_cache(config, settings, tmp_path / "cache")


def test_grating_preview_is_hardware_free(tmp_path):
    config = small_config(tmp_path)
    settings = DriftingGratingSettings(refresh_hz=config.display.refresh_hz)
    path = write_grating_preview(config, settings, tmp_path / "gratings.png")
    assert path.is_file()
    with Image.open(path) as image:
        assert image.width == 4 * 256
        pixels = np.asarray(image)
        assert np.count_nonzero(np.all(pixels == (255, 0, 255), axis=2)) > 0


def test_retinotopy_default_and_4_direction_fixed_and_shuffled_plans():
    default = RetinotopySettings()
    assert default.enabled_directions == ("left_to_right", "top_to_bottom")
    assert [DIRECTIONS[name].sign for name in DIRECTIONS] == [1, -1, 1, -1]
    assert [(DIRECTIONS[name].start_edge, DIRECTIONS[name].end_edge) for name in DIRECTIONS] == [
        ("left", "right"), ("right", "left"), ("top", "bottom"), ("bottom", "top")
    ]
    assert default.repeats_per_direction == 20
    assert default.sequence_order_mode == "fixed"
    assert default.sweep_duration_s == 20.0 and default.inter_sweep_gray_s == 5.0
    four = RetinotopySettings(
        enabled_directions=tuple(DIRECTIONS), repeats_per_direction=2,
        sequence_order_mode="fixed", refresh_hz=59.82,
    )
    plan = build_retinotopy_plan(four)
    directions = [event.sequence_id for event in plan.events if event.kind == "retinotopy-sweep"]
    assert directions == list(DIRECTIONS) * 2
    shuffled = replace(four, sequence_order_mode="shuffled", sequence_seed=44)
    assert build_retinotopy_plan(shuffled).stable_json() == build_retinotopy_plan(shuffled).stable_json()
    assert [event.sequence_id for event in build_retinotopy_plan(shuffled).events if event.kind == "retinotopy-sweep"] == [
        "right_to_left", "left_to_right", "top_to_bottom", "bottom_to_top",
        "top_to_bottom", "left_to_right", "bottom_to_top", "right_to_left",
    ]


@pytest.mark.parametrize(
    ("direction", "first", "middle", "last"),
    [
        ("left_to_right", -8.0, 40.0, 88.0),
        ("right_to_left", 88.0, 40.0, -8.0),
        ("top_to_bottom", -6.0, 30.0, 66.0),
        ("bottom_to_top", 66.0, 30.0, -6.0),
    ],
)
def test_retinotopy_direction_positions_and_bar_polarity(tmp_path, direction, first, middle, last):
    config = small_config(tmp_path)
    settings = RetinotopySettings(
        sweep_duration_s=5 / 15,
        inter_sweep_gray_s=0.1,
        initial_gray_s=0.1,
        final_gray_s=0.1,
        enabled_directions=(direction,),
        repeats_per_direction=1,
        refresh_hz=config.display.refresh_hz,
    )
    positions = boundary_positions_px(config, settings, direction)
    assert len(positions) == 5
    assert positions[0] == first
    assert positions[2] == middle
    assert positions[-1] == last
    width = bar_width_px(config, settings, direction)
    assert width == (8 if direction in {"left_to_right", "right_to_left"} else 6)
    frame = generate_retinotopy_frame(config, settings, direction=direction, source_frame_index=2)
    axis = DIRECTIONS[direction].movement_axis
    if axis == "x":
        assert np.all(frame[:, 40 - width:40] == 0)
        assert np.all(frame[:, 40:40 + width] == 255)
    else:
        assert np.all(frame[30 - width:30] == 0)
        assert np.all(frame[30:30 + width] == 255)
    assert np.all(generate_retinotopy_frame(
        config, settings, direction=direction, source_frame_index=0
    ) == 127)
    assert np.all(generate_retinotopy_frame(
        config, settings, direction=direction, source_frame_index=4
    ) == 127)
    first_visible = generate_retinotopy_frame(
        config, settings, direction=direction, source_frame_index=1
    )
    last_visible = generate_retinotopy_frame(
        config, settings, direction=direction, source_frame_index=3
    )
    expected_leading_color = 255 if direction in {"left_to_right", "top_to_bottom"} else 0
    for visible_frame, source_index in ((first_visible, 1), (last_visible, 3)):
        boundary = round(boundary_positions_px(config, settings, direction)[source_index])
        if axis == "x":
            leading_sample = visible_frame[30, boundary if expected_leading_color == 255 else boundary - 1, 0]
            trailing_sample = visible_frame[30, boundary - 1 if expected_leading_color == 255 else boundary, 0]
        else:
            leading_sample = visible_frame[boundary if expected_leading_color == 255 else boundary - 1, 40, 0]
            trailing_sample = visible_frame[boundary - 1 if expected_leading_color == 255 else boundary, 40, 0]
        assert leading_sample == expected_leading_color
        assert trailing_sample == (0 if expected_leading_color == 255 else 255)


def test_retinotopy_59_82hz_refresh_mapping_and_complete_analysis_frame_plan(tmp_path):
    config = small_config(tmp_path)
    counts = refreshes_per_source_frame(300, 59.82, 15)
    assert set(counts) == {3, 4}
    assert counts.count(3) == 4
    assert counts.count(4) == 296
    assert sum(counts) == round(20 * 59.82)
    with pytest.raises(ValueError, match="must not be below movement rate"):
        refreshes_per_source_frame(30, 59.82, 60)
    settings = RetinotopySettings(
        sweep_duration_s=1.0,
        inter_sweep_gray_s=0.2,
        initial_gray_s=0.2,
        final_gray_s=0.2,
        enabled_directions=("left_to_right", "top_to_bottom"),
        repeats_per_direction=1,
        refresh_hz=59.82,
    )
    plan = build_retinotopy_plan(settings)
    rows = build_frame_plan_rows(config, settings, plan)
    assert len(rows) == 30
    assert {row["direction"] for row in rows} == set(settings.enabled_directions)
    assert all(row["screen_width_px"] == 80 for row in rows)
    assert all(row["active_width_cm"] == 12.0 for row in rows)
    assert all(row["eye_screen_distance_cm"] == 16.0 for row in rows)
    assert all(row["nominal_refresh_hz"] == 59.82 for row in rows)
    assert all(row["pixel_coordinate_convention"].endswith("+y down") for row in rows)
    assert all(row["screen_plane_coordinate_convention"].endswith("+y up") for row in rows)
    assert all(row["boundary_coordinate_semantics"].startswith("integer boundary") for row in rows)
    first_sweep_positions = boundary_positions_px(config, settings, "left_to_right")
    left_rows = [row for row in rows if row["direction"] == "left_to_right"]
    assert [row["nominal_boundary_position_px"] for row in left_rows] == list(first_sweep_positions)
    assert [row["boundary_position_px"] for row in left_rows] == [round(value) for value in first_sweep_positions]
    assert left_rows[7]["boundary_screen_x_cm"] == pytest.approx(0.0)
    top_rows = [row for row in rows if row["direction"] == "top_to_bottom"]
    assert top_rows[7]["boundary_screen_y_cm"] == pytest.approx(0.0)
    assert all(
        row["last_nominal_display_refresh_index"]
        == row["first_nominal_display_refresh_index"] + row["refresh_count"] - 1
        for row in rows
    )
    for sweep_rows in (
        [row for row in rows if row["sweep_index"] == sweep]
        for sweep in {row["sweep_index"] for row in rows}
    ):
        assert [row["source_frame_index"] for row in sweep_rows] == list(range(15))
        assert all(
            right["first_nominal_display_refresh_index"]
            == left["last_nominal_display_refresh_index"] + 1
            for left, right in pairwise(sweep_rows)
        )
    update_actual_kms_mapping(rows, [{
        "frame_index": rows[0]["first_nominal_display_refresh_index"],
        "kernel_event_ns": 123,
        "callback_monotonic_ns": 124,
    }])
    assert rows[0]["first_kms_kernel_event_ns"] == 123
    path = tmp_path / "retinotopy_frame_plan.csv"
    write_frame_plan(path, rows)
    with path.open(encoding="utf-8", newline="") as handle:
        loaded = list(csv.DictReader(handle))
    assert len(loaded) == len(rows)
    assert loaded[0]["boundary_visual_angle_x_deg"] != ""
    assert loaded[0]["black_visible_start_px"] != ""
    assert loaded[0]["screen_center_convention"].startswith("pixel center")


def test_screen_geometry_coordinate_sign_conventions(tmp_path):
    config = small_config(tmp_path)
    display = config.display
    center = ((display.width_px - 1) / 2, (display.height_px - 1) / 2)
    assert pixel_to_screen_cm(config, *center) == pytest.approx((0.0, 0.0))
    assert pixel_edge_to_screen_cm(
        config, display.width_px / 2, display.height_px / 2
    ) == pytest.approx((0.0, 0.0))
    left_x, left_y = pixel_to_screen_cm(config, 0, center[1])
    right_x, right_y = pixel_to_screen_cm(config, display.width_px - 1, center[1])
    top_x, top_y = pixel_to_screen_cm(config, center[0], 0)
    bottom_x, bottom_y = pixel_to_screen_cm(config, center[0], display.height_px - 1)
    assert left_x < 0 < right_x and left_y == right_y == 0
    assert top_y > 0 > bottom_y and top_x == bottom_x == 0
    left_angle, _ = screen_cm_to_visual_angle_deg(config, left_x, left_y)
    right_angle, _ = screen_cm_to_visual_angle_deg(config, right_x, right_y)
    _, top_angle = screen_cm_to_visual_angle_deg(config, top_x, top_y)
    _, bottom_angle = screen_cm_to_visual_angle_deg(config, bottom_x, bottom_y)
    assert left_angle < 0 < right_angle and bottom_angle < 0 < top_angle
    assert geometry_snapshot(config)["pixel_coordinate_convention"].endswith("+y down")


def test_retinotopy_frame_plan_maps_reverse_sweeps_to_reversed_axis_cache(tmp_path):
    config = small_config(tmp_path)
    settings = RetinotopySettings(
        sweep_duration_s=1.0,
        inter_sweep_gray_s=0.2,
        initial_gray_s=0.2,
        final_gray_s=0.2,
        enabled_directions=tuple(DIRECTIONS),
        repeats_per_direction=1,
        refresh_hz=59.82,
    )
    rows = build_frame_plan_rows(config, settings, build_retinotopy_plan(settings))
    source_count = 15
    by_direction = {
        direction: [row for row in rows if row["direction"] == direction]
        for direction in DIRECTIONS
    }
    for direction, direction_rows in by_direction.items():
        expected = (
            list(range(source_count - 1, -1, -1))
            if DIRECTIONS[direction].sign < 0
            else list(range(source_count))
        )
        assert [row["cache_frame_index"] for row in direction_rows] == expected


def test_retinotopy_cache_and_labeled_preview(tmp_path):
    config = small_config(tmp_path)
    settings = RetinotopySettings(
        sweep_duration_s=2 / 15,
        inter_sweep_gray_s=0.1,
        initial_gray_s=0.1,
        final_gray_s=0.1,
        enabled_directions=("left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"),
        repeats_per_direction=1,
        refresh_hz=59.82,
    )
    cache = build_retinotopy_cache(config, settings, tmp_path / "cache")
    for direction in settings.enabled_directions:
        axis = DIRECTIONS[direction].movement_axis
        assert len(cache.read_frame(axis, 1)) == 80 * 60 * 2
    cache.close()
    path = write_retinotopy_preview(config, settings, tmp_path / "retinotopy.png")
    with Image.open(path) as image:
        assert image.width == 3 * 320
        assert image.height >= 2 * 100


def test_protocol_toml_defaults_match_legacy_and_can_be_seed_overridden():
    root = Path(__file__).parents[2]
    config = Config()
    grating = load_protocol_settings(
        "drifting-gratings", root / "config/protocols/drifting_gratings.example.toml",
        refresh_hz=59.82,
    )
    retino = load_protocol_settings(
        "retinotopy", root / "config/protocols/retinotopy.example.toml",
        refresh_hz=59.82,
    )
    smoke = load_protocol_settings(
        "retinotopy", root / "config/protocols/retinotopy.smoke.toml",
        refresh_hz=config.display.refresh_hz,
        seed=11,
    )
    assert grating.trials_per_orientation == 80 and grating.sequence_seed == 20261018
    assert retino.repeats_per_direction == 20 and retino.enabled_directions == (
        "left_to_right", "top_to_bottom"
    )
    assert smoke.repeats_per_direction == 1 and smoke.sequence_seed == 11


def test_fake_display_simulated_grating_session_and_failure_cleanup(tmp_path):
    config = small_config(tmp_path)
    settings = DriftingGratingSettings(
        orientations_deg=(0.0, 90.0), trials_per_orientation=1,
        stim_duration_s=2 / 59.82,
        iti_base_s=1 / 59.82,
        iti_jitter_max_s=0.0,
        initial_gray_s=1 / 59.82,
        final_gray_s=1 / 59.82,
        refresh_hz=59.82,
    )
    cache = build_grating_cache(config, settings, tmp_path / "cache")
    cache.close()
    result = run_visual_mapping(
        config,
        protocol_name="drifting-gratings",
        settings=settings,
        session_id="fake-gratings",
        seed=settings.sequence_seed,
        cache_root=tmp_path / "cache",
        simulate=True,
    )
    assert result.ok
    event_rows = [json.loads(line) for line in (result.session_root / "events.jsonl").read_text().splitlines()]
    names = [item["event"] for item in event_rows]
    assert names.index("SESSION_START") < names.index("DISPLAY_ACQUIRE_REQUEST")
    assert names.index("DISPLAY_ACQUIRE_REQUEST") < names.index("STIMULUS_PRESENTATION_START")
    assert names.index("STIMULUS_PRESENTATION_END") < names.index("SESSION_END")
    plan = json.loads((result.session_root / "plan.json").read_text())
    assert plan["metadata"]["render_cache_key"]
    inspection = inspect_session(result.session_root)
    assert inspection["status"] == "COMPLETE"
    assert inspection["missing_required_files"] == []
    assert inspection["corrupt_artifacts"] == []

    class FailingDisplay:
        closed = False

        def open(self, _config):
            return None

        def present_sequence(self, _frames):
            raise RuntimeError("injected fake display failure")

        def close(self):
            self.closed = True

    failing = FailingDisplay()
    failed = run_visual_mapping(
        config,
        protocol_name="drifting-gratings",
        settings=settings,
        session_id="fake-gratings-failure",
        seed=settings.sequence_seed,
        cache_root=tmp_path / "cache",
        simulate=True,
        display_factory=lambda: failing,
    )
    assert not failed.ok
    assert failing.closed
    assert json.loads((failed.session_root / "final_status.json").read_text())["status"] == "FAILED"

    class InterruptedDisplay(FailingDisplay):
        def present_sequence(self, _frames):
            raise KeyboardInterrupt

    interrupted_display = InterruptedDisplay()
    interrupted = run_visual_mapping(
        config,
        protocol_name="drifting-gratings",
        settings=settings,
        session_id="fake-gratings-interrupted",
        seed=settings.sequence_seed,
        cache_root=tmp_path / "cache",
        simulate=True,
        display_factory=lambda: interrupted_display,
    )
    assert interrupted.status == "INTERRUPTED"
    assert interrupted_display.closed
    assert json.loads(
        (interrupted.session_root / "final_status.json").read_text()
    )["status"] == "INTERRUPTED"


def test_missing_visual_mapping_cache_fails_before_session_creation(tmp_path):
    config = small_config(tmp_path)
    settings = DriftingGratingSettings(
        orientations_deg=(0.0,), trials_per_orientation=1, refresh_hz=59.82
    )
    with pytest.raises(FrameCacheError, match="cache"):
        run_visual_mapping(
            config,
            protocol_name="drifting-gratings",
            settings=settings,
            session_id="missing-cache",
            seed=settings.sequence_seed,
            cache_root=tmp_path / "missing-cache-root",
            simulate=True,
        )
    assert not (tmp_path / "sessions" / "missing-cache").exists()


def test_visual_mapping_rejects_protocol_refresh_mismatch_before_cache_access(tmp_path):
    config = small_config(tmp_path)
    settings = DriftingGratingSettings(
        orientations_deg=(0.0,), trials_per_orientation=1, refresh_hz=60.0
    )
    with pytest.raises(ValueError, match="protocol refresh_hz .* must match configured display"):
        run_visual_mapping(
            config,
            protocol_name="drifting-gratings",
            settings=settings,
            session_id="refresh-mismatch",
            seed=settings.sequence_seed,
            cache_root=tmp_path / "no-cache-required-to-fail",
            simulate=True,
        )
    assert not (tmp_path / "sessions" / "refresh-mismatch").exists()


def test_simulated_retinotopy_session_writes_frame_plan(tmp_path):
    config = small_config(tmp_path)
    settings = RetinotopySettings(
        sweep_duration_s=2 / 15,
        inter_sweep_gray_s=1 / 59.82,
        initial_gray_s=1 / 59.82,
        final_gray_s=1 / 59.82,
        enabled_directions=("left_to_right", "top_to_bottom"),
        repeats_per_direction=1,
        refresh_hz=59.82,
    )
    cache = build_retinotopy_cache(config, settings, tmp_path / "cache")
    cache.close()
    result = run_visual_mapping(
        config,
        protocol_name="retinotopy",
        settings=settings,
        session_id="fake-retinotopy",
        seed=settings.sequence_seed,
        cache_root=tmp_path / "cache",
        simulate=True,
    )
    assert result.ok
    rows = list(csv.DictReader((result.session_root / "retinotopy_frame_plan.csv").open()))
    assert len(rows) == 4
    assert {row["direction"] for row in rows} == {"left_to_right", "top_to_bottom"}
    assert all(row["render_cache_key"] and row["cache_sha256"] for row in rows)
    assert json.loads((result.session_root / "screen_geometry.json").read_text())["eye_screen_distance_cm"] == 16.0
