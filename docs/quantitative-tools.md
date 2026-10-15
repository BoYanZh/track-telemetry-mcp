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
can be unavailable after parsing. Binary adapter dispatch/clock tests use
synthetic TTC results; they do not claim real XRK/XRZ decoder validation.
