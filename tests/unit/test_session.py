import json
from dataclasses import replace

from rpi_vstim.core.config import Config
from rpi_vstim.core.session import new_session


def test_session_writes_common_outputs(tmp_path):
    config = replace(Config(), paths=replace(Config().paths, output_root=tmp_path))
    output = new_session(config, session_id="test-session")
    output.write_initial_outputs()
    assert (tmp_path / "test-session" / "session_manifest.json").is_file()
    assert (tmp_path / "test-session" / "resolved_config.json").is_file()
    assert (tmp_path / "test-session" / "provenance.json").is_file()


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
