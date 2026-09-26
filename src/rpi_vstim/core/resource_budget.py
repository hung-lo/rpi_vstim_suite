"""Transparent, parameterized memory/storage estimates for bounded components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceBudgetInputs:
    width_px: int
    height_px: int
    pixel_format: str
    prepared_cache_frames: int = 8
    natural_source_cache_frames: int = 8
    camera_queue_bytes_per_camera: int = 0
    camera_bitrate_bps: tuple[int, ...] = ()
    telemetry_buffer_packets: int = 256
    telemetry_packet_bytes: int = 4096
    log_buffer_bytes: int = 1 << 20


@dataclass(frozen=True)
class ResourceBudget:
    scanout_bytes: int
    prepared_cache_bytes: int
    natural_source_cache_bytes: int
    camera_queue_bytes: int
    telemetry_buffer_bytes: int
    log_buffer_bytes: int
    estimated_ram_bytes: int
    camera_storage_bytes_per_second: int

    def as_dict(self) -> dict[str, int]:
        return {
            "scanout_bytes": self.scanout_bytes,
            "prepared_cache_bytes": self.prepared_cache_bytes,
            "natural_source_cache_bytes": self.natural_source_cache_bytes,
            "camera_queue_bytes": self.camera_queue_bytes,
            "telemetry_buffer_bytes": self.telemetry_buffer_bytes,
            "log_buffer_bytes": self.log_buffer_bytes,
            "estimated_ram_bytes": self.estimated_ram_bytes,
            "camera_storage_bytes_per_second": self.camera_storage_bytes_per_second,
        }


def estimate_budget(inputs: ResourceBudgetInputs) -> ResourceBudget:
    if inputs.width_px <= 0 or inputs.height_px <= 0:
        raise ValueError("display dimensions must be positive")
    if inputs.pixel_format not in {"RGB565", "XRGB8888"}:
        raise ValueError("unsupported pixel format")
    if min(
        inputs.prepared_cache_frames,
        inputs.natural_source_cache_frames,
        inputs.camera_queue_bytes_per_camera,
        inputs.telemetry_buffer_packets,
        inputs.telemetry_packet_bytes,
        inputs.log_buffer_bytes,
    ) < 0:
        raise ValueError("resource limits must be non-negative")
    bytes_per_pixel = 2 if inputs.pixel_format == "RGB565" else 4
    scanout = inputs.width_px * inputs.height_px * bytes_per_pixel * 2
    prepared = scanout // 2 * inputs.prepared_cache_frames
    natural_source = inputs.width_px * inputs.height_px * 3 * inputs.natural_source_cache_frames
    camera_queue = inputs.camera_queue_bytes_per_camera * len(inputs.camera_bitrate_bps)
    telemetry = inputs.telemetry_buffer_packets * inputs.telemetry_packet_bytes
    total = scanout + prepared + natural_source + camera_queue + telemetry + inputs.log_buffer_bytes
    return ResourceBudget(
        scanout,
        prepared,
        natural_source,
        camera_queue,
        telemetry,
        inputs.log_buffer_bytes,
        total,
        sum(inputs.camera_bitrate_bps) // 8,
    )
