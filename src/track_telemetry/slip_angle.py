"""Estimate vehicle sideslip from independent yaw-rate and GPS course.

This module calculates a **vehicle sideslip proxy**, not tire slip angle and not a
sensor-direct body-heading measurement. RaceChrono's GPS heading/bearing describes the
direction of travel. Vehicle body heading is estimated by integrating an independent
yaw-rate channel from an anchor where sideslip is assumed to be approximately zero.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .channels import (
    GPS_HEADING_DEG,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    SPEED_KMH,
    YAW_RATE_DPS,
)
from .geometry import (
    integrate_body_heading_deg,
    latlon_to_xy_m,
    travel_heading_deg,
    wrap_degrees,
)
from .models import TelemetrySession


def _travel_heading(
    session: TelemetrySession,
    timestamps_s: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
    *,
    half_window: int,
) -> tuple[np.ndarray, str]:
    """Return GPS course heading, preferring the receiver's bearing channel."""
    heading_ch = session.optional_channel(GPS_HEADING_DEG)
    if heading_ch is not None:
        heading = heading_ch.interp(timestamps_s)
        if np.count_nonzero(np.isfinite(heading)) >= max(3, len(heading) // 2):
            return np.mod(heading, 360.0), "gps_bearing_channel"
    return travel_heading_deg(x_m, y_m, half_window=half_window), "latlon_course"


def analyze_slip_angle(
    session: TelemetrySession,
    start_s: float,
    end_s: float,
    *,
    anchor_s: float | None = None,
    yaw_sign: float = 1.0,
    low_speed_mph: float = 8.0,
    heading_half_window: int = 5,
    include_samples: bool = False,
    sample_stride: int = 5,
    allow_gps_derived_yaw: bool = False,
) -> dict[str, Any]:
    """Estimate vehicle sideslip angle over a bounded time window.

    Definition::

        beta_proxy = wrap(gps_course_heading - estimated_body_heading)
        estimated_body_heading = anchor_heading + integral(yaw_rate * dt)

    ``anchor_s`` should be a point where vehicle sideslip is reasonably assumed to be
    near zero, such as a stable straight or settled pre-corner segment. Integration
    drift means this method is most useful over bounded corner/incident windows rather
    than an entire session.

    A yaw-rate channel derived from GPS heading is not independent of GPS course and is
    therefore rejected by default. Set ``allow_gps_derived_yaw`` only for debugging; a
    resulting slip estimate is not physically informative.
    """
    if end_s <= start_s:
        raise ValueError("end_s must be greater than start_s")
    if heading_half_window < 1:
        raise ValueError("heading_half_window must be positive")

    yaw_source = str(session.metadata.get("yaw_rate_source", "unknown"))
    if yaw_source == "gps_heading_derivative" and not allow_gps_derived_yaw:
        raise ValueError(
            "Slip-angle proxy requires yaw rate independent of GPS course. "
            "This session's yaw_rate_source is gps_heading_derivative."
        )

    lat_ch = session.channel(GPS_LATITUDE_DEG)
    lon_ch = session.channel(GPS_LONGITUDE_DEG)
    yaw_ch = session.channel(YAW_RATE_DPS)
    speed_ch = session.channel(SPEED_KMH)

    mask = (lat_ch.timestamps >= start_s) & (lat_ch.timestamps <= end_s)
    t = lat_ch.timestamps[mask]
    lat = lat_ch.values[mask]
    lon = lon_ch.interp(t)
    valid = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon)
    t, lat, lon = t[valid], lat[valid], lon[valid]
    if len(t) < 5:
        raise ValueError("Slip-angle window has too few valid GPS samples")

    origin_lat = float(np.nanmedian(lat))
    origin_lon = float(np.nanmedian(lon))
    x, y = latlon_to_xy_m(
        lat,
        lon,
        origin_lat_deg=origin_lat,
        origin_lon_deg=origin_lon,
    )
    travel, travel_source = _travel_heading(
        session,
        t,
        x,
        y,
        half_window=heading_half_window,
    )
    yaw = yaw_ch.interp(t)
    speed = speed_ch.interp(t)

    anchor_time = float(start_s if anchor_s is None else anchor_s)
    anchor_i = int(np.argmin(np.abs(t - anchor_time)))
    if not np.isfinite(travel[anchor_i]):
        finite_heading = np.flatnonzero(np.isfinite(travel))
        if not len(finite_heading):
            raise ValueError("Could not derive GPS course heading")
        anchor_i = int(finite_heading[np.argmin(np.abs(finite_heading - anchor_i))])

    body = integrate_body_heading_deg(
        t,
        np.nan_to_num(yaw, nan=0.0),
        float(travel[anchor_i]),
        anchor_index=anchor_i,
        yaw_sign=yaw_sign,
    )
    beta = np.asarray(wrap_degrees(travel - body), dtype=np.float64)

    low_speed_kmh = float(low_speed_mph) * 1.609344
    valid_beta = (
        np.isfinite(beta)
        & np.isfinite(speed)
        & (speed >= low_speed_kmh)
        & np.isfinite(yaw)
        & np.isfinite(travel)
    )
    masked_beta = np.where(valid_beta, beta, np.nan)

    finite = np.flatnonzero(np.isfinite(masked_beta))
    peak_i = (
        int(finite[np.nanargmax(np.abs(masked_beta[finite]))])
        if len(finite)
        else None
    )
    rms = (
        float(np.sqrt(np.nanmean(masked_beta[finite] ** 2)))
        if len(finite)
        else None
    )

    result: dict[str, Any] = {
        "window": {
            "start_s": float(start_s),
            "end_s": float(end_s),
            "anchor_s": float(t[anchor_i]),
            "anchor_assumption": "vehicle sideslip approximately 0 deg",
        },
        "sources": {
            "travel_heading": travel_source,
            "yaw_rate": yaw_source,
            "body_heading": "integrated_yaw_rate",
        },
        "definition": "beta_proxy_deg = wrap(gps_course_deg - body_heading_estimate_deg)",
        "summary": {
            "max_abs_slip_angle_proxy_deg": (
                float(abs(masked_beta[peak_i])) if peak_i is not None else None
            ),
            "max_abs_slip_angle_time_s": float(t[peak_i]) if peak_i is not None else None,
            "rms_slip_angle_proxy_deg": rms,
        },
        "caveats": [
            "This is vehicle sideslip (beta) proxy, not tire slip angle.",
            "RaceChrono GPS heading/bearing is travel/course direction, not vehicle body orientation.",
            "Body heading is estimated by integrating an independent yaw-rate channel from a zero-slip anchor.",
            "Yaw-rate bias causes integration drift; prefer bounded corner/incident windows over whole-session analysis.",
            "The proxy is masked below the configured low-speed threshold because course heading becomes unreliable.",
            "A dual-antenna GNSS or other direct body-heading source would allow a more direct sideslip measurement.",
        ],
    }

    if include_samples:
        stride = max(1, int(sample_stride))
        rows: list[dict[str, float | None]] = []
        for i in range(0, len(t), stride):
            rows.append(
                {
                    "time_s": float(t[i]),
                    "x_m": float(x[i]),
                    "y_m": float(y[i]),
                    "speed_kmh": float(speed[i]) if np.isfinite(speed[i]) else None,
                    "yaw_rate_dps": float(yaw[i]) if np.isfinite(yaw[i]) else None,
                    "travel_heading_deg": (
                        float(travel[i]) if np.isfinite(travel[i]) else None
                    ),
                    "body_heading_estimate_deg": float(body[i]),
                    "slip_angle_proxy_deg": (
                        float(masked_beta[i]) if np.isfinite(masked_beta[i]) else None
                    ),
                }
            )
        result["samples"] = rows

    return result
