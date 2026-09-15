"""Lap, section, and same-layout comparison metrics."""

from __future__ import annotations

from typing import Any

import numpy as np

from .channels import (
    ACCELERATOR_PCT,
    BRAKE_PRESSURE_KPA,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    LAT_G,
    LONG_G,
    SPEED_KMH,
    THROTTLE_PCT,
    YAW_RATE_DPS,
)
from .controls import select_power_control
from .geometry import cumulative_distance_m, latlon_to_xy_m
from .models import Lap, TelemetrySession


def fastest_timed_lap(session: TelemetrySession) -> Lap | None:
    timed = [lap for lap in session.laps if lap.is_timed and np.isfinite(lap.duration_s)]
    return min(timed, key=lambda lap: lap.duration_s) if timed else None


def _lap_gps_progress(
    session: TelemetrySession, lap: Lap
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lat_ch = session.channel(GPS_LATITUDE_DEG)
    lon_ch = session.channel(GPS_LONGITUDE_DEG)
    mask = (lat_ch.timestamps >= lap.start_s) & (lat_ch.timestamps <= lap.end_s)
    t = lat_ch.timestamps[mask]
    lat = lat_ch.values[mask]
    lon = lon_ch.interp(t)
    valid = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon)
    t, lat, lon = t[valid], lat[valid], lon[valid]
    if len(t) < 3:
        raise ValueError(f"Lap {lap.number} has too few valid GPS samples")

    x, y = latlon_to_xy_m(lat, lon)
    distance = cumulative_distance_m(x, y)
    if distance[-1] <= 0:
        raise ValueError(f"Lap {lap.number} GPS distance is zero")
    progress = distance / distance[-1]

    keep = np.concatenate(([True], np.diff(progress) > 1e-9))
    return t[keep], progress[keep], distance[keep]


def _channel_on_progress(
    session: TelemetrySession,
    lap: Lap,
    channel_name: str,
    progress_grid: np.ndarray,
) -> np.ndarray:
    t, progress, _ = _lap_gps_progress(session, lap)
    values = session.channel(channel_name).interp(t)
    valid = np.isfinite(progress) & np.isfinite(values)
    if np.count_nonzero(valid) < 2:
        return np.full_like(progress_grid, np.nan, dtype=np.float64)
    return np.interp(progress_grid, progress[valid], values[valid], left=np.nan, right=np.nan)


def _elapsed_on_progress(
    session: TelemetrySession, lap: Lap, progress_grid: np.ndarray
) -> tuple[np.ndarray, float]:
    t, progress, distance = _lap_gps_progress(session, lap)
    elapsed = t - lap.start_s
    out = np.interp(progress_grid, progress, elapsed)
    return out, float(distance[-1])


def _window_values(session: TelemetrySession, lap: Lap, name: str) -> np.ndarray:
    channel = session.optional_channel(name)
    if channel is None:
        return np.array([], dtype=np.float64)
    mask = (channel.timestamps >= lap.start_s) & (channel.timestamps <= lap.end_s)
    return channel.values[mask]


def _window_channel_values(channel, lap: Lap) -> np.ndarray:
    if channel is None:
        return np.array([], dtype=np.float64)
    mask = (channel.timestamps >= lap.start_s) & (channel.timestamps <= lap.end_s)
    return channel.values[mask]


def _safe_stat(values: np.ndarray, op: str) -> float | None:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return None
    if op == "min":
        return float(np.min(values))
    if op == "max":
        return float(np.max(values))
    if op == "mean":
        return float(np.mean(values))
    if op == "p95_abs":
        return float(np.percentile(np.abs(values), 95))
    raise ValueError(op)


def lap_summary(session: TelemetrySession, lap_number: int) -> dict[str, Any]:
    lap = session.lap(lap_number)
    speed = _window_values(session, lap, SPEED_KMH)
    control_source, control_channel = select_power_control(session)
    control = _window_channel_values(control_channel, lap)
    lat_g = _window_values(session, lap, LAT_G)
    long_g = _window_values(session, lap, LONG_G)
    yaw = _window_values(session, lap, YAW_RATE_DPS)

    result: dict[str, Any] = {
        "lap": lap.to_dict(),
        "speed_kmh": {
            "min": _safe_stat(speed, "min"),
            "mean": _safe_stat(speed, "mean"),
            "max": _safe_stat(speed, "max"),
        },
        "lat_g_abs_p95": _safe_stat(lat_g, "p95_abs"),
        "long_g_min": _safe_stat(long_g, "min"),
        "yaw_rate_abs_p95_dps": _safe_stat(yaw, "p95_abs"),
        "control_source": control_source,
    }
    if len(control):
        valid = control[np.isfinite(control)]
        full_fraction = float(np.mean(valid >= 95.0)) if len(valid) else None
        result["full_control_fraction"] = full_fraction
        if control_source == THROTTLE_PCT:
            result["full_throttle_fraction"] = full_fraction
        elif control_source == ACCELERATOR_PCT:
            result["full_accelerator_fraction"] = full_fraction
    return result


def section_metrics(
    session: TelemetrySession,
    lap_number: int,
    start_progress: float,
    end_progress: float,
    *,
    samples: int = 401,
) -> dict[str, Any]:
    """Measure a lap section addressed by normalized GPS distance [0, 1]."""
    if not (0.0 <= start_progress < end_progress <= 1.0):
        raise ValueError("Expected 0 <= start_progress < end_progress <= 1")
    lap = session.lap(lap_number)
    grid = np.linspace(start_progress, end_progress, max(21, int(samples)))
    speed = _channel_on_progress(session, lap, SPEED_KMH, grid)
    if not np.any(np.isfinite(speed)):
        raise ValueError("Section has no valid speed samples")
    min_i = int(np.nanargmin(speed))

    result: dict[str, Any] = {
        "lap_number": lap_number,
        "start_progress": start_progress,
        "end_progress": end_progress,
        "entry_speed_kmh": float(speed[0]),
        "min_speed_kmh": float(speed[min_i]),
        "min_speed_progress": float(grid[min_i]),
        "exit_speed_kmh": float(speed[-1]),
    }

    control_source, control_channel = select_power_control(session)
    result["control_source"] = control_source
    if control_source is not None and control_channel is not None:
        control = _channel_on_progress(session, lap, control_source, grid)
        entry_control = float(control[0]) if np.isfinite(control[0]) else None
        exit_control = float(control[-1]) if np.isfinite(control[-1]) else None
        candidates = np.flatnonzero((np.arange(len(grid)) >= min_i) & (control >= 90.0))
        reapply_progress = float(grid[candidates[0]]) if len(candidates) else None

        result["entry_control_pct"] = entry_control
        result["exit_control_pct"] = exit_control
        result["full_control_reapply_progress"] = reapply_progress

        if control_source == THROTTLE_PCT:
            result["entry_throttle_pct"] = entry_control
            result["exit_throttle_pct"] = exit_control
            result["full_throttle_reapply_progress"] = reapply_progress
        elif control_source == ACCELERATOR_PCT:
            result["entry_accelerator_pct"] = entry_control
            result["exit_accelerator_pct"] = exit_control
            result["full_accelerator_reapply_progress"] = reapply_progress

    if session.optional_channel(BRAKE_PRESSURE_KPA) is not None:
        brake = _channel_on_progress(session, lap, BRAKE_PRESSURE_KPA, grid)
        result["peak_brake_pressure_kpa"] = (
            float(np.nanmax(brake)) if np.any(np.isfinite(brake)) else None
        )
        onset = np.flatnonzero(brake >= 100.0)
        result["brake_onset_progress"] = float(grid[onset[0]]) if len(onset) else None

    return result


def compare_laps(
    session_a: TelemetrySession,
    lap_a_number: int,
    session_b: TelemetrySession,
    lap_b_number: int,
    *,
    same_layout_confirmed: bool,
    mini_sectors: int = 20,
) -> dict[str, Any]:
    """Compare two laps by normalized GPS distance.

    This method is intentionally gated. Normalized distance is invalid for different layouts;
    callers must explicitly confirm the same physical layout first.
    """
    if not same_layout_confirmed:
        raise ValueError(
            "Normalized-distance comparison requires same_layout_confirmed=True. "
            "For different layouts, compare shared physical sections aligned by GPS instead."
        )
    if mini_sectors < 1:
        raise ValueError("mini_sectors must be positive")

    lap_a = session_a.lap(lap_a_number)
    lap_b = session_b.lap(lap_b_number)
    edges = np.linspace(0.0, 1.0, mini_sectors + 1)
    elapsed_a, distance_a = _elapsed_on_progress(session_a, lap_a, edges)
    elapsed_b, distance_b = _elapsed_on_progress(session_b, lap_b, edges)
    sector_a = np.diff(elapsed_a)
    sector_b = np.diff(elapsed_b)

    sectors = []
    for i in range(mini_sectors):
        sectors.append(
            {
                "sector": i + 1,
                "start_progress": float(edges[i]),
                "end_progress": float(edges[i + 1]),
                "lap_a_s": float(sector_a[i]),
                "lap_b_s": float(sector_b[i]),
                "a_minus_b_s": float(sector_a[i] - sector_b[i]),
            }
        )

    return {
        "lap_a": lap_a.to_dict(),
        "lap_b": lap_b.to_dict(),
        "lap_a_minus_b_total_s": float(lap_a.duration_s - lap_b.duration_s),
        "gps_distance_m": {"lap_a": distance_a, "lap_b": distance_b},
        "mini_sectors": sectors,
    }
