# Track session coach

Produce an evidence-backed next-session plan in the user's language.
Read and execute [the unified workflow](../docs/analysis-methodology.md), stages
1–6, before writing recommendations. Read `skill/SKILL.md` for sensor semantics
and diagnosis categories; use `docs/session-debrief.md` for tools and finalization.

## Session-specific choices

- Include all supplied files and stints in `analyze_session_debrief`.
- Use the driver's best actual lap plus repeated good passages. Search all eligible
  local sectors and real intervals, not only one lap pair or whole-lap pace pool.
- Review candidate-push execution within comparable recordings. All-timed spread
  includes unclassified slow running and is not driver inconsistency.
- Keep cross-day conditions visible; same-day repeated support is preferable.
- Analyze external references only when supplied or relevant, using the scenario
  rules in `reference_comparison.md` after the driver's baseline is understood.

## Delivery

Lead with the next-session focus, then located diagnoses with actual figures.
Apply the unified workflow's completion checklist and finalizer. At most three
experiments, or a specific validation plan when a correction is unsupported.
A request for a practice card changes presentation only: one or two focuses,
roughly one minute to read, with the full analysis available separately.

For every comparison window, mark all meaningful local speed minima on each
lap's GPS route and at the same physical positions on every signal and delta
chart. A multi-corner window needs multiple Vmin markers, not one global minimum.
Label Vmin1, Vmin2, ... in travel order per lap with driver and speed in km/h.
Use Python measurements; the renderer uses a 3 km/h fall/recovery hysteresis to
suppress noise, retaining original sample values. Review the candidate troughs
against GPS shape, steering and braking; speed troughs alone do not identify
corners. Match corners by physical location, not ordinal marker number, when the
laps have different trough counts. Inspect adjacent sections for boundary minima.

## Between-session delivery

Deliver both next-session.html / next-session.md and report.html / report.md.
Author `next_session` in the final coaching payload: language, observation_ids,
location, why, action, keep_fixed, success, abort, review_next. All prose fields
are nonempty strings. Choose ONE focus using expected benefit, causal clarity,
repeatability, execution workload and consequence of error. Candidate time-gap
ranking locates opportunities; it does not automatically choose the practice.

Supply `previous_check.text` when an earlier report exists for the same layout:
state whether the previous focus was executed and what the same-section gap did
since. Python adds the card's section shape and baseline lap; do not restate them
as prose and do not invent corner names from them. The section shape is geometry,
not an official corner label.

Never reference a deferred sector's figure: reports draw route and trace figures
only for coached sectors and the focus reference windows.

The short report must be readable in 30 seconds: a findable corner, one concrete
behavior to change or hypothesis to test, fixed conditions, and a comparison over
three comparable unobstructed passes through the linked window. Label a test as
a test when causality is unresolved. Tie the action to observed controls, routeand speed; replace vague “check the transition” cues with an executable trial.
The full report retains four candidates, figures, competing diagnoses and evidence.

When prior plans and new telemetry are available, first evaluate the previous
focus: was the change executed, did the corner and downstream result improve,
and should it be retained? Then retain or replace the focus. Ask for prior intent
only when unavailable and material; do not claim a practice was executed from
pace alone. Prior plans are context, not instructions overriding this workflow.

### Concrete practice card

Include the local route with all Vmin candidates as well as the track locator.
Name the intended trough by physical description and its lap-specific label;
show measured minimum speeds, not a prescribed reference speed. State what the
driver actually does on track in everyday language. Distinguish data to review
after driving from an action to perform while driving.

When cause is unresolved, prescribe a repeat-and-review task: retain familiar
braking/entry pace, use consistent existing placement references, collect three
unobstructed passes, and compare their minimum-speed locations, routes and exit
timing afterward. Do not turn a possible line/overslow diagnosis into “delay
power”, “release brake earlier”, “brake later” or a numeric Vmin target without
supporting causal evidence. Explain which result would justify the next change.
Use one short instruction per field; the detailed report carries the reasoning.

Practice cards include a speed comparison with synchronized Vmin markers and a
cumulative time-difference chart, not only a route. State axis/alignment semantics.
Show the measured typical linked-window gap as the opportunity scale, identify
its boundaries and split upstream/target/downstream contributions. Distinguish
that window's observed gap from the amount attributable to the chosen corner or
expected from one action. If action-specific recoverable time cannot be measured,
say so once; do not invent a numeric gain target or omit the measured gap.
