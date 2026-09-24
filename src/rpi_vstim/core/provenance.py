from __future__ import annotations

import os
import platform
import sys

from .timestamps import utc_ns


def collect_provenance() -> dict[str, object]:
    return {
        "created_utc_ns": utc_ns(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "repository_commit": os.environ.get("RPI_VSTIM_SOURCE_COMMIT", "unknown"),
        "phase": "00",
    }

