---
name: track-telemetry-analysis
description: Quantitative, risk-aware HPDE and track telemetry analysis using deterministic MCP metrics.
---

# Track Telemetry Analysis

Use this skill when the user asks to analyze motorsports telemetry, compare laps, diagnose corner speed, evaluate braking, or reconstruct a slide/spin/off-track incident.

## Core principle

Use deterministic code for measurement and the LLM for interpretation. Do not estimate values that the telemetry tools can calculate.

## Inputs

At least one telemetry session is required. Optional inputs include:

- reference lap/session
- onboard video
- track/layout name
- tire and vehicle setup
- driver concern or target corner
- user/video-marked incident events such as a surface change

## Workflow

### 1. Inspect before interpreting

Call `inspect_session` and `list_laps` first.

Check:

- available channels and sample rates
- whether channels are missing, frozen, sparse, or obviously invalid
- lap types and PB
- track/layout metadata

Never silently treat an interpolated, frozen, or absent channel as a measurement.

### 2. Establish layout compatibility

Before lap-to-lap normalized-distance comparison, verify that both laps use the same physical layout.

- Same layout: `compare_laps(..., same_layout_confirmed=true)` is allowed.
- Different layouts: do not compare whole-lap percentages. Align only shared physical sections using GPS/onboard context and analyze those sections separately.

### 3. Diagnose sections with a fixed taxonomy

For each relevant corner or section, distinguish the primary issue:

1. conservative entry / braking too early
2. excessive minimum-speed loss / overslow
3. long or weak braking instead of shorter useful braking
4. throttle reapplied too late
5. weak exit speed
6. line / placement / geometry problem
7. already good enough; further gain has poor risk/reward

Do not collapse these into generic advice such as "carry more speed."

### 4. Report entry, minimum, and exit

Use `analyze_section` or equivalent deterministic metrics. Minimum speed alone is not sufficient. Exit speed and throttle timing often dominate the next straight.

### 5. Braking analysis

Use `analyze_braking` and separate:

- raw transient peak deceleration
- useful sustained 0.5 s deceleration
- useful sustained 1.0 s deceleration
- brake pressure or pedal ramp
- peak brake pressure / pedal value
- entry and minimum speed for each braking event

Do not recommend chasing a round-number target such as 1.0 g merely because it is round. Determine whether the actual loss is braking strength, braking duration, release timing, minimum speed, or geometry.

Do not claim ABS activation unless the available channels support that inference. The current tool intentionally returns `abs_evidence: not_inferred` by default.

### 6. High-speed risk handling

Do not recommend deliberately adding high-speed slide because a reference driver is faster.

Treat unexpected countersteer at high speed as a warning that the current pace is near or beyond the driver's relaxed-control envelope. Prefer repeatability, asphalt margin, predictable steering, and small pace increments.

Do not use lateral G alone as proof that a tire is at its limit.

### 7. Incident / spin analysis

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

### 8. Reference-driver comparison

Reference onboard overlay values may be approximate. Prefer speed and obvious pedal timing over uncalibrated overlay brake percentages. Never numerically equate video brake % with hydraulic kPa unless calibration is known.

### 9. Output format

Start with the main conclusion, then provide quantitative evidence.

Preferred section table:

| Section | Entry | Minimum | Exit | Reference | Primary diagnosis | Risk/ROI |
|---|---:|---:|---:|---:|---|---|

Then provide:

- highest-ROI changes for the next session
- what not to chase yet
- one or two concrete driving cues per important section

Keep recommendations tied to measured evidence. Explicitly state uncertainty where channels, layout alignment, or reference data are incomplete.
