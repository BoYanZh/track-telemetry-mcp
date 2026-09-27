---
name: track-telemetry-analysis
description: Quantitative, risk-aware HPDE and track telemetry analysis using deterministic MCP metrics.
---

# Track Telemetry Analysis

Use this skill when the user asks to analyze motorsports telemetry, compare laps, diagnose corner speed, evaluate braking, reconstruct a slide/spin/off-track incident, or recover approximate reference telemetry from an onboard video overlay.

This is the detailed analysis policy for the MCP. Repository-aware agents should also follow the concise contract in `AGENTS.md`.

## Agent contract

For RCZ work, the default sequence is:

```text
list_sessions
  -> prepare_session
  -> inspect_session only when detailed evidence quality matters
  -> smallest relevant analysis tool set
  -> interpretation
```

Treat `prepare_session.recommended_tools` as general-purpose availability hints, not a checklist. Treat `available_specialized_tools` as opt-in capabilities that should be used only when the user's question specifically requires them.

Do not call every supported tool by default.

## Core principle

Use deterministic code for measurement and the LLM for interpretation. Do not estimate values that the telemetry tools can calculate.

Keep source quality explicit:

1. raw logger telemetry such as RaceChrono RCZ is the primary quantitative source;
2. calibrated values recovered from a video overlay are pseudo telemetry and approximate;
3. manual visual observations are context, not sensor measurements.

Keep channel semantics explicit. In particular:

- `throttle_pct` means throttle-body position when that source exposes it;
- `accelerator_pct` means accelerator-pedal position;
- analysis tools prefer `throttle_pct` and fall back to `accelerator_pct` only when throttle is absent;
- always inspect and preserve `control_source` in lap, section, and incident outputs;
- never call accelerator-pedal percentage "throttle" or present it as throttle-body angle.

Keep heading/slip semantics explicit:

- RaceChrono GPS heading/bearing is direction of travel (course), not vehicle body heading;
- vehicle sideslip is the angle between course and body heading;
- `analyze_slip_angle` estimates body heading by integrating an **independent** CAN/gyro yaw-rate channel from a near-zero-slip anchor;
- if `yaw_rate_source` is `gps_heading_derivative`, do not use it to claim sideslip because the yaw source is not independent of GPS course;
- call the result `slip_angle_proxy` / vehicle sideslip proxy, not tire slip angle or directly measured body angle.

## Inputs

At least one telemetry session or reference onboard video is required. Optional inputs include:

- reference lap/session
- onboard video
- overlay calibration JSON
- track/layout name
- tire and vehicle setup
- driver concern or target corner
- user/video-marked incident events such as a surface change

## Task prompt selection

Use the reusable task prompts in `prompts/` for output structure and task-specific reasoning. They do not replace MCP measurement or capability checks:

- `prompts/session_coach.md` — default for general session/lap-time coaching and next-session recommendations.
- `prompts/reference_comparison.md` — when comparing the driver to an external reference driver or video-derived pseudo telemetry.
- `prompts/incident_review.md` — for a slide, spin, off-track, snap-back, or other loss-of-control review.
- `prompts/post_session_debrief.md` — for a compact end-of-day learning summary and next-session experiment plan.

When a request spans multiple tasks, use `session_coach.md` as the primary structure and borrow the specialized prompt rules only for the relevant sections.

## Workflow

### 0. Discover and gate tools lazily

For file-backed RCZ work, start with `list_sessions`, then call `prepare_session` for the selected session.

Interpret the preparation result as follows:

- `recommended_tools` lists generally useful tools that the session can support; call only the ones needed for the question.
- `available_specialized_tools` lists opt-in braking/slip/incident capabilities; availability does not mean they should be called.
- `capabilities.tool_support` is the authoritative gate for whether a tool's hard prerequisites are present.
- `capabilities.unsupported_reasons` explains why an unavailable tool should not be attempted.

Use `inspect_session` when detailed channel names, sample rates, metadata, or evidence quality matter. Use `list_laps` when the compact lap list from `prepare_session` is insufficient.

Do not run broad analysis merely because the tools are available. Prefer one or two high-value measurements, inspect the result, and only then drill deeper if the user's question remains unresolved.

### 1. Inspect raw telemetry before interpreting

For RCZ/session analysis, inspect the selected session before interpreting measurements.

Check:

- `capabilities.tool_support` before specialized analysis
- available channels and sample rates
- whether channels are missing, frozen, sparse, or obviously invalid
- lap types and PB
- track/layout metadata
- whether power input is sourced from `throttle_pct` or `accelerator_pct`
- `yaw_rate_source` before using yaw for sideslip analysis

Never silently treat an interpolated, frozen, or absent channel as a measurement.

### 2. Recover reference-video telemetry when raw data is unavailable

If a reference driver has only an onboard video with telemetry overlays, use `extract_reference_overlay` after creating a calibration config for that overlay.

The current extractor can recover:

- analog speedometer needle angle -> calibrated speed
- track-map marker X/Y -> approximate position on the video's own map graphic

Use multiple manually verified angle/speed anchors. Keep missing detections as missing; do not silently interpolate them into measurements.

Treat the result as **pseudo telemetry**. It is suitable for approximate corner speed and spatial alignment, not as an equal-quality substitute for the user's raw RCZ data.

Overlay brake/throttle percentages, RPM, gear, or digital text may still require separate extraction or manual frame reads unless a calibrated detector exists. Never invent channels that were not extracted.

### 3. Establish layout compatibility

Before lap-to-lap normalized-distance comparison, verify that both laps use the same physical layout.

- Same layout: `compare_laps(..., same_layout_confirmed=true)` is allowed.
- Different layouts: do not compare whole-lap percentages. Align only shared physical sections using GPS/onboard context and analyze those sections separately.

A video overlay track-map position is useful for shared-corner alignment, but its pixel coordinates are not geographic GPS coordinates.

### 4. Diagnose sections with a fixed taxonomy

For each relevant corner or section, distinguish the primary issue:

1. conservative entry / braking too early
2. excessive minimum-speed loss / overslow
3. long or weak braking instead of shorter useful braking
4. power control reapplied too late
5. weak exit speed
6. line / placement / geometry problem
7. already good enough; further gain has poor risk/reward

Do not collapse these into generic advice such as "carry more speed."

When discussing item 4, use the actual `control_source`: say "throttle reapplication" only for `throttle_pct`; say "accelerator-pedal reapplication" for `accelerator_pct`.

### 5. Report entry, minimum, and exit

Use `analyze_section` or equivalent deterministic metrics. Minimum speed alone is not sufficient. Exit speed and power-control timing often dominate the next straight.

Use the neutral fields `entry_control_pct`, `exit_control_pct`, and `full_control_reapply_progress` for source-independent analysis. Source-specific aliases may also be present, but they must not be used to blur throttle-body and accelerator-pedal semantics.

### 6. Braking analysis

Use `analyze_braking` and separate:

- raw transient peak deceleration
- useful sustained 0.5 s deceleration
- useful sustained 1.0 s deceleration
- brake pressure or pedal ramp
- peak brake pressure / pedal value
- entry and minimum speed for each braking event

Do not recommend chasing a round-number target such as 1.0 g merely because it is round. Determine whether the actual loss is braking strength, braking duration, release timing, minimum speed, or geometry.

Do not claim ABS activation unless the available channels support that inference. The current tool intentionally returns `abs_evidence: not_inferred` by default.

### 7. Slip-angle / vehicle-sideslip analysis

Use `analyze_slip_angle` when the user asks whether the car is rotating/sliding or whether body orientation is diverging from its path.

The tool estimates:

```text
beta_proxy = wrap(GPS course - yaw-integrated body heading)
```

Interpret it with these constraints:

- this is vehicle sideslip (`beta`) proxy, **not tire slip angle**;
- GPS course/bearing is motion direction, not hardware/body pointing direction;
- body heading is estimated by integrating yaw rate and must be anchored at a moment where sideslip is reasonably assumed near zero;
- yaw rate must be independent of GPS course; reject `yaw_rate_source=gps_heading_derivative` for physical sideslip claims;
- gyro/CAN bias accumulates during integration, so prefer bounded corner/incident windows rather than a whole lap/session;
- mask/ignore low-speed values where GPS course is noisy;
- use trend and timing more strongly than a single absolute beta number unless a direct body-heading sensor exists.

For detailed derivation see `docs/slip-angle.md`.

### 8. High-speed risk handling

Do not recommend deliberately adding high-speed slide because a reference driver is faster.

Treat unexpected countersteer at high speed as a warning that the current pace is near or beyond the driver's relaxed-control envelope. Prefer repeatability, asphalt margin, predictable steering, and small pace increments.

Do not use lateral G or slip-angle proxy alone as proof that a tire is at its limit.

### 9. Incident / spin analysis

Use `analyze_incident` for a bounded time window.

Reconstruct and distinguish, when supported:

- initial yaw excursion
- opposite steering input
- power-control reduction, labeled as throttle-body or accelerator-pedal input according to `control_source`
- initial yaw arrest / partial recovery
- snap-back
- brake onset
- user/video-marked surface change
- large body-vs-travel divergence / near-backwards slide

Important interpretation rules:

- GPS heading is velocity/course direction, not vehicle body heading.
- Body heading from yaw integration is an estimate anchored before the slide.
- Sideslip proxy is unreliable at low speed.
- Never infer asphalt vs dirt from telemetry alone. Only mark a surface change when supported by video, observation, or another source.
- Separate vehicle behavior before and after a confirmed surface change.
- `control_pct` is the source-independent power-control value; use `control_source` to determine whether it is throttle-body or accelerator-pedal percentage.

If the user asks for a visual replay, use `render_incident_player` with `sample_stride=1` for native-rate playback. A clean lap may be supplied as `reference_lap_number`; that line is a reference trajectory, never a claimed track boundary.

### 10. Reference-driver comparison

Reference onboard overlay values may be approximate. Prefer calibrated speed and obvious pedal timing over uncalibrated overlay brake percentages. Never numerically equate video brake % with hydraulic kPa unless calibration is known.

When the reference layout differs, use the video track-map marker/onboard visuals to identify the same physical corner, then compare only the shared section.

### 11. Output format

Start with the main conclusion, then provide quantitative evidence.

Preferred section table:

| Section | Entry | Minimum | Exit | Reference | Primary diagnosis | Risk/ROI |
|---|---:|---:|---:|---:|---|---|

Then provide:

- highest-ROI changes for the next session
- what not to chase yet
- one or two concrete driving cues per important section

Keep recommendations tied to measured evidence. Explicitly state uncertainty where channels, layout alignment, reference data, control-source fallback, or slip-angle anchoring are incomplete.
