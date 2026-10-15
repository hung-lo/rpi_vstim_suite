"""Present two synthetic RGB frames; no external image corpus is required."""

import argparse

from rpi_vstim.display import FakeDisplayBackend, KmsDisplayBackend
from rpi_vstim.session import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="TOML profile; KMS access is explicit")
    args = parser.parse_args()
    config = load_config(args.config)
    display = KmsDisplayBackend() if config.display.backend == "kms" else FakeDisplayBackend()
    try:
        display.open(config.display)
        if isinstance(display, KmsDisplayBackend):
            pixels = config.display.width_px * config.display.height_px
            image_a = bytes((255, 0, 0)) * pixels
            image_b = bytes((0, 0, 255)) * pixels
            print(display.present_rgb_pair(image_a, image_b, frames=60, sequence_id="synthetic-pair"))
        else:
            for color in ((255, 0, 0), (0, 0, 255)):
                print(display.present_color(color, frames=30))
    finally:
        display.close()


if __name__ == "__main__":
    main()
