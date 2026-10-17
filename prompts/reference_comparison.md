# Reference driver comparison

Find transferable lessons from an external driver, not a speed target to copy.
Read and execute [the unified workflow](../docs/analysis-methodology.md), stages
1–6. `skill/SKILL.md` owns source semantics and diagnosis categories;
`docs/session-debrief.md` owns artifact schemas and finalization.

## Independent screening before practice selection

Supply reference files via `reference_paths` / `--reference`, separately from
own files. Read every window in `external_reference_scan`; do not restrict the
expert to the driver's own top sectors. Report two rankings: observed external
time differences and next-session practice priorities. Review all large fast
corner differences even when the driver's own laps are uniformly slow there.
Provide external_decisions for the five largest external gaps, with an explicit
practice/validate/defer reason per window, before finalization. Choose at most
three practice/validation focuses. Use stable physical S IDs; list unmatched
areas rather than calling the coverage complete.

## Reference-specific choices

- Retain the driver's own PB and repeatable passages as the training baseline.
  Compare the external driver's repeated good passages, not just one fastest lap.
- Verify vehicle, tires, transmission, setup, conditions and source comparability
  where evidence exists. A vehicle label is not a verified configuration.
- Confirm physical layout independently before whole-lap comparisons. Otherwise
  analyze only established shared physical sections; do not use whole-lap fractions
  across incompatible layouts or treat GPS fit alone as confirmation.
- Normalize units explicitly while preserving raw values and source clocks.
  Compare power channels only when semantics match. Unknown channel origin stays
  unknown; a channel label does not prove pedal/body identity or acquisition rate.
- Video-overlay estimates remain approximate pseudo telemetry. Prefer calibrated
  speed/position; do not equate video brake percentage to hydraulic pressure.
- Store repeated reference-lap measurements and alignment quality individually.
  Separate entry-state, vehicle and condition advantages from technique candidates.
- Treat high-speed advantages as later validation when route or control causes
  remain unresolved. Do not prescribe reference speeds or G peaks as targets.

## Delivery

For each located area state diagnosis, measured difference, competing explanation,
G/vehicle response when available, and one next-session action or validation.
Keep source details in JSON and generic limitations in collapsed notes. Apply the
unified completion checklist; finish reports and a prioritized practice plan.

Use the unified workflow's brake-boundary and loss-attribution requirements before
quantifying an improvement; show them beside the diagnosed location.

Each external decision also requires `cue`: one short driver-facing sentence
stating what to do or test next session. Render cue in the overview; keep the
selection/deferral reason in collapsed priority notes. Ranking mechanics and
overlap warnings are not practice instructions.
