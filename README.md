# track-telemetry-mcp

Deterministic motorsports telemetry analysis for MCP agents.

**Python measures; the agent interprets.** Instead of asking an LLM to eyeball raw telemetry, this project turns RaceChrono sessions and calibrated reference video into structured measurements that agents can reason over reliably.

## Highlights

- RaceChrono `.rcz` support via [TrackTelemetryConverter](https://github.com/BoYanZh/TrackTelemetryConverter)
- multi-stint RaceChrono RCZ recordings with all-day PB discovery and stable original lap numbers
- lap/PB discovery and lap summaries
- P1 GPS overlays, speed-vs-distance, Delta T and conditional P2 G/input/health figure reports
- section analysis: entry, minimum, exit speed, braking, steering, and power-control event timing
- same-layout lap comparison aligned by physical GPS position, with alignment-quality guards and optional Delta T/V profile
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
uv pip install -e ".[dev,rcz,video,viz]"
```

Use only the extras you need:

- `rcz` — RaceChrono decoding through a pinned `track-telemetry-converter` commit
- `video` — reference-video overlay extraction
- `dev` — pytest + ruff
- `viz` — optional headless Matplotlib HTML/PNG telemetry visualization

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
list_sessions (one recording with its stints)
  -> prepare_session (all recorded stints and the true all-day PB)
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
- render GPS, V-S and Delta T for substantive same-layout lap comparisons, with P2 diagnostic charts only where useful and measured.

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
| `list_sessions` | discover RCZ recordings and contained stints | returns opaque session IDs, not host paths |
| `prepare_session` | all-stint PB/laps + capability gating | preferred second call |
| `inspect_session` | detailed metadata, channels, sample rates | use when evidence quality matters |
| `list_laps` | all-stint lap list including original numbers and stint indices | optional after `prepare_session` |
| `analyze_lap` | whole-lap summary | timed lap required |
| `analyze_section` | entry/minimum/exit + braking/steering/power event timeline | normalized distance within one layout; threshold-based timing |
| `compare_laps` | physical-position-aligned mini-sectors; optional sampled Delta T/V profile | same physical layout must be confirmed; GPS alignment must pass quality guards |
| `render_lap_comparison` | P1 GPS trajectory overlay, speed vs reference distance, cumulative Delta T | requires same layout, GPS alignment and `viz` dependency; outputs HTML + PNG |
| `render_session_report` | P2 G-G/G traces, driver inputs, vehicle health for one timed lap | channel- and rate-gated; missing channels skipped |
| `analyze_braking` | deceleration and brake events | does not infer ABS from pressure alone |
| `analyze_slip_angle` | rotation / vehicle-sideslip proxy | independent yaw source required |
| `analyze_incident` | slide/spin/off-track reconstruction | bounded known incident window |
| `render_incident_player` | standalone incident replay | reference path is not a track boundary |
| `extract_reference_overlay` | approximate onboard-reference telemetry | calibrated video only; pseudo telemetry |

All RCZ-backed tools keep the `path` parameter for compatibility. With a telemetry root configured, `path` may be either a file inside the root or a `session_id` returned by `list_sessions`.

### Multiple RaceChrono stints

RCZ files can contain `resume_1/`, `resume_2/`, etc. The MCP reads all recorded stints by default, retains their physical acquisition time offsets, and exposes the original RaceChrono lap numbers across the day. `prepare_session(path, stint=3)`, `inspect_session(path, stint=3)`, or `list_laps(path, stint=3)` can restrict discovery to one stint; omit the parameter or use `stint="all"` to inspect the whole recording. `list_sessions` shows the available stints, and `prepare_session`/`list_laps` include `stint` alongside each lap and report the overall fastest timed lap. A normal recording containing original lap 22 in stint 3 is addressed simply with `analyze_lap(path, 22)` or `compare_laps(..., lap_b=22, ...)`.

When the source repeats the same original lap number in multiple stints, the MCP uses composite unique lap IDs (e.g., `3000007` for original lap 7 in stint 2) and keeps both `original_number` and `stint` visible; use the exposed `number` as the selector. Synthetic untimed out-lap IDs may be negative. The low-level `load_rcz(path, target_stint=N)` API remains available for callers needing a single stint.

Across-stint time gaps are preserved and **must not be treated as driving telemetry**. For incident windows, select a window inside a single recorded stint; do not interpolate driving behavior across session breaks.

## Telemetry visualization (P1/P2)

Install with `pip install -e ".[rcz,viz]"` to generate PNG figures
plus a portable HTML report containing embedded images. Static figures
are intentional; linked interactive dashboards are not part of P1/P2.

Use a file path under `TRACK_TELEMETRY_ROOT` (or a `session_id` from
`list_sessions`). The `output_html` path must also be inside that root.

```python
render_lap_comparison(
    path_a="day1.rcz", lap_a=14, path_b="day2.rcz", lap_b=22,
    same_layout_confirmed=True, output_html="reports/fast-laps.html",
    plots=["gps_trace", "speed_distance", "delta_time"],
)
render_session_report(
    path="day2.rcz", lap_number=22,
    output_html="reports/lap22-diagnostics.html",
    plots=["gg_diagram", "g_traces", "driver_inputs", "vehicle_health"],
)
```

Each tool returns `output_html`, `plot_files`, `generated_plots`,
`skipped_plots`, `notes` and per-channel samples, rate, and lap coverage.
P1 comparison includes GPS alignment quality. Speed and Delta-T use physical
reference-distance interpolation only; plot grid size is **not** source sample
rate. Raw GPS sample points are visible when sparse. P2 G-G requires paired
longitudinal and lateral G channels sampled at least 5 Hz, while other P2
plots include only recorded channels with sufficient lap coverage. Source
metadata should be checked before using derived G to infer physical grip.
No chart fills missing data with assumed zeros or bridges different stints.

RCZ GPS source selection is intentionally unchanged by this feature.
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
track_telemetry_converter
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

Tests use synthetic telemetry, including multi-stint RCZ ZIP archives decoded with the pinned Converter dependency.

```bash
uv run ruff check .
uv run pytest -q
```

CI targets Python 3.10 and 3.12, including RCZ decoding through the pinned Converter dependency using a synthetic archive. Real-world RCZ files are still needed for validation of logger timing and GPS quality.

Raw `.rcz`, MoTeC files, video, and personal telemetry should not be committed.

## Current limitations

- local file-backed RCZ/video input only
- no automatic named-corner database
- different-layout shared-corner matching is still a workflow rule, not an automatic matcher
- aligned Delta T/V uses lap B as a physical reference path; inadequate GPS agreement fails explicitly
- section event markers use fixed thresholds, not a vehicle dynamics model; verify against video
- reference-video extraction currently covers analog speed + overlay map position
- sideslip/body heading depends on yaw-source quality, anchor quality, and integration drift

## License

MIT
