"""GPS geometry and heading reconstruction helpers."""

from __future__ import annotations

import numpy as np

_EARTH_RADIUS_M = 6_371_000.0


def wrap_degrees(angle: np.ndarray | float) -> np.ndarray | float:
    """Wrap degrees to [-180, 180)."""
    return (np.asarray(angle) + 180.0) % 360.0 - 180.0


def latlon_to_xy_m(
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
    *,
    origin_lat_deg: float | None = None,
    origin_lon_deg: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Project a local GPS trace to east/north meters with an equirectangular projection."""
    lat = np.asarray(latitude_deg, dtype=np.float64)
    lon = np.asarray(longitude_deg, dtype=np.float64)
    if len(lat) != len(lon):
        raise ValueError("Latitude and longitude lengths differ")
    if len(lat) == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    lat0 = float(np.nanmedian(lat) if origin_lat_deg is None else origin_lat_deg)
    lon0 = float(np.nanmedian(lon) if origin_lon_deg is None else origin_lon_deg)
    lat0_rad = np.deg2rad(lat0)
    x = np.deg2rad(lon - lon0) * _EARTH_RADIUS_M * np.cos(lat0_rad)
    y = np.deg2rad(lat - lat0) * _EARTH_RADIUS_M
    return x, y


def cumulative_distance_m(x_m: np.ndarray, y_m: np.ndarray) -> np.ndarray:
    x = np.asarray(x_m, dtype=np.float64)
    y = np.asarray(y_m, dtype=np.float64)
    if len(x) != len(y):
        raise ValueError("x/y lengths differ")
    if len(x) == 0:
        return np.array([], dtype=np.float64)
    step = np.hypot(np.diff(x), np.diff(y))
    return np.concatenate(([0.0], np.cumsum(step)))


def normalized_progress(x_m: np.ndarray, y_m: np.ndarray) -> np.ndarray:
    distance = cumulative_distance_m(x_m, y_m)
    if len(distance) == 0 or distance[-1] <= 0:
        return np.zeros_like(distance)
    return distance / distance[-1]


def travel_heading_deg(x_m: np.ndarray, y_m: np.ndarray, half_window: int = 3) -> np.ndarray:
    """Estimate GPS course heading in degrees clockwise from north."""
    x = np.asarray(x_m, dtype=np.float64)
    y = np.asarray(y_m, dtype=np.float64)
    if len(x) != len(y):
        raise ValueError("x/y lengths differ")
    n = len(x)
    if n == 0:
        return np.array([], dtype=np.float64)
    half_window = max(1, int(half_window))
    heading = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        lo = max(0, i - half_window)
        hi = min(n - 1, i + half_window)
        dx = x[hi] - x[lo]
        dy = y[hi] - y[lo]
        if dx == 0 and dy == 0:
            continue
        heading[i] = np.degrees(np.arctan2(dx, dy)) % 360.0
    return heading


def integrate_body_heading_deg(
    timestamps_s: np.ndarray,
    yaw_rate_dps: np.ndarray,
    anchor_heading_deg: float,
    *,
    anchor_index: int = 0,
    yaw_sign: float = 1.0,
) -> np.ndarray:
    """Integrate yaw rate around a known heading anchor.

    The result is an estimate, not a direct body-heading sensor measurement. ``yaw_sign``
    exists because source conventions differ; +1 assumes positive yaw increases GPS-style
    clockwise heading.
    """
    t = np.asarray(timestamps_s, dtype=np.float64)
    yaw = np.asarray(yaw_rate_dps, dtype=np.float64)
    if len(t) != len(yaw):
        raise ValueError("timestamp/yaw lengths differ")
    if len(t) == 0:
        return np.array([], dtype=np.float64)
    anchor_index = int(np.clip(anchor_index, 0, len(t) - 1))
    body = np.full(len(t), np.nan, dtype=np.float64)
    body[anchor_index] = float(anchor_heading_deg)

    for i in range(anchor_index + 1, len(t)):
        dt = t[i] - t[i - 1]
        rate = 0.5 * (yaw[i - 1] + yaw[i]) * yaw_sign
        body[i] = body[i - 1] + rate * dt
    for i in range(anchor_index - 1, -1, -1):
        dt = t[i + 1] - t[i]
        rate = 0.5 * (yaw[i] + yaw[i + 1]) * yaw_sign
        body[i] = body[i + 1] - rate * dt
    return body % 360.0
