# track-telemetry-mcp

Deterministic motorsports telemetry analysis exposed through MCP.

The design goal is simple: **Python measures; the LLM interprets.** Raw telemetry should not be summarized by eyeballing thousands of samples in a prompt when deterministic code can calculate the relevant metrics first.

## What it does

- Reuses [`BoYanZh/MotecLogGenerator`](https://github.com/BoYanZh/MotecLogGenerator) for RaceChrono `.rcz` decoding.
- Normalizes useful channels into a small `TelemetrySession` model.
- Finds lap/PB metadata and calculates lap summaries.
- Measures normalized-distance sections: entry speed, minimum speed, exit speed, pedal timing, and brake onset.
- Separates raw deceleration spikes from sustained braking performance.
- Reconstructs incidents using GPS travel direction, yaw-rate integration, steering, throttle, and braking.
- Exposes the deterministic functions as MCP tools.
- Includes a reusable analysis workflow in [`skill/SKILL.md`](skill/SKILL.md).

## Architecture

```text
RaceChrono .rcz
      |
      v
MotecLogGenerator
      |
      v
TelemetrySession
      |
      +--> laps / sections
      +--> braking
      +--> incident reconstruction
      +--> same-layout lap comparison
      |
      v
MCPServer
      |
      v
ChatGPT / Codex / OpenCode / Cursor / other MCP clients
```

The MCP wrapper is intentionally thin. All analysis functions are ordinary Python functions and can be tested without an MCP client.

## Project layout

```text
src/track_telemetry/
  channels.py        canonical field names
  models.py          TelemetrySession / Lap / ChannelSeries
  geometry.py        GPS projection, travel heading, yaw integration
  motec_adapter.py   MotecLogGenerator -> TelemetrySession
  laps.py            PB, lap/section metrics, same-layout comparison
  braking.py         brake events and sustained deceleration
  incidents.py       slide/spin reconstruction
  mcp_server.py      MCP tool wrapper

skill/SKILL.md       reusable LLM workflow
schemas/             documented MCP result shapes
tests/               synthetic-data tests only
```

## Requirements

- Python 3.10+
- `numpy`
- MCP Python SDK v2
- optional `MotecLogGenerator` dependency for RCZ input

## Install

Using `uv`:

```bash
git clone https://github.com/BoYanZh/track-telemetry-mcp.git
cd track-telemetry-mcp

uv venv
uv pip install -e ".[dev,rcz]"
```

The `rcz` extra installs MotecLogGenerator directly from its GitHub repository so this project does not duplicate the RCZ decoder.

## Run locally over stdio

The console entrypoint defaults to stdio:

```bash
TRACK_TELEMETRY_ROOT=/absolute/path/to/telemetry \
uv run track-telemetry-mcp
```

`TRACK_TELEMETRY_ROOT` is strongly recommended. When it is set, file-backed tools reject paths outside that directory.

Example MCP client config:

```json
{
  "mcpServers": {
    "track-telemetry": {
      "command": "uv",
      "args": ["run", "track-telemetry-mcp"],
      "env": {
        "TRACK_TELEMETRY_ROOT": "/absolute/path/to/telemetry"
      }
    }
  }
}
```

## Run over Streamable HTTP

For a local remote-MCP endpoint or a secure tunnel:

```bash
TRACK_TELEMETRY_TRANSPORT=streamable-http \
TRACK_TELEMETRY_ROOT=/absolute/path/to/telemetry \
uv run track-telemetry-mcp
```

The SDK serves the MCP endpoint over Streamable HTTP. This mode is useful behind a tunnel such as `cloudflared` during development.

**Do not expose the file-backed server directly to the public internet.** A production deployment should add authentication and replace arbitrary path arguments with a storage/session abstraction.

## MCP tools

### `inspect_session(path)`

Returns metadata, lap table, available channels, sample rates, and fastest timed lap.

### `list_laps(path)`

Returns a compact lap table and PB lap number.

### `analyze_lap(path, lap_number)`

Returns lap-level speed statistics, lateral-G 95th percentile, longitudinal-G minimum, yaw-rate 95th percentile, and full-throttle fraction when available.

### `analyze_section(path, lap_number, start_progress, end_progress)`

Measures a section addressed by normalized GPS distance `[0, 1]`:

- entry speed
- minimum speed and position
- exit speed
- throttle at entry/exit
- first full-throttle reapplication after minimum speed
- brake onset
- peak brake pressure

### `analyze_braking(path, lap_number=None)`

Separates:

- raw peak deceleration
- sustained 0.5 s deceleration
- sustained 1.0 s deceleration
- brake control ramp rate
- peak brake pressure/pedal
- entry and minimum speed for individual braking events

It intentionally does **not** claim ABS activation from brake pressure alone.

### `analyze_incident(path, start_s, end_s, ...)`

Reconstructs an incident using:

- GPS course/travel direction
- yaw-rate-integrated body-heading estimate
- sideslip proxy
- steering sign change
- throttle reduction
- brake onset
- snap-back detection
- optional user/video-marked surface-change time
- near-backwards sliding detection

Important: GPS heading is movement direction, not body orientation. Body heading is estimated, not directly measured.

### `compare_laps(...)`

Compares mini-sectors by normalized GPS distance **only when** `same_layout_confirmed=true`.

The guard is deliberate. Different layouts must be compared by shared physical sections aligned with GPS/onboard context, not by whole-lap percentage.

## Example analysis policy

The skill uses a fixed diagnostic taxonomy instead of generic advice:

1. conservative entry / braking too early
2. excessive minimum-speed loss / overslow
3. long or weak braking
4. throttle reapplied too late
5. weak exit speed
6. line / placement problem
7. already good enough / poor risk-reward to chase

For high-speed sections, reference-driver pace is evidence, not a target that should automatically be copied.

## Tests

Tests use synthetic telemetry only:

```bash
uv run pytest
uv run ruff check .
```

Raw `.rcz`, MoTeC files, video, and personal telemetry are ignored and should not be committed.

## Current limitations / next steps

- File-backed RCZ input only; no R2/GCS session store yet.
- No automatic named-corner database yet.
- Different-layout shared-corner GPS alignment is a workflow rule but is not yet a dedicated matching algorithm.
- No satellite-map UI yet.
- Incident body heading depends on yaw-rate sign convention and a pre-slide anchor.

Likely next steps are a session/object-storage abstraction, a track/corner definition format, and an optional UI for synchronized map + telemetry playback.
