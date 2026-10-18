#!/usr/bin/env python3
import sys

from rpi_vstim.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["retinotopy", "run", *sys.argv[1:]]))

