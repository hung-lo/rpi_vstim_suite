# Writing a protocol

Start with [minimal_session.py](../examples/minimal_session.py). Load a TOML
profile with `rpi_vstim.session.load_config`, choose a unique session ID, and
call `new_session`. `write_initial_outputs()` creates the self-contained
directory. Write a deterministic plan with `write_plan()` before frames.
`rpi_vstim.display` exposes fake and KMS backends; `open(config.display)`,
`present`/`present_color`/`present_sequence`, and `close()` are the basic shape.

Emit ordinary events with `SessionOutput.record_event`. Integrated
timing-sensitive protocols use `rpi_vstim.events.UnifiedEventStream` and
`SessionClock` for bounded JSONL handoff without disk I/O in callbacks.
Select cameras in `config.cameras.devices` and resolve stable identities
before creating `LocalCameraSupervisor`. Select inputs in rig config or
explicitly as in [gpio_input.py](../examples/gpio_input.py). Output services
require configured roles, safe polarity, and deliberate activation.

Use `try/finally` around acquired services. On Ctrl-C, stop cameras, close
display/GPIO, mark `ABORTED`, then close outputs. Mark `COMPLETE` only after
required services and cleanup succeed; failures become `FAILED` or
`CLEANUP_FAILED`. Production `core.lifecycle`/`core.runtime` implements these
boundaries. `protocols.base.ExperimentProtocol` describes `build_plan` and
`run`; registration is explicit in `protocols/__init__.py`. A new protocol
can also be a normal script using the public service modules.

The [natural-image protocol](../src/rpi_vstim/protocols/natural_images/) shows
deterministic planning and selection. Its Box151 runner in
`core.natural_image_demo` integrates KMS, cameras, licks, logs, and storage.
Supply your own image corpus; this repository grants no dataset rights.
