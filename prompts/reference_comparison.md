# Reference Driver Comparison

Compare the driver's telemetry against an external reference driver without treating the reference as an automatic target.

Follow `skill/SKILL.md`. Measure with deterministic tools first. Clearly distinguish raw telemetry from pseudo telemetry reconstructed from video overlays.

## Workflow

1. Verify layout compatibility.
   - If the physical layout is identical, same-layout normalized-distance comparison is allowed.
   - If layouts differ, compare only shared physical sections aligned by GPS/onboard context.
   - Never compare whole-lap percentages across different layouts.

2. Establish data quality for both sides.
   - Raw RCZ/CAN/GPS telemetry has higher confidence than video-derived pseudo telemetry.
   - For video-derived reference data, report extraction/calibration limitations.
   - Do not invent missing throttle, brake, steering, or line data.

3. Compare each shared section using:
   - entry speed
   - minimum speed
   - exit speed
   - braking point/duration when supported
   - throttle timing when supported
   - line/map position when supported

4. Diagnose *why* the reference is faster.

Use categories such as:
- later braking but similar minimum speed
- same entry but higher minimum speed
- similar minimum speed but earlier throttle / better exit
- lower entry with better geometry and exit
- line/placement difference
- reference advantage not safely actionable yet
- insufficient evidence

5. Separate opportunity from target.

For each reference advantage, decide whether it is:
- immediately actionable
- worth testing in a small increment
- dependent on line/technique first
- low ROI
- high consequence / not worth chasing yet

High-speed reference speed is evidence, not an instruction to copy the number.

## Output

### Main differences

| Section | Driver entry/min/exit | Reference entry/min/exit | What creates the gap | Confidence | Actionability |
|---|---|---|---|---|---|

### Highest-ROI reference lessons

Give at most 3 concrete changes. Tie each to measured evidence.

### Reference advantages not to copy yet

Explicitly call out high-speed, low-confidence, setup-dependent, or line-dependent differences that should not become immediate speed targets.

### Data limitations

State whether the reference data came from raw telemetry or video overlay extraction, how it was aligned, and which channels are approximate or unavailable.