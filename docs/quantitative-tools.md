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
