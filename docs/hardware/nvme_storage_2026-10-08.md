# NVMe production session storage

The Pi 5 production SSD is a 953.9 GiB nominal NVMe device. Its existing ext4
filesystem UUID is `18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99`, mounted by the
existing fstab entry at `/mnt/behavbox_ssd`. A direct 1 GiB write measured
about 438 MB/s.

Production natural-image sessions use `/mnt/behavbox_ssd/sessions/<session-id>`
directly. There is no SD-card staging or post-session copy. Before any KMS,
camera, or GPIO acquisition, the runner requires a writable mount with source
`/dev/nvme0n1p1`, type `ext4`, the UUID above, and at least 20 GiB free. Failure
aborts rather than redirecting to a local path.

The session metadata records output-root, mount identity, capacity, and free
space at start and end. The intended operator command is:

```text
cd /home/pi/rpi_vstim_suite
rpi-vstim natural-images run --mouse-id V1_2 \
  --output-root /mnt/behavbox_ssd/sessions \
  --licks --cameras --camera-preview
```

PoE is not part of NVMe validation and remains pending hardware investigation.
