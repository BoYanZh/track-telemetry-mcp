# Incident / Spin Review

Analyze a slide, spin, off-track, or loss-of-control event using telemetry and video evidence without over-claiming causality.

Follow `skill/SKILL.md`. Use `analyze_incident` for a bounded time window and request sample output when detailed reconstruction is needed.

## Goals

Determine, when the evidence supports it:
- what changed first
- when the driver recognized the problem
- whether steering/yaw response temporarily stabilized the car
- how throttle/brake changes relate in time
- whether body-vs-travel divergence continued after yaw was reduced
- whether a confirmed surface change altered the second half of the event
- what the highest-ROI prevention cue is for the future

The goal is not to assign blame or prove a single root cause when the telemetry cannot do so.

## Required interpretation rules

- GPS course/heading is the direction of travel, not vehicle body heading.
- Body heading from yaw-rate integration is an estimate anchored before the incident.
- Treat sideslip as a proxy, especially at low speed.
- Do not infer asphalt, dirt, oil, debris, or another surface from telemetry alone.
- If video/driver observation gives a surface-change time, separate pre-change and post-change behavior.
- A throttle lift that occurs after yaw begins is not evidence that the lift caused the initial loss.
- Distinguish initial instability, driver response, partial recovery, snap-back, and later consequences.
- Do not judge tire breakaway characteristics from loose-surface behavior after an off-track transition.

## Timeline

Build a concise event timeline around important moments such as:
- normal state immediately before the event
- first meaningful yaw excursion
- first opposite steering/countersteer
- throttle reduction
- peak lateral/yaw behavior when useful
- initial yaw arrest / partial catch
- confirmed surface change
- snap-back / opposite yaw
- brake onset
- near-backwards sliding
- stop / recovery

Use exact timestamps when available.

## Prevention analysis

Separate prevention into three layers:

1. **Earlier prevention** — pace, line, control margin, or setup/context choices that avoid entering the marginal state.
2. **Recognition** — whether the telemetry suggests the driver recognized the event promptly enough.
3. **Recovery** — what happened after recognition, without turning the review into instructions to deliberately practice dangerous high-speed slides.

For high-speed incidents, prioritize avoiding the marginal state over optimizing heroic recovery technique.

## Output

### Main conclusion

State the most likely sequence in 2-4 sentences, explicitly distinguishing fact from inference.

### Event timeline

| Time | Speed | Steering / yaw / pedals | Interpretation | Confidence |
|---:|---:|---|---|---|

### What caused what

Use three buckets:
- supported by telemetry/video
- plausible contributor
- not supported / cannot determine

### Was the response late?

Answer quantitatively when possible. Do not call the response slow merely because the incident was not recovered.

### Prevention for next time

Give at most 3 cues or constraints. Prefer earlier pace/line/repeatability cues to risky recovery advice.

### Mechanical follow-up

Only include inspection items that logically follow from the event (for example tire/bead/wheel/alignment checks after a dirt excursion). Do not invent damage.

### Limitations

State missing channels, yaw-sign uncertainty, video timing uncertainty, surface-change uncertainty, and low-speed heading limitations.