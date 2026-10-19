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
own persistent `--control-socket` and `--session-id` values when it launches the
engine.

Preparation validates configuration, storage availability, plans the selected
images, hashes and validates the assets, probes the configured display using
read-only `modetest` discovery, and resolves camera identities when cameras are
enabled. It may create the configured output-root directory, but it does not
create a session, start camera recording, acquire KMS, or start audio. READY
therefore has no acquisition clock running. START creates the session and
starts the requested acquisition services. Preparation and READY times are
preserved in session control provenance after START.

## Socket messages

The transport is one UTF-8 JSON object per connection, terminated by a newline.
The monitor's proposed request shape omits a schema field; the engine treats
that envelope as version 1. Clients may send `schema_version: 1` explicitly,
and any other explicit version is rejected. Responses always include
`schema_version: 1`. For example:

```json
{"command":"status"}
{"request_id":"start-001","command":"start"}
{"request_id":"stop-001","command":"stop"}
{"request_id":"abort-001","command":"abort"}
```

Mutating commands require a request ID. Acknowledgements include the same ID,
`ok`, current state, and a structured error on failure. The last 128 mutating
request IDs are cached: a retry with the same ID and body receives the original
acknowledgement without repeating the action; reusing an ID with a different
body is rejected. Requests are limited to 16 KiB. Multiple clients may query
status; all requests are processed serially by the engine.

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
