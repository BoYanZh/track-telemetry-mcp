"""Lap, section, and same-layout comparison metrics."""

from __future__ import annotations

from typing import Any

import numpy as np

from .alignment import align_laps
from .channels import (
    ACCELERATOR_PCT,
    BRAKE_POS_PCT,
    BRAKE_PRESSURE_KPA,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    LAT_G,
    LONG_G,
    SPEED_KMH,
    STEERING_DEG,
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
    control_source, control_channel = select_power_control(
        session,
        start_s=lap.start_s,
        end_s=lap.end_s,
    )
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

    control_source, control_channel = select_power_control(
        session,
        start_s=lap.start_s,
        end_s=lap.end_s,
    )
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

    # Event order matters more for coaching than isolated peak values.
    timeline: dict[str, float | str | None] = {
        "brake_onset_progress": None,
        "peak_brake_progress": None,
        "brake_release_start_progress": None,
        "brake_end_progress": None,
        "steering_onset_progress": None,
        "steering_unwind_progress": None,
        "first_power_reapply_progress": None,
        "full_power_reapply_progress": result.get("full_control_reapply_progress"),
        "brake_steering_overlap_fraction": None,
        "brake_control_source": None,
    }
    brake_channel = session.optional_channel(BRAKE_PRESSURE_KPA)
    brake_name = BRAKE_PRESSURE_KPA
    brake_threshold = 100.0
    if brake_channel is None:
        brake_channel = session.optional_channel(BRAKE_POS_PCT)
        brake_name = BRAKE_POS_PCT
        brake_threshold = 3.0
    brake_active = np.zeros(len(grid), dtype=bool)
    if brake_channel is not None:
        brake = _channel_on_progress(session, lap, brake_name, grid)
        brake_active = np.isfinite(brake) & (brake >= brake_threshold)
        timeline["brake_control_source"] = brake_name
        onset = np.flatnonzero(brake_active)
        if len(onset):
            onset_i = int(onset[0])
            timeline["brake_onset_progress"] = float(grid[onset_i])
            result["brake_onset_progress"] = float(grid[onset_i])
            finite_after = np.where(np.isfinite(brake[onset_i:]), brake[onset_i:], -np.inf)
            peak_i = onset_i + int(np.argmax(finite_after))
            timeline["peak_brake_progress"] = float(grid[peak_i])
            # Event boundaries below are threshold crossings after peak pressure.
            release = np.flatnonzero(
                np.isfinite(brake[peak_i:]) & (brake[peak_i:] <= 0.9 * brake[peak_i])
            )
            if len(release):
                timeline["brake_release_start_progress"] = float(grid[peak_i + release[0]])
            finished = np.flatnonzero(
                np.isfinite(brake[peak_i:]) & (brake[peak_i:] < brake_threshold)
            )
            if len(finished):
                timeline["brake_end_progress"] = float(grid[peak_i + finished[0]])
        if brake_name == BRAKE_PRESSURE_KPA:
            result["peak_brake_pressure_kpa"] = _safe_stat(brake, "max")
        else:
            result["peak_brake_position_pct"] = _safe_stat(brake, "max")

    steering_ch = session.optional_channel(STEERING_DEG)
    if steering_ch is not None:
        steering = _channel_on_progress(session, lap, STEERING_DEG, grid)
        steering_abs = np.abs(steering)
        active = np.isfinite(steering_abs) & (steering_abs >= 10.0)
        onset = np.flatnonzero(active)
        if len(onset):
            timeline["steering_onset_progress"] = float(grid[onset[0]])
            peak_i = int(np.nanargmax(steering_abs))
            lower = np.flatnonzero(
                np.isfinite(steering_abs[peak_i:])
                & (steering_abs[peak_i:] <= 0.5 * steering_abs[peak_i])
            )
            if len(lower):
                timeline["steering_unwind_progress"] = float(grid[peak_i + lower[0]])
            if brake_channel is not None:
                timeline["brake_steering_overlap_fraction"] = float(np.mean(active & brake_active))

    if control_source is not None and control_channel is not None:
        control = _channel_on_progress(session, lap, control_source, grid)
        valid = control[np.isfinite(control)]
        if len(valid):
            # A modest rise after vmin is distinct from reaching >=90% power control.
            threshold = min(90.0, float(np.nanmin(valid)) + 10.0)
            first = np.flatnonzero(
                (np.arange(len(grid)) >= min_i)
                & np.isfinite(control)
                & (control >= threshold)
            )
            if len(first):
                timeline["first_power_reapply_progress"] = float(grid[first[0]])
    result["driver_input_timeline"] = timeline

    return result


def compare_laps(
    session_a: TelemetrySession,
    lap_a_number: int,
    session_b: TelemetrySession,
    lap_b_number: int,
    *,
    same_layout_confirmed: bool,
    mini_sectors: int = 20,
    profile_points: int = 201,
    include_profile: bool = False,
) -> dict[str, Any]:
    """Compare laps at matched physical points on lap B's GPS trace.

    Normalized *individual* lap distance introduces phase errors when racing
    lines differ. This comparison projects lap A to lap B's reference geometry,
    using time order to disambiguate crossings and start/finish.
    """
    if not same_layout_confirmed:
        raise ValueError(
            "Physical GPS comparison requires same_layout_confirmed=True. "
            "Different layouts require shared-section matching."
        )
    if not (1 <= mini_sectors <= 200):
        raise ValueError("mini_sectors must be between 1 and 200")
    if not (2 <= profile_points <= 5001):
        raise ValueError("profile_points must be between 2 and 5001")

    lap_a = session_a.lap(lap_a_number)
    lap_b = session_b.lap(lap_b_number)
    aligned = align_laps(
        session_a,
        lap_a,
        session_b,
        lap_b,
        grid_points=max(201, mini_sectors * 10 + 1, profile_points if include_profile else 2),
    )
    grid = aligned["distance_m"]
    length = float(grid[-1])
    edges = np.linspace(0.0, length, mini_sectors + 1)
    elapsed_a = np.interp(edges, grid, aligned["elapsed_a_s"])
    elapsed_b = np.interp(edges, grid, aligned["elapsed_b_s"])
    sector_a = np.diff(elapsed_a)
    sector_b = np.diff(elapsed_b)

    sectors = []
    for i in range(mini_sectors):
        sectors.append(
            {
                "sector": i + 1,
                "start_progress": float(edges[i] / length),
                "end_progress": float(edges[i + 1] / length),
                "lap_a_s": float(sector_a[i]),
                "lap_b_s": float(sector_b[i]),
                "a_minus_b_s": float(sector_a[i] - sector_b[i]),
            }
        )

    result: dict[str, Any] = {
        "lap_a": lap_a.to_dict(),
        "lap_b": lap_b.to_dict(),
        "lap_a_minus_b_total_s": float(lap_a.duration_s - lap_b.duration_s),
        "gps_distance_m": aligned["gps_path_length_m"],
        "alignment_quality": aligned["alignment_quality"],
        "mini_sectors": sectors,
    }
    if include_profile:
        target = np.linspace(0.0, length, profile_points)
        t_a = np.interp(target, grid, aligned["elapsed_a_s"])
        t_b = np.interp(target, grid, aligned["elapsed_b_s"])

        def optional_speed(values: np.ndarray) -> np.ndarray:
            good = np.isfinite(values)
            if np.count_nonzero(good) < 2:
                return np.full_like(target, np.nan)
            return np.interp(target, grid[good], values[good], left=np.nan, right=np.nan)

        speed_a = optional_speed(aligned["speed_a_kmh"])
        speed_b = optional_speed(aligned["speed_b_kmh"])
        result["profile"] = [
            {
                "reference_distance_m": float(s),
                "progress": float(s / length),
                "lap_a_elapsed_s": float(a),
                "lap_b_elapsed_s": float(b),
                "delta_t_s": float(a - b),
                "lap_a_speed_kmh": float(va) if np.isfinite(va) else None,
                "lap_b_speed_kmh": float(vb) if np.isfinite(vb) else None,
                "delta_v_kmh": float(va - vb) if np.isfinite(va) and np.isfinite(vb) else None,
            }
            for s, a, b, va, vb in zip(target, t_a, t_b, speed_a, speed_b)
        ]
    return result
