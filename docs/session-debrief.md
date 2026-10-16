# One-shot track coaching

Give a capable agent the repository link and telemetry attachments, and ask for
a complete next-session HPDE debrief. The agent installs the relevant adapter
and viz extras, makes files accessible under TRACK_TELEMETRY_ROOT, and calls
analyze_session_debrief once with all input paths and an output directory.

For shell environments:

```sh
track-telemetry-coach analyze session.rcz other.rcz --output debrief
```

Add --same-layout-confirmed only after independent evidence establishes the same
physical layout for every supplied file and stint. A track name or plausible GPS
match alone is insufficient. Without confirmation, timing and consistency still
run, but section comparisons remain unavailable. Separate incompatible layouts
into separate calls. CLI paths are explicit local user inputs; MCP paths and
outputs remain confined to TRACK_TELEMETRY_ROOT.

RCZ discovery includes every stint. Other formats reuse TTC adapters and recorded
lap boundaries. Each file retains its own clock. Invalid/nonpositive/untimed laps
are excluded explicitly. All-timed timing spread is reported separately per stint
and must not be interpreted as driver consistency: yielding, warmup, cooldown and
traffic can all slow an otherwise timed lap.

Whole-lap execution review screens candidate-push laps within each recording's best + max(1 s,
2% of best). This is a transparent pace heuristic, not proof of intent or clean
running. Slower laps remain in the evidence as unclassified_slow, not traffic.
Even a near-PB lap may contain an interruption. Concentrated sector loss above
max(0.75 s, median sector delta + 4 scaled MAD) is flagged as unresolved and that
lap/sector is omitted from technique ranking. Flags can represent traffic,
yielding, a mistake or a real technique issue; the heuristic does not decide why.
Review flagged sectors with driver/video context rather than silently discarding
them or interpreting them as driver errors. Do not compare candidate-pool MAD to
all-lap MAD as evidence of improved driving; screening itself truncates spread.

Optional lap_context annotations are an array of objects with session (zero-based
input index), lap, classification and an external evidence note. Classifications
are confirmed_push, traffic, warmup, cooldown or unknown. Explicit context overrides
pace screening; the reference prefers externally confirmed push laps. Supply the
array to the MCP tool or use --lap-context context.json in the CLI. Without such
context, keep push intent and traffic status unconfirmed, even for the fastest lap.

The reference supplies common physical coordinates, not a performance ceiling.
It prefers externally confirmed push laps, otherwise the fastest candidate
passing GPS self-alignment. Cross-lap comparisons must pass alignment gates.
All valid timed laps contribute eligible local mini-sectors, including otherwise
slower laps: whole-lap pace is not a local exclusion. Explicit traffic/warmup/
cooldown context excludes a lap; unresolved concentrated loss excludes only the
affected sample. The report contains the all-lap matrix, fastest-sector donor,
near-best count within 0.1 s, second-fastest sample and virtual sums per file and
combined. These are optimistic combinations of recorded intervals, not a driven
lap or guaranteed time gain. Cross-day conditions remain unverified.

At every source switch, entry/exit speeds are compared, including the wrap across
the finish line. A difference above 5 km/h is flagged for review. Matching speeds
do not prove compatible lines, steering, grip or vehicle states. The top diagnostic
sections compare the fastest actual whole lap with that section's fastest donor
on the same physical reference grid, rather than a median slow-lap example.
Section control timing maps physical reference boundaries back to each lap.
Diagnostics reuse source-gated G-G, braking, wheel-speed and steering functions.
Unavailable metrics retain reasons rather than zero values.

## Artifacts and completion

- report.md and report.html contain measured findings and an initial baseline plan.
  Final reports include per-stint timing tables, including recorded stints with
  no timed laps, and HTML figures that can be read alongside the coaching plan.
- evidence.json contains session inventory, native rates/provenance, observations,
  comparisons, confidence, confounders, unavailable diagnostics and practice plan.
- PNG plots and linked HTML bundles use existing P1/P2 renderers when available.
- agent-handoff.md tells the hosting agent how to finish coaching.

The Python command is provider-independent. It does not call an LLM. Its status
is awaiting_agent_interpretation, even when calculations succeed. The hosting
agent must inspect actual outputs, interpret the evidence, tailor at most three
experiments and update both reports plus JSON hypotheses and practice_plan.
Each hypothesis must cite observation IDs, state confidence and alternatives.
Each experiment needs one change, a location, baseline, measurable success,
abort condition and re-test. Keep missing-data limitations visible. Complete
coaching is the hosting agent's responsibility; successful plotting is not completion.

Finish with `finalize_session_debrief(evidence_path, coaching)` or
`track-telemetry-coach finalize debrief/evidence.json coaching.json`. The coaching
object contains summary, hypotheses and experiments. Each hypothesis supplies
observation_ids, explanation, confidence (low/moderate/high), and confounders.
Each experiment supplies observation_ids, location, change, baseline,
success_measure, abort_condition and re_test. The finalizer checks references
and the one-to-three experiment limit before writing matching completed reports
and updating JSON status. It validates structure, not the truth of an AI claim;
the host remains responsible for evidence-based interpretation.

## Human-readable presentation

Final reports follow the hosting agent's language, inferred from its summary or
set explicitly with language: zh-CN or en. The agent should supply a short title
and a concise summary in the user's language. Optional sections entries link
observation_id to title, what_happened, interpretation, cue and watch_out.

The HTML report uses a north-up sampled GPS map with direction arrows and lettered
highlights, followed by each location's speed comparison and coaching narrative.
Letters are report locations, never invented official corner numbers. Positions
come from the actual reference lap; without valid geometry, the report states the
limitation. Use map-based location descriptions instead of unexplained distance
ranges. Speed traces retain physical reference-position alignment.

Primary text contains formatted lap times and plain-language practice fields.
Lead with the few corner areas most worth testing and their map locations.
The full mini-sector matrix, virtual sums and source-switch audit are collapsed
under calculation details after the coaching, so they do not bury the action plan.
Selection details are collapsed; raw measurements and provenance remain in JSON.
Main maps and speed figures are inline SVG, so the completed HTML can be opened
as one file without network access or neighboring image files.

For local real-data validation, set TRACK_TELEMETRY_REAL_RCZ to a private RCZ path
and run pytest tests/test_debrief.py. Recordings are never added to the repository.

### Corner-focused presentation

Lead with the fastest actual lap versus the mini-sector theoretical best, then the three priority locations. Keep recording statistics and the full mini-sector matrix in the evidence or closed details. For each priority section, `corner_passages` retains every aligned real passage, with the adjacent sections as context. Inspect the highlighted baseline/donor GPS routes, measured lateral and longitudinal G, and separate pedal, throttle body, pressure and steering traces before writing the diagnosis. Context-window statistics must not be presented as target-sector statistics; `core_g_usage` covers the target alone. G availability requires verified source and native-rate gates. GPS scatter includes drift and does not prove a line advantage. The theoretical sum has no continuous GPS or G trace.

The report now opens route details at the target section and provides local zoom,
pan and adjoining-window controls. Control/response traces remain visible on the
same physical-position axis; the shaded band is the timed target, not an official
corner boundary. `sections` order determines presentation priority while map
letters remain stable. Add `braking_analysis`, `steering_analysis`, and
`power_analysis` and `g_analysis` prose after inspecting actual measurements. `input_analysis`
reuses `analyze_braking` events and retains raw control summaries; high-pedal
crossings are recorded samples at >=90%, not sustained application or proof of
intent. Review `timing_check` before recommending a donor: the sector advantage
may disappear when adjacent sections are counted. Never compare two different
window minima as a common apex. The report's embedded zoom controls work offline;
all coaching text remains HTML-escaped.

Default corner presentation: exactly one power-control trace (prefer accelerator pedal), one brake trace (prefer pressure), steering, and planar combined G = hypot(lat_g, long_g). Use one short finding per item; omit duplicate sensors and repeated caveats. Keep detailed channels and provenance in JSON.

Treat mini-sectors as loss locators, not causal corner boundaries. Inspect
`corner_passages.chain_window` and split upstream/target/downstream timing.
The provisional window follows verified brake events toward the next brake,
using shared physical limits for both laps. Missing events fall back explicitly;
lap boundaries truncate the chain. Non-overlapping upstream events may be different
corners, not a matched action. Trace exit-speed deficits into downstream acceleration
before prescribing; do not diagnose an already-full-pedal sector as late power.
Keep the four concise signal findings, but name the upstream action to practise
and measure the full linked window. Official corner/straight identity still needs
external confirmation.
