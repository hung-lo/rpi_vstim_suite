"""Small, non-hardware Phase 00 command-line surface."""

from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .audio import AudioError, FakeAudio, SoundDeviceAudio
from .core.config import CameraDeviceConfig, ConfigError, load_config
from .core.dry_run import build_dry_run_report
from .core.natural_image_demo import AudioCoexistenceSettings, run_natural_image_demo
from .core.runtime import run_simulated_session
from .core.session import inspect_session
from .core.virtual_rig import run_virtual_session
from .display.diagnostics import DisplayProbeError, display_probe
from .display.kms import KmsDisplayBackend
from .display.native_probe import NativeKmsError, run_native_probe
from .display.photodiode import PhotodiodePatch
from .doctor import inspect_machine
from .hardware.lgpio_backend import LgpioBackend
from .hardware.operator_bait import LgpioOperatorBaitMonitor
from .hardware.operator_control import (
    JsonlEventLog,
    OperatorControlError,
    OperatorControlService,
    send_manual_bait,
)
from .hardware.water_service import (
    WaterHoldStateMachine,
    WaterServiceController,
    validate_service_button_gpio,
    validate_service_seconds,
)
from .protocols import available_protocols, get_protocol
from .protocols.audio_pilot import AudioPilotSettings, run_audio_pilot
from .telemetry.benchmark import run_benchmark
from .telemetry.payloads import TelemetryMessage
from .telemetry.publisher import UdpTelemetryPublisher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpi-vstim")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("list-protocols", help="list available protocol implementations")
    preflight = commands.add_parser("preflight", help="report production contracts without hardware")
    preflight.add_argument("--config", type=Path)
    preflight.add_argument("--protocol", choices=[p.name for p in available_protocols()])
    preflight.add_argument("--seed", type=int, default=0)
    preflight.add_argument("--json", action="store_true", dest="as_json")
    inspect = commands.add_parser("inspect-session", help="inspect a session without mutating it")
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--json", action="store_true", dest="as_json")
    inspect.add_argument(
        "--deep-camera-qc",
        action="store_true",
        help="optionally count every decodable camera frame; may take a long time",
    )
    session = commands.add_parser("session", help="session artifact operations")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    validate_session = session_commands.add_parser(
        "validate", help="validate a session without mutating it"
    )
    validate_session.add_argument("path", type=Path)
    validate_session.add_argument("--json", action="store_true", dest="as_json")
    doctor = commands.add_parser("doctor", help="inspect machine capabilities without changing them")
    doctor.add_argument("--config", type=Path, help="TOML profile for the output root")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    telemetry = commands.add_parser("telemetry", help="local telemetry transport checks")
    telemetry_commands = telemetry.add_subparsers(dest="telemetry_command", required=True)
    telemetry_demo = telemetry_commands.add_parser("demo", help="send schema messages to loopback")
    telemetry_demo.add_argument("--messages", type=int, default=4)
    telemetry_demo.add_argument("--json", action="store_true", dest="as_json")
    telemetry_benchmark = telemetry_commands.add_parser(
        "benchmark", help="measure local telemetry handoff latency"
    )
    telemetry_benchmark.add_argument("--messages", type=int, default=1000)

    hardware = commands.add_parser("hardware", help="hardware discovery and diagnostics")
    hardware_commands = hardware.add_subparsers(dest="hardware_command", required=True)
    display_probe_command = hardware_commands.add_parser(
        "display-probe", help="read DRM connectors and configured display modes"
    )
    display_probe_command.add_argument("--config", type=Path, help="TOML configuration file")
    display_probe_command.add_argument("--json", action="store_true", dest="as_json")
    kms_probe_command = hardware_commands.add_parser(
        "kms-probe", help="native DRM resource probe without modesetting"
    )
    kms_probe_command.add_argument("--config", type=Path, help="TOML configuration file")
    kms_probe_command.add_argument("--binary", type=Path, help="native kms_probe executable")
    kms_probe_command.add_argument("--device", help="DRM card; omitted scans card*")
    kms_probe_command.add_argument("--lease", action="store_true")
    kms_probe_command.add_argument("--json", action="store_true", dest="as_json")
    kms_smoke_command = hardware_commands.add_parser(
        "kms-smoke", help="short native DRM page-flip smoke test with restoration"
    )
    kms_smoke_command.add_argument("--config", type=Path, help="TOML configuration file")
    kms_smoke_command.add_argument("--binary", type=Path, help="native kms_probe executable")
    kms_smoke_command.add_argument("--device", help="DRM card; omitted scans card*")
    kms_smoke_command.add_argument("--frames", type=int, default=60)
    kms_smoke_command.add_argument("--lease", action="store_true")
    kms_smoke_command.add_argument("--json", action="store_true", dest="as_json")
    render_smoke_command = hardware_commands.add_parser(
        "kms-render-smoke", help="display-only production-renderer smoke test"
    )
    render_smoke_command.add_argument("--config", type=Path, help="TOML configuration file")
    render_smoke_command.add_argument("--binary", type=Path, help="native kms_probe executable")
    render_smoke_command.add_argument("--frames", type=int, default=300)
    render_smoke_command.add_argument("--lease", action="store_true")
    render_smoke_command.add_argument("--json", action="store_true", dest="as_json")

    operator = commands.add_parser("operator", help="headless operator controls")
    operator_commands = operator.add_subparsers(dest="operator_command", required=True)
    operator_bait = operator_commands.add_parser("bait", help="request one calibrated manual bait")
    operator_bait.add_argument("--config", type=Path)
    operator_bait.add_argument("--json", action="store_true", dest="as_json")
    operator_service = operator_commands.add_parser(
        "service", help="run legacy GPIO23 or keyboard manual-bait controls"
    )
    operator_service.add_argument("--config", type=Path)
    operator_service.add_argument("--session-id", default="operator-control")
    operator_service.add_argument("--no-keyboard", action="store_true")

    water = commands.add_parser("water", help="operator-only plumbing controls")
    water_commands = water.add_subparsers(dest="water_command", required=True)
    water_prime = water_commands.add_parser("prime", help="open reward_left continuously for a duration")
    water_prime.add_argument("--seconds", type=float, required=True)
    water_prime.add_argument("--config", type=Path)
    water_prime.add_argument("--json", action="store_true", dest="as_json")
    water_service = water_commands.add_parser(
        "service", help="legacy GPIO23 button plumbing service (not current Pi 5 rig)"
    )
    water_service.add_argument("--config", type=Path)

    config = commands.add_parser("config", help="validate configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    validate = config_commands.add_parser("validate")
    validate.add_argument("path", type=Path, nargs="?", help="TOML file")
    validate.add_argument("--experimental", action="store_true")

    run = commands.add_parser("run", help="reserved protocol entry point")
    run.add_argument("protocol", choices=[p.name for p in available_protocols()])
    run.add_argument("--camera", action="store_true", help="enable configured local cameras")
    run.add_argument("--cameras", help="comma-separated configured local camera IDs or 'all'")
    run.add_argument("--simulate", action="store_true", help="run the hardware-independent simulation")
    run.add_argument("--config", type=Path, help="TOML configuration file")
    run.add_argument("--output-root", type=Path, help="simulation session output directory")
    run.add_argument("--session-id", default="simulation")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--dry-run", action="store_true", help="report production contracts without hardware")
    run.add_argument("--json", action="store_true", dest="as_json")

    natural_images = commands.add_parser("natural-images", help="real natural-image demonstrations")
    natural_image_commands = natural_images.add_subparsers(dest="natural_image_command", required=True)
    natural_image_run = natural_image_commands.add_parser(
        "run", help="run natural images with optional real licks and CSI cameras"
    )
    natural_image_run.add_argument("--mouse-id", required=True)
    natural_image_run.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "config"
        / "rigs"
        / "pi5_natural_image_demo.example.toml",
    )
    natural_image_run.add_argument("--output-root", type=Path)
    natural_image_run.add_argument("--session-id")
    natural_image_run.add_argument("--seed", type=int, default=0)
    natural_image_run.add_argument("--image-count", type=int)
    natural_image_run.add_argument("--licks", action="store_true")
    natural_image_run.add_argument("--cameras", action="store_true")
    natural_image_run.add_argument("--camera-preview", action="store_true")
    natural_image_run.add_argument(
        "--audio-coexistence", action="store_true",
        help="play the deterministic pilot audio schedule in the same session",
    )
    natural_image_run.add_argument(
        "--audio-config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config/rigs/pi5_audio_pilot.example.toml",
        help="audio pilot profile containing the unique USB device match and gains",
    )
    natural_image_run.add_argument("--native-binary", type=Path)
    natural_image_run.add_argument("--json", action="store_true", dest="as_json")

    audio_pilot = commands.add_parser("audio-pilot", help="run the engineering USB-audio pilot")
    audio_pilot.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[2]
                             / "config/rigs/pi5_audio_pilot.example.toml")
    audio_pilot.add_argument("--output-root", type=Path)
    audio_pilot.add_argument("--session-id")
    audio_pilot.add_argument("--seed", type=int)
    audio_pilot.add_argument("--smoke", action="store_true", help="2 repeats per sound (6 trials)")
    audio_pilot.add_argument("--simulate", action="store_true", help="use fake audio without waiting")
    audio_pilot.add_argument("--json", action="store_true", dest="as_json")

    virtual = commands.add_parser("virtual-run", help="run a production-shaped virtual rig")
    virtual.add_argument("protocol", choices=[p.name for p in available_protocols()])
    virtual.add_argument("--output-root", type=Path, required=True)
    virtual.add_argument("--session-id", default="virtual-session")
    virtual.add_argument("--seed", type=int, default=0)
    virtual.add_argument("--camera-mode", default="normal")
    virtual.add_argument("--fail-camera", default="")
    virtual.add_argument("--interrupt", action="store_true")
    virtual.add_argument("--fault", choices=(
        "session_metadata_write", "storage_low_space", "asset_manifest_creation",
        "producer_start", "producer_mid", "display_consumer_start", "display_consumer_mid",
        "finalization", "cleanup",
    ))
    virtual.add_argument("--json", action="store_true", dest="as_json")

    return parser


def _doctor(config_path: Path | None, as_json: bool) -> int:
    try:
        result = inspect_machine(load_config(config_path))
    except (ConfigError, OSError, ValueError) as exc:
        print(f"doctor invalid: {exc}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {json.dumps(value, sort_keys=True)}")
    return 0


def _telemetry_demo(messages: int) -> dict[str, object]:
    if messages < 1:
        raise ValueError("messages must be positive")
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    publisher = UdpTelemetryPublisher("127.0.0.1", receiver.getsockname()[1])
    try:
        for sequence in range(messages):
            if not publisher.publish(
                TelemetryMessage(
                    "lifecycle",
                    "telemetry-demo",
                    "demo",
                    "TASK",
                    sequence_number=sequence,
                )
            ):
                raise RuntimeError("local telemetry handoff dropped a demo packet")
        publisher.close()
        received = 0
        while received < messages:
            receiver.recv(8192)
            received += 1
        return {
            "messages": messages,
            "received": received,
            "queued": publisher.queued_count,
            "sent": publisher.sent_count,
            "dropped": publisher.dropped_count,
            "errors": publisher.error_count,
        }
    finally:
        publisher.close()
        receiver.close()


def _representative_rgb888(width_px: int, height_px: int, phase: int) -> bytes:
    frame = bytearray(width_px * height_px * 3)
    for y in range(height_px):
        for x in range(width_px):
            offset = (y * width_px + x) * 3
            frame[offset] = (x * 255) // max(width_px - 1, 1)
            frame[offset + 1] = (y * 255) // max(height_px - 1, 1)
            frame[offset + 2] = (x + y + phase) % 256
    return bytes(frame)


def _run_operator_service(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        stopped = False

        def stop_signal(_signum: int, _frame: object) -> None:
            nonlocal stopped
            stopped = True

        previous = signal.signal(signal.SIGTERM, stop_signal)
        try:
            service = OperatorControlService(
                config,
                session_id=args.session_id,
                enable_keyboard=not args.no_keyboard,
            )
            service.run_forever(stop=lambda: stopped)
        finally:
            signal.signal(signal.SIGTERM, previous)
    except KeyboardInterrupt:
        return 130
    except (ConfigError, OSError, OperatorControlError, RuntimeError, ValueError) as exc:
        print(f"operator service failed: {exc}", file=sys.stderr)
        return 2
    return 0


def _run_water_prime(args: argparse.Namespace) -> int:
    backend = None
    try:
        validate_service_seconds(args.seconds)
        def stop_signal(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        config = load_config(args.config)
        previous = signal.signal(signal.SIGTERM, stop_signal)
        backend = LgpioBackend(
            config.hardware,
            roles=("reward_left",),
            ownership_path=config.paths.reward_hardware_lock_path,
        )
        backend.start()
        logger = JsonlEventLog(config.paths.operator_event_log)
        controller = WaterServiceController(
            backend,
            config.hardware,
            event_sink=logger,
        )
        events = controller.prime(args.seconds, source="terminal")
        payload = {
            "ok": True,
            "delivery_mode": "continuous_open_service",
            "requested_seconds": args.seconds,
            "events": [event.as_dict() for event in events],
        }
        signal.signal(signal.SIGTERM, previous)
    except KeyboardInterrupt:
        print("water prime interrupted; GPIO19 was closed", file=sys.stderr)
        return 130
    except (ConfigError, OSError, OperatorControlError, RuntimeError, ValueError) as exc:
        print(f"water prime failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if "previous" in locals():
            signal.signal(signal.SIGTERM, previous)
        if backend is not None:
            backend.stop()
    print(json.dumps(payload, sort_keys=True) if args.as_json else "water prime complete")
    return 0


def _run_water_service(args: argparse.Namespace) -> int:
    backend = None
    monitor = None
    hold = None
    stopped = False
    try:
        config = load_config(args.config)
        controls = config.operator_controls
        validate_service_button_gpio(controls.bait_button_gpio)
        if controls.bait_button_idle_level is None or controls.bait_button_active_level is None:
            raise ConfigError("water service requires explicit GPIO23 idle and active levels")
        backend = LgpioBackend(
            config.hardware,
            roles=("reward_left",),
            ownership_path=config.paths.reward_hardware_lock_path,
        )
        backend.start()
        logger = JsonlEventLog(config.paths.operator_event_log)
        controller = WaterServiceController(backend, config.hardware, event_sink=logger)
        hold = WaterHoldStateMachine(
            controller,
            idle_level=controls.bait_button_idle_level,
            active_level=controls.bait_button_active_level,
            release_stable_ms=controls.bait_button_release_stable_ms,
        )
        monitor = LgpioOperatorBaitMonitor(
            config,
            on_raw_edge=lambda edge: hold.handle_level(edge.level, edge.timestamp_ns),
        )
        monitor.start()

        def stop_signal(_signum: int, _frame: object) -> None:
            nonlocal stopped
            stopped = True

        previous = signal.signal(signal.SIGTERM, stop_signal)
        try:
            while not stopped:
                hold.check_timeout()
                hold.check_release()
                time.sleep(0.02)
        finally:
            signal.signal(signal.SIGTERM, previous)
    except KeyboardInterrupt:
        return 130
    except (ConfigError, OSError, OperatorControlError, RuntimeError, ValueError) as exc:
        print(f"water service failed: {exc}", file=sys.stderr)
        return 2
    finally:
        try:
            if hold is not None:
                hold.close()
        finally:
            try:
                if monitor is not None:
                    monitor.stop()
            finally:
                if backend is not None:
                    backend.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "audio-pilot":
        try:
            config = load_config(args.config)
            if config.protocol.name != "audio-pilot":
                raise ConfigError("audio-pilot config must set protocol.name = 'audio-pilot'")
            settings = AudioPilotSettings.from_config(config)
            if args.seed is not None:
                settings = replace(settings, seed=args.seed)
            if args.smoke:
                settings = replace(settings, repeats_per_stimulus=2)
            if args.output_root is not None:
                config = replace(config, paths=replace(config.paths, output_root=args.output_root))
            config = replace(config, session=replace(config.session, simulation=args.simulate))
            session_id = args.session_id or datetime.now(UTC).strftime("audio-pilot-%Y%m%dT%H%M%S%fZ")
            audio = FakeAudio() if args.simulate else SoundDeviceAudio(settings.device_name_match)
            result = run_audio_pilot(config, settings, audio, session_id=session_id,
                                     sleep=(lambda _seconds: None) if args.simulate else time.sleep)
        except (AudioError, ConfigError, OSError, TypeError, ValueError, RuntimeError,
                KeyboardInterrupt) as exc:
            print(f"audio pilot failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2, sort_keys=True) if args.as_json else result)
        return 0
    if args.command == "list-protocols":
        for protocol in available_protocols():
            print(f"{protocol.name}\t{protocol.status}")
        return 0
    if args.command == "preflight":
        try:
            config = load_config(args.config)
            if args.protocol:
                protocol = get_protocol(args.protocol)
                config = replace(config, protocol=replace(config.protocol, name=args.protocol, version=protocol.version))
            report = build_dry_run_report(config, protocol_name=args.protocol, seed=args.seed)
        except (ConfigError, OSError, ValueError) as exc:
            print(f"preflight invalid: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, indent=2, sort_keys=True) if args.as_json else _format_preflight(report))
        return 0
    if args.command == "inspect-session" or (
        args.command == "session" and args.session_command == "validate"
    ):
        report = inspect_session(args.path, deep_camera_qc=getattr(args, "deep_camera_qc", False))
        print(json.dumps(report, indent=2, sort_keys=True) if args.as_json else _format_inspection(report))
        return 1 if report["corrupt_artifacts"] else 0
    if args.command == "doctor":
        return _doctor(args.config, args.as_json)
    if args.command == "telemetry" and args.telemetry_command == "demo":
        try:
            payload = _telemetry_demo(args.messages)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"telemetry demo failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(payload, sort_keys=True) if args.as_json else payload)
        return 0
    if args.command == "telemetry" and args.telemetry_command == "benchmark":
        try:
            payload = run_benchmark(args.messages)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"telemetry benchmark failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(payload, sort_keys=True))
        return 0
    if args.command == "natural-images" and args.natural_image_command == "run":
        try:
            config = load_config(args.config)
            audio = None
            audio_settings = None
            if args.audio_coexistence:
                audio_config = load_config(args.audio_config)
                if audio_config.protocol.name != "audio-pilot":
                    raise ConfigError("--audio-config must use protocol.name = 'audio-pilot'")
                pilot_settings = AudioPilotSettings.from_config(audio_config)
                audio_settings = AudioCoexistenceSettings(
                    device_name_match=pilot_settings.device_name_match,
                    gains_db=pilot_settings.gains_db,
                )
                audio = SoundDeviceAudio(audio_settings.device_name_match)
            if args.output_root is not None:
                config = replace(config, paths=replace(config.paths, output_root=args.output_root))
            session_id = args.session_id or (
                f"{args.mouse_id}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
            )
            print(
                "\n".join(
                    (
                        f"Session: {session_id}",
                        "Protocol: natural-images",
                        "",
                        f"Stimulus: {config.display.stimulus_connector} / leased KMS",
                        f"  corpus: {config.paths.asset_root}",
                        "Licks: LEFT BCM26, RIGHT BCM27" if args.licks else "Licks: DISABLED",
                        "Cameras: two CSI recordings at 640x480 @ 30 fps"
                        if args.cameras
                        else "Cameras: DISABLED",
                        (
                            f"USB audio: persistent 48 kHz stream ({audio_settings.device_name_match})"
                            if audio_settings else "USB audio: DISABLED"
                        ),
                        "Preview: requested on HDMI-A-1 side-by-side" if args.camera_preview else "Preview: DISABLED",
                        "Reward: DISABLED",
                        "Vacuum: DISABLED",
                        "GPIO23: untouched",
                        "GPIO9 IRIG: untouched",
                        "",
                        "Ctrl-C to stop safely.",
                    )
                ),
                flush=True,
            )
            result = run_natural_image_demo(
                config,
                mouse_id=args.mouse_id,
                session_id=session_id,
                seed=args.seed,
                image_count=args.image_count,
                use_licks=args.licks,
                use_cameras=args.cameras,
                camera_preview=args.camera_preview,
                native_binary=args.native_binary,
                audio=audio,
                audio_settings=audio_settings,
            )
        except (AudioError, ConfigError, OSError, TypeError, ValueError, RuntimeError) as exc:
            print(f"natural-image demo failed: {exc}", file=sys.stderr)
            return 2
        payload = {
            "session_root": str(result.session_root),
            "status": result.status,
            "error": result.error,
            "raw_lick_count": result.raw_lick_count,
            "classified_lick_count": result.classified_lick_count,
            "camera_manifest": result.camera_manifest,
            "event_diagnostics": result.event_diagnostics,
            "camera_preview": result.camera_preview,
            "audio_summary": result.audio_summary,
        }
        if args.camera_preview and not result.camera_preview.get("enabled"):
            print(f"WARNING: camera preview unavailable: {result.camera_preview.get('reason')}", file=sys.stderr)
        print(
            json.dumps(payload, indent=2, sort_keys=True)
            if args.as_json
            else f"{result.status}: {result.session_root}"
        )
        return 0 if result.ok else 1
    if args.command == "operator" and args.operator_command == "bait":
        try:
            config = load_config(args.config)
            payload = send_manual_bait(config.paths.operator_control_socket)
        except (ConfigError, OSError, OperatorControlError, ValueError) as exc:
            print(f"operator bait failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(payload, sort_keys=True) if args.as_json else payload.get("status", "accepted"))
        return 0 if payload.get("ok") else 2
    if args.command == "operator" and args.operator_command == "service":
        return _run_operator_service(args)
    if args.command == "water" and args.water_command == "prime":
        return _run_water_prime(args)
    if args.command == "water" and args.water_command == "service":
        return _run_water_service(args)
    if args.command == "virtual-run":
        try:
            config = load_config(None)
            protocol = get_protocol(args.protocol)
            cameras = config.cameras
            if not cameras.devices:
                cameras = replace(
                    cameras,
                    devices=(
                        CameraDeviceConfig("face", "face", required=True, device="virtual-face"),
                        CameraDeviceConfig("behavior", "behavior", device="virtual-behavior"),
                    ),
                )
            config = replace(
                config,
                paths=replace(config.paths, output_root=args.output_root),
                protocol=replace(config.protocol, name=args.protocol, version=protocol.version),
                cameras=cameras,
            )
            failures = {item.strip() for item in args.fail_camera.split(",") if item.strip()}
            result = run_virtual_session(
                config,
                protocol_name=args.protocol,
                session_id=args.session_id,
                seed=args.seed,
                camera_mode=args.camera_mode,
                camera_failures=failures,
                interrupt=args.interrupt,
                fault=args.fault,
            )
            payload = {
                "final_state": result.final_state.value,
                "ok": result.ok,
                "error": result.error,
                "session_root": str(result.session.context.session_root),
                "degraded": result.degraded,
                "camera_manifest": result.services.cameras.manifest(),
                "display_metrics": result.services.display.sequence.metrics(),
                "telemetry": {
                    "published": result.services.telemetry.publish_count,
                    "retained": len(result.services.telemetry.messages),
                    "dropped": result.services.telemetry.dropped_count,
                },
            }
        except (ConfigError, OSError, ValueError, RuntimeError) as exc:
            print(f"virtual-run invalid: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(payload, indent=2, sort_keys=True) if args.as_json else f"{payload['final_state']}: {payload['session_root']}")
        return 0 if result.ok else 1
    if args.command == "hardware" and args.hardware_command == "display-probe":
        try:
            config = load_config(args.config).display
            print(display_probe(config, as_json=args.as_json))
        except (ConfigError, DisplayProbeError, OSError, ValueError) as exc:
            print(f"display probe failed: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "hardware" and args.hardware_command == "kms-render-smoke":
        display = KmsDisplayBackend(
            native_binary=args.binary,
            use_lease=True if args.lease else None,
        )
        try:
            loaded = load_config(args.config)
            config = loaded.display
            display.photodiode = PhotodiodePatch(
                loaded.photodiode.corner,
                loaded.photodiode.size_px,
                loaded.photodiode.on_value,
                loaded.photodiode.off_value,
            )
            display.open(config)
            display.present_rgb_pair(
                _representative_rgb888(config.width_px, config.height_px, 0),
                _representative_rgb888(config.width_px, config.height_px, 37),
                frames=args.frames,
                sequence_id="production-renderer-smoke",
            )
            payload = display.last_probe_payload
            if payload is None:
                raise NativeKmsError("production renderer returned no native result")
            print(json.dumps(payload, indent=2, sort_keys=True) if args.as_json else payload)
        except (ConfigError, NativeKmsError, OSError, ValueError) as exc:
            print(f"KMS renderer command failed: {exc}", file=sys.stderr)
            return 2
        finally:
            display.close()
        return 0
    if args.command == "hardware" and args.hardware_command in {"kms-probe", "kms-smoke"}:
        try:
            config = load_config(args.config).display
            payload = run_native_probe(
                config,
                frames=1 if args.hardware_command == "kms-probe" else args.frames,
                binary=args.binary,
                device=args.device,
                probe_only=args.hardware_command == "kms-probe",
                lease=args.lease or config.ownership == "lease",
            )
            print(json.dumps(payload, indent=2, sort_keys=True) if args.as_json else payload)
        except (ConfigError, NativeKmsError, OSError, ValueError) as exc:
            print(f"KMS command failed: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "config" and args.config_command == "validate":
        try:
            config = load_config(args.path)
            if args.experimental and (
                not config.session.experimental or config.session.simulation
            ):
                raise ConfigError(
                    "--experimental requires session.experimental=true and session.simulation=false"
                )
            config.validate(require_paths=args.experimental, repo_root=Path.cwd())
        except (ConfigError, OSError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 2
        print(f"valid: {args.path or 'package defaults'}")
        return 0
    if args.command == "run":
        if args.dry_run:
            try:
                config = load_config(args.config)
                if args.config is None:
                    protocol = get_protocol(args.protocol)
                    config = replace(config, protocol=replace(config.protocol, name=args.protocol, version=protocol.version))
                report = build_dry_run_report(config, protocol_name=args.protocol, seed=args.seed)
            except (ConfigError, OSError, ValueError) as exc:
                print(f"dry-run invalid: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(report, indent=2, sort_keys=True) if args.as_json else _format_preflight(report))
            return 0
        if args.simulate:
            try:
                config = load_config(args.config)
                if args.config is None:
                    protocol = get_protocol(args.protocol)
                    config = replace(
                        config,
                        protocol=replace(
                            config.protocol,
                            name=args.protocol,
                            version=protocol.version,
                        ),
                    )
                if args.cameras or args.camera:
                    if args.cameras in (None, "all"):
                        selected_ids = {device.id for device in config.cameras.devices}
                    else:
                        selected_ids = {item.strip() for item in args.cameras.split(",") if item.strip()}
                    unknown_ids = selected_ids - {device.id for device in config.cameras.devices}
                    if unknown_ids:
                        raise ConfigError(f"unknown camera ID(s): {', '.join(sorted(unknown_ids))}")
                    config = replace(
                        config,
                        cameras=replace(
                            config.cameras,
                            devices=tuple(
                                device for device in config.cameras.devices if device.id in selected_ids
                            ),
                        ),
                    )
                else:
                    config = replace(config, cameras=replace(config.cameras, devices=()))
                if args.output_root is not None:
                    config = replace(config, paths=replace(config.paths, output_root=args.output_root))
                result = run_simulated_session(
                    config,
                    protocol_name=args.protocol,
                    session_id=args.session_id,
                    seed=args.seed,
                )
            except (ConfigError, OSError, ValueError) as exc:
                print(f"simulation invalid: {exc}", file=sys.stderr)
                return 2
            print(f"{result.final_state.value}: {result.session.context.session_root}")
            if result.degraded:
                print(f"degraded: {', '.join(result.degraded)}")
            return 0 if result.ok else 1
        print(
            f"protocol '{args.protocol}' is a Phase 00 placeholder; no experiment was started",
            file=sys.stderr,
        )
        return 2
    build_parser().print_help()
    return 0


def _format_preflight(report: dict[str, object]) -> str:
    plan = report["plan"]
    cameras = report["camera_requirements"]
    camera_text = ", ".join(
        f"{camera['role']}={camera['stable_identity'] or '<unresolved>'}"
        for camera in cameras
    ) or "none"
    budget = report["resource_budget"]
    storage = report["storage"]
    return (
        f"protocol={report['protocol']} frames={plan['total_frames']} "
        f"duration_s={plan['estimated_duration_s']:.3f} assets={report['asset_status']} "
        f"asset_digest={report['asset_manifest_digest'] or '<deferred>'} "
        f"ram_bytes={budget['estimated_ram_bytes']} storage_bytes={storage['estimated_required_bytes']} "
        f"cameras={camera_text} hardware_access=False"
    )


def _format_inspection(report: dict[str, object]) -> str:
    return (
        f"status={report['status']} incomplete={report['incomplete']} "
        f"missing={len(report['missing_required_files'])} "
        f"corrupt={len(report['corrupt_artifacts'])}"
    )
