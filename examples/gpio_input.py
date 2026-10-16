"""Record edges on an explicitly selected input pin. Never drives an output."""

import argparse
import json
import time
from pathlib import Path

from rpi_vstim.hardware.policy import RESERVED_GPIO_BCM, reserved_gpio_message


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pin", type=int, required=True, help="BCM input pin")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.pin <= 27 or args.seconds <= 0:
        parser.error("pin must be BCM 0..27 and seconds must be positive")
    if args.pin in RESERVED_GPIO_BCM:
        parser.error(reserved_gpio_message(args.pin))
    try:
        import lgpio
    except ImportError:
        parser.error("lgpio is unavailable; run this example on a configured Pi")
    chip = lgpio.gpiochip_open(0)
    callback = None
    try:
        lgpio.gpio_claim_alert(chip, args.pin, lgpio.BOTH_EDGES, 0)
        with args.output.open("x", encoding="utf-8") as events:
            def on_edge(_chip: int, pin: int, level: int, timestamp_ns: int) -> None:
                events.write(json.dumps({"pin": pin, "level": level, "monotonic_ns": timestamp_ns}) + "\n")
                events.flush()

            callback = lgpio.callback(chip, args.pin, lgpio.BOTH_EDGES, on_edge)
            time.sleep(args.seconds)
    finally:
        if callback is not None:
            callback.cancel()
        lgpio.gpiochip_close(chip)


if __name__ == "__main__":
    main()
