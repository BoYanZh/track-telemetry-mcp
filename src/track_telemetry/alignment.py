"""Align two laps by physical GPS position on a reference lap (not percent traveled)."""

from __future__ import annotations

from typing import Any

import numpy as np

from .channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG, SPEED_KMH
from .geometry import cumulative_distance_m, latlon_to_xy_m
from .models import Lap, TelemetrySession


def _gps_trace(session: TelemetrySession, lap: Lap) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lat_ch = session.channel(GPS_LATITUDE_DEG)
    lon_ch = session.channel(GPS_LONGITUDE_DEG)
    mask = (lat_ch.timestamps >= lap.start_s) & (lat_ch.timestamps <= lap.end_s)
    t = lat_ch.timestamps[mask]
    lat = lat_ch.values[mask]
    lon = lon_ch.interp(t)
    valid = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon)
    t, lat, lon = t[valid], lat[valid], lon[valid]
    if len(t) < 3 or np.any(np.diff(t) <= 0):
        raise ValueError("Lap has too few unique, valid GPS samples for alignment")
    speed_ch = session.optional_channel(SPEED_KMH)
    speed = speed_ch.interp(t) if speed_ch is not None else np.full_like(t, np.nan)
    return t, lat, lon, speed


def _project_to_reference(
    t: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    lap: Lap,
    ref_t: np.ndarray,
    ref_x: np.ndarray,
    ref_y: np.ndarray,
    ref_lap: Lap,
    ref_s: np.ndarray,
    *,
    max_lateral_deviation_m: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Project each point to a nearby *time-ordered* reference segment.

    A broad fractional-time gate resolves start/finish and track crossings, but
    physical GPS position determines the actual alignment. Fail closed when a
    lap diverges materially instead of returning a plausible-looking false delta.
    """
    dx, dy = np.diff(ref_x), np.diff(ref_y)
    segment_len_sq = dx * dx + dy * dy
    ref_fraction = (ref_t[:-1] - ref_lap.start_s) / ref_lap.duration_s
    projected = np.empty(len(t))
    deviation = np.empty(len(t))
    for i, (px, py) in enumerate(zip(x, y)):
        expected = (t[i] - lap.start_s) / lap.duration_s
        eligible = (np.abs(ref_fraction - expected) <= 0.25) & (segment_len_sq > 1e-6)
        indices = np.flatnonzero(eligible)
        if not len(indices):
            raise ValueError("No reference GPS segments close to expected lap progress")
        fraction = np.clip(
            ((px - ref_x[indices]) * dx[indices] + (py - ref_y[indices]) * dy[indices])
            / segment_len_sq[indices],
            0.0,
            1.0,
        )
        offset_x = px - (ref_x[indices] + fraction * dx[indices])
        offset_y = py - (ref_y[indices] + fraction * dy[indices])
        nearest = int(np.argmin(offset_x * offset_x + offset_y * offset_y))
        j = indices[nearest]
        projected[i] = ref_s[j] + fraction[nearest] * (ref_s[j + 1] - ref_s[j])
        deviation[i] = float(np.hypot(offset_x[nearest], offset_y[nearest]))

    p95 = float(np.percentile(deviation, 95))
    if p95 > max_lateral_deviation_m:
        raise ValueError(
            f"GPS trajectories do not align: p95 deviation {p95:.1f}m "
            f"> {max_lateral_deviation_m:.1f}m"
        )
    regressions = np.diff(projected)
    if np.any(regressions < -max(10.0, max_lateral_deviation_m)):
        raise ValueError("GPS alignment jumps backwards; possible wrong layout or track crossing")
    projected = np.maximum.accumulate(projected)
    ref_length = float(ref_s[-1])
    endpoint_tolerance = max(25.0, 0.015 * ref_length)
    if projected[0] > endpoint_tolerance or ref_length - projected[-1] > endpoint_tolerance:
        raise ValueError("GPS trace does not cover both lap timing boundaries")

    return projected, {
        "method": "time-gated-nearest-reference-segment",
        "p95_lateral_deviation_m": p95,
        "max_lateral_deviation_m": float(np.max(deviation)),
        "minor_backward_adjustments": int(np.count_nonzero(regressions < -0.1)),
        "reference_distance_m": ref_length,
    }


def align_laps(
    session_a: TelemetrySession,
    lap_a: Lap,
    session_b: TelemetrySession,
    lap_b: Lap,
    *,
    grid_points: int,
    max_lateral_deviation_m: float = 25.0,
) -> dict[str, Any]:
    """Produce elapsed time and velocity at *the same physical reference locations*.

    Session B is the reference centerline. The start/end timing anchors use the
    official lap boundaries, not the first/last GPS sample timestamps.
    """
    if not (lap_a.is_timed and lap_b.is_timed):
        raise ValueError("Both laps must be timed laps")
    if not (np.isfinite(lap_a.duration_s) and np.isfinite(lap_b.duration_s)):
        raise ValueError("Lap times must be finite")
    if lap_a.duration_s <= 0 or lap_b.duration_s <= 0:
        raise ValueError("Lap times must be positive")
    if not (2 <= grid_points <= 5001):
        raise ValueError("grid_points must be between 2 and 5001")

    t_b, lat_b, lon_b, v_b = _gps_trace(session_b, lap_b)
    t_a, lat_a, lon_a, v_a = _gps_trace(session_a, lap_a)
    origin_lat, origin_lon = float(np.median(lat_b)), float(np.median(lon_b))
    bx, by = latlon_to_xy_m(lat_b, lon_b, origin_lat_deg=origin_lat, origin_lon_deg=origin_lon)
    ax, ay = latlon_to_xy_m(lat_a, lon_a, origin_lat_deg=origin_lat, origin_lon_deg=origin_lon)
    s_b = cumulative_distance_m(bx, by)
    if s_b[-1] <= 0:
        raise ValueError("Reference lap has zero GPS path length")
    s_a, quality = _project_to_reference(
        t_a, ax, ay, lap_a, t_b, bx, by, lap_b, s_b,
        max_lateral_deviation_m=max_lateral_deviation_m,
    )
    length = float(s_b[-1])

    def profile(
        s: np.ndarray, t: np.ndarray, speed: np.ndarray, lap: Lap,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # Discard duplicate positions introduced by GPS noise or clipping.
        valid = np.concatenate(([True], np.diff(s) > 0.05))
        positions, times, speeds = s[valid], t[valid], speed[valid]
        inner = (positions > 1e-6) & (positions < length - 1e-6)
        positions = np.concatenate(([0.0], positions[inner], [length]))
        elapsed = np.concatenate(([0.0], times[inner] - lap.start_s, [lap.duration_s]))
        speeds = np.concatenate(([speeds[0]], speeds[inner], [speeds[-1]]))
        grid = np.linspace(0.0, length, grid_points)
        timeline = np.interp(grid, positions, elapsed)
        finite_speed = np.isfinite(speeds)
        velocity = (
            np.interp(grid, positions[finite_speed], speeds[finite_speed], left=np.nan, right=np.nan)
            if np.count_nonzero(finite_speed) >= 2
            else np.full_like(grid, np.nan)
        )
        return grid, timeline, velocity

    grid, time_a, speed_a = profile(s_a, t_a, v_a, lap_a)
    _, time_b, speed_b = profile(s_b, t_b, v_b, lap_b)
    return {
        "distance_m": grid,
        "elapsed_a_s": time_a,
        "elapsed_b_s": time_b,
        "speed_a_kmh": speed_a,
        "speed_b_kmh": speed_b,
        "alignment_quality": quality,
        "gps_path_length_m": {
            "lap_a": float(cumulative_distance_m(ax, ay)[-1]),
            "lap_b": length,
        },
    }
