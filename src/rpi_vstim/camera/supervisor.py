"""Bounded local camera-worker supervision without device access at import time."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from threading import Thread
from typing import Any

from rpi_vstim.camera.identity import ResolvedCamera
from rpi_vstim.core.camera import CameraState
from rpi_vstim.core.timestamps import monotonic_ns, utc_ns


class CameraSupervisorError(RuntimeError):
    pass


class CameraStartupError(CameraSupervisorError):
    pass


def probe_camera_output(
    path: Path | str,
    *,
    count_frames: bool = False,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Read container metadata, optionally counting frames for offline QC."""
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
    command.extend(
        (
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,time_base,start_time,duration,nb_read_frames:format=format_name,start_time,duration,size",
            "-of",
            "json",
            str(path),
        )
    )
    try:
        result = subprocess.run(
            tuple(command),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CameraSupervisorError(f"ffprobe failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"ffprobe exited {result.returncode}"
        raise CameraSupervisorError(detail)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CameraSupervisorError(f"ffprobe returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CameraSupervisorError("ffprobe returned invalid metadata")
    return payload


def verify_camera_output(
    path: Path | str,
    *,
    expected: Mapping[str, Any] | None = None,
    camera_start_monotonic_ns: int | None = None,
    camera_ready_monotonic_ns: int | None = None,
    camera_stop_monotonic_ns: int | None = None,
    scientific_interval_monotonic_ns: tuple[int, int] | None = None,
    coverage_timing_source: str | None = None,
    timeout_s: float = 5.0,
    min_size_bytes: int = 1024,
) -> dict[str, Any]:
    """Perform bounded, metadata-only production checks on a recording."""
    # shortcut: frame-level integrity requires the explicit offline deep-QC path.
    path = Path(path)
    result: dict[str, Any] = {
        "ok": False,
        "verification_method": "ffprobe_stream_metadata",
        "verification_error": None,
        "file_size_bytes": 0,
        "codec_name": None,
        "width_px": None,
        "height_px": None,
        "media_duration_s": None,
        "media_start_time_s": None,
        "media_end_time_s": None,
        "metadata_avg_fps": None,
        "scientific_interval_covered": None,
        "coverage_timing_source": coverage_timing_source,
    }
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        result["verification_error"] = f"recording file is unavailable: {exc}"
        return result
    result["file_size_bytes"] = file_size
    if file_size < min_size_bytes:
        result["verification_error"] = f"recording is too small ({file_size} bytes)"
        return result
    try:
        payload = probe_camera_output(path, timeout_s=timeout_s)
    except CameraSupervisorError as exc:
        result["verification_error"] = str(exc)
        return result

    streams = payload.get("streams")
    formats = payload.get("format")
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        result["verification_error"] = "container has no video stream"
        return result
    stream = streams[0]
    container = formats if isinstance(formats, dict) else {}
    codec = str(stream.get("codec_name") or "").lower()
    width = stream.get("width")
    height = stream.get("height")
    format_name = str(container.get("format_name") or "").lower()
    result.update(codec_name=codec or None, width_px=width, height_px=height)
    if path.suffix.lower() == ".mp4" and not any(name in format_name for name in ("mp4", "mov")):
        result["verification_error"] = f"unexpected MP4 container metadata: {format_name or 'missing'}"
        return result
    checks = (
        (expected.get("codec") if expected else None, codec, "codec"),
        (expected.get("width_px") if expected else None, width, "width"),
        (expected.get("height_px") if expected else None, height, "height"),
    )
    for wanted, actual, name in checks:
        if wanted is not None and str(wanted).lower() != str(actual).lower():
            result["verification_error"] = f"recording {name} {actual!r} does not match requested {wanted!r}"
            return result
    duration_s = None
    for value in (stream.get("duration"), container.get("duration")):
        try:
            duration_s = float(value)
            break
        except (TypeError, ValueError):
            continue
    start_s = None
    for value in (stream.get("start_time"), container.get("start_time")):
        try:
            start_s = float(value)
            break
        except (TypeError, ValueError):
            continue
    try:
        time_base = Fraction(str(stream.get("time_base")))
    except (ValueError, ZeroDivisionError):
        time_base = Fraction(0)
    if duration_s is None or start_s is None:
        result["verification_error"] = "container duration or start timestamp is unavailable"
        return result
    if duration_s <= 0 or time_base <= 0:
        result["verification_error"] = "container duration or stream time base is invalid"
        return result
    result.update(
        media_duration_s=duration_s,
        media_start_time_s=start_s,
        media_end_time_s=start_s + duration_s,
    )
    rate = 0.0
    for rate_value in (stream.get("avg_frame_rate"), stream.get("r_frame_rate")):
        try:
            rate = float(Fraction(str(rate_value)))
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            break
    result["metadata_avg_fps"] = rate or None
    requested_fps = expected.get("fps") if expected else None
    if requested_fps is not None and (rate <= 0 or abs(rate - float(requested_fps)) > float(requested_fps) * 0.1):
        result["verification_error"] = f"recording frame rate {rate:g} is not sensible for requested {requested_fps:g} fps"
        return result

    if camera_start_monotonic_ns is not None and camera_stop_monotonic_ns is not None:
        camera_runtime_s = (camera_stop_monotonic_ns - camera_start_monotonic_ns) / 1_000_000_000
        if abs(duration_s - camera_runtime_s) > 5.0:
            result["verification_error"] = "media duration is inconsistent with the camera process lifecycle"
            return result

    if scientific_interval_monotonic_ns is not None:
        interval_start_ns, interval_end_ns = scientific_interval_monotonic_ns
        interval_s = (interval_end_ns - interval_start_ns) / 1_000_000_000
        ready_ns = camera_ready_monotonic_ns or camera_start_monotonic_ns
        result["scientific_interval_covered"] = bool(
            interval_end_ns >= interval_start_ns
            and camera_start_monotonic_ns is not None
            and ready_ns is not None
            and camera_stop_monotonic_ns is not None
            and camera_start_monotonic_ns <= interval_start_ns
            and ready_ns <= interval_start_ns
            and camera_stop_monotonic_ns >= interval_end_ns
            and duration_s >= interval_s
        )
        if not result["scientific_interval_covered"]:
            result["verification_error"] = "recording lifecycle or media duration does not cover the scientific display interval"
            return result
    result["ok"] = True
    return result


@dataclass(frozen=True)
class CameraPreviewEnvironment:
    """The small, relevant environment selection for native camera preview."""

    enabled: bool
    environment: dict[str, str] | None
    metadata: dict[str, object]


def _local_display_usable(environment: Mapping[str, str]) -> bool:
    """Probe XWayland without changing the parent process environment."""
    try:
        return subprocess.run(
            ("xrandr", "--display", ":0", "--query"),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def resolve_camera_preview_environment(
    environment: Mapping[str, str] | None = None,
    *,
    uid: int | None = None,
    runtime_root: Path = Path("/run/user"),
    display_probe: Callable[[Mapping[str, str]], bool] = _local_display_usable,
) -> CameraPreviewEnvironment:
    """Select an SSH-safe native preview environment, only when it is usable."""
    child_environment = dict(os.environ if environment is None else environment)
    supplied_display = child_environment.get("DISPLAY")
    if supplied_display:
        return CameraPreviewEnvironment(
            True,
            child_environment,
            {
                "requested": True,
                "enabled": True,
                "selection": "user_environment",
                "display": supplied_display,
                "xdg_runtime_dir": child_environment.get("XDG_RUNTIME_DIR"),
                "wayland_display": child_environment.get("WAYLAND_DISPLAY"),
            },
        )

    runtime_dir = runtime_root / str(os.getuid() if uid is None else uid)
    if runtime_dir.is_dir():
        child_environment.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
        if (runtime_dir / "wayland-0").is_socket():
            child_environment.setdefault("WAYLAND_DISPLAY", "wayland-0")
    child_environment["DISPLAY"] = ":0"
    if display_probe(child_environment):
        return CameraPreviewEnvironment(
            True,
            child_environment,
            {
                "requested": True,
                "enabled": True,
                "selection": "local_xwayland",
                "display": ":0",
                "xdg_runtime_dir": child_environment.get("XDG_RUNTIME_DIR"),
                "wayland_display": child_environment.get("WAYLAND_DISPLAY"),
            },
        )
    return CameraPreviewEnvironment(
        False,
        None,
        {
            "requested": True,
            "enabled": False,
            "selection": "unavailable",
            "reason": "local XWayland display :0 was not usable",
        },
    )


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
    preview_enabled: bool = False
    preview_requested: bool = False
    preview_geometry: tuple[int, int, int, int] | None = None
    preview_connector: str | None = None
    child_environment: Mapping[str, str] | None = None


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
    recording_ready_monotonic_ns: int | None = None
    stop_utc_ns: int | None = None
    stop_monotonic_ns: int | None = None
    bytes_written: int = 0
    reported_frames: int | None = None
    decoded_frame_count: int | None = None
    active_runtime_s: float | None = None
    media_duration_s: float | None = None
    media_start_time_s: float | None = None
    media_end_time_s: float | None = None
    metadata_avg_fps: float | None = None
    expected_frame_count: float | None = None
    effective_fps: float | None = None
    frame_count_discrepancy: float | None = None
    decode_probe_success: bool | None = None
    production_qc_success: bool | None = None
    verification_method: str = "not_checked"
    verification_error: str | None = None
    scientific_interval_start_monotonic_ns: int | None = None
    scientific_interval_end_monotonic_ns: int | None = None
    scientific_interval_covered: bool | None = None
    coverage_timing_source: str | None = None
    dropped_frames: int | None = None
    exit_status: int | None = None
    exit_reason: str | None = None
    verification_state: str = "not_checked"
    diagnostic_log_path: str = ""
    preview_enabled: bool = False
    preview_requested: bool = False
    preview_geometry: tuple[int, int, int, int] | None = None
    preview_connector: str | None = None
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
        "--timeout",
        "0",
        "--output",
        str(output_path),
    ]
    if spec.preview_enabled:
        if spec.preview_geometry is None:
            raise ValueError("preview geometry is required when camera preview is enabled")
        command.extend(("--preview", ",".join(str(value) for value in spec.preview_geometry)))
    else:
        command.append("--nopreview")
    if spec.requested_width_px is not None:
        command.extend(("--width", str(spec.requested_width_px)))
    if spec.requested_height_px is not None:
        command.extend(("--height", str(spec.requested_height_px)))
    if spec.requested_fps is not None:
        command.extend(("--framerate", f"{spec.requested_fps:g}"))
    if output_path.suffix == ".mp4":
        command.extend(("--codec", "libav", "--libav-video-codec", "libx264", "--libav-format", "mp4"))
    elif spec.pixel_format_or_codec:
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
            preview_enabled=spec.preview_enabled,
            preview_requested=spec.preview_requested,
            preview_geometry=spec.preview_geometry,
            preview_connector=spec.preview_connector,
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
            kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE}
            if self.spec.child_environment is not None:
                kwargs["env"] = self.spec.child_environment
            self.process = self._popen_factory(self.spec.command, **kwargs)
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
        self.status.recording_ready_monotonic_ns = monotonic_ns()

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
        self.request_stop()
        self.finish_stop()
        self.verify_stop()
        return self.status

    def request_stop(self) -> None:
        """Signal promptly; the supervisor signals every camera before waiting."""
        if self._stopped or self.process is None:
            return
        if self.status.state == CameraState.RECORDING:
            self._publish("CAMERA_STOP_REQUESTED")
        if self.process.poll() is None:
            try:
                sender = getattr(self.process, "send_signal", None)
                if self.spec.backend == "rpicam" and sender is not None:
                    sender(signal.SIGINT)
                else:
                    self.process.terminate()
            except OSError as exc:
                self._fail(f"camera terminate failed: {exc}")

    def finish_stop(self) -> None:
        """Reap after all children have received their stop request."""
        if self._stopped:
            return
        if self.process is None:
            self._stopped = True
            self._write_diagnostic()
            return self.status
        graceful_exit = self.process.poll() is not None or self._reap(self.spec.stop_timeout_s)
        if self.process.poll() is None:
            self._terminate(force=True)
        self._reap(self.spec.stop_timeout_s)
        if self.process.poll() is None:
            self.status.exit_reason = "camera process remained alive after kill"
            self._fail("camera process remained alive after kill")
        elif self.status.exit_status is None:
            self.status.exit_status = int(self.process.poll())
        if self.status.state == CameraState.RECORDING:
            if graceful_exit and (self.spec.backend != "rpicam" or self.status.exit_status == 0):
                self.status.state = CameraState.COMPLETED
                self.status.exit_reason = self.status.exit_reason or "graceful_stop"
            elif self.status.exit_status == 0:
                self.status.state = CameraState.COMPLETED
            else:
                self._fail(f"camera exited with status {self.status.exit_status}")
        self.status.stop_utc_ns = utc_ns()
        self.status.stop_monotonic_ns = monotonic_ns()
        self._refresh_bytes()

    def verify_stop(self) -> None:
        if self._stopped or self.process is None:
            return
        self._probe_output()
        self.status.verification_state = self._verification_state()
        if self.status.state == CameraState.COMPLETED and self.status.verification_state != "recorded":
            self._fail(self.status.verification_error or "production recording verification failed")
        self._write_diagnostic()
        self._stopped = True
        self._publish("CAMERA_STOPPED")

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
            sender = getattr(self.process, "send_signal", None)
            if self.spec.backend != "rpicam" or sender is None:
                self.process.terminate()
            else:
                sender(signal.SIGINT)
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
            if self.spec.backend != "rpicam":
                return "recorded" if self.status.bytes_written > 0 else "recorded_unverified"
            return "recorded" if self.status.production_qc_success else "output_nonempty_failed"
        if self.status.bytes_written > 0:
            return "output_nonempty_failed"
        return "recording_failed"

    def _probe_output(self) -> None:
        """Record bounded post-stop metadata evidence for native rpicam outputs."""
        if self.spec.backend != "rpicam":
            return
        if self.status.start_monotonic_ns is not None and self.status.stop_monotonic_ns is not None:
            self.status.active_runtime_s = (
                self.status.stop_monotonic_ns - self.status.start_monotonic_ns
            ) / 1_000_000_000
        self.status.verification_method = "ffprobe_stream_metadata"
        self.status.reported_frames = None
        self.status.decoded_frame_count = None
        self.status.decode_probe_success = None
        interval = None
        if (
            self.status.scientific_interval_start_monotonic_ns is not None
            and self.status.scientific_interval_end_monotonic_ns is not None
        ):
            interval = (
                self.status.scientific_interval_start_monotonic_ns,
                self.status.scientific_interval_end_monotonic_ns,
            )
        qc = verify_camera_output(
            self.output_path,
            expected={
                "codec": self.spec.pixel_format_or_codec or None,
                "width_px": self.spec.requested_width_px,
                "height_px": self.spec.requested_height_px,
                "fps": self.spec.requested_fps,
            },
            camera_start_monotonic_ns=self.status.start_monotonic_ns,
            camera_ready_monotonic_ns=self.status.recording_ready_monotonic_ns,
            camera_stop_monotonic_ns=self.status.stop_monotonic_ns,
            scientific_interval_monotonic_ns=interval,
            coverage_timing_source=self.status.coverage_timing_source,
        )
        self.status.bytes_written = int(qc["file_size_bytes"])
        self.status.media_duration_s = qc["media_duration_s"]
        self.status.media_start_time_s = qc["media_start_time_s"]
        self.status.media_end_time_s = qc["media_end_time_s"]
        self.status.metadata_avg_fps = qc["metadata_avg_fps"]
        self.status.scientific_interval_covered = qc["scientific_interval_covered"]
        self.status.production_qc_success = bool(qc["ok"])
        self.status.verification_error = qc["verification_error"]

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
        session_root_resolved = self.session_root.resolve()
        outputs = tuple(
            (
                spec,
                self.session_root / "camera" / spec.camera_id / f"capture.{spec.output_extension}",
            )
            for spec in self.specs
        )
        for _spec, output in outputs:
            if not output.resolve().is_relative_to(session_root_resolved):
                raise CameraStartupError(f"camera output path escapes session directory: {output}")
        started: list[_CameraWorker] = []
        for spec, output in outputs:
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

    def stop(
        self,
        *,
        scientific_interval_monotonic_ns: tuple[int, int] | None = None,
        coverage_timing_source: str | None = None,
    ) -> tuple[CameraWorkerStatus, ...]:
        workers = tuple(self._workers.values())
        if scientific_interval_monotonic_ns is not None:
            for worker in workers:
                worker.status.scientific_interval_start_monotonic_ns = scientific_interval_monotonic_ns[0]
                worker.status.scientific_interval_end_monotonic_ns = scientific_interval_monotonic_ns[1]
                worker.status.coverage_timing_source = coverage_timing_source
        # Never let an MP4 probe for camera A keep camera B recording.
        for worker in workers:
            worker.request_stop()
        for worker in workers:
            worker.finish_stop()
        for worker in workers:
            worker.verify_stop()
        statuses = tuple(worker.status for worker in workers)
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
