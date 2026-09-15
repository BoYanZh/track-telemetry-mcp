"""Brake telemetry metrics."""

from __future__ import annotations

from typing import Any

import numpy as np

from .channels import BRAKE_POS_PCT, BRAKE_PRESSURE_KPA, LONG_G, SPEED_KMH
from .models import TelemetrySession


def _fill_missing(values: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64).copy()
    good = np.isfinite(out)
    if not np.any(good):
        return out
    index = np.arange(len(out))
    if np.count_nonzero(good) == 1:
        out[~good] = out[good][0]
    else:
        out[~good] = np.interp(index[~good], index[good], out[good])
    return out


def _sustained_decel(t: np.ndarray, g: np.ndarray, window_s: float) -> float | None:
    if len(t) < 2:
        return None
    dt = np.diff(t)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if len(dt) == 0:
        return None
    count = max(1, int(round(window_s / float(np.median(dt)))))
    if count > len(g):
        return None
    values = _fill_missing(g)
    if not np.any(np.isfinite(values)):
        return None
    rolling = np.convolve(values, np.ones(count) / count, mode="valid")
    return float(max(0.0, -np.nanmin(rolling)))


def _active_segments(mask: np.ndarray) -> list[tuple[int, int]]:
    padded = np.concatenate(([False], np.asarray(mask, dtype=bool), [False])).astype(np.int8)
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1) - 1
    return list(zip(starts.tolist(), stops.tolist()))


def analyze_braking(
    session: TelemetrySession,
    lap_number: int | None = None,
    *,
    pressure_threshold_kpa: float = 100.0,
    brake_pos_threshold_pct: float = 3.0,
    min_event_s: float = 0.15,
) -> dict[str, Any]:
    long_ch = session.channel(LONG_G)
    if lap_number is None:
        start_s = float(long_ch.timestamps[0])
        end_s = float(long_ch.timestamps[-1])
        lap_payload = None
    else:
        lap = session.lap(lap_number)
        start_s, end_s = lap.start_s, lap.end_s
        lap_payload = lap.to_dict()

    mask = (long_ch.timestamps >= start_s) & (long_ch.timestamps <= end_s)
    t = long_ch.timestamps[mask]
    long_g = long_ch.values[mask]
    if len(t) < 2:
        raise ValueError("Not enough longitudinal-G data in requested window")

    pressure_ch = session.optional_channel(BRAKE_PRESSURE_KPA)
    position_ch = session.optional_channel(BRAKE_POS_PCT)
    if pressure_ch is not None:
        control = pressure_ch.interp(t)
        active = control >= pressure_threshold_kpa
        control_name = BRAKE_PRESSURE_KPA
    elif position_ch is not None:
        control = position_ch.interp(t)
        active = control >= brake_pos_threshold_pct
        control_name = BRAKE_POS_PCT
    else:
        control = np.zeros_like(t)
        active = np.zeros_like(t, dtype=bool)
        control_name = None

    speed_ch = session.optional_channel(SPEED_KMH)
    speed = speed_ch.interp(t) if speed_ch is not None else np.full_like(t, np.nan)
    events: list[dict[str, Any]] = []

    for start_i, end_i in _active_segments(active):
        duration = float(t[end_i] - t[start_i])
        if duration < min_event_s:
            continue
        et = t[start_i : end_i + 1]
        eg = long_g[start_i : end_i + 1]
        ec = control[start_i : end_i + 1]
        es = speed[start_i : end_i + 1]
        peak_i = int(np.nanargmax(ec)) if np.any(np.isfinite(ec)) else 0
        peak_control = float(ec[peak_i]) if np.isfinite(ec[peak_i]) else None
        peak_time = float(et[peak_i]) if peak_control is not None else None
        ramp = None
        if peak_control is not None and peak_time is not None and peak_time > et[0]:
            first = float(ec[0]) if np.isfinite(ec[0]) else 0.0
            ramp = float((peak_control - first) / (peak_time - et[0]))
        finite_g = eg[np.isfinite(eg)]
        finite_speed = es[np.isfinite(es)]
        events.append(
            {
                "start_s": float(et[0]),
                "end_s": float(et[-1]),
                "duration_s": duration,
                "control_channel": control_name,
                "peak_control": peak_control,
                "peak_control_time_s": peak_time,
                "control_ramp_per_s": ramp,
                "raw_peak_decel_g": float(max(0.0, -np.min(finite_g))) if len(finite_g) else None,
                "sustained_0_5s_decel_g": _sustained_decel(et, eg, 0.5),
                "sustained_1_0s_decel_g": _sustained_decel(et, eg, 1.0),
                "entry_speed_kmh": float(finite_speed[0]) if len(finite_speed) else None,
                "min_speed_kmh": float(np.min(finite_speed)) if len(finite_speed) else None,
            }
        )

    finite_g = long_g[np.isfinite(long_g)]
    result: dict[str, Any] = {
        "lap": lap_payload,
        "raw_peak_decel_g": float(max(0.0, -np.min(finite_g))) if len(finite_g) else None,
        "sustained_0_5s_decel_g": _sustained_decel(t, long_g, 0.5),
        "sustained_1_0s_decel_g": _sustained_decel(t, long_g, 1.0),
        "event_count": len(events),
        "events": events,
        "abs_evidence": "not_inferred",
    }
    if pressure_ch is not None:
        finite_pressure = control[np.isfinite(control)]
        result["peak_brake_pressure_kpa"] = float(np.max(finite_pressure)) if len(finite_pressure) else None
    return result
