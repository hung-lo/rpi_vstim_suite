# Documentation map

## Current software architecture

- [Architecture](architecture.md)
- [Configuration and compatibility](compatibility_matrix.md)
- [Display backend](display_backend.md)
- [Natural-image assets](natural_image_assets.md)
- [Camera workflow](camera_workflow.md)
- [Storage and session format](data_format.md)
- [Telemetry](telemetry_protocol.md)
- [Resource budget](resource_budget.md)
- [Native sequence transport](native_sequence_transport_abi.md)
- [Next-lab acceptance](next_lab_acceptance.md)

## RC hardening

- [Architecture audit](pre_hardware_architecture_audit_2026-09-26.md)
- [Test-gap audit](pre_hardware_test_gap_audit_2026-09-26.md)
- [RC hardening report](pre_hardware_rc_hardening_report_2026-09-26.md)

## Evidence and deferred gates

The [hardware reports](hardware/) are historical evidence and are not rewritten
by software-only work. Current authoritative Phase 3 measurements preserve
HDMI-A-2 / connector 42 for visual stimulus and HDMI-A-1 / connector 33 for
the camera monitor. Physical KMS, camera topology and capture, experiment SSD
identity/throughput, GPIO/reward/lick, and photodiode validation are deferred
until the rig is available. The SD card is not production-storage acceptance.

The current Phase 4 continuous-KMS natural-image issue and validation status is
tracked in
[pi5_phase4_continuous_kms_natural_image_2026-10-02.md](hardware/pi5_phase4_continuous_kms_natural_image_2026-10-02.md).

The [source parity matrix](source_parity_matrix.md) records frozen-reference
behavior and intentional differences. Frozen reference repositories remain
read-only inputs.
