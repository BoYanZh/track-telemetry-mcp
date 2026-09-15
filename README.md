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
- Recovers **approximate reference telemetry** from calibrated onboard-video overlays when the reference driver has no raw log.
- Generates a standalone interactive HTML incident player with GPS path, estimated body heading, travel direction, sideslip proxy, and event timeline.
- Exposes the deterministic functions as MCP tools.
- Includes a reusable analysis workflow in [`skill/SKILL.md`](skill/SKILL.md).
- Includes task-specific coaching prompts in [`prompts/`](prompts/).

## Architecture

```text
                         +---------------------------+
RaceChrono .rcz -------->| MotecLogGenerator adapter |
                         +-------------+-------------+
                                       |
                                       v
                               TelemetrySession
                                       |
                +----------------------+--------------------+
                |                      |                    |
                v                      v                    v
          laps / sections          braking          incident reconstruction
                |                                           |
                |                                           +--> HTML player
                |
                +--> same-layout lap comparison

Reference onboard video
        |
        v
calibrated overlay CV extractor
        |
        +--> pseudo telemetry: time / map X-Y / speed / needle angle

All deterministic functions
        |
        v
MCPServer
        |
        v
ChatGPT / Codex / OpenCode / Cursor / other MCP clients
```

Raw logger telemetry and video-derived pseudo telemetry are deliberately kept distinct. A video overlay is useful reference evidence, not an equal-quality substitute for the user's RCZ data.

## Project layout

```text
src/track_telemetry/
  channels.py          canonical field names
  models.py            TelemetrySession / Lap / ChannelSeries
  geometry.py          GPS projection, travel heading, yaw integration
  motec_adapter.py     MotecLogGenerator -> TelemetrySession
  laps.py              PB, lap/section metrics, same-layout comparison
  braking.py           brake events and sustained deceleration
  incidents.py         slide/spin reconstruction
  reference_video.py   calibrated onboard-overlay -> pseudo telemetry
  visualization.py     incident JSON -> standalone HTML
  templates/
    incident_player.html
  mcp_server.py        MCP tool wrapper

examples/
  reference_overlay_config.example.json
prompts/
  session_coach.md
  reference_comparison.md
  incident_review.md
  post_session_debrief.md
skill/SKILL.md         reusable LLM workflow
schemas/               documented MCP result shapes
tests/                 synthetic-data tests only
```

## Requirements

- Python 3.10+
- `numpy`
- MCP Python SDK v2
- optional `MotecLogGenerator` dependency for RCZ input
- optional OpenCV dependency for reference-video overlay extraction

## Install

Using `uv`:

```bash
git clone https://github.com/BoYanZh/track-telemetry-mcp.git
cd track-telemetry-mcp

uv venv
uv pip install -e ".[dev,rcz,video]"
```

Use only the extras you need. The `rcz` extra installs MotecLogGenerator directly from its GitHub repository so this project does not duplicate the RCZ decoder. The `video` extra installs headless OpenCV.

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

The MCP Python SDK v2 serves the endpoint over Streamable HTTP. This mode is useful behind a tunnel such as `cloudflared` during development.

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

Set `include_samples=true` when a downstream visualization needs the reconstructed path. `sample_stride=1` preserves native GPS samples for smooth playback.

Important: GPS heading is movement direction, not body orientation. Body heading is estimated, not directly measured.

### `compare_laps(...)`

Compares mini-sectors by normalized GPS distance **only when** `same_layout_confirmed=true`.

The guard is deliberate. Different layouts must be compared by shared physical sections aligned with GPS/onboard context, not by whole-lap percentage.

### `extract_reference_overlay(...)`

Recovers approximate telemetry from another driver's onboard overlay.

Inputs:

- local video path
- overlay calibration JSON
- time range
- sampling frequency, e.g. 10 Hz
- optional CSV output path

Current automated channels:

- analog speedometer needle angle
- calibrated speed in mph
- track-map marker X/Y in the video's overlay coordinate system

The useful output schema mirrors the prototype used for the Buttonwillow reference analysis:

```text
video_t,map_x,map_y,speed_mph,needle_angle
```

Start with [`examples/reference_overlay_config.example.json`](examples/reference_overlay_config.example.json). The configuration specifies:

- speedometer ROI
- needle center
- multiple verified angle/speed anchors
- optional track-map ROI
- optional HSV color range for the moving map marker

This is **pseudo telemetry**. Do not claim RCZ-level precision. Brake/throttle percentages, RPM, gear, or text overlays are not automatically extracted unless a calibrated detector for that overlay is added.

### `render_incident_player(...)`

Writes a standalone HTML animation from real incident GPS samples.

It can show:

- complete incident path
- current position
- estimated vehicle body orientation
- GPS travel/velocity direction
- speed, yaw rate, steering, throttle, sideslip proxy
- detected event markers and buttons
- optional clean/reference lap path
- 0.25x / 0.5x / 1x / 2x playback

A clean-lap line is only a trajectory reference. It is **not** treated as a track/asphalt boundary.

Example:

```text
render_incident_player(
    path="session.rcz",
    start_s=92.5,
    end_s=103.5,
    anchor_s=92.5,
    surface_change_s=95.0,
    sample_stride=1,
    reference_lap_number=26,
    output_html="spin.html"
)
```

The player is deliberately map-source agnostic. It does not embed a non-georeferenced satellite screenshot because that creates scale/alignment errors. A future map layer should use georeferenced tiles or orthophotos.

## Reference-video workflow

When a reference driver publishes an onboard with a telemetry overlay but no raw log:

1. Pick a representative frame and record the speedometer and track-map ROIs.
2. Record the analog needle center in full-frame pixel coordinates.
3. Collect at least two, preferably several, verified `(needle angle, speed)` anchors.
4. If the track-map marker has a distinctive color, calibrate an HSV range for it.
5. Run `extract_reference_overlay` around the reference lap at roughly 10 Hz.
6. Check detection continuity before trusting the resulting curve.
7. Use recovered speed/map position for approximate shared-corner alignment and speed comparison.
8. Keep raw RCZ measurements and pseudo telemetry labeled separately in the final analysis.

For different track layouts, the overlay map/onboard video can identify shared physical corners, but whole-lap normalized percentage comparison remains invalid.

## Incident HTML workflow

The HTML renderer generalizes the useful parts of the Buttonwillow spin prototype:

```text
analyze_incident(..., include_samples=True, sample_stride=1)
        |
        v
incident JSON
        |
        v
render_incident_player / write_incident_html
        |
        v
standalone interactive HTML
```

The renderer does not bake Buttonwillow-specific event times or base64 telemetry into the template.

## Coaching prompts

The skill defines long-lived analysis rules; the files in `prompts/` define the structure of a specific coaching task.

- [`prompts/session_coach.md`](prompts/session_coach.md) — **default** general telemetry coach. Finds the highest-ROI lap-time opportunities and ends with at most three next-session changes plus success metrics and safety/abort conditions.
- [`prompts/reference_comparison.md`](prompts/reference_comparison.md) — external reference-driver comparison, including video-derived pseudo telemetry and different-layout caution.
- [`prompts/incident_review.md`](prompts/incident_review.md) — slide/spin/off-track causal timeline, response timing, prevention, and evidence-vs-inference separation.
- [`prompts/post_session_debrief.md`](prompts/post_session_debrief.md) — compact end-of-session learning loop: what improved, what remained inconsistent, and the next experiments.

For a normal request such as "analyze my PB and tell me what to work on next," use `session_coach.md`. Specialized prompts should replace or supplement only the relevant part of that workflow.

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

- File-backed RCZ/video input only; no R2/GCS session store yet.
- Reference video extraction currently covers analog speed + overlay map position, not every possible overlay widget.
- No automatic named-corner database yet.
- Different-layout shared-corner GPS/video alignment is a workflow rule but is not yet a dedicated matching algorithm.
- No georeferenced satellite/map tile UI yet.
- Incident body heading depends on yaw-rate sign convention and a pre-slide anchor.

Likely next steps are a session/object-storage abstraction, a track/corner definition format, richer pluggable overlay detectors, and an Apps SDK UI built on the incident-player payload.
