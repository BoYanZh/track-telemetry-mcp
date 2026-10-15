"""Source-gated descriptive braking, wheel-speed and steering response metrics."""

from __future__ import annotations

import numpy as np

from .braking import _active_segments
from .channels import (
    BRAKE_POS_PCT,
    BRAKE_PRESSURE_KPA,
    LAT_G,
    LONG_G,
    SPEED_KMH,
    STEERING_DEG,
    WHEEL_FL_KMH,
    WHEEL_FR_KMH,
    WHEEL_RL_KMH,
    WHEEL_RR_KMH,
    YAW_RATE_DPS,
)
from .models import TelemetrySession
from .quality import channel_source, matched_window, measured_source, require_native_rates
from .slip_angle import yaw_is_independent

WHEELS = (WHEEL_FL_KMH, WHEEL_FR_KMH, WHEEL_RL_KMH, WHEEL_RR_KMH)


def _control(session):
    if BRAKE_PRESSURE_KPA in session.channels:
        return BRAKE_PRESSURE_KPA, 100.0
    if BRAKE_POS_PCT in session.channels:
        return BRAKE_POS_PCT, 3.0
    raise ValueError("Recorded brake pressure or brake pedal position required")


def _require_units(session, expected):
    for name, unit in expected.items():
        if session.channel(name).units.lower() != unit.lower():
            raise ValueError(f"{name} must use {unit} units")


def _require_measured(session, lap_number, names):
    if not all(measured_source(channel_source(session, name, lap_number)) for name in names):
        raise ValueError("Verified measured CAN/IMU sources required")


def analyze_braking_efficiency(session: TelemetrySession, lap_number: int) -> dict:
    """Measure speed loss per distance and brake application, not a grip-efficiency score."""
    control, threshold = _control(session)
    _require_measured(session, lap_number, (control, LONG_G))
    require_native_rates(session, lap_number, (control, LONG_G, SPEED_KMH), 5)
    _require_units(session, {control: "kPa" if control == BRAKE_PRESSURE_KPA else "%",
                             LONG_G: "G", SPEED_KMH: "km/h"})
    t, values, weights, quality = matched_window(session, lap_number, (SPEED_KMH, LONG_G, control))
    speed, g, brake = values.T
    # Break an application at missing samples or long gaps. Do not invent a
    # continuous braking event by integrating across an interruption.
    active = (brake[:-1] >= threshold) & (brake[1:] >= threshold) & (weights > 0)
    events = []
    for start, end in _active_segments(active):
        stop = end + 1
        duration = float(t[stop] - t[start])
        if duration < 0.2:
            continue
        v = speed[start:stop + 1] / 3.6
        if np.any(v < 0):
            raise ValueError("Negative speed in braking event")
        dt = np.diff(t[start:stop + 1])
        distance = float(np.sum((v[:-1] + v[1:]) * 0.5 * dt))
        effective_g = float((v[0] ** 2 - v[-1] ** 2) / (2 * distance * 9.80665)) if distance > 0 else None
        events.append({
            "start_s": float(t[start]), "end_s": float(t[stop]), "duration_s": duration,
            "distance_m": distance, "entry_speed_kmh": float(speed[start]),
            "exit_speed_kmh": float(speed[stop]), "speed_loss_kmh": float(speed[start] - speed[stop]),
            "speed_energy_deceleration_g": effective_g,
            "mean_measured_deceleration_g": float(np.sum(-(g[start:stop] + g[start + 1:stop + 1]) * 0.5 * dt) / duration),
            "control_integral_unit_s": float(np.sum((brake[start:stop] + brake[start + 1:stop + 1]) * 0.5 * dt)),
        })
    return {"lap": session.lap(lap_number).to_dict(), "quality": quality,
            "control_channel": control, "control_threshold": threshold,
            "event_count": len(events), "events": events,
            "limitations": ["No friction-limit or optimal-braking percentage is inferred.",
                            "Speed/G disagreement may reflect grade, drag, alignment or sensor error.",
                            "Events are observed control-active intervals, not exact pedal-onset boundaries."]}


def analyze_wheel_speeds(session: TelemetrySession, lap_number: int) -> dict:
    """Report four-wheel speed differences and straight-braking deficit indications.

    A wheel/GPS speed deficit is a proxy, not tire slip or confirmed ABS activation.
    High native sampling is mandatory; GPS resampling cannot qualify wheel sensors.
    """
    control, threshold = _control(session)
    _require_measured(session, lap_number, (*WHEELS, control, LAT_G))
    native = require_native_rates(session, lap_number, WHEELS, 20)
    require_native_rates(session, lap_number, (SPEED_KMH, control, LAT_G), 10)
    _require_units(session, {**dict.fromkeys((*WHEELS, SPEED_KMH), "km/h"), LAT_G: "G",
                             control: "kPa" if control == BRAKE_PRESSURE_KPA else "%"})
    t, values, weights, quality = matched_window(
        session, lap_number, (*WHEELS, SPEED_KMH, control, LAT_G),
        min_hz=20, max_gap_s=0.075, tolerance_s=0.01)
    wheel, speed, brake, lat = values[:, :4], values[:, 4], values[:, 5], values[:, 6]
    valid = weights > 0
    if np.any(wheel[1:][valid] < 0) or np.any(wheel[:-1][valid] < 0):
        raise ValueError("Wheel speeds must be non-negative")
    eligible = (valid & (speed[:-1] >= 30) & (speed[1:] >= 30) &
                (brake[:-1] >= threshold) & (brake[1:] >= threshold) &
                (abs(lat[:-1]) <= 0.1) & (abs(lat[1:]) <= 0.1))
    eligible_s = float(weights[eligible].sum())
    deficit = 1 - wheel / np.maximum(speed[:, None], 1)
    indications = {}
    for i, name in enumerate(WHEELS):
        mask = eligible & (deficit[:-1, i] >= 0.1) & (deficit[1:, i] >= 0.1)
        durations = [float(t[end + 1] - t[start]) for start, end in _active_segments(mask)
                     if t[end + 1] - t[start] >= 0.1]
        indications[name] = {"sustained_deficit_event_count": len(durations),
                             "sustained_deficit_duration_s": float(sum(durations))}
    return {"lap": session.lap(lap_number).to_dict(), "quality": quality,
            "native_wheel_rate_hz": native, "eligible_straight_braking_s": eligible_s,
            "constant_wheel_channels": [name for i, name in enumerate(WHEELS)
                                        if np.ptp(wheel[:-1][valid, i]) < 0.01],
            "maximum_wheel_spread_kmh": float(np.max(np.ptp(wheel[:-1][valid], axis=1))),
            "deficit_threshold_fraction": 0.1, "minimum_deficit_duration_s": 0.1,
            "wheel_deficit_indications": indications, "abs_activation": "not_confirmed",
            "limitations": ["Requires direct ABS status for confirmation; pressure or speed differences alone are insufficient.",
                            "Tire circumference, wheel calibration, GPS latency, turning and differential action confound deficits.",
                            "A constant channel can represent steady motion, wheel lock or a frozen sensor; inspect it before interpretation.",
                            "No eligible straight braking means no opportunity to assess deficits, not evidence of no ABS."]}


def analyze_steering_response(session: TelemetrySession, lap_number: int, *,
                              start_s: float | None = None, end_s: float | None = None) -> dict:
    """Measure signed steering/yaw gain and bounded delay correlation on a clean lap."""
    _require_measured(session, lap_number, (STEERING_DEG, YAW_RATE_DPS))
    if not yaw_is_independent(channel_source(session, YAW_RATE_DPS, lap_number)):
        raise ValueError("Independent yaw source required")
    native = require_native_rates(session, lap_number, (STEERING_DEG, YAW_RATE_DPS), 10)
    require_native_rates(session, lap_number, (SPEED_KMH,), 5)
    _require_units(session, {STEERING_DEG: "deg", YAW_RATE_DPS: "deg/s", SPEED_KMH: "km/h"})
    t, values, weights, quality = matched_window(
        session, lap_number, (STEERING_DEG, YAW_RATE_DPS, SPEED_KMH),
        min_hz=10, max_gap_s=0.15, tolerance_s=0.01, start_s=start_s, end_s=end_s)
    dt = np.diff(t)
    if np.any(weights <= 0) or np.max(abs(dt / np.median(dt) - 1)) > 0.05:
        raise ValueError("Response delay requires a continuous near-uniform matched clock")
    steering, yaw, speed = values.T
    if np.any(speed < 30) or np.ptp(speed) > 20:
        raise ValueError("Response requires >=30 km/h and speed range <=20 km/h")
    if np.ptp(steering) < 5 or np.std(yaw) < 0.5 or t[-1] - t[0] < 5:
        raise ValueError("Insufficient steering/yaw excitation or duration")
    ds, dy = np.diff(steering), np.diff(yaw)
    if np.std(ds) < 1e-6 or np.std(dy) < 1e-6:
        raise ValueError("Insufficient changing steering/yaw excitation")
    candidates = []
    max_lag = min(int(0.5 / np.median(dt)), len(ds) // 4)
    for lag in range(max_lag + 1):
        x = ds[:len(ds) - lag] if lag else ds
        y = dy[lag:] if lag else dy
        if np.std(x) > 1e-6 and np.std(y) > 1e-6:
            candidates.append((lag, float(np.corrcoef(x, y)[0, 1])))
    lag, correlation = max(candidates, key=lambda item: abs(item[1]))
    if abs(correlation) < 0.6:
        raise ValueError("Steering/yaw change correlation below 0.6")
    x = steering[:len(steering) - lag] if lag else steering
    y = yaw[lag:] if lag else yaw
    gain = float(np.dot(x - x.mean(), y - y.mean()) / np.sum((x - x.mean()) ** 2))
    return {"lap": session.lap(lap_number).to_dict(), "quality": quality,
            "native_response_rate_hz": native, "yaw_gain_dps_per_steering_deg": gain,
            "observed_delay_s": float(lag * np.median(dt)),
            "delay_resolution_s": float(np.median(dt)), "change_correlation": correlation,
            "delay_at_search_boundary": lag == max_lag,
            "speed_range_kmh": [float(speed.min()), float(speed.max())],
            "limitations": ["Correlation delay includes clock offsets, filtering and vehicle response; not causal proof.",
                            "Gain uses recorded steering-wheel angle; no road-wheel ratio or understeer gradient is inferred.",
                            "A peak at the search boundary may indicate a delay outside the 0-0.5 s search."]}
