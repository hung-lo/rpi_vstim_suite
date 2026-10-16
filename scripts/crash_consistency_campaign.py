#!/usr/bin/env python3
"""Exercise terminal session states at lifecycle/finalization boundaries."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.core.session import inspect_session
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan


FAULTS = (
    "asset_manifest_creation", "session_metadata_write", "storage_low_space",
    "producer_start", "producer_mid", "finalization", "cleanup",
)


def run() -> dict[str, object]:
    plan = build_plan(NaturalImageSettings(
        images=("a", "b"), trial_count=2, initial_gray_frames=1,
        final_gray_frames=1, image_duration_s=1 / 60, iti_frames=(1,),
    ))
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-crash-") as temporary:
        root = Path(temporary)
        results: dict[str, dict[str, object]] = {}
        for name in (*FAULTS, "interrupt"):
            config = config_from_mapping({"paths": {"output_root": root}})
            result = run_simulated_session(
                config, plan=plan, session_id=name, interrupt=name == "interrupt", fault=None if name == "interrupt" else name,
            )
            first = inspect_session(result.session.context.session_root)
            second = inspect_session(result.session.context.session_root)
            assert first == second
            assert first["status"] != "COMPLETE" or name == "cleanup"
            results[name] = {"runtime_state": result.final_state.value, "inspect_status": first["status"], "corrupt": first["corrupt_artifacts"]}
        return {"boundaries": len(results), "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(run(), sort_keys=True))


if __name__ == "__main__":
    main()
