import json
from dataclasses import replace

import pytest

from rpi_vstim.core.config import Config
from rpi_vstim.core.session import new_session


def test_session_writes_common_outputs(tmp_path):
    config = replace(Config(), paths=replace(Config().paths, output_root=tmp_path))
    output = new_session(config, session_id="test-session")
    output.write_initial_outputs()
    assert (tmp_path / "test-session" / "session_manifest.json").is_file()
    assert (tmp_path / "test-session" / "resolved_config.json").is_file()
    assert (tmp_path / "test-session" / "provenance.json").is_file()
    output.write_preflight_report({"passed": True})
    output.update_status("COMPLETE", lifecycle="COMPLETE")
    assert (tmp_path / "test-session" / "preflight_report.json").is_file()
    assert (tmp_path / "test-session" / "final_status.json").is_file()


def test_session_persists_seed_and_source_commit(tmp_path, monkeypatch):
    config = replace(Config(), paths=replace(Config().paths, output_root=tmp_path))
    monkeypatch.setenv("RPI_VSTIM_SOURCE_COMMIT", "abc123")
    output = new_session(config, session_id="reproducible", seed=42)
    output.write_initial_outputs()

    root = tmp_path / "reproducible"
    manifest = json.loads((root / "session_manifest.json").read_text())
    provenance = json.loads((root / "provenance.json").read_text())
    assert manifest["random_seeds"] == {"protocol": 42}
    assert manifest["source_commit"] == "abc123"
    assert provenance["repository_commit"] == "abc123"


def test_session_records_selected_asset_identities(tmp_path):
    config = replace(Config(), paths=replace(Config().paths, output_root=tmp_path))
    output = new_session(config, session_id="asset-provenance")
    output.write_initial_outputs()
    output.write_plan({"metadata": {"selected_images": ["a.png"]}})
    output.write_asset_manifest(
        {
            "manifest_hash": "session-manifest",
            "source_manifest_sha256": "repository-manifest",
            "entries": [{"relative_path": "a.png", "sha256": "image-sha"}],
        }
    )

    root = tmp_path / "asset-provenance"
    provenance = json.loads((root / "provenance.json").read_text())
    table = json.loads((root / "selected_image_table.json").read_text())
    assert provenance["asset_manifest_digest"] == "repository-manifest"
    assert provenance["selected_image_identities"] == [
        {"filename": "a.png", "sha256": "image-sha"}
    ]
    assert table["images"][0]["sha256"] == "image-sha"


def test_session_id_cannot_escape_output_root(tmp_path):
    config = replace(Config(), paths=replace(Config().paths, output_root=tmp_path))
    with pytest.raises(ValueError, match="unsupported"):
        new_session(config, session_id="../not-a-session")
