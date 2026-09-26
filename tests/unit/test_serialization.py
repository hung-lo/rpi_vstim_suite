import json

from rpi_vstim.camera.supervisor import CameraWorkerStatus
from rpi_vstim.core.assets import AssetResolver
from rpi_vstim.core.resource_budget import ResourceBudgetInputs, estimate_budget
from rpi_vstim.core.storage import preflight_storage
from rpi_vstim.display.timing import analyze_flip_events, summarize_intervals


def test_new_dataclass_schemas_are_json_serializable(tmp_path):
    manifest = AssetResolver(tmp_path).build_manifest(())
    storage = preflight_storage(tmp_path, require_mount=False, allow_test_path=True)
    budget = estimate_budget(ResourceBudgetInputs(2, 2, "RGB565"))
    camera = CameraWorkerStatus("face", "face", "serial", "fake", True)
    summary = summarize_intervals((16_666.0,), nominal_refresh_hz=60.0)
    trace = analyze_flip_events([], nominal_refresh_hz=60.0)

    values = [
        manifest.as_dict(),
        storage.as_dict(),
        budget.as_dict(),
        camera.as_dict(),
        summary.as_dict(),
        trace.as_dict(),
    ]
    encoded = json.dumps(values, sort_keys=True)
    assert '"schema_version"' in encoded
