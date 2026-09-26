#!/usr/bin/env python3
"""Compatibility entry point for the package fake camera emulator."""

import sys
from pathlib import Path

try:
    from rpi_vstim.tools.fake_camera import main
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
    from rpi_vstim.tools.fake_camera import main


if __name__ == "__main__":
    main()
