# Vehicle sideslip / slip-angle proxy

The project estimates **vehicle sideslip angle** (often written `beta`) over a bounded
corner or incident window. This is not tire slip angle and it is not a direct body-heading
measurement.

## Why RaceChrono GPS heading is not enough by itself

`MotecLogGenerator` parses RaceChrono GPS heading into `CH_GPS_HEADING` / `YawNorth` and,
when a real yaw-rate channel is unavailable, can derive yaw rate by differentiating that
heading. In RaceChrono terminology the GPS quantity is the receiver's **bearing/course**:
it describes the direction of motion over the ground, not the physical direction the car
body is pointing.

Therefore this is invalid:

```text
slip angle = GPS bearing - GPS bearing
```

and so is any calculation that compares GPS bearing with a yaw rate that was itself
derived from the same GPS bearing. `analyze_slip_angle` rejects
`yaw_rate_source = gps_heading_derivative` by default.

## Definition used here

Let:

- `chi(t)` = GPS course/bearing, i.e. direction of travel;
- `r(t)` = independent vehicle yaw rate from CAN or gyroscope;
- `psi_est(t)` = estimated vehicle-body heading;
- `beta_proxy(t)` = estimated vehicle sideslip.

Choose an anchor time `t0` where the vehicle is believed to have approximately zero
sideslip, for example a stable straight or settled pre-corner segment:

```text
psi_est(t0) = chi(t0)
```

Then integrate yaw rate:

```text
psi_est(t) = psi_est(t0) + integral[r(t) dt]
```

and calculate:

```text
beta_proxy(t) = wrap_to_[-180,180)(chi(t) - psi_est(t))
```

The sign depends on yaw-rate convention. The MCP tool exposes `yaw_sign` so a source can
be corrected without silently changing the raw channel.

## Travel-heading source

The implementation prefers the RaceChrono GPS bearing channel when it has enough valid
samples. If it is unavailable, it derives course from the local latitude/longitude trace.
The latter is noisier and uses a short spatial window.

Neither source is vehicle-body heading.

## Required yaw-rate source

Useful sideslip estimation requires yaw rate independent from GPS course, for example:

- ECU/CAN yaw-rate sensor;
- RaceBox / phone / external IMU gyro Z, after the parser has aligned timestamps.

A `gps_heading_derivative` yaw-rate source is rejected because it is not independent.

## Why this remains a proxy

The body heading is obtained by integrating yaw rate. Gyro bias therefore accumulates as
heading drift. The anchor also assumes approximately zero sideslip at one instant. For
those reasons:

- prefer short corner/incident windows rather than whole-session integration;
- choose an anchor immediately before the maneuver when possible;
- mask very low speeds, where GPS course becomes noisy;
- use the magnitude/trend as stronger evidence than an exact absolute beta value;
- do not interpret it as front- or rear-tire slip angle.

A dual-antenna GNSS, optical heading system, or another direct body-heading measurement
would allow a substantially more direct sideslip calculation:

```text
beta = wrap(course_heading - measured_body_heading)
```

## MCP usage

```text
analyze_slip_angle(
    path="session.rcz",
    start_s=92.5,
    end_s=95.0,
    anchor_s=92.5,
    include_samples=true,
    sample_stride=1
)
```

Important result fields:

- `sources.travel_heading`
- `sources.yaw_rate`
- `sources.body_heading`
- `summary.max_abs_slip_angle_proxy_deg`
- `summary.rms_slip_angle_proxy_deg`
- per-sample `travel_heading_deg`
- per-sample `body_heading_estimate_deg`
- per-sample `slip_angle_proxy_deg`

The tool reports its assumptions and caveats in every result so an LLM should not silently
promote the proxy to a directly measured slip angle.
