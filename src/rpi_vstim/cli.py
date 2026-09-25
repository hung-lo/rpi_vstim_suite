"""Small, non-hardware Phase 00 command-line surface."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .core.config import ConfigError, load_config
from .core.runtime import run_simulated_session
from .display.diagnostics import DisplayProbeError, display_probe
from .display.kms import KmsDisplayBackend
from .display.native_probe import NativeKmsError, run_native_probe
from .display.photodiode import PhotodiodePatch
from .protocols import available_protocols, get_protocol


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpi-vstim")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("list-protocols", help="list available protocol implementations")
    doctor = commands.add_parser("doctor", help="show Phase 00 diagnostic status")
    doctor.add_argument("--json", action="store_true", dest="as_json")

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

    return parser


def _doctor(as_json: bool) -> int:
    result = {
        "phase": "00",
        "status": "skeleton",
        "hardware_access": False,
        "message": "No hardware, display, camera, GPIO, or network telemetry access is performed.",
    }
    if as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("rpi-vstim Phase 00 skeleton")
        print(result["message"])
    return 0


def _representative_rgb888(width_px: int, height_px: int, phase: int) -> bytes:
    frame = bytearray(width_px * height_px * 3)
    for y in range(height_px):
        for x in range(width_px):
            offset = (y * width_px + x) * 3
            frame[offset] = (x * 255) // max(width_px - 1, 1)
            frame[offset + 1] = (y * 255) // max(height_px - 1, 1)
            frame[offset + 2] = (x + y + phase) % 256
    return bytes(frame)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list-protocols":
        for protocol in available_protocols():
            print(f"{protocol.name}\t{protocol.status}")
        return 0
    if args.command == "doctor":
        return _doctor(args.as_json)
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
            use_lease=args.lease,
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
                lease=args.lease,
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
