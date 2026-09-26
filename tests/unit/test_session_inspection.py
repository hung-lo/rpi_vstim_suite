import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.core.session import inspect_session


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
