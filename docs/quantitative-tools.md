# Quantitative measurements

## Reference laps and G usage

`compare_reference_laps(driver_path, driver_lap, reference_path, reference_lap,
same_layout_confirmed=True)` reuses the physical GPS projection and alignment
quality gates from `compare_laps`. Positive delta means the driver is slower.
It returns a distance profile, mini-sectors, the three largest positive losses,
and independent optional G measurements for each lap. Missing G does not block
GPS comparison. Confirm vehicle, tires, conditions and traffic separately.
An observed time difference is not a guaranteed improvement.

`analyze_gg_usage(path, lap_number)` returns time-weighted occupancy above
0.5/1.0/1.5 G, braking/acceleration/combined-load occupancy, and the observed
combined-G peak and weighted 95th percentile. These describe recorded use,
not available tire grip or a percentage of an assumed friction circle.

G measurements require verified CAN/IMU acceleration provenance, G units,
unique increasing clocks, at least 5 Hz output, and 80% coverage by valid
matched intervals. Samples pair within 20 ms, without interpolation. Gaps
over 250 ms and non-finite points contribute no duration. Output rates can
reflect converter resampling and must not be called native acquisition rates.
Sensor mounting, axis signs, grade and banking remain interpretation limits.

## TTC inputs

Install `.[rcz]` for RCZ, RaceChrono CSV and VBOX VBO, or `.[ttc]` to also
install libxrk for AiM XRK/XRZ. Discovery and path-based tools accept these
extensions. This is a supported subset, not full TTC format parity.

Sessions report source format, parser diagnostics, source channel inventory,
recording datetime with timezone limitations, and clock semantics. Timestamps
retain their common TTC clock; channels are never rebased individually.
Wheel speeds map to `wheel_fl/fr/rl/rr_kmh`.

RCZ retains original lap IDs, stints and recorder epoch. AiM retains logger
lap IDs and shared-clock boundaries. CSV preserves original labels separately
from unique selection IDs, bounds interior laps by label transitions, and marks
edge groups partial. Transitions have sample-interval timing uncertainty.
CSV without labels and VBO without TTC lap metadata have no timed laps.

CSV accelerator_pos/PPS remains pedal position. Ambiguous mixed pedal/body
exports are rejected. Non-RCZ names alone do not prove independent CAN/IMU
measurements. Unknown provenance remains unknown, so source-sensitive tools
can be unavailable after parsing. Automated binary adapter dispatch/clock tests
use synthetic TTC results. A separate local smoke check with TTC's public
`aim_sample.xrk` and its zlib-compressed XRZ copy verified identical normalized
channel values, timestamps and 11 laps using libxrk 0.13.0. No private recording
is needed or included. The normalized sample preserves GPS start at 0.068 s
versus RPM at 0 s, speed conversion and recording datetime.

## Vehicle response measurements

All tools operate on one selected timed lap. They use nearby measured samples
without interpolation and require at least 80% matched interval coverage.
Unknown units, unverified required sources and inadequate rates fail closed.
`prepare_session` reports prerequisite availability; runtime quality gates remain
mandatory. Native rates come from RCZ device/PID inventory or explicit session
metadata. Export/output sample rates never substitute for native acquisition.

`analyze_braking_efficiency` measures contiguous control-active intervals,
speed loss, integrated travel distance, speed-energy deceleration in G,
measured mean deceleration and the brake-control integral. Speed, G and brake
require native rates >=5 Hz. Missing intervals split events. There is no
universal efficiency score, inferred grip ceiling or claim of optimal braking.
Pressure uses kPa, pedal uses percent, and their integrals are not interchangeable.

`analyze_wheel_speeds` requires all four measured wheels at native >=20 Hz,
plus speed, lateral G and brake at native >=10 Hz. Matched output is >=20 Hz
within 10 ms. It reports maximum wheel spread and sustained deficits >=10%
for >=0.1 s versus recorded speed during braking at >=30 km/h and |lateral G|
<=0.1. This is a wheel-speed deficit proxy, not a true tire slip ratio.
ABS activation remains `not_confirmed`. Direct ABS status is required to
confirm intervention. Turning, tire sizes, filtering and GPS latency confound
the proxy; no eligible braking means no assessment opportunity.

`analyze_steering_response` requires measured steering and independent yaw at
native >=10 Hz, speed at native >=5 Hz, >=10 Hz near-uniform continuous matched
output, >=5 s duration, >=5 degrees steering range, and changing yaw/steering.
Speed must stay >=30 km/h with range <=20 km/h. It searches 0-0.5 s positive
delay using signed correlation of sample changes and reports signed yaw gain
against recorded steering angle. Correlation magnitude must reach 0.6.
Clock offsets and filtering contribute to delay; a boundary peak is flagged.
Neither an understeer gradient nor a road-wheel steering ratio is inferred.
