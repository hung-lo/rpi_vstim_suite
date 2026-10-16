"""Start here when writing a protocol: config, events, optional fake services, cleanup."""

import argparse
from dataclasses import replace
from pathlib import Path

from rpi_vstim.core.camera import FakeLocalCameraService
from rpi_vstim.core.config import CameraDeviceConfig
from rpi_vstim.display import FakeDisplayBackend
from rpi_vstim.session import load_config, new_session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--cameras", action="store_true", help="simulate configured cameras")
    args = parser.parse_args()
    loaded = load_config()
    config = replace(loaded, paths=replace(loaded.paths, output_root=args.output_root))
    if args.cameras:
        config = replace(config, cameras=replace(config.cameras, devices=(
            CameraDeviceConfig("face", "face", device="fake-face"),
            CameraDeviceConfig("behavior", "behavior", device="fake-behavior"),
        )))
    session = new_session(config, protocol_name="minimal", session_id="minimal-session")
    display = FakeDisplayBackend() if args.display else None
    cameras = FakeLocalCameraService(config.cameras) if args.cameras else None
    status = "COMPLETE"
    cleanup_error = None
    try:
        session.write_initial_outputs()
        session.record_event("PROTOCOL_STARTED")
        if display:
            display.open(config.display)
            session.write_display_result(display.present_color((127, 127, 127), frames=2))
        if cameras:
            cameras.start(session.context.session_root)
        session.record_event("PROTOCOL_FINISHED")
    except KeyboardInterrupt:
        status = "ABORTED"
        raise
    except Exception:
        status = "FAILED"
        raise
    finally:
        for close in (cameras.stop if cameras else None, display.close if display else None):
            if close is None:
                continue
            try:
                close()
            except (OSError, RuntimeError) as exc:
                cleanup_error = str(exc)
                status = "CLEANUP_FAILED"
        if session.context.session_root.exists():
            session.update_status(status, lifecycle=status, cleanup_errors=[cleanup_error] if cleanup_error else None)
            session.close()
    if cleanup_error:
        raise RuntimeError(cleanup_error)
    print(session.context.session_root)


if __name__ == "__main__":
    main()
