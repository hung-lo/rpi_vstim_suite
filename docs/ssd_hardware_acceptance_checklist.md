# SSD hardware acceptance checklist

This checklist is prepared for the next lab session. It was not run during
the Mac software-groundwork pass.

1. Run `lsblk -f`, `blkid`, `findmnt`, and inspect `/etc/fstab`.
2. Identify the expected SSD by filesystem/device identity without formatting.
3. Validate existing mount intent; mount only when the target is unambiguous.
4. Confirm the mount is writable and has the required free space.
5. Run a bounded disposable write/read test and record conservative throughput.
6. Start one local camera and verify output growth on the SSD.
7. Start both local cameras and verify deterministic per-camera files/manifests.
8. Repeat display + dual-camera + SSD writes under the eventual camera mode.
9. Collect the corrected 300-frame leased kernel timestamp trace.
10. Record RAM, CPU/load, temperature, throttling, free space, and page-flip data.
11. Interrupt and recover cleanly; verify no orphan camera process remains.
12. Confirm no output fell back to `/`, the home directory, `/tmp`, or the Pi SD card.

The software preflight is fail-closed by default: it requires a mounted,
writable configured root, free-space thresholds, and can require an expected
device identity through an injected identity reader. It does not mount,
format, discover, or select hardware automatically.
