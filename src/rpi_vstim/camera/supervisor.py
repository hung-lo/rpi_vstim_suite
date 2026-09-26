"""Bounded local camera-worker supervision without device access at import time."""

from __future__ import annotations

import subprocess
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Sequence

from rpi_vstim.camera.identity import ResolvedCamera
from rpi_vstim.core.camera import CameraState
from rpi_vstim.core.timestamps import monotonic_ns, utc_ns


class CameraSupervisorError(RuntimeError):
    pass


class CameraStartupError(CameraSupervisorError):
    pass


class BoundedCameraStatusChannel:
    """Drop oldest status records when a slow parent exceeds bounded capacity."""

    def __init__(self, capacity: int = 64) -> None:
        if capacity <= 0:
            raise ValueError("camera status capacity must be positive")
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)
        self.capacity = capacity
        self.dropped = 0

    def publish(self, value: dict[str, Any]) -> None:
        if len(self._items) == self.capacity:
            self.dropped += 1
        self._items.append(value)

    def drain(self) -> tuple[dict[str, Any], ...]:
        values = tuple(self._items)
        self._items.clear()
        return values


@dataclass(frozen=True)
class CameraCaptureSpec:
    camera_id: str
    role: str
    stable_device_identifier: str
    required: bool
    backend: str
    command: tuple[str, ...]
    output_extension: str = "h264"
    output_naming_policy: str = "capture"
    requested_width_px: int | None = None
    requested_height_px: int | None = None
    requested_fps: float | None = None
    pixel_format_or_codec: str = ""
    startup_timeout_s: float = 5.0
    stop_timeout_s: float = 5.0
    stall_timeout_s: float | None = 30.0
    max_diagnostic_bytes: int = 64 * 1024
    resolved_camera: ResolvedCamera | None = None


@dataclass
class CameraWorkerStatus:
    camera_id: str
    role: str
    stable_device_identifier: str
    backend: str
    required: bool
    runtime_selector: str = ""
    topology: str = ""
    family: str = ""
    requested_width_px: int | None = None
    requested_height_px: int | None = None
    requested_fps: float | None = None
    pixel_format_or_codec: str = ""
    negotiated_mode: str = ""
    state: CameraState = CameraState.CONFIGURED
    output_path: str = ""
    start_utc_ns: int | None = None
    start_monotonic_ns: int | None = None
    stop_utc_ns: int | None = None
    stop_monotonic_ns: int | None = None
    bytes_written: int = 0
    reported_frames: int | None = None
    dropped_frames: int | None = None
    exit_status: int | None = None
    exit_reason: str | None = None
    verification_state: str = "not_checked"
    diagnostic_log_path: str = ""
    last_growth_monotonic_ns: int | None = None
    last_growth_bytes: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value


PopenFactory = Callable[..., Any]


def build_rpicam_command(
    spec: CameraCaptureSpec,
    output_path: Path,
    *,
    resolved_camera: ResolvedCamera,
) -> tuple[str, ...]:
    """Build a future rpicam command after stable identity resolution.

    Identity resolution is deliberately separate: this command does not guess
    a transient `/dev/videoN` or camera index.
    """
    command = [
        "rpicam-vid",
        "--camera",
        resolved_camera.runtime_selector,
        "--no-raw",
        "--nopreview",
        "--output",
        str(output_path),
    ]
    if spec.requested_width_px is not None:
        command.extend(("--width", str(spec.requested_width_px)))
    if spec.requested_height_px is not None:
        command.extend(("--height", str(spec.requested_height_px)))
    if spec.requested_fps is not None:
        command.extend(("--framerate", f"{spec.requested_fps:g}"))
    if spec.pixel_format_or_codec:
        command.extend(("--codec", spec.pixel_format_or_codec))
    return tuple(command)


class _CameraWorker:
    def __init__(
        self,
        spec: CameraCaptureSpec,
        output_path: Path,
        *,
        popen_factory: PopenFactory,
        status_channel: BoundedCameraStatusChannel,
        verify_output_growth: bool,
        diagnostic_path: Path,
    ) -> None:
        self.spec = spec
        self.output_path = output_path
        self._popen_factory = popen_factory
        self._status_channel = status_channel
        self._verify_output_growth = verify_output_growth
        self.diagnostic_path = diagnostic_path
        self.process: Any | None = None
        self._stderr_thread: Thread | None = None
        self._stderr_chunks: deque[bytes] = deque()
        self._stderr_bytes = 0
        self._stopped = False
        self._last_observed_bytes: int | None = None
        self.status = CameraWorkerStatus(
            camera_id=spec.camera_id,
            role=spec.role,
            stable_device_identifier=spec.stable_device_identifier,
            backend=spec.backend,
            required=spec.required,
            runtime_selector=(spec.resolved_camera.runtime_selector if spec.resolved_camera else ""),
            topology=spec.resolved_camera.topology if spec.resolved_camera else "",
            family=spec.resolved_camera.family if spec.resolved_camera else "",
            requested_width_px=spec.requested_width_px,
            requested_height_px=spec.requested_height_px,
            requested_fps=spec.requested_fps,
            pixel_format_or_codec=spec.pixel_format_or_codec,
            output_path=str(output_path),
            diagnostic_log_path=str(diagnostic_path),
        )

    def _publish(self, event: str, detail: str = "") -> None:
        self._status_channel.publish(
            {
                "camera_id": self.spec.camera_id,
                "event": event,
                "state": self.status.state.value,
                "detail": detail,
                "timestamp_utc_ns": utc_ns(),
                "timestamp_monotonic_ns": monotonic_ns(),
            }
        )

    def start(self) -> None:
        if self.process is not None and not self._stopped:
            raise CameraStartupError(f"camera already started: {self.spec.camera_id}")
        if not self.spec.stable_device_identifier and self.spec.required:
            raise CameraStartupError(f"required camera lacks stable identity: {self.spec.camera_id}")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.output_path.exists():
            raise CameraStartupError(f"camera output already exists: {self.output_path}")
        self.status.start_utc_ns = utc_ns()
        self.status.start_monotonic_ns = monotonic_ns()
        try:
            self.process = self._popen_factory(
                self.spec.command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self._fail(f"camera process failed to start: {exc}")
            raise CameraStartupError(self.spec.camera_id) from exc
        if self.process.poll() is not None:
            self._fail(f"camera process exited during startup: {self.process.returncode}")
            raise CameraStartupError(self.spec.camera_id)
        self.status.state = CameraState.RECORDING
        self._start_stderr_capture()
        self._publish("CAMERA_STARTED")
        if (
            self._verify_output_growth
            and not self._wait_for_output_growth(self.spec.startup_timeout_s)
        ):
            self._fail("camera output did not appear or grow before startup timeout")
            self._terminate(force=True)
            self._reap(self.spec.stop_timeout_s)
            raise CameraStartupError(self.spec.camera_id)
        self._refresh_bytes()

    def _wait_for_output_growth(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                return False
            self._refresh_bytes()
            if self.status.bytes_written > 0:
                return True
            time.sleep(0.01)
        return False

    def poll(self) -> CameraWorkerStatus:
        if self.process is not None and self.status.state == CameraState.RECORDING:
            exit_status = self.process.poll()
            if exit_status is not None:
                self.status.exit_status = int(exit_status)
                self._fail(f"camera process exited during recording: {exit_status}")
        self._refresh_bytes()
        if self._stalled():
            self._fail("camera output stalled before the configured deadline")
            self._terminate(force=False)
            if self.process is not None and self.process.poll() is None:
                self._terminate(force=True)
        return self.status

    def stop(self) -> CameraWorkerStatus:
        if self._stopped:
            return self.status
        if self.process is None:
            self._stopped = True
            self._write_diagnostic()
            return self.status
        graceful_exit = False
        if self.status.state == CameraState.RECORDING:
            self._publish("CAMERA_STOP_REQUESTED")
        if self.process.poll() is None:
            graceful_exit = self._terminate(force=False)
        if self.process.poll() is None:
            self._terminate(force=True)
        self._reap(self.spec.stop_timeout_s)
        if self.process.poll() is None:
            self.status.exit_reason = "camera process remained alive after kill"
            self._fail("camera process remained alive after kill")
        elif self.status.exit_status is None:
            self.status.exit_status = int(self.process.poll())
        if self.status.state == CameraState.RECORDING:
            if graceful_exit:
                self.status.state = CameraState.COMPLETED
                self.status.exit_reason = self.status.exit_reason or "graceful_stop"
            elif self.status.exit_status == 0:
                self.status.state = CameraState.COMPLETED
            else:
                self._fail(f"camera exited with status {self.status.exit_status}")
        self.status.stop_utc_ns = utc_ns()
        self.status.stop_monotonic_ns = monotonic_ns()
        self._refresh_bytes()
        self.status.verification_state = self._verification_state()
        self._write_diagnostic()
        self._stopped = True
        self._publish("CAMERA_STOPPED")
        return self.status

    def _terminate(self, *, force: bool) -> bool:
        if self.process is None or self.process.poll() is not None:
            return self.process is not None
        if force:
            try:
                self.process.kill()
            except OSError as exc:
                self._fail(f"camera kill failed: {exc}")
                return False
            self.status.exit_reason = "forced_kill_after_stop_timeout"
            return False
        try:
            self.process.terminate()
        except OSError as exc:
            self._fail(f"camera terminate failed: {exc}")
            return False
        if not self._reap(self.spec.stop_timeout_s):
            self.status.exit_reason = "stop_timeout"
            return False
        return True

    def _reap(self, timeout_s: float) -> bool:
        if self.process is None:
            return True
        if self.process.poll() is not None:
            self.status.exit_status = int(self.process.poll())
            return True
        try:
            result = self.process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False
        if result is not None:
            self.status.exit_status = int(result)
        else:
            result = self.process.poll()
            if result is not None:
                self.status.exit_status = int(result)
        return self.process.poll() is not None

    def _fail(self, detail: str) -> None:
        self.status.state = CameraState.FAILED if self.spec.required else CameraState.DEGRADED
        self.status.error = detail
        if self.status.exit_reason is None:
            self.status.exit_reason = detail
        self._publish("CAMERA_FAILED", detail)

    def _refresh_bytes(self) -> None:
        try:
            bytes_written = self.output_path.stat().st_size
        except OSError:
            bytes_written = 0
        now = monotonic_ns()
        if self._last_observed_bytes is None or bytes_written > self._last_observed_bytes:
            self.status.last_growth_monotonic_ns = now
            self.status.last_growth_bytes = bytes_written
        self._last_observed_bytes = bytes_written
        self.status.bytes_written = bytes_written

    def _stalled(self) -> bool:
        timeout = self.spec.stall_timeout_s
        return bool(
            timeout is not None
            and self.status.state == CameraState.RECORDING
            and self.status.last_growth_monotonic_ns is not None
            and monotonic_ns() - self.status.last_growth_monotonic_ns
            > int(timeout * 1_000_000_000)
        )

    def _verification_state(self) -> str:
        if self.status.state == CameraState.COMPLETED:
            return "recorded" if self.status.bytes_written > 0 else "recorded_unverified"
        if self.status.bytes_written > 0:
            return "output_nonempty_failed"
        return "recording_failed"

    def _start_stderr_capture(self) -> None:
        stream = getattr(self.process, "stderr", None)
        if stream is None or not hasattr(stream, "read"):
            return
        self._stderr_thread = Thread(target=self._capture_stderr, args=(stream,), daemon=True)
        self._stderr_thread.start()

    def _capture_stderr(self, stream: Any) -> None:
        remaining = self.spec.max_diagnostic_bytes
        while remaining > 0:
            chunk = stream.read(min(4096, remaining))
            if not chunk:
                return
            if isinstance(chunk, str):
                chunk = chunk.encode(errors="replace")
            self._stderr_chunks.append(bytes(chunk))
            self._stderr_bytes += len(chunk)
            remaining -= len(chunk)

    def _write_diagnostic(self) -> None:
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=self.spec.stop_timeout_s)
        if not self._stderr_chunks:
            return
        self.diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        self.diagnostic_path.write_bytes(b"".join(self._stderr_chunks)[-self.spec.max_diagnostic_bytes :])


class LocalCameraSupervisor:
    """Supervise one bounded local process per configured camera."""

    def __init__(
        self,
        specs: Sequence[CameraCaptureSpec],
        *,
        session_root: Path | None = None,
        popen_factory: PopenFactory = subprocess.Popen,
        status_capacity: int = 64,
        verify_output_growth: bool = True,
    ) -> None:
        ids = [spec.camera_id for spec in specs]
        if len(ids) != len(set(ids)):
            raise ValueError("camera IDs must be unique")
        self.specs = tuple(specs)
        self.session_root = session_root
        self._popen_factory = popen_factory
        self._verify_output_growth = verify_output_growth
        self.status_channel = BoundedCameraStatusChannel(status_capacity)
        self._workers: dict[str, _CameraWorker] = {}
        self._active = False

    def start(self, session_root: Path | None = None) -> None:
        if self._active:
            raise RuntimeError("camera supervisor is already active")
        self.session_root = session_root or self.session_root
        if self.session_root is None:
            raise ValueError("session_root is required")
        started: list[_CameraWorker] = []
        for spec in self.specs:
            output = (
                self.session_root
                / "camera"
                / spec.camera_id
                / f"capture.{spec.output_extension}"
            )
            diagnostic = output.with_name("stderr.log")
            worker = _CameraWorker(
                spec,
                output,
                popen_factory=self._popen_factory,
                status_channel=self.status_channel,
                verify_output_growth=self._verify_output_growth,
                diagnostic_path=diagnostic,
            )
            worker.status.output_path = str(output.relative_to(self.session_root))
            worker.status.diagnostic_log_path = str(diagnostic.relative_to(self.session_root))
            self._workers[spec.camera_id] = worker
            try:
                worker.start()
                started.append(worker)
            except CameraStartupError:
                if spec.required:
                    for previous in started:
                        previous.stop()
                    self._write_manifest()
                    self._active = False
                    raise
        self._active = True
        self._write_manifest()

    def poll(self) -> tuple[CameraWorkerStatus, ...]:
        return tuple(worker.poll() for worker in self._workers.values())

    def stop(self) -> tuple[CameraWorkerStatus, ...]:
        statuses = tuple(worker.stop() for worker in self._workers.values())
        self._active = False
        self._write_manifest()
        return statuses

    def manifest(self) -> list[dict[str, Any]]:
        return [worker.status.as_dict() for worker in self._workers.values()]

    def drain_status(self) -> tuple[dict[str, Any], ...]:
        return self.status_channel.drain()

    def _write_manifest(self) -> None:
        if self.session_root is None:
            return
        from rpi_vstim.core.session import atomic_write_json

        atomic_write_json(
            self.session_root / "camera_manifest.json",
            {
                "schema_version": 1,
                "cameras": self.manifest(),
                "status_queue_dropped": self.status_channel.dropped,
            },
        )
