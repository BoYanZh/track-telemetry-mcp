# track-telemetry-mcp

Deterministic motorsports telemetry analysis for MCP agents.

**Python measures; the agent interprets.** Instead of asking an LLM to eyeball raw telemetry, this project turns RaceChrono sessions and calibrated reference video into structured measurements that agents can reason over reliably.

## Highlights

- RaceChrono `.rcz` support via [TrackTelemetryConverter](https://github.com/BoYanZh/TrackTelemetryConverter)
- lap/PB discovery and lap summaries
- section analysis: entry, minimum, exit speed, braking, and power-control timing
- same-layout lap comparison with an explicit layout guard
- braking analysis with raw vs sustained deceleration
- bounded vehicle-sideslip proxy using GPS course + independent yaw rate
- slide/spin/off-track reconstruction and standalone HTML replay
- approximate reference telemetry from calibrated onboard-video overlays
- agent-oriented capability discovery through `prepare_session`

Raw logger telemetry and video-derived pseudo telemetry are intentionally kept separate.

## Install

Python 3.10+ is required.

```bash
git clone https://github.com/BoYanZh/track-telemetry-mcp.git
cd track-telemetry-mcp

uv venv
uv pip install -e ".[dev,rcz,video]"
```

Use only the extras you need:

- `rcz` — RaceChrono decoding through a pinned TrackTelemetryConverter commit
- `video` — reference-video overlay extraction
- `dev` — pytest + ruff

## Run

The default transport is stdio.

```bash
TRACK_TELEMETRY_ROOT=/absolute/path/to/telemetry \
uv run track-telemetry-mcp
```

`TRACK_TELEMETRY_ROOT` is required by default. File-backed tools reject paths outside that directory.

For deliberate unrestricted local development only:

```bash
TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH=1 uv run track-telemetry-mcp
```

Session discovery is disabled in unsafe mode.

### MCP client config

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

Streamable HTTP is also supported:

```bash
TRACK_TELEMETRY_TRANSPORT=streamable-http \
TRACK_TELEMETRY_ROOT=/absolute/path/to/telemetry \
uv run track-telemetry-mcp
```

Do not expose the file-backed server directly to the public internet without authentication and a proper storage/session abstraction.

## Agent usage

Default flow:

```text
list_sessions
  -> prepare_session
  -> inspect_session only if detailed evidence quality matters
  -> smallest relevant analysis tool set
  -> interpretation
```

Important rules:

- use deterministic MCP measurements instead of estimating telemetry values manually;
- do not call every supported tool by default;
- use specialized braking/slip/incident tools only when the user's question needs them;
- confirm the same physical layout before `compare_laps`;
- only use `analyze_slip_angle` when independent yaw rate is available;
- keep accelerator-pedal percentage distinct from throttle-body percentage;
- treat video-derived values as approximate pseudo telemetry.

Repository-aware agents should read [`AGENTS.md`](AGENTS.md). Agents that support reusable skills should load [`skill/SKILL.md`](skill/SKILL.md).

### Copy-paste instruction

```text
For motorsports telemetry analysis, use the track-telemetry MCP.

Start with list_sessions, then prepare_session for the selected session.
Use inspect_session only when detailed channel/sample-rate context is needed.

Use deterministic MCP measurements instead of estimating telemetry values yourself.
Call only the smallest set of analysis tools required for the user's question.
Do not call every supported tool by default.

Only use analyze_slip_angle when independent yaw rate is available.
Only use compare_laps after confirming the same physical track layout.
Do not relabel accelerator-pedal percentage as throttle-body percentage.
Treat video-derived telemetry as approximate pseudo telemetry.
```

## Tools

| Tool | Use for | Important constraint |
|---|---|---|
| `list_sessions` | discover RCZ sessions | returns opaque session IDs, not host paths |
| `prepare_session` | PB/laps + capability gating | preferred second call |
| `inspect_session` | detailed metadata, channels, sample rates | use when evidence quality matters |
| `list_laps` | detailed lap list | optional after `prepare_session` |
| `analyze_lap` | whole-lap summary | timed lap required |
| `analyze_section` | entry/minimum/exit + control timing | normalized distance within one layout |
| `compare_laps` | mini-sector lap comparison | same physical layout must be confirmed |
| `analyze_braking` | deceleration and brake events | does not infer ABS from pressure alone |
| `analyze_slip_angle` | rotation / vehicle-sideslip proxy | independent yaw source required |
| `analyze_incident` | slide/spin/off-track reconstruction | bounded known incident window |
| `render_incident_player` | standalone incident replay | reference path is not a track boundary |
| `extract_reference_overlay` | approximate onboard-reference telemetry | calibrated video only; pseudo telemetry |

All RCZ-backed tools keep the `path` parameter for compatibility. With a telemetry root configured, `path` may be either a file inside the root or a `session_id` returned by `list_sessions`.

## Data semantics

Three rules matter most:

1. **Throttle is not accelerator pedal.** `throttle_pct` means throttle-body position; `accelerator_pct` means pedal position. Results expose `control_source` explicitly.
2. **GPS heading is direction of travel, not body heading.** Vehicle sideslip requires yaw rate independent of GPS course and is reported as a bounded-window proxy, not tire slip angle.
3. **Reference video is approximate.** Overlay-derived speed/map position is pseudo telemetry and should not be treated as RCZ-quality logger data.

See [`docs/slip-angle.md`](docs/slip-angle.md) for the full sideslip derivation and limitations.

## Architecture

```text
RaceChrono .rcz
      |
      v
TrackTelemetryConverter
      |
      v
TelemetrySession
  |       |        |
  v       v        v
laps   braking   slip/incidents
  |                 |
  +-> comparison    +-> HTML replay

Reference onboard video
      |
      v
calibrated overlay extractor
      |
      +-> approximate pseudo telemetry

deterministic Python analysis
      |
      v
MCPServer
      |
      v
Codex / Cursor / OpenCode / ChatGPT / other MCP clients
```

## Analysis guidance

For the standard review process and detailed agent behavior:

- [`docs/analysis-methodology.md`](docs/analysis-methodology.md) — validate -> locate time loss -> diagnose -> prioritize -> re-test
- [`AGENTS.md`](AGENTS.md) — concise repo-level agent contract
- [`skill/SKILL.md`](skill/SKILL.md) — full telemetry-analysis policy
- [`prompts/`](prompts/) — task-specific coaching/debrief structures
- [`docs/slip-angle.md`](docs/slip-angle.md) — sideslip derivation

## Development

Tests use synthetic telemetry only.

```bash
uv run ruff check .
uv run pytest -q
```

CI targets Python 3.10 and 3.12.

Raw `.rcz`, MoTeC files, video, and personal telemetry should not be committed.

## Current limitations

- local file-backed RCZ/video input only
- no automatic named-corner database
- different-layout shared-corner matching is still a workflow rule, not an automatic matcher
- reference-video extraction currently covers analog speed + overlay map position
- sideslip/body heading depends on yaw-source quality, anchor quality, and integration drift

## License

MIT
