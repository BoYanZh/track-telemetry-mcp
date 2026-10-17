# Coaching analysis workflow

This is the authoritative analysis sequence for session and reference-driver
coaching. Task prompts select a scenario; `skill/SKILL.md` owns channel semantics,
capability gates and the diagnosis taxonomy. `session-debrief.md` owns tool calls,
artifact schemas and finalization. Python measures; the hosting agent interprets.

## 1. Validate data and comparison scope

Start complete reviews with `analyze_session_debrief` and all supplied files/stints.
For focused questions, prepare the session and request only relevant tools.
Record lap identity, units, source, quality, normalized/export clock and verified
native acquisition rate separately. Missing data stays unavailable.
Independently confirm identical physical layouts before enabling full comparisons.
Without confirmation, limit work to independently established shared physical
sections; a successful GPS fit or track name alone does not establish layout.
Label timed laps, candidate-push laps and external annotations separately. Pace
screening proves neither intent nor clean running. Inspect interruptions before
attributing a difference to technique.

Exit: usable evidence, explicit comparison scope and unavailable channels.

## 2. Screen opportunities before choosing a lap pair

Read `opportunity_screening`, the all-lap physical mini-sector matrix and real
contiguous intervals. Include valid local sections from otherwise slower laps.
Review every sector, including sector 1 and the finish/start area, even when the
PB owns its fastest sample. Review source-switch states and keep per-session and
combined results separate. Virtual best is an opportunity index, not a continuous
trajectory. Finish/start joins require adjacent recorded laps; adding the end and
start of one row does not create a continuous passage. Overlapping intervals are alternatives; their differences never sum.

Use the driver's best actual lap and repeated good passages as the baseline.
An external reference adds an independent whole-route screening pass; supply it
through MCP `reference_paths` or CLI `--reference`, separately from driver files.
It does not replace the driver's own repeatability review. `external_reference_scan`
visits every baseline sector and matches local passages before own-lap shortlisting.
A consistently slow fast corner must remain visible even with zero own-lap variance.
The observed-difference ranking is distinct from the agent's practice ranking.
Finalization requires `external_decisions` for the five largest external differences:
`observation_id`, `status` (practice/validate/defer), and a concrete `reason`.
At most three may be practice/validation focuses. Explain large fast-section
deferrals rather than suppressing them during measurement. Stable S01–S20 IDs
refer to the baseline's physical sectors, never official corner names. Select a few linked corners for deeper measurement,
not simply the three largest single-sector gaps.

Exit: candidate locations, source laps, repeated support and exclusions.

## 3. Measure the complete linked window

Trace the preceding corner through the target into subsequent acceleration and
the next braking event. Use shared physical boundaries for both passages.
Inspect `corner_passages.chain_window` and `timing_check`; report missing or
mismatched anchors and lap truncation. Retract a donor advantage that disappears
across the linked window. A full-pedal straight may inherit its loss upstream.

Python must calculate the following evidence, using existing tools where available:

| Measurement | Required distinction |
|---|---|
| Entry state | Speed already carried into the window vs newly accumulated time |
| Stage timing | Upstream, target and downstream differences with consistent sign |
| Shared markers | Position, source time, speed, brake, steering, power and G when available |
| Events | Onset/release, minimum-speed position, steering build/unwind and power progression |
| Repetition | Individual supporting laps, measurements, exclusions and alignment quality |

Window extrema describe a window; they are not simultaneous events. Compare
values at the same physical marker before combining them in an explanation.
Different minimum-speed positions are not a shared apex. An approximate GPS
circle fit needs spatial-span sensitivity and repeated-pass checks before use.
If the workflow did not calculate needed evidence, obtain a targeted deterministic
measurement and persist it with source/units/method; do not estimate it by eye.
These requirements are an agent contract, not a claim every field is already
produced automatically by the current backend.

Exit: traceable measurements sufficient to test a causal explanation, or the
specific missing measurement needed for a validation task.

## 4. Compare explanations before prescribing

Read traces in this order: cumulative Delta-T, speed vs physical distance,
braking against steering, power progression, then G and GPS response.
Separate three layers:

- Observation: where time accumulates, speed changes and recorded actions.
- Hypothesis: line/placement, braking, steering timing, power or entry-state explanation.
- Test: one behavior or one unresolved hypothesis to check next session.

Classify with the canonical taxonomy in `skill/SKILL.md`. Lower minimum speed
alone is not proven overslow. Overslow describes unnecessary speed loss; route
and control timing may explain why it occurs. Higher brake pressure can respond
to a tighter path. Steering peak alone does not establish understeer or line.
G is vehicle response, not a separate fault or an available-grip target. Compare
its spatial timing with speed, steering and route, after checking axes and source.
When longitudinal G is absent, combined G stays unavailable.

For each hypothesis retain supporting and contradictory observations, confidence,
confounders and a falsifying measurement in JSON. Check traffic, deliberate lifts,
vehicle/setup and conditions as alternatives. Do not infer intent from a trace.

Exit: a supported diagnosis or a bounded validation question, not a generic cue.

## 5. Select the next-session focus

Rank qualitatively by retained linked-window difference, repeated support,
evidence clarity, downstream influence, workload and consequence of error.
Fast corners onto long acceleration deserve review; speed alone is not priority.
Prefer one focus; select at most three experiments. Distinguish improving PB from
reproducing pace already recorded. For each specify location, one changed behavior,
what stays fixed, baseline, success over the linked window, abort and re-test.
If a correction is unsupported, use zero experiments and a concrete nonempty
`validation_plan`: name the position/event to check and how the result changes
the next decision. Do not fill uncertainty with generic brake-release advice.

Exit: a small executable practice plan, not a list of theoretical gains.

## 6. Render, inspect and finish

Every discussed area, including deferred areas, gets a recognizable description,
a full-track locator, equal-scale local route, direction and shared markers.
Use the user's language. Show speed, one semantically matched power trace, one
brake trace, steering and combined planar G when supported. Omit ambiguous
cross-source overlays; retain provenance and unavailable reasons in evidence.
Use relevant P1/P2 renderers; inspect actual figures, not only file existence.

Write short findings beside the plots: diagnosis, evidence, cause, response and
next action. Put generic measurement caveats once in collapsed notes. Keep local
uncertainty visible only when it changes the practice decision.
A short practice card uses the same analysis, with one or two focuses and a link
to the full evidence; it is not a cheaper diagnostic method or a CLI mode claim.

Before `finalize_session_debrief`, check:

- Each diagnosis cites measured observations; each illustrated location is findable.
- Same-position claims use synchronized values, not unrelated peaks.
- Stage differences conserve the linked total; repeated support is stored by lap.
- Units, pedal/body semantics and sample-rate provenance remain correct.
- Each recommendation has one action/test and a measurable next-session outcome.
- Both reports, evidence and practice plan are finished; charts alone are incomplete.

Stop when the driver can identify where, what to test and how to evaluate it in
30 seconds. Reopen with new telemetry, video or driver feedback. For checked
first-party rationale see [telemetry-review-sources.md](telemetry-review-sources.md).

Fast-area review flags also require a selection/deferral reason, even outside the
five largest gaps. Current descriptive trigger: target-segment minimum >=120 km/h
and observed target difference >=0.2 s. It is a review trigger, not a risk rating.

The driver-facing overview shows at most three practice focuses, with one local
time difference each. Keep all-sector ranking, linked timing and passage counts
in collapsed evidence. Explain repetition as how many reference passes were faster,
not a confidence score. Full-route analysis does not require a full-route main table.
