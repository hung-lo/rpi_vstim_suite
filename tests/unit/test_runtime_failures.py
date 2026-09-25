import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.lifecycle import LifecycleState
from rpi_vstim.core.runtime import build_simulated_services, run_simulated_session
from rpi_vstim.core.session import SessionOutput
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan


def small_plan():
    return build_plan(
        NaturalImageSettings(
            images=("a", "b"),
            trial_count=1,
            initial_gray_frames=1,
            final_gray_frames=1,
            image_duration_s=1 / 60,
            iti_frames=(1,),
        )
    )


def make_config(tmp_path):
    return config_from_mapping({"paths": {"output_root": tmp_path}})


def test_display_gpio_camera_and_event_failures_cleanup(tmp_path, monkeypatch):
    cases = []

    display_services = build_simulated_services(make_config(tmp_path))
    display_services.display.present_color = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("display failed")
    )
    cases.append(("display", display_services, "display failed"))

    gpio_services = build_simulated_services(make_config(tmp_path))
    gpio_services.hardware.start = lambda: (_ for _ in ()).throw(RuntimeError("gpio failed"))
    cases.append(("gpio", gpio_services, "gpio failed"))

    camera_services = build_simulated_services(make_config(tmp_path))
    original_manifest = camera_services.cameras.manifest
    camera_failed = False

    def fail_camera_once():
        nonlocal camera_failed
        if not camera_failed:
            camera_failed = True
            raise RuntimeError("camera task failed")
        return original_manifest()

    camera_services.cameras.manifest = fail_camera_once
    cases.append(("camera", camera_services, "camera task failed"))

    for session_id, services, message in cases:
        result = run_simulated_session(
            make_config(tmp_path), plan=small_plan(), session_id=session_id, services=services
        )
        assert result.final_state == LifecycleState.FAILED
        assert result.error == message
        assert result.services.hardware.backend.outputs_safe
        assert result.services.display.config is None

    event_services = build_simulated_services(make_config(tmp_path))
    original_record = SessionOutput.record_event
    failed = False

    def fail_event(self, event, **kwargs):
        nonlocal failed
        if event == "PLAN_EVENT" and not failed:
            failed = True
            raise RuntimeError("event log failed")
        return original_record(self, event, **kwargs)

    monkeypatch.setattr(SessionOutput, "record_event", fail_event)
    result = run_simulated_session(
        make_config(tmp_path), plan=small_plan(), session_id="event", services=event_services
    )
    assert result.final_state == LifecycleState.FAILED
    assert result.error == "event log failed"
    assert result.services.hardware.backend.outputs_safe


def test_manifest_failure_becomes_terminal_without_orphan_created(tmp_path, monkeypatch):
    original = SessionOutput.update_status
    failed = False

    def fail_once(self, status, **kwargs):
        nonlocal failed
        if status == "COMPLETE" and not failed:
            failed = True
            raise RuntimeError("manifest failed")
        return original(self, status, **kwargs)

    monkeypatch.setattr(SessionOutput, "update_status", fail_once)
    result = run_simulated_session(make_config(tmp_path), plan=small_plan(), session_id="manifest")
    manifest = json.loads((tmp_path / "manifest" / "session_manifest.json").read_text())
    assert result.final_state == LifecycleState.FAILED
    assert manifest["status"] == "FAILED"
