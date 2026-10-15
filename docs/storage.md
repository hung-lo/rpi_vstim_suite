# Storage and session output

Generic profiles use a configurable output directory. Each session gets a
unique directory; `new_session` refuses to overwrite an existing ID. Basic
session metadata includes `resolved_config.json`, `provenance.json`,
`session_manifest.json`, `final_status.json`, and `events.csv`. Integrated
runs additionally write `events.jsonl` with clock mapping, display/KMS
results and trace, camera manifests and `capture.mp4`, plans, selected image
tables, and asset provenance when used. These artifacts are conditional.

The Box151 production root is `/mnt/behavbox_ssd/sessions`. Preflight
requires its expected mounted ext4 NVMe source/UUID, writable root, and
minimum free space before acquisition. There is no silent SD-card fallback.
Cameras record directly into session storage. Other rigs select their own
root; Box151 SSD is not a generic dependency.

See [data format](data_format.md) and [NVMe evidence](hardware/nvme_storage_2026-10-08.md).
