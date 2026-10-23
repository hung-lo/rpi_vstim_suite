# Operator control adapter

`rpi_vstim.control` provides the engine side of a local supervisor interface.
It is separate from the older manual-bait GPIO service. The engine remains the
only owner of the display, cameras, GPIO, audio, session, events, and storage.
Without `--operator-control`, existing protocol commands continue to start
normally.

## Natural-image launch

```bash
rpi-vstim natural-images run \
  --mouse-id <identifier> \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --licks --cameras --camera-preview \
  --session-id <session-id> \
  --operator-control \
  --telemetry-port 5055
```

The socket path may be omitted; the engine chooses a per-user, per-session path
under `XDG_RUNTIME_DIR`, or an owner-only directory under `/tmp`. The socket is
mode `0600`. Only clients with the same local user identity can connect. The
engine removes its socket on normal shutdown. `--telemetry-port` is optional and
publishes best-effort status snapshots to loopback UDP at 2 Hz; it carries no
commands. Telemetry startup failure does not stop the experiment.
The launched process prints its resolved socket path. A supervisor supplies its
own unique `--control-socket`, `--control-state-file`, and `--session-id` values
when it launches the engine. The state-file path must not already exist. For
backwards compatibility, `--control-state-file` is optional; a supervisor that
needs terminal recovery after process exit must provide it.

Hardware preparation validates configuration and storage, plans and validates
the selected images, probes the configured display using read-only `modetest`
discovery, and resolves camera identities when cameras are enabled. It may
create the output-root directory, but it does not create a session, start
cameras, acquire KMS, or start audio. READY therefore has no acquisition clock
running. START creates the session and starts the requested acquisition
services. Preparation and READY times are preserved in session control
provenance after START.

### Hardware-free Natural Images simulation

Use the existing fake display with an explicit output root to test the real
operator socket without probing KMS or starting cameras, GPIO, or audio:

```bash
rpi-vstim natural-images run \
  --mouse-id simulation \
  --config config/rigs/natural_images.operator_simulation.toml \
  --image-count 5 \
  --session-id monitor-simulation \
  --output-root /tmp/rpi-vstim-monitor-simulation \
  --operator-control --simulate \
  --control-socket /tmp/rpi-vstim-monitor-simulation.sock \
  --control-state-file /tmp/rpi-vstim-monitor-simulation-state.json
```

`--simulate` requires `--output-root` and rejects `--licks`, `--cameras`,
`--camera-preview`, and `--audio-coexistence`. PREPARING validates the selected
assets and plan; READY creates no session and starts no frame clock. START
creates a simulated session and advances the frame plan at the configured
nominal refresh rate using `FakeDisplayBackend`. STOP and ABORT follow the same
engine lifecycle and finalize their sessions normally. Session metadata marks
`simulated: true` and `display_backend: simulated`; events use
`SIMULATED_STIMULUS_PLAN_EVENT`, and no KMS trace or physical presentation
timestamp is produced. Simulation timing is for supervisor integration only.

### Supervisor parameter provenance sidecar

An installed monitor registry may add the trusted
`--operator-session-metadata <path>` argument. The supervisor creates a unique
mode-0600 JSON sidecar per launch; browser input cannot select its path or
contents. Natural Images validates schema version 1, session/subject/protocol
identity, profile identity/version, and the resolved `image_count` before
PREPARE. It copies the accepted snapshot to
`provenance.json` and `session_manifest.json`; the effective value is also
present in `resolved_config.json` and the seeded plan. The sidecar is optional
for older deployments and does not alter the Unix control-v1 message schema.

## Socket messages

The transport is one UTF-8 JSON object per connection, terminated by a newline.
The canonical v1 contract requires every request, including `status`, to contain
`schema_version: 1` and a nonempty `request_id`. Every response contains
`schema_version: 1` and echoes that exact `request_id`. The engine still accepts
some older messages without the v1 envelope for compatibility, but supervisors
and new clients should use the strict form:

```json
{"schema_version":1,"request_id":"status-001","command":"status"}
{"schema_version":1,"request_id":"start-001","command":"start"}
{"schema_version":1,"request_id":"stop-001","command":"stop"}
{"schema_version":1,"request_id":"abort-001","command":"abort"}
```

Acknowledgements include the exact request ID, `ok`, current state, and a
structured error on failure. A successful `start`, `stop`, or `abort` response
means the command was accepted; it does not mean cleanup has finished. In
particular STOP and a RUNNING ABORT normally acknowledge `FINISHING`, then the
terminal state is published after protocol cleanup. The last 128 mutating
request IDs are cached: a retry with the same ID and body receives the original
acknowledgement without repeating the action; reusing an ID with a different
body is rejected. Requests are limited to 16 KiB. Multiple clients may query
status; all requests are processed serially by the engine.

## Durable state after process exit

When `--control-state-file` is supplied, the engine writes a small versioned
JSON lifecycle artifact. It is separate from the scientific session record and
does not replace session events or final status. The file is mode `0600`; its
parent directory is created with owner-only permissions if needed. The first
snapshot is created without overwriting an existing path, so a supervisor must
choose a new path for each launch. Updates use a fully written and synced
temporary file followed by atomic replacement.

The artifact identifies its `session_id`, `protocol`, engine PID, and unique
`control_instance_id`, and records the lifecycle state, terminal flag, update
times, terminal reason, request ID where STOP/ABORT caused the outcome, concise
error summary, and session output path when available. The supervisor should
remember the instance ID observed in startup output or live status and reject a
file whose schema, session, protocol, or instance ID does not match that launch.

While the control socket is alive, live engine status is authoritative. After
the socket disappears, the matching engine-written state file is authoritative
for lifecycle recovery. If it is absent, malformed, nonterminal, or mismatched,
the supervisor should treat the process as exited without a recoverable terminal
state; it must not infer COMPLETE or ABORTED from an exit code or parse
VStim-specific scientific files.

Lifecycle is engine-owned:

```text
PREPARING -> READY -> RUNNING -> FINISHING -> COMPLETE
      |        |          |             |
     ERROR   ABORTED    ABORTED         ERROR
```

Disconnecting a client changes no state. Reconnecting and querying `status`
recovers the session ID, protocol, state, elapsed time, ETA when known,
capabilities, hardware status, integrity summary, and protocol state. STOP asks
the natural-image producer to end at a frame boundary and uses normal cleanup;
the session is marked COMPLETE with the partial display count recorded. ABORT
uses the same cleanup path and marks the session ABORTED. Neither uses SIGKILL.
The engine atomically persists each lifecycle transition, including the terminal
state, before notifying its launcher that the run is finished and before closing
the control socket.

## Capabilities and semantic actions

Capabilities are advertised by the protocol and filtered by lifecycle state.
Natural images advertises `start` and `abort` in READY, then `stop` and `abort`
while RUNNING; it does not advertise pause or bait actions. A protocol may
advertise semantic bait actions in READY or RUNNING when its task policy allows
them, then provide a callback:

```python
def deliver_bait(channel: str, request_id: str) -> dict[str, str]:
    # The protocol validates task state and delegates to its existing safe
    # reward service; it never accepts a GPIO number from the supervisor.
    return {"channel": channel, "request_id": request_id}

control = ExperimentControl(
    session_id=session_id,
    protocol="your-protocol",
    run=run_protocol,
    capabilities={"bait_left": True},
    semantic_actions={"deliver_bait": deliver_bait},
)
```

The engine rejects actions that are not advertised or are invalid for the
current state. Accepted semantic actions are recorded as `OPERATOR_ACTION` in
the session event stream with source, channel, request ID, and result. No reward
output is wired through this interface in the current natural-image adapter.

## Telemetry boundary

Control requests and acknowledgements use only the reliable Unix socket. The
optional UDP path carries snapshots only and may drop packets. Telemetry adds
the generic `session`, `hardware`, `integrity`, `protocol_state`, and
`capabilities` objects while retaining the existing envelope. It does not
replace `events.jsonl`, KMS timestamps, or other scientific records. Missing
hardware values mean “not reported”; the monitor must not probe or control
devices itself.

## Adding another protocol

Keep task logic in the protocol. Prepare deterministic plans and preflight
before `mark_ready()`. Give `ExperimentControl` a runner that starts acquisition
only after START, polls its `stop_requested` and `abort_requested` flags at safe
protocol boundaries, performs normal cleanup, and returns COMPLETE, ABORTED, or
an error result. Bind its operator events to that session's authoritative event
writer. Advertise only the semantic actions the protocol can safely perform.
This adapter is currently integrated with natural images only; drifting
gratings, retinotopy, and Go/NoGo are not wired to it.
