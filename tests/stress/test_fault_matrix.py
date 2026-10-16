from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.lifecycle import LifecycleState
from rpi_vstim.core.runtime import run_simulated_session


def config(tmp_path: Path):
    return config_from_mapping({"paths": {"output_root": tmp_path}})


def test_fault_matrix_has_explicit_terminal_outcomes(tmp_path):
    faults = (
        "session_metadata_write",
        "storage_low_space",
        "asset_manifest_creation",
        "producer_start",
        "producer_mid",
        "display_consumer_start",
        "display_consumer_mid",
        "finalization",
        "cleanup",
    )
    results = {
        fault: run_simulated_session(config(tmp_path), session_id=fault, fault=fault)
        for fault in faults
    }
    assert all(result.final_state in LifecycleState for result in results.values())
    assert results["cleanup"].final_state == LifecycleState.CLEANUP_FAILED
    assert results["session_metadata_write"].final_state == LifecycleState.FAILED
    assert all(
        (tmp_path / fault / "final_status.json").is_file()
        for fault in faults
    )
