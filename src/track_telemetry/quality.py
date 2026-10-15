"""Conservative, timestamp-matched measurement windows without interpolation."""

from __future__ import annotations

import numpy as np

from .models import TelemetrySession


def channel_source(session: TelemetrySession, name: str, lap_number: int) -> str:
    lap = session.lap(lap_number)
    by_stint = session.metadata.get("channel_provenance_by_stint", {})
    sources = by_stint.get(lap.stint, by_stint.get(str(lap.stint), {}))
    keys = {"long_g": "longitudinal_accel_source", "lat_g": "lateral_accel_source",
            "yaw_rate_dps": "yaw_rate_source"}
    return str(sources.get(name, session.metadata.get("channel_sources", {}).get(
        name, session.metadata.get(keys.get(name, ""), "unknown"))))


def measured_source(source: str) -> bool:
    return source in {"can", "imu"} or source.startswith(("rcz_can_", "rcz_gyro_", "rcz_accelerometer_"))


def native_rate(session: TelemetrySession, name: str, lap_number: int) -> float | None:
    """Resolve native rates from recorder inventory, never from resampled output."""
    declared = session.metadata.get("native_sample_rate_hz", {}).get(name)
    if declared is not None:
        return float(declared)
    lap = session.lap(lap_number)
    source = channel_source(session, name, lap_number)
    for inventory in session.metadata.get("device_summary_by_stint", []):
        if inventory["stint"] != lap.stint:
            continue
        for device in inventory.get("devices", []):
            dev_id = device["device_id"]
            prefix = f"rcz_can_12_{dev_id}_pid_"
            if device["role"] == "can_obd" and source.startswith(prefix):
                return device.get("native_can_pid_rates", {}).get(
                    "pid_" + source[len(prefix):], {}).get("rate_hz")
            if ((device["role"] == "gyroscope" and source == f"rcz_gyro_3_{dev_id}") or
                    (device["role"] == "accelerometer" and source == f"rcz_accelerometer_2_{dev_id}") or
                    (device["role"] == "gps" and source == f"rcz_gps_1_{dev_id}")):
                return device.get("native_sample_rate_hz")
    return None


def require_native_rates(session: TelemetrySession, lap_number: int,
                         names: tuple[str, ...], min_hz: float) -> dict:
    rates = {name: native_rate(session, name, lap_number) for name in names}
    if any(rate is None or not np.isfinite(rate) or rate < min_hz for rate in rates.values()):
        raise ValueError(f"Verified native sampling >= {min_hz:g} Hz required: {rates}")
    return rates


def matched_window(
    session: TelemetrySession, lap_number: int, names: tuple[str, ...],
    *, min_hz: float = 5.0, max_gap_s: float = 0.25, tolerance_s: float = 0.02,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Pair nearby finite raw points; weights count only consecutive valid intervals.

    Reject duplicate clocks, large gaps and low coverage. Never match outside the
    selected lap or repeatedly reuse one slow-channel point to create high-rate data.
    """
    lap = session.lap(lap_number)
    if not lap.is_timed or not np.isfinite(lap.duration_s) or lap.duration_s <= 0:
        raise ValueError("A finite positive timed lap is required")
    series = [session.channel(name).slice(lap.start_s, lap.end_s) for name in names]
    for ch in series:
        if len(ch.timestamps) < 10 or not np.all(np.isfinite(ch.timestamps)):
            raise ValueError(f"Insufficient finite timestamps: {ch.name}")
        dt = np.diff(ch.timestamps)
        if np.any(dt <= 0) or (ch.sample_rate_hz or 0) < min_hz:
            raise ValueError(f"Requires unique timestamps and >= {min_hz:g} Hz: {ch.name}")
    # Slowest output channel supplies the clock. Native rates remain separate.
    base = min(series, key=lambda ch: ch.sample_rate_hz or 0)
    t = base.timestamps
    columns = []
    good = np.ones(len(t), dtype=bool)
    errors = []
    for ch in series:
        right = np.searchsorted(ch.timestamps, t).clip(0, len(ch.timestamps) - 1)
        left = np.maximum(right - 1, 0)
        idx = np.where(abs(t - ch.timestamps[left]) <= abs(t - ch.timestamps[right]), left, right)
        error = abs(t - ch.timestamps[idx])
        good &= (error <= tolerance_s) & np.isfinite(ch.values[idx])
        columns.append(ch.values[idx])
        errors.append(error)
    values = np.column_stack(columns)
    dt = np.diff(t)
    valid_interval = good[:-1] & good[1:] & (dt <= max_gap_s)
    weights = np.where(valid_interval, dt, 0.0)
    coverage = float(weights.sum() / lap.duration_s)
    if coverage < 0.8:
        raise ValueError(f"Matched interval coverage {coverage:.1%} is below 80%")
    return t, values, weights, {
        "coverage_fraction": coverage,
        "matched_samples": int(good.sum()),
        "output_sample_rate_hz": {ch.name: ch.sample_rate_hz for ch in series},
        "max_pair_error_s": float(np.max(np.array(errors)[:, good])),
        "max_gap_s": max_gap_s,
        "native_rate_note": "Output Hz may reflect converter resampling; native Hz is not inferred.",
        "sources": {name: channel_source(session, name, lap_number) for name in names},
        "native_sample_rate_hz": {name: native_rate(session, name, lap_number) for name in names},
    }
