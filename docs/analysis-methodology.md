# Telemetry Analysis Methodology

This document defines the default review process for driver telemetry in this repository.

The goal is not to inspect every channel. The goal is to find the largest credible time loss, explain it with the smallest useful set of measurements, and turn it into a small number of testable driving changes.

## Review loop

```text
Validate data
  -> Select reference
  -> Locate time loss
  -> Classify the loss
  -> Diagnose inputs and vehicle response
  -> Cross-check context
  -> Prioritize by gain / repeatability / confidence / risk
  -> Prescribe <= 3 changes
  -> Re-test next session
```

This is a closed loop. Every recommendation should become a hypothesis that can be checked in the next session.

## 1. Validate the data

Before interpreting technique, confirm that the evidence is usable.

Check:

- session and layout identity;
- timed-lap validity;
- channel availability and sample rates;
- missing, frozen, sparse, or obviously invalid channels;
- source semantics, especially throttle body vs accelerator pedal;
- yaw-rate source before any sideslip analysis;
- whether the lap contains traffic, cooldown behavior, a yellow flag, an off-track, or another confounder.

MCP mapping:

```text
list_sessions
  -> prepare_session
  -> inspect_session when detailed channel/sample-rate context matters
```

Do not silently turn missing or low-quality data into a measurement.

## 2. Select the reference

Choose the strongest reference that answers the question while minimizing confounders.

A useful preference order is:

1. faster driver, same car, same physical layout, comparable conditions;
2. the driver's own clean best lap;
3. a representative good lap from the same session;
4. an external onboard/video reference with approximate extracted telemetry.

A personal-best lap is not automatically the best technique reference. It may contain one unusually strong sector and several mediocre ones.

For normalized-distance comparison, independently confirm that both laps use the same physical layout before calling `compare_laps`.

## 3. Locate time loss first

Start with **where time is lost**, not with a favorite channel or technique theory.

Use lap delta, mini-sectors, speed traces, and section timing to identify the few areas that matter most.

Typical sequence:

```text
whole-lap comparison
  -> top time-loss sectors
  -> one or two candidate corners/sections
  -> detailed section analysis
```

MCP mapping:

- `compare_laps` for same-layout mini-sector comparison;
- `analyze_lap` for broad lap-level context;
- `analyze_section` after the important section has been identified.

Do not scan every specialized tool before finding the important loss areas.

## 4. Treat consistency as a first-class metric

Do not optimize only for one hero lap.

Compare:

- PB vs representative good lap;
- best sectors vs repeatable sectors;
- repeated entry/minimum/exit behavior;
- braking and control timing variance;
- whether the faster technique is repeatable without large corrections or excursions.

A slower but repeatable pattern can be a better training baseline than an isolated fast event.

When the evidence suggests inconsistent execution, classify the primary problem as **consistency / execution variance** rather than forcing it into a corner-speed or braking category.

## 5. Classify the loss

For each important section, identify the primary diagnosis before prescribing a fix.

Use this taxonomy:

1. conservative entry / braking too early;
2. long or weak braking;
3. excessive minimum-speed loss / overslow;
4. power control reapplied too late;
5. weak exit speed;
6. line / placement / geometry problem;
7. consistency / execution variance;
8. already good enough / poor risk-reward to chase.

Do not collapse these into generic advice such as "carry more speed."

## 6. Diagnose inputs and vehicle response

Once the important section and loss type are known, inspect the minimum evidence needed to explain it.

A useful order is:

### Braking

```text
lift
-> brake onset
-> pressure/pedal build
-> raw and sustained deceleration
-> release timing
-> overlap with steering
```

Use `analyze_braking` when braking behavior is the question.

Do not infer ABS activation from brake pressure alone.

### Entry and mid-corner

```text
turn-in
-> brake release / trail-brake overlap
-> speed decay
-> minimum speed
-> steering demand
-> yaw / lateral response when relevant
```

Use `analyze_section` for entry/minimum/exit behavior.

Use `analyze_slip_angle` only when rotation/sliding matters and the session has yaw rate independent of GPS course.

### Exit

```text
first power input
-> modulation
-> sustained/full power
-> steering unwind
-> exit speed
```

Always preserve `control_source`: accelerator-pedal percentage is not throttle-body percentage.

### Incidents

Use `analyze_incident` only for a known bounded incident window. Use video or driver observation for external events such as a surface change; do not infer them from telemetry alone.

## 7. Cross-check context

Before turning a numerical difference into a technique conclusion, ask whether another explanation is more likely.

Examples:

- traffic or point-by;
- yellow flag or cooldown lap;
- tire-pressure or temperature issue;
- a deliberate lift for safety;
- a curb or surface the driver was avoiding;
- different track layout;
- different vehicle/setup/conditions;
- sensor dropout or source fallback.

Video and driver feedback are context. They should confirm or challenge the telemetry interpretation, not be silently promoted to sensor measurements.

## 8. Prioritize by gain, repeatability, confidence, and risk

Do not rank opportunities by theoretical lap time alone.

A useful qualitative model is:

```text
priority ~ expected time gain
           x repeatability benefit
           x evidence confidence
           / execution risk
```

This does not need to be a literal numeric score. It is a reasoning framework.

Prefer:

- large, repeated losses;
- changes supported by multiple measurements;
- improvements that make the car easier to place and repeat;
- lower-risk opportunities before high-speed limit chasing.

For high-speed sections, a faster reference is evidence, not an instruction to reproduce the same slip or correction.

## 9. Prescribe at most three changes

A useful recommendation should be small enough to execute on track.

Each change should contain:

- **cue** — what the driver should do or notice;
- **metric** — what telemetry should move if the hypothesis is correct;
- **success condition** — what better execution looks like;
- **abort condition** — what indicates the change should not be pushed further.

Example:

```text
Hypothesis:
The driver is overslowing because the main braking phase extends too far into turn-in.

Change:
Finish the main deceleration slightly earlier and release more decisively.

Cue:
Begin releasing as steering load builds instead of holding a large brake input to minimum speed.

Metric:
Higher minimum speed with similar or earlier brake onset and shorter high-pressure duration.

Success:
The gain repeats across several clean laps without larger steering corrections.

Abort:
The car becomes difficult to place, requires unexpected countersteer, or reduces track margin.
```

Limit a normal debrief to the highest-value one to three changes.

## 10. Re-test next session

Every recommendation should create a measurable next-session experiment.

Use:

```text
hypothesis
  -> driving change
  -> measurable target
  -> repeated clean attempts
  -> telemetry validation
  -> keep / revise / discard
```

Compare the new result against both the prior PB and a representative baseline. Improvement means more than a single faster lap: look for repeatability, cleaner control, and the expected metric change.

## Recommended output

Start with the main conclusion, then the evidence.

A useful section table is:

| Section | Time loss | Entry | Minimum | Exit | Primary diagnosis | Confidence | Risk/ROI |
|---|---:|---:|---:|---:|---|---|---|

Then report:

1. the highest-value opportunities;
2. what not to chase yet;
3. at most three next-session experiments, each with cue / metric / success / abort.

## Relationship to the MCP

The MCP provides deterministic measurements. The methodology decides **which measurement to request next**.

```text
Methodology: where is the important loss and what evidence would resolve it?
      |
      v
MCP tools: calculate the requested evidence
      |
      v
Agent: interpret, prioritize, prescribe, and define the next test
```

The default agent flow remains:

```text
list_sessions
  -> prepare_session
  -> locate the important loss
  -> smallest relevant analysis tool set
  -> interpretation and next-session experiment
```

For repository-level constraints see [`../AGENTS.md`](../AGENTS.md). For detailed source semantics and task-specific analysis policy see [`../skill/SKILL.md`](../skill/SKILL.md).
