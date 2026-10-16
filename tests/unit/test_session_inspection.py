import json
import subprocess

from rpi_vstim.cli import build_parser
from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.core.session import inspect_session


def add_mp4_artifacts(root):
    output = root / "camera" / "face" / "capture.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"x" * 2048)
    (root / "camera_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cameras": [
                    {
                        "camera_id": "face",
                        "backend": "rpicam",
                        "output_path": "camera/face/capture.mp4",
                        "requested_width_px": 640,
                        "requested_height_px": 480,
                        "requested_fps": 30,
                        "pixel_format_or_codec": "h264",
                        "start_monotonic_ns": 100,
                        "stop_monotonic_ns": 1000,
                        "verification_state": "recorded_unverified",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "display_results.jsonl").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kernel_timestamp_clock": "monotonic",
                "first_page_flip_kernel_event_ns": 200,
                "last_page_flip_kernel_event_ns": 300,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "display_results.json").write_text(
        json.dumps({"schema_version": 1, "record_count": 1}), encoding="utf-8"
    )


def mp4_probe_payload(*, count_frames=False):
    stream = {
        "codec_name": "h264",
        "width": 640,
        "height": 480,
        "avg_frame_rate": "30/1",
        "time_base": "1/90000",
        "start_time": "0",
        "duration": "0.5",
    }
    if count_frames:
        stream["nb_read_frames"] = "15"
    return json.dumps(
        {
            "streams": [stream],
            "format": {
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "start_time": "0",
                "duration": "0.5",
            },
        }
    )


def test_inspect_session_reports_complete_outputs_without_mutation(tmp_path):
    config = config_from_mapping({"paths": {"output_root": tmp_path}})
    run_simulated_session(config, session_id="inspectable")
    root = tmp_path / "inspectable"
    before = (root / "session_manifest.json").read_text()
    report = inspect_session(root)
    assert report["status"] == "COMPLETE"
    assert report["required_files_present"]
    assert not report["incomplete"]
    assert report["last_event"]["event"] == "SESSION_FINISHED"
    assert (root / "session_manifest.json").read_text() == before


def test_inspect_session_recognizes_interrupted_output(tmp_path):
    root = tmp_path / "partial"
    root.mkdir()
    (root / "session_manifest.json").write_text(json.dumps({"status": "CREATED", "incomplete": True}))
    (root / ".session-incomplete").write_text("incomplete\n")
    report = inspect_session(root)
    assert report["status"] == "CORRUPT"
    assert report["incomplete"]
    assert "plan.json" in report["missing_required_files"]
    assert "session_manifest.json" in report["corrupt_artifacts"]


def test_inspect_session_detects_future_schema_without_mutation(tmp_path):
    config = config_from_mapping({"paths": {"output_root": tmp_path}})
    run_simulated_session(config, session_id="future")
    root = tmp_path / "future"
    manifest = json.loads((root / "session_manifest.json").read_text())
    manifest["schema_version"] = 999
    (root / "session_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = inspect_session(root)
    assert report["status"] == "CORRUPT"
    assert report["corrupt_artifacts"] == ["session_manifest.json"]


def test_inspect_session_detects_display_stream_corruption_and_orphans(tmp_path):
    config = config_from_mapping({"paths": {"output_root": tmp_path}})
    run_simulated_session(config, session_id="stream")
    root = tmp_path / "stream"
    (root / "display_results.jsonl").write_text("not-json\n", encoding="utf-8")
    (root / ".leftover.tmp").write_text("partial", encoding="utf-8")
    report = inspect_session(root)
    assert "display_results.jsonl" in report["corrupt_artifacts"]
    assert report["orphan_artifacts"] == [".leftover.tmp"]


def test_inspect_session_fast_qc_clears_old_timeout_label_and_deep_qc_is_opt_in(tmp_path, monkeypatch):
    config = config_from_mapping({"paths": {"output_root": tmp_path}})
    run_simulated_session(config, session_id="fast-mp4-qc")
    root = tmp_path / "fast-mp4-qc"
    add_mp4_artifacts(root)
    commands = []

    def ffprobe(command, **kwargs):
        commands.append((command, kwargs))
        deep = "-count_frames" in command
        return subprocess.CompletedProcess(
            command, 0, mp4_probe_payload(count_frames=deep), ""
        )

    monkeypatch.setattr("rpi_vstim.camera.supervisor.subprocess.run", ffprobe)
    report = inspect_session(root)
    assert report["status"] == "COMPLETE"
    assert report["camera_fast_qc"][0]["ok"]
    assert report["camera_fast_qc"][0]["scientific_interval_covered"]
    assert "-count_frames" not in commands[0][0]
    assert report["camera_deep_qc"] is None

    deep_report = inspect_session(root, deep_camera_qc=True)
    assert deep_report["camera_deep_qc"][0] == {
        "camera_id": "face",
        "ok": True,
        "decoded_frame_count": 15,
    }
    assert "-count_frames" not in commands[1][0]
    assert "-count_frames" in commands[2][0]
    assert build_parser().parse_args(
        ["inspect-session", str(root), "--deep-camera-qc"]
    ).deep_camera_qc
