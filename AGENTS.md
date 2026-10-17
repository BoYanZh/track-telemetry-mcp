# AGENTS.md

This repository is a deterministic motorsports telemetry measurement backend for agents.

The core rule is:

> Python measures; the agent interprets.

Do not estimate telemetry values manually when an MCP tool can calculate them.

## Default workflow

For a complete session review or coaching request, call `analyze_session_debrief`
with all supplied telemetry paths. Independently confirm identical physical
layouts before enabling comparisons. Read the JSON evidence and actual plots,
then finish both reports and tailor at most three next-session experiments.
Do not stop after plot generation or hand back an uncompleted coaching handoff.
Follow [the one-shot contract](docs/session-debrief.md). Focused questions can
still use the smaller tool sequence below.

For RaceChrono/RCZ analysis:

1. Call `list_sessions`.
2. Select a session and call `prepare_session`.
3. Use `inspect_session` only when detailed channel names, sample rates, metadata, or evidence quality matter.
4. Use `list_laps` only when the lap summary from `prepare_session` is insufficient.
5. Call the smallest analysis tool set that answers the user's question.
6. Interpret the returned deterministic measurements and state important uncertainty.

Do not call every available tool by default.

External-driver files belong in `reference_paths`, not the driver `paths`. Review
`external_reference_scan` across all covered sectors independently of own-lap
ranking. Keep observed differences and practice priority separate; explain the
five largest external gaps with `external_decisions` before finalization.

For every session or reference coaching review, read and execute
[the unified workflow](docs/analysis-methodology.md), stages 1–6. It owns opportunity
screening, linked-window measurements, competing explanations, practice selection
and report acceptance. Scenario prompts add only scenario-specific choices.

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

## Visualization selection

For substantive same-layout lap comparisons, generate the P1 GPS trajectory
overlay, speed vs reference distance, and cumulative Delta-T report using
render_lap_comparison when the viz extra is installed. Request conditional P2 G-G,
G traces, driver inputs or vehicle-health charts with render_session_report
when recorded channels warrant them. Inspect actual output files, sample
rates, alignment and skipped reasons. Missing data is not zero; interpolation
does not create higher-rate GPS. Never join discontinuous stints in a plot.

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

For corner/section analysis, classify with the canonical 8-class diagnosis list in
`skill/SKILL.md` ("Diagnose sections with a fixed taxonomy"). Do not collapse
these into generic advice such as "carry more speed."

For high-speed sections, do not recommend deliberately adding slide because a reference driver is faster. Prefer repeatability, predictable steering, and incremental changes.

## Detailed policy

For the standard review methodology — validate data, choose a reference, locate time loss first, diagnose, prioritize, prescribe, and re-test — follow [`docs/analysis-methodology.md`](docs/analysis-methodology.md).

For source semantics, incident rules, output format, and risk-aware coaching guidance, follow [`skill/SKILL.md`](skill/SKILL.md).

Task-specific prompts are in [`prompts/`](prompts/).

Corner presentation, linked-window diagnosis and concision rules live in
`skill/SKILL.md` (four-signal findings, mini-sectors as loss locators with
upstream/target/downstream timing, line-vs-timing comparison, zero-experiment
validation plans). Follow them as written; do not keep a local copy here.
