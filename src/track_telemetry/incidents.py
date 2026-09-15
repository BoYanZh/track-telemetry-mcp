"""Incident/spin reconstruction from GPS, yaw rate, steering, and pedal telemetry."""

from __future__ import annotations

from typing import Any

import numpy as np

from .channels import (
    ACCELERATOR_PCT,
    BRAKE_POS_PCT,
    BRAKE_PRESSURE_KPA,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    SPEED_KMH,
    STEERING_DEG,
    THROTTLE_PCT,
    YAW_RATE_DPS,
)
from .controls import select_power_control
from .geometry import (
    integrate_body_heading_deg,
    latlon_to_xy_m,
    travel_heading_deg,
    wrap_degrees,
)
from .models import TelemetrySession


def _first_index(mask: np.ndarray, start: int = 0, stop: int | None = None) -> int | None:
    end = len(mask) if stop is None else min(len(mask), stop)
    found = np.flatnonzero(mask[start:end])
    return int(start + found[0]) if len(found) else None


def _event(kind: str, t: np.ndarray, i: int, **values: Any) -> dict[str, Any]:
    return {"type": kind, "time_s": float(t[i]), **values}


def analyze_incident(
    session: TelemetrySession,
    start_s: float,
    end_s: float,
    *,
    anchor_s: float | None = None,
    surface_change_s: float | None = None,
    yaw_sign: float = 1.0,
    initial_yaw_threshold_dps: float = 10.0,
    snap_threshold_dps: float = 15.0,
    low_speed_mph: float = 8.0,
    include_samples: bool = False,
    sample_stride: int = 5,
) -> dict[str, Any]:
    """Reconstruct body heading vs GPS travel direction around an incident.

    Body heading is estimated by integrating yaw rate and anchoring it to GPS travel
    direction before the slide. It is therefore a trend tool, not a direct body-heading
    measurement. ``surface_change_s`` is only a user/video-supplied marker; this function
    does not infer asphalt vs dirt from telemetry alone.

    Power-control semantics are explicit: throttle-body percentage is preferred when
    available in the incident window; accelerator-pedal percentage is used only as a
    labeled fallback.
    """
    if end_s <= start_s:
        raise ValueError("end_s must be greater than start_s")

    lat_ch = session.channel(GPS_LATITUDE_DEG)
    lon_ch = session.channel(GPS_LONGITUDE_DEG)
    mask = (lat_ch.timestamps >= start_s) & (lat_ch.timestamps <= end_s)
    t = lat_ch.timestamps[mask]
    lat = lat_ch.values[mask]
    lon = lon_ch.interp(t)
    valid = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon)
    t, lat, lon = t[valid], lat[valid], lon[valid]
    if len(t) < 5:
        raise ValueError("Incident window has too few valid GPS samples")

    origin_lat = float(np.nanmedian(lat))
    origin_lon = float(np.nanmedian(lon))
    x, y = latlon_to_xy_m(
        lat,
        lon,
        origin_lat_deg=origin_lat,
        origin_lon_deg=origin_lon,
    )
    travel = travel_heading_deg(x, y, half_window=5)
    yaw = session.channel(YAW_RATE_DPS).interp(t)
    speed = session.channel(SPEED_KMH).interp(t)
    steer_ch = session.optional_channel(STEERING_DEG)
    steer = steer_ch.interp(t) if steer_ch is not None else np.full_like(t, np.nan)
    control_source, control_ch = select_power_control(
        session,
        start_s=start_s,
        end_s=end_s,
    )
    control = control_ch.interp(t) if control_ch is not None else np.full_like(t, np.nan)
    pressure_ch = session.optional_channel(BRAKE_PRESSURE_KPA)
    brake_pos_ch = session.optional_channel(BRAKE_POS_PCT)
    brake_pressure = pressure_ch.interp(t) if pressure_ch is not None else np.full_like(t, np.nan)
    brake_pos = brake_pos_ch.interp(t) if brake_pos_ch is not None else np.full_like(t, np.nan)

    anchor_time = start_s if anchor_s is None else float(anchor_s)
    anchor_i = int(np.nanargmin(np.abs(t - anchor_time)))
    if not np.isfinite(travel[anchor_i]):
        finite_heading = np.flatnonzero(np.isfinite(travel))
        if not len(finite_heading):
            raise ValueError("Could not derive GPS travel heading")
        anchor_i = int(finite_heading[0])
    body = integrate_body_heading_deg(
        t,
        np.nan_to_num(yaw, nan=0.0),
        float(travel[anchor_i]),
        anchor_index=anchor_i,
        yaw_sign=yaw_sign,
    )
    beta = np.asarray(wrap_degrees(travel - body), dtype=np.float64)

    low_speed_kmh = low_speed_mph * 1.609344
    moving = np.isfinite(speed) & (speed >= low_speed_kmh)
    yaw_active = moving & np.isfinite(yaw) & (np.abs(yaw) >= initial_yaw_threshold_dps)
    onset_i = _first_index(yaw_active)
    timeline: list[dict[str, Any]] = []

    if onset_i is not None:
        initial_sign = 1.0 if yaw[onset_i] >= 0 else -1.0
        timeline.append(
            _event(
                "yaw_excursion_onset",
                t,
                onset_i,
                yaw_rate_dps=float(yaw[onset_i]),
                speed_kmh=float(speed[onset_i]),
            )
        )

        opposite_steer = (
            np.isfinite(steer)
            & (np.abs(steer) >= 5.0)
            & (np.sign(steer) == -initial_sign)
        )
        counter_i = _first_index(opposite_steer, onset_i)
        if counter_i is not None:
            timeline.append(
                _event(
                    "opposite_steering_sign_onset",
                    t,
                    counter_i,
                    steering_deg=float(steer[counter_i]),
                    yaw_rate_dps=float(yaw[counter_i]),
                )
            )

        snap_mask = (
            moving
            & np.isfinite(yaw)
            & (np.sign(yaw) == -initial_sign)
            & (np.abs(yaw) >= snap_threshold_dps)
        )
        snap_i = _first_index(snap_mask, onset_i + 1)
        if snap_i is not None:
            search_yaw = np.abs(yaw[onset_i : snap_i + 1])
            if np.any(np.isfinite(search_yaw)):
                arrest_i = onset_i + int(np.nanargmin(search_yaw))
                if abs(yaw[arrest_i]) <= 5.0:
                    timeline.append(
                        _event(
                            "initial_yaw_arrested",
                            t,
                            arrest_i,
                            yaw_rate_dps=float(yaw[arrest_i]),
                            sideslip_proxy_deg=float(beta[arrest_i]),
                        )
                    )
            timeline.append(
                _event(
                    "snap_back",
                    t,
                    snap_i,
                    yaw_rate_dps=float(yaw[snap_i]),
                    speed_kmh=float(speed[snap_i]),
                    sideslip_proxy_deg=float(beta[snap_i]),
                )
            )

        if control_ch is not None:
            lookback = max(0, onset_i - 25)
            if np.nanmax(control[lookback : onset_i + 1]) >= 90.0:
                reduction_i = _first_index(np.isfinite(control) & (control <= 80.0), onset_i)
                if reduction_i is not None:
                    event_type = (
                        "throttle_reduction"
                        if control_source == THROTTLE_PCT
                        else "accelerator_reduction"
                    )
                    timeline.append(
                        _event(
                            event_type,
                            t,
                            reduction_i,
                            control_source=control_source,
                            control_pct=float(control[reduction_i]),
                        )
                    )

        brake_active = np.zeros(len(t), dtype=bool)
        if pressure_ch is not None:
            brake_active |= np.isfinite(brake_pressure) & (brake_pressure >= 100.0)
        if brake_pos_ch is not None:
            brake_active |= np.isfinite(brake_pos) & (brake_pos >= 3.0)
        brake_i = _first_index(brake_active, onset_i)
        if brake_i is not None:
            timeline.append(
                _event(
                    "brake_onset",
                    t,
                    brake_i,
                    brake_pressure_kpa=(
                        float(brake_pressure[brake_i]) if np.isfinite(brake_pressure[brake_i]) else None
                    ),
                    brake_pos_pct=(
                        float(brake_pos[brake_i]) if np.isfinite(brake_pos[brake_i]) else None
                    ),
                )
            )

    if surface_change_s is not None and start_s <= surface_change_s <= end_s:
        surface_i = int(np.argmin(np.abs(t - surface_change_s)))
        timeline.append(_event("surface_change_user_marked", t, surface_i))

    backwards = moving & np.isfinite(beta) & (np.abs(beta) >= 150.0)
    backwards_i = _first_index(backwards)
    if backwards_i is not None:
        timeline.append(
            _event(
                "near_backwards_slide",
                t,
                backwards_i,
                speed_kmh=float(speed[backwards_i]),
                sideslip_proxy_deg=float(beta[backwards_i]),
            )
        )

    timeline.sort(key=lambda item: item["time_s"])
    moving_indices = np.flatnonzero(moving & np.isfinite(beta))
    peak_yaw_i = int(np.nanargmax(np.abs(yaw))) if np.any(np.isfinite(yaw)) else None
    max_beta_i = (
        int(moving_indices[np.nanargmax(np.abs(beta[moving_indices]))])
        if len(moving_indices)
        else None
    )

    result: dict[str, Any] = {
        "window": {"start_s": start_s, "end_s": end_s, "anchor_s": float(t[anchor_i])},
        "projection_origin": {
            "latitude_deg": origin_lat,
            "longitude_deg": origin_lon,
        },
        "control_source": control_source,
        "summary": {
            "peak_abs_yaw_rate_dps": (
                float(abs(yaw[peak_yaw_i])) if peak_yaw_i is not None else None
            ),
            "peak_abs_yaw_time_s": float(t[peak_yaw_i]) if peak_yaw_i is not None else None,
            "max_abs_sideslip_proxy_deg": (
                float(abs(beta[max_beta_i])) if max_beta_i is not None else None
            ),
            "max_abs_sideslip_time_s": float(t[max_beta_i]) if max_beta_i is not None else None,
        },
        "timeline": timeline,
        "caveats": [
            "GPS heading is travel/course direction, not body orientation.",
            "Body heading is estimated by integrating yaw rate from a pre-slide anchor.",
            "Sideslip proxy becomes unreliable at low speed.",
            "Surface type is never inferred from telemetry; pass surface_change_s only when supported by video/observation.",
            "Steering-sign interpretation depends on the source convention.",
            "Power-control source is explicit; accelerator pedal percentage is never relabeled as throttle-body percentage.",
        ],
    }

    if include_samples:
        stride = max(1, int(sample_stride))
        rows = []
        for i in range(0, len(t), stride):
            row = {
                "time_s": float(t[i]),
                "x_m": float(x[i]),
                "y_m": float(y[i]),
                "speed_kmh": float(speed[i]) if np.isfinite(speed[i]) else None,
                "yaw_rate_dps": float(yaw[i]) if np.isfinite(yaw[i]) else None,
                "steering_deg": float(steer[i]) if np.isfinite(steer[i]) else None,
                "control_pct": float(control[i]) if np.isfinite(control[i]) else None,
                "body_heading_estimate_deg": float(body[i]),
                "travel_heading_deg": float(travel[i]) if np.isfinite(travel[i]) else None,
                "sideslip_proxy_deg": float(beta[i]) if np.isfinite(beta[i]) else None,
            }
            if control_source == THROTTLE_PCT:
                row["throttle_pct"] = row["control_pct"]
            elif control_source == ACCELERATOR_PCT:
                row["accelerator_pct"] = row["control_pct"]
            rows.append(row)
        result["samples"] = rows
    return result
