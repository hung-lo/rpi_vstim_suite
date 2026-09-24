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

