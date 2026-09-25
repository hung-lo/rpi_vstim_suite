"""Small, non-hardware Phase 00 command-line surface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core.config import ConfigError, load_config
from .protocols import available_protocols


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpi-vstim")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("list-protocols", help="list protocol placeholders")
    doctor = commands.add_parser("doctor", help="show Phase 00 diagnostic status")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    config = commands.add_parser("config", help="validate configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    validate = config_commands.add_parser("validate")
    validate.add_argument("path", type=Path, nargs="?", help="TOML file")
    validate.add_argument("--experimental", action="store_true")

    run = commands.add_parser("run", help="reserved protocol entry point")
    run.add_argument("protocol", choices=[p.name for p in available_protocols()])
    run.add_argument("--camera", action="store_true", help="enable configured local cameras")
    run.add_argument("--cameras", help="comma-separated configured local camera IDs or 'all'")

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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list-protocols":
        for protocol in available_protocols():
            print(f"{protocol.name}\t{protocol.status}")
        return 0
    if args.command == "doctor":
        return _doctor(args.as_json)
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
        print(
            f"protocol '{args.protocol}' is a Phase 00 placeholder; no experiment was started",
            file=sys.stderr,
        )
        return 2
    build_parser().print_help()
    return 0
