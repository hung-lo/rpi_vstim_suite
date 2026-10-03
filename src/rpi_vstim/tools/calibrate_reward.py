"""Interactive real-rig calibration for one continuous reward opening."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rpi_vstim.core.config import load_config
from rpi_vstim.hardware.calibration import (
    CalibrationCondition,
    CalibrationProfile,
    current_commit,
    write_csv,
    write_png_curve,
    write_profile,
)
from rpi_vstim.hardware.lgpio_backend import LgpioBackend
from rpi_vstim.hardware.reward import RewardController, RewardEvent


def _durations(value: str) -> tuple[float, ...]:
    result = tuple(float(item) for item in value.split(",") if item.strip())
    if not result or any(item <= 0 for item in result):
        raise argparse.ArgumentTypeError("durations must be a non-empty comma-separated list of positives")
    return result


def _mass(prompt: str) -> float:
    while True:
        try:
            value = float(input(prompt).strip())
            if value >= 0:
                return value
        except ValueError:
            pass
        print("Enter a non-negative mass in grams.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rig-id", required=True)
    parser.add_argument("--calibration-id", required=True)
    parser.add_argument("--operator", default="")
    parser.add_argument("--fluid", default="water")
    parser.add_argument("--durations-ms", type=_durations, required=True)
    parser.add_argument("--delivery-count", type=int, default=100)
    parser.add_argument("--target-volume-ul", type=float)
    parser.add_argument("--inter-reward-ms", type=float, default=500.0)
    parser.add_argument("--warmup-count", type=int, default=0)
    parser.add_argument("--warmup-duration-ms", type=float)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="required acknowledgement that GPIO19 will be driven on the attached rig",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute:
        raise SystemExit("refusing to drive GPIO; rerun with --execute after confirming the rig")
    if args.delivery_count <= 0 or args.inter_reward_ms < 0:
        raise SystemExit("delivery-count must be positive and inter-reward-ms must be non-negative")
    if args.warmup_count < 0 or (args.warmup_count and args.warmup_duration_ms is None):
        raise SystemExit("warmup-count requires a positive warmup-duration-ms")

    config = load_config(args.config)
    if config.hardware.backend != "lgpio":
        raise SystemExit("reward calibration requires the production lgpio backend")
    if config.hardware.reward_active_level is None:
        raise SystemExit("reward_active_level must be configured after physical polarity validation")
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    events: list[RewardEvent] = []
    conditions: list[CalibrationCondition] = []

    with LgpioBackend(config.hardware, roles=("reward_left",)) as backend:
        if backend.read_level("reward_left") != config.hardware.reward_initial_level:
            raise SystemExit("reward line is not at its configured inactive electrical level")
        warmup = args.warmup_duration_ms or args.durations_ms[0]
        controller = RewardController(
            backend,
            config.hardware,
            duration_ms=warmup,
            event_sink=events.append,
        )
        for _ in range(args.warmup_count):
            controller.deliver(command_id="calibration-warmup")
            time.sleep(args.inter_reward_ms / 1000.0)
        for duration_ms in args.durations_ms:
            print(f"Prepare collection for {duration_ms:g} ms openings.")
            input("Press Enter when the collection vessel is ready. ")
            initial_mass_g = _mass("Initial mass (g): ")
            controller = RewardController(
                backend,
                config.hardware,
                duration_ms=duration_ms,
                event_sink=events.append,
            )
            for index in range(args.delivery_count):
                controller.deliver(command_id=f"{args.calibration_id}-{duration_ms:g}-{index + 1}")
                if index + 1 < args.delivery_count:
                    time.sleep(args.inter_reward_ms / 1000.0)
            final_mass_g = _mass("Final mass (g): ")
            conditions.append(
                CalibrationCondition.measured(
                    duration_ms, args.delivery_count, initial_mass_g, final_mass_g
                )
            )

    profile = CalibrationProfile.create(
        calibration_id=args.calibration_id,
        rig_id=args.rig_id,
        conditions=conditions,
        fluid=args.fluid,
        operator=args.operator,
        software_commit=current_commit(),
        hardware_backend=config.hardware.backend,
        selected_target_volume_ul=args.target_volume_ul,
    )
    if args.target_volume_ul is not None:
        profile = profile.with_target(args.target_volume_ul)
    write_profile(profile, output_dir / f"{args.calibration_id}.json")
    write_csv(profile, output_dir / f"{args.calibration_id}.csv")
    write_png_curve(profile, output_dir / f"{args.calibration_id}.png")
    print(f"Wrote calibration outputs to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
