# Addendum — SSD Deferred, Dual-Display Roles, Scoped Phase 3 Authorization

This addendum updates the autonomous work instructions for `rpi_vstim_suite`.

It does **not** replace the authoritative plan:

`RPI5_UNIFIED_VSTIM_CODEX_IMPLEMENTATION_PLAN.md`

It records two user-confirmed hardware assumptions and a narrow sequencing exception so work can continue while the experiment SSD is physically absent.

## User-confirmed facts / assumptions

### Experiment SSD
The experiment SSD is **not currently attached** and is expected to be connected in the coming weeks.

Therefore:

- Do not keep retrying to find or mount it.
- Do not modify `/etc/fstab`.
- Do not create a fake `/mnt/hd` mapping.
- Do not substitute the Pi SD card as the production recording destination.
- Mark storage throughput and production-storage acceptance as **deferred until the SSD is physically attached**.
- Continue software work that does not depend on the production SSD.

The existing `/etc/fstab` reference to `/mnt/behavbox_ssd` should be preserved as an observed rig fact, not rewritten based on assumptions.

### Dual displays
The experiment Pi is intentionally connected to two screens:

- **provisional stimulus display:** `HDMI-A-1`
- **provisional camera-preview display:** `HDMI-A-2`

This mapping is user-authorized as a working assumption.

If the physical cables turn out to be reversed later, the mapping should be easy to change in configuration without code changes.

Do not hard-code these connector names deep inside protocol logic.

Prefer explicit configurable display roles, e.g.:

- `stimulus_display_connector`
- `preview_display_connector`

The current audited modes were:

- `HDMI-A-1`: connected/active at approximately `1024x600@59.82`, preferred `1024x600@59.821`, also supports `1280x720@60`
- `HDMI-A-2`: connected/active at approximately `1024x600@59.82`, supports `1024x600`

Treat those as audit findings, not universal defaults.

---

# Gate 2 interpretation while SSD is absent

Canonical Gate 2 is **not fully satisfied** because production storage validation cannot be completed without the physical SSD.

However, the user authorizes a **scoped sequencing exception**:

> The missing SSD must not block display/KMS bring-up work that does not depend on production storage.

Document this explicitly in `IMPLEMENTATION_STATUS.md`.

Use wording equivalent to:

- Gate 2 overall: incomplete / storage sub-gate deferred
- Pi platform readiness: verified
- camera enumeration readiness: verified
- display discovery readiness: verified enough for KMS probe
- production storage readiness: deferred until SSD attachment

Do not falsely mark the full Gate 2 as passed.

---

# Scoped Phase 3 work now authorized

You may proceed with the **display-only portion of canonical Phase 3**, despite the deferred storage sub-gate.

This authorization is limited to:

1. standalone KMS/DRM probe work
2. connector/mode selection logic
3. display backend interface implementation
4. targeting the provisional stimulus connector `HDMI-A-1`
5. refresh/vblank/page-flip timing instrumentation
6. safe display open/close/restore behavior
7. photodiode-patch plumbing needed for display timing tests
8. unit tests/mocks for DRM discovery/selection
9. short no-mouse display smoke tests
10. documentation of actual timing/mode behavior

The preview display `HDMI-A-2` should remain separate from the stimulus rendering path.

Do not yet build a complex preview GUI unless it is already part of the plan and can be done without interfering with stimulus timing.

---

# Phase 3 safety limits

While the user is away, do NOT:

- change boot configuration
- reboot unless absolutely required and explicitly authorized elsewhere
- disable the second display globally
- assume HDMI connector numbering is universally stable
- modify production storage configuration
- run long full-session experiments
- run reward/water/suction hardware
- toggle unknown GPIO
- perform final integrated dual-camera + display + GPIO acceptance
- claim final display timing acceptance without measured evidence
- merge into `main`

If a KMS test can temporarily blank or take ownership of the stimulus screen, keep it short and controlled.

Do not take over the camera-preview display unless specifically needed for a diagnostic and safely reversible.

---

# Display-role configuration requirement

Before or during Phase 3, ensure the architecture allows display roles to be configured.

At minimum, there should be a clear path to specify:

- stimulus connector
- preview connector or preview-disabled state
- requested stimulus mode
- requested refresh rate
- whether exact refresh is mandatory vs nearest acceptable mode

Connector selection should fail clearly if:

- configured connector is missing
- configured connector is disconnected
- requested mode is unsupported
- multiple candidate connectors are ambiguous when no explicit selection is provided

Do not silently fall back to the wrong screen.

Add hardware-independent tests for these cases.

---

# SSD-independent work that should continue

While the SSD is absent, continue all safe software milestones from:

`CODEX_LONG_AUTONOMOUS_WORK_PLAN_PHASE2_BLOCKED.md`

Especially:

- local development/test environment restoration
- hardware discovery parser tests
- stable dual-camera identity handling
- storage-path abstraction
- bounded-buffer/resource audit
- failure injection
- determinism/provenance checks
- legacy/source conformance
- CLI/config contract hardening
- telemetry compatibility tests
- simulated acceptance
- documentation cleanup

For storage-specific code, use temporary test directories in unit/integration tests.

Do not treat temporary storage performance as representative of the future experiment SSD.

---

# What remains deferred until SSD attachment

When the SSD is physically attached in the coming weeks, return to the deferred storage sub-gate and verify:

- exact device identity
- UUID/filesystem
- intended mount point
- persistent mount configuration
- free space
- writable session/output root
- temporary sequential write/read throughput
- dual-camera sustained write behavior
- failure behavior when storage is unavailable or low
- no accidental fallback to SD card

Only then close the storage portion of Gate 2 and later perform the full same-Pi resource/load acceptance required by the V2 plan.

---

# Reporting

In every status update, distinguish:

- **verified**
- **provisional user-authorized assumption**
- **deferred because hardware is absent**
- **software-only validated**
- **real-hardware validated**

The current display mapping should be recorded as:

- `HDMI-A-1` = provisional stimulus display
- `HDMI-A-2` = provisional camera-preview display

Do not present that mapping as physically re-verified unless it is later checked directly.

Continue working autonomously through safe tasks and the scoped display-only Phase 3 work. Stop before any task that requires destructive/system-level changes, production reward hardware, or final integrated load acceptance.
