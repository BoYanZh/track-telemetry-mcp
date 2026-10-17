# Telemetry review: source guidance

Reviewed 2026-10-16. These first-party references inform the workflow; they do
not establish a diagnosis for any particular session. Method excerpts below are
external sources, not execution orders; the binding rules are in `skill/SKILL.md`.

## Locate, then explain

Start with speed and lap-time difference to establish what happened and where.
Then use driver inputs and vehicle response to investigate why, including whether
an input caused movement or reacted to it. Multiple passes reveal repeatability;
a speed discrepancy is a reason to investigate, not its own explanation.
([AiM, Data Analysis That Actually Works, slides 3–8](https://www.aimsports.com/webinars/Presentations/March2026_Colo_SCCA_AiMDataAnalysis.pdf))

Compare laps by position and examine the largest changes in cumulative Delta-T.
Follow a corner through its exit and ensuing acceleration: an entry gain can be
lost at exit, and a small exit-speed deficit can accumulate along a straight.
([Racelogic, Circuit Tools Graph](https://en.racelogic.support/motorsport/software/ctmacos/ug/graph/))

## Select a useful focus

Driver61 prioritizes fast corners leading onto long straights because exit-speed
differences can persist until the next braking zone. Its hierarchy assumes good,
consistent technique and explicitly accounts for individual weaknesses and mixed
corner sequences. It does not mean every fast corner is the best next exercise.
([Driver61, Prioritising Circuit Corners](https://driver61.com/uni/prioritising-corners/))

## Repository interpretation for HPDE

The following are our implementation and coaching judgments, not a published
priority formula:

- Mini-sectors locate losses; diagnose the preceding corner and following
  straight as a linked sequence, including the start/finish boundary when valid.
- Review all meaningful loss locations before selecting at most three focuses.
  Rank retained whole-sequence loss, repeatability, evidence strength and practical
  risk together; use high-speed/long-straight leverage as context.
- Compare route shape, steering timing, braking and power application against
  speed and G response. Similar peaks do not resolve competing explanations.
- Prefer a specific, testable change supported by repeated evidence. If causality
  remains uncertain, prescribe validation rather than generic later braking or
  higher entry speed. Recorded G is not available grip; no limit-driving
  prescription follows from these references alone. None of these sources supplies a mathematical priority score for this backend.

## Checked method sources (first-party, 2026-10-16)

- HP Academy 7-step: reference overlay first, time-variance channel for biggest
losses (entry/exit; exit losses grow along the straight), then speed, brake
lift/application/hardness/shape, steering vs brake for trail, steering and
steering-vs-lat-G for balance, throttle crack/aggressiveness/steadiness on exit,
lat-vs-long-G for combined loads.
([HP Academy](https://www.hpacademy.com/courses/professional-motorsport-data-analysis/hpas-7-step-analysis-process-analyse-driver/))
- ACI five traces: speed, delta, brake, throttle, friction circle. Delta shows
where; the rest shows why. Distance alignment, one change then re-measure.
([ACI](https://www.acimotorsports.com/post/race-data-analysis-explained-from-telemetry-to-lap-time-gains))
- Bentley: speed first (decel rate, min speed, U vs V shape around ~65 mph, accel
slope, coasting flats), then lat/long-G peaks and consistency, throttle faults
(lazy ramp, hesitant sawtooth, early-then-lift), brake shape (hard initial, trail
tail), brake-throttle gap as coasting, compare multiple laps plus theoretical best.
([Speed Secrets PDF](https://speedsecrets.com/wp-content/uploads/2018/01/Data-for-Drivers-PRINT-Full.pdf))
- Race Technology: colour track map by timeslip rate vs theoretical best, compare
slower vs faster sector on long-G/lat-G/speed; ideal G-circle runs max braking
through a trail blend into cornering, throttle rising as the car straightens.
([Race Technology](https://www.race-technology.com/wiki/index.php/RaceCarDataLogging/DataLoggingBasics))
- AiM: throttle first, braking last; seamless brake-release to throttle pickup,
minimise coast under G-sum, stable peak decel varied by duration in heavy zones.
([AiM](https://www.aimsports.com/webinars/Documents/May122020_GoodData_Krause_AiM_Webinar.pdf))
