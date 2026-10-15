"""Present three deterministic colors. Default profile uses a fake display."""

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
        for color in ((0, 0, 0), (127, 127, 127), (255, 255, 255)):
            print(display.present_color(color, frames=30))
    finally:
        display.close()


if __name__ == "__main__":
    main()
