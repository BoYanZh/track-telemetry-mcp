# AGENTS.md

This repository is a deterministic motorsports telemetry measurement backend for agents.

The core rule is:

> Python measures; the agent interprets.

Do not estimate telemetry values manually when an MCP tool can calculate them.

## Default workflow

For RaceChrono/RCZ analysis:

1. Call `list_sessions`.
2. Select a session and call `prepare_session`.
3. Use `inspect_session` only when detailed channel names, sample rates, metadata, or evidence quality matter.
4. Use `list_laps` only when the lap summary from `prepare_session` is insufficient.
5. Call the smallest analysis tool set that answers the user's question.
6. Interpret the returned deterministic measurements and state important uncertainty.

Do not call every available tool by default.

## Tool selection

Use general tools first when appropriate:

- `analyze_lap` for one known timed lap.
- `compare_laps` for same-layout lap comparison.
- `analyze_section` for entry/minimum/exit and control timing in a specific section.

Use specialized tools only when the question requires them:

- `analyze_braking` for braking/deceleration questions.
- `analyze_slip_angle` for rotation/sliding questions and only when independent yaw rate is available.
- `analyze_incident` for a known slide/spin/off-track time window.
- `render_incident_player` only when a visual replay is useful.
- `extract_reference_overlay` only when raw reference telemetry is unavailable and a calibrated overlay config exists.

## Hard interpretation constraints

- `compare_laps` requires the same physical layout to be independently confirmed before using normalized lap progress.
- `accelerator_pct` is accelerator-pedal position and must not be called throttle-body position.
- `throttle_pct` is throttle-body position when the source exposes it.
- Vehicle sideslip analysis requires yaw rate independent of GPS course. Do not claim physical sideslip from `yaw_rate_source=gps_heading_derivative`.
- GPS heading/bearing is direction of travel, not measured vehicle body heading.
- Video-derived values are approximate pseudo telemetry, not RCZ-quality logger data.
- Do not infer asphalt/dirt or another surface change from telemetry alone; a surface marker must come from video, observation, or another external source.
- A reference/clean lap trajectory is not a track boundary.
- Do not infer ABS activation from brake pressure alone.

## Analysis style

Prefer measured evidence over generic coaching.

For corner/section analysis, distinguish among:

1. conservative entry / braking too early;
2. excessive minimum-speed loss / overslow;
3. long or weak braking;
4. power control reapplied too late;
5. weak exit speed;
6. line / placement / geometry problem;
7. already good enough / poor risk-reward to chase.

For high-speed sections, do not recommend deliberately adding slide because a reference driver is faster. Prefer repeatability, predictable steering, and incremental changes.

## Detailed policy

For the complete telemetry workflow, source semantics, incident rules, output format, and risk-aware coaching guidance, follow [`skill/SKILL.md`](skill/SKILL.md).

Task-specific prompts are in [`prompts/`](prompts/).
