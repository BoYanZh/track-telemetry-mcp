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
are excluded explicitly. Consistency includes all positive timed laps and is
reported separately per stint; traffic laps are not silently removed.

The reference is the fastest timed lap passing GPS self-alignment. This is a
candidate reference, not a certified clean lap. Cross-lap comparisons must also
pass existing physical GPS alignment gates. Loss ranking uses median signed
mini-sector differences over eligible comparisons, repeat support and cautious
confidence. Diagnostic examples use losses closest to the sector median,
rather than extreme slow laps. No theoretical-best sum or promised time saving is produced.
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

For local real-data validation, set TRACK_TELEMETRY_REAL_RCZ to a private RCZ path
and run pytest tests/test_debrief.py. Recordings are never added to the repository.
