import pytest

from rpi_vstim.core.resource_budget import ResourceBudgetInputs, estimate_budget


def test_resource_budget_is_parameterized_and_bounded():
    budget = estimate_budget(
        ResourceBudgetInputs(
            width_px=1024,
            height_px=600,
            pixel_format="RGB565",
            prepared_cache_frames=8,
            natural_source_cache_frames=2,
            frame_transport_capacity=4,
            camera_count=2,
            camera_queue_bytes_per_camera=1024,
            camera_bitrate_bps=(8_000_000, 12_000_000),
        )
    )
    assert budget.scanout_bytes == 2_457_600
    assert budget.camera_storage_bytes_per_second == 2_500_000
    assert budget.estimated_ram_bytes == sum(budget.as_dict()[name] for name in (
        "scanout_bytes",
        "prepared_cache_bytes",
        "natural_source_cache_bytes",
        "frame_transport_queue_bytes",
        "camera_queue_bytes",
        "asset_manifest_bytes",
        "status_queue_bytes",
        "telemetry_buffer_bytes",
        "log_buffer_bytes",
    ))


def test_resource_budget_rejects_invalid_values():
    with pytest.raises(ValueError, match="dimensions"):
        estimate_budget(ResourceBudgetInputs(0, 600, "RGB565"))
    with pytest.raises(ValueError, match="unsupported"):
        estimate_budget(ResourceBudgetInputs(1, 1, "RGBA"))
