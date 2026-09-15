---
name: track-telemetry-analysis
description: Quantitative, risk-aware HPDE and track telemetry analysis using deterministic MCP metrics.
---

# Track Telemetry Analysis

Use this skill when the user asks to analyze motorsports telemetry, compare laps, diagnose corner speed, evaluate braking, reconstruct a slide/spin/off-track incident, or recover approximate reference telemetry from an onboard video overlay.

## Core principle

Use deterministic code for measurement and the LLM for interpretation. Do not estimate values that the telemetry tools can calculate.

Keep source quality explicit:

1. raw logger telemetry such as RaceChrono RCZ is the primary quantitative source;
2. calibrated values recovered from a video overlay are pseudo telemetry and approximate;
3. manual visual observations are context, not sensor measurements.

## Inputs

At least one telemetry session or reference onboard video is required. Optional inputs include:

- reference lap/session
- onboard video
- overlay calibration JSON
- track/layout name
- tire and vehicle setup
- driver concern or target corner
- user/video-marked incident events such as a surface change

## Workflow

### 1. Inspect raw telemetry before interpreting

For RCZ/session analysis call `inspect_session` and `list_laps` first.

Check:

- available channels and sample rates
- whether channels are missing, frozen, sparse, or obviously invalid
- lap types and PB
- track/layout metadata

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
4. throttle reapplied too late
5. weak exit speed
6. line / placement / geometry problem
7. already good enough; further gain has poor risk/reward

Do not collapse these into generic advice such as "carry more speed."

### 5. Report entry, minimum, and exit

Use `analyze_section` or equivalent deterministic metrics. Minimum speed alone is not sufficient. Exit speed and throttle timing often dominate the next straight.

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

### 7. High-speed risk handling

Do not recommend deliberately adding high-speed slide because a reference driver is faster.

Treat unexpected countersteer at high speed as a warning that the current pace is near or beyond the driver's relaxed-control envelope. Prefer repeatability, asphalt margin, predictable steering, and small pace increments.

Do not use lateral G alone as proof that a tire is at its limit.

### 8. Incident / spin analysis

Use `analyze_incident` for a bounded time window.

Reconstruct and distinguish, when supported:

- initial yaw excursion
- opposite steering input
- throttle reduction
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

If the user asks for a visual replay, use `render_incident_player` with `sample_stride=1` for native-rate playback. A clean lap may be supplied as `reference_lap_number`; that line is a reference trajectory, never a claimed track boundary.

### 9. Reference-driver comparison

Reference onboard overlay values may be approximate. Prefer calibrated speed and obvious pedal timing over uncalibrated overlay brake percentages. Never numerically equate video brake % with hydraulic kPa unless calibration is known.

When the reference layout differs, use the video track-map marker/onboard visuals to identify the same physical corner, then compare only the shared section.

### 10. Output format

Start with the main conclusion, then provide quantitative evidence.

Preferred section table:

| Section | Entry | Minimum | Exit | Reference | Primary diagnosis | Risk/ROI |
|---|---:|---:|---:|---:|---|---|

Then provide:

- highest-ROI changes for the next session
- what not to chase yet
- one or two concrete driving cues per important section

Keep recommendations tied to measured evidence. Explicitly state uncertainty where channels, layout alignment, or reference data are incomplete.
