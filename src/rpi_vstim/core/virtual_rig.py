"""Virtual-rig composition using the production lifecycle boundaries."""

from __future__ import annotations

import sys
import struct
import zlib
from dataclasses import replace
from pathlib import Path

from rpi_vstim.camera.supervisor import CameraCaptureSpec, LocalCameraSupervisor
from rpi_vstim.core.camera import CameraState
from rpi_vstim.core.config import Config
from rpi_vstim.core.lifecycle import RuntimeServices
from rpi_vstim.core.runtime import SimulationResult, run_simulated_session
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.display.transport import (
    DisplaySequenceFrame,
    DisplaySequenceMetadata,
    InMemoryDisplaySequenceAdapter,
)
from rpi_vstim.hardware.worker import SimulatedHardwareWorker
from rpi_vstim.telemetry.publisher import InMemoryTelemetryPublisher


class VirtualDisplayBackend(FakeDisplayBackend):
    """Fake display that also exercises bounded sequence ownership/acknowledgement."""

    def __init__(self, capacity: int = 2, *, fault: str | None = None) -> None:
        super().__init__()
        self.sequence = InMemoryDisplaySequenceAdapter(capacity)
        self._producer_sequence = 0
        self.fault = fault
        self._present_count = 0

    def open(self, config):
        if self.fault == "display_consumer_start":
            raise RuntimeError("injected display consumer startup failure")
        return super().open(config)

    def present(self, program, *, sequence_id: str):
        if self.fault == "display_consumer_mid" and self._present_count >= 1:
            raise RuntimeError("injected display consumer mid-session failure")
        for frame_index in range(program.frame_count):
            payload = bytes((frame_index % 256,))
            self.sequence.publish(
                DisplaySequenceFrame(
                    DisplaySequenceMetadata(
                        frame_index,
                        sequence_id,
                        sequence_id,
                        sequence_id,
                        "on",
                        len(payload),
                        self._producer_sequence,
                    ),
                    payload,
                )
            )
            lease = self.sequence.consume(timeout_s=1)
            if lease is None:
                raise RuntimeError("virtual display sequence ended unexpectedly")
            lease.acknowledge()
            self._producer_sequence += 1
        self._present_count += 1
        return super().present(program, sequence_id=sequence_id)

    def close(self) -> None:
        self.sequence.finish()
        super().close()
        if self.fault == "cleanup":
            raise RuntimeError("injected display cleanup failure")


class VirtualCameraService:
    """Real subprocess fake-camera service behind the runtime camera boundary."""

    def __init__(self, config: Config, *, mode: str = "normal", fail_ids: set[str] | None = None) -> None:
        self.config = config
        self.mode = mode
        self.fail_ids = fail_ids or set()
        self.supervisor: LocalCameraSupervisor | None = None

    @property
    def degraded(self) -> bool:
        return bool(
            self.supervisor
            and any(status.state == CameraState.DEGRADED for status in self.supervisor.poll())
        )

    def start(self, session_root: Path) -> None:
        emulator = Path(__file__).parents[1] / "tools" / "fake_camera.py"
        specs = []
        for device in self.config.cameras.devices:
            output = session_root / "camera" / device.id / f"capture.{device.output_extension}"
            mode = "fail" if device.id in self.fail_ids else self.mode
            specs.append(
                CameraCaptureSpec(
                    device.id,
                    device.role,
                    device.stable_device_identifier,
                    device.required,
                    "virtual-subprocess",
                    (
                        sys.executable,
                        str(emulator),
                        "--output",
                        str(output),
                        "--mode",
                        mode,
                    ),
                    output_extension=device.output_extension,
                    startup_timeout_s=device.startup_timeout_s,
                    stop_timeout_s=device.stop_timeout_s,
                    stall_timeout_s=device.stall_timeout_s,
                )
            )
        self.supervisor = LocalCameraSupervisor(specs, verify_output_growth=self.config.cameras.verify_output_growth)
        self.supervisor.start(session_root)

    def stop(self) -> None:
        if self.supervisor is not None:
            self.supervisor.stop()

    def manifest(self) -> list[dict[str, object]]:
        return self.supervisor.manifest() if self.supervisor is not None else []


def run_virtual_session(
    config: Config,
    *,
    protocol_name: str,
    session_id: str,
    seed: int = 0,
    camera_mode: str = "normal",
    camera_failures: set[str] | None = None,
    interrupt: bool = False,
    fault: str | None = None,
) -> SimulationResult:
    output_root = config.paths.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    config = replace(config, paths=replace(config.paths, asset_root=output_root / ".virtual-assets"))
    asset_root = config.paths.asset_root
    _write_virtual_assets(asset_root, protocol_name)
    display = VirtualDisplayBackend(fault=fault)
    cameras = VirtualCameraService(config, mode=camera_mode, fail_ids=camera_failures)
    services = RuntimeServices(
        display=display,
        hardware=SimulatedHardwareWorker(),
        cameras=cameras,
        telemetry=InMemoryTelemetryPublisher(),
    )
    return run_simulated_session(
        config,
        protocol_name=protocol_name,
        session_id=session_id,
        seed=seed,
        camera_failures=(),
        interrupt=interrupt,
        services=services,
        fault=fault,
    )


def _write_virtual_assets(root: Path, protocol_name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    prefix = "reward_image_" if protocol_name == "reward-conditioning" else "natural_image_"
    width = 2 if protocol_name == "reward-conditioning" else 4
    for index in range(14):
        path = root / f"{prefix}{index:0{width}d}.png"
        if not path.exists():
            path.write_bytes(_png_bytes((index * 17 % 256, 127, 255 - index * 17 % 256)))


def _png_bytes(rgb: tuple[int, int, int]) -> bytes:
    raw = b"\x00" + bytes(rgb) * 2 + b"\x00" + bytes(rgb) * 2

    def chunk(kind: bytes, value: bytes) -> bytes:
        body = kind + value
        return struct.pack(">I", len(value)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
