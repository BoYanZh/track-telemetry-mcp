"""Deterministic, source-labeled static telemetry figures for MCP agents.

Matplotlib is an optional dependency. Figures are saved as PNGs and embedded
into one portable HTML report; no smoothing or synthetic input channels.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .alignment import align_laps
from .channels import (
    ACCELERATOR_PCT,
    BRAKE_POS_PCT,
    BRAKE_PRESSURE_KPA,
    COOLANT_TEMP_C,
    ENGINE_OIL_PRESSURE_KPA,
    ENGINE_OIL_TEMP_C,
    ENGINE_RPM,
    GEAR,
    GEARBOX_TEMP_C,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    LAT_G,
    LONG_G,
    SPEED_KMH,
    STEERING_DEG,
    THROTTLE_PCT,
)
from .geometry import latlon_to_xy_m
from .models import Lap, TelemetrySession

COMPARISON_PLOTS = ("gps_trace", "speed_distance", "delta_time")
SESSION_PLOTS = ("gg_diagram", "g_traces", "driver_inputs", "vehicle_health")

_CONTROL_CHANNELS = (
    (SPEED_KMH, "Speed", "km/h"),
    (BRAKE_PRESSURE_KPA, "Brake pressure", "kPa"),
    (BRAKE_POS_PCT, "Brake position", "%"),
    (ACCELERATOR_PCT, "Accelerator pedal", "%"),
    (THROTTLE_PCT, "Throttle body", "%"),
    (STEERING_DEG, "Steering", "deg"),
    (ENGINE_RPM, "Engine RPM", "rpm"),
    (GEAR, "Gear", ""),
)
_HEALTH_CHANNELS = (
    (ENGINE_OIL_PRESSURE_KPA, "Oil pressure", "kPa"),
    (ENGINE_OIL_TEMP_C, "Oil temperature", "°C"),
    (COOLANT_TEMP_C, "Coolant temperature", "°C"),
    (GEARBOX_TEMP_C, "Gearbox / ATF temperature", "°C"),
)


def _figure(*, height: float = 4.8):
    try:
        from matplotlib.figure import Figure
    except ImportError as exc:
        raise RuntimeError(
            "Telemetry figures require matplotlib. Install with: pip install -e '.[viz]'"
        ) from exc
    return Figure(figsize=(10, height), layout="constrained")


def _lap_samples(
    session: TelemetrySession, lap: Lap, channel_name: str
) -> tuple[np.ndarray, np.ndarray]:
    channel = session.optional_channel(channel_name)
    if channel is None:
        return np.array([], dtype=float), np.array([], dtype=float)
    mask = (
        (channel.timestamps >= lap.start_s)
        & (channel.timestamps <= lap.end_s)
        & np.isfinite(channel.timestamps)
        & np.isfinite(channel.values)
    )
    return channel.timestamps[mask] - lap.start_s, channel.values[mask]


def _sample_rate(t: np.ndarray) -> float | None:
    if len(t) < 2:
        return None
    positive = np.diff(t)
    positive = positive[positive > 0]
    return float(1 / np.median(positive)) if len(positive) else None


def _channel_info(session: TelemetrySession, lap: Lap, names: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    result = {}
    for name in names:
        t, _ = _lap_samples(session, lap, name)
        result[name] = {
            "samples": int(len(t)),
            "rate_hz": _sample_rate(t),
            "lap_coverage_fraction": (
                float((t[-1] - t[0]) / lap.duration_s) if len(t) >= 2 else 0.0
            ),
        }
    return result


def _valid_series(
    session: TelemetrySession,
    lap: Lap,
    name: str,
    *,
    min_points: int = 5,
    min_coverage: float = 0.5,
) -> tuple[np.ndarray, np.ndarray] | None:
    t, v = _lap_samples(session, lap, name)
    if len(t) < min_points or t[-1] - t[0] < lap.duration_s * min_coverage:
        return None
    if np.any(np.diff(t) <= 0):
        # Timestamp deduplication is safe for plotting but never invents samples.
        indices = np.concatenate(([True], np.diff(t) > 0))
        t, v = t[indices], v[indices]
    return (t, v) if len(t) >= min_points else None


def _plot_raw(ax, t: np.ndarray, v: np.ndarray, *, label: str) -> None:
    """Plot raw points without connecting stretches of missing samples."""
    if len(t) < 2:
        return
    good = np.diff(t)
    positive = good[good > 0]
    if not len(positive):
        return
    gap = max(0.5, float(np.median(positive)) * 4)
    breaks = np.flatnonzero(good > gap)
    left = 0
    for right in (*breaks, len(t) - 1):
        ax.plot(t[left : right + 1], v[left : right + 1], label=label if left == 0 else None)
        left = right + 1
    rate = _sample_rate(t)
    if rate is not None and rate < 3:
        ax.scatter(t, v, s=10, alpha=0.65)


def _save_report(
    output_html: Path,
    title: str,
    figures: list[tuple[str, Any]],
    *,
    skipped: dict[str, str],
    notes: list[str],
    channel_quality: dict[str, Any],
) -> dict[str, Any]:
    if not figures:
        raise ValueError("No requested plots can be produced from available measured channels")
    output_html.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    paths: dict[str, str] = {}
    for plot_name, fig in figures:
        png = output_html.with_name(f"{output_html.stem}_{plot_name}.png")
        fig.savefig(png, dpi=125)
        paths[plot_name] = str(png)
        encoded = base64.b64encode(png.read_bytes()).decode("ascii")
        sections.append(
            f'<section><h2>{html.escape(plot_name.replace("_", " ").title())}</h2>'
            f'<img alt="{html.escape(plot_name)}" src="data:image/png;base64,{encoded}"></section>'
        )
    note_html = "".join(f"<li>{html.escape(note)}</li>" for note in notes)
    skipped_html = "".join(
        f"<li>{html.escape(name)}: {html.escape(reason)}</li>"
        for name, reason in skipped.items()
    )
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{font:15px system-ui,sans-serif;max-width:1100px;margin:30px auto;"
        "padding:0 20px;color:#222}section{margin:25px 0 35px}img{width:100%;height:auto}"
        "li{line-height:1.65}h1{font-size:25px}h2{font-size:19px}</style>"
        f"<h1>{html.escape(title)}</h1>"
        + "".join(sections)
        + "<h2>Data quality and interpretation</h2><ul>" + note_html + "</ul>"
        + ("<h2>Unavailable plots</h2><ul>" + skipped_html + "</ul>" if skipped else "")
        + "</html>"
    )
    output_html.write_text(document, encoding="utf-8")
    return {
        "output_html": str(output_html),
        "plot_files": paths,
        "generated_plots": list(paths),
        "skipped_plots": skipped,
        "notes": notes,
        "channel_quality": channel_quality,
    }


def _select_plots(requested: list[str] | None, supported: tuple[str, ...]) -> list[str]:
    chosen = list(supported) if requested is None else requested
    if not chosen:
        raise ValueError("Select at least one plot")
    unknown = set(chosen) - set(supported)
    if unknown:
        raise ValueError(f"Unknown plot(s): {', '.join(sorted(unknown))}")
    return list(dict.fromkeys(chosen))


def _gps_xy(session: TelemetrySession, lap: Lap, lat0: float, lon0: float):
    t, latitude = _lap_samples(session, lap, GPS_LATITUDE_DEG)
    lon_channel = session.channel(GPS_LONGITUDE_DEG)
    longitude = lon_channel.interp(t + lap.start_s)
    valid = np.isfinite(latitude) & np.isfinite(longitude)
    if np.count_nonzero(valid) < 3:
        raise ValueError("Insufficient valid GPS positions to draw track trajectory")
    x, y = latlon_to_xy_m(
        latitude[valid], longitude[valid], origin_lat_deg=lat0, origin_lon_deg=lon0
    )
    return t[valid], x, y


def render_lap_comparison(
    session_a: TelemetrySession,
    lap_a_number: int,
    session_b: TelemetrySession,
    lap_b_number: int,
    output_html: Path,
    *,
    same_layout_confirmed: bool,
    plots: list[str] | None = None,
) -> dict[str, Any]:
    """Render GPS geometry + distance-aligned speed and delta-T (P1)."""
    chosen = _select_plots(plots, COMPARISON_PLOTS)
    if not same_layout_confirmed:
        raise ValueError("Lap comparison requires same_layout_confirmed=True")
    lap_a = session_a.lap(lap_a_number)
    lap_b = session_b.lap(lap_b_number)
    aligned = align_laps(session_a, lap_a, session_b, lap_b, grid_points=601)
    distance = aligned["distance_m"]
    quality = aligned["alignment_quality"]

    required_names = (GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG, SPEED_KMH)
    quality_by_lap = {
        "lap_a": _channel_info(session_a, lap_a, required_names),
        "lap_b": _channel_info(session_b, lap_b, required_names),
    }
    all_figures: list[tuple[str, Any]] = []
    note = [
        "GPS lines show sampled trajectories, not track boundaries or verified official corner positions.",
        "Speed and Delta T use physical GPS-position alignment; interpolation adds no measured samples.",
        f"GPS alignment p95 lateral deviation: {quality['p95_lateral_deviation_m']:.1f} m.",
        "Delta T = lap A elapsed minus lap B elapsed; positive means lap A is behind.",
    ]
    gps_rates = [
        info["rate_hz"]
        for data in quality_by_lap.values()
        for channel_name, info in data.items()
        if channel_name == GPS_LATITUDE_DEG and info["rate_hz"] is not None
    ]
    if gps_rates and min(gps_rates) < 5:
        note.append(
            f"Low GPS sample rate ({min(gps_rates):.1f} Hz); do not interpret corner/brake timing from interpolated curves."
        )

    label_a = f"A: {session_a.session_id} L{lap_a.number}"
    label_b = f"B: {session_b.session_id} L{lap_b.number}"
    if "gps_trace" in chosen:
        origin_ch = session_b.channel(GPS_LATITUDE_DEG)
        valid = np.isfinite(origin_ch.values)
        if not np.any(valid):
            raise ValueError("No valid reference latitude")
        lat0 = float(np.median(origin_ch.values[valid]))
        lon_ch = session_b.channel(GPS_LONGITUDE_DEG)
        lon0 = float(np.median(lon_ch.values[np.isfinite(lon_ch.values)]))
        _, xa, ya = _gps_xy(session_a, lap_a, lat0, lon0)
        _, xb, yb = _gps_xy(session_b, lap_b, lat0, lon0)
        fig = _figure(height=6.5)
        ax = fig.subplots()
        ax.plot(xa, ya, linewidth=1.6, label=label_a)
        ax.plot(xb, yb, linewidth=1.6, label=label_b)
        ax.scatter([xb[0]], [yb[0]], marker="o", s=46, label="First recorded B GPS fix")
        if gps_rates and min(gps_rates) < 5:
            ax.scatter(xa, ya, s=5, alpha=0.2)
            ax.scatter(xb, yb, s=5, alpha=0.2)
        ax.set(xlabel="East (m)", ylabel="North (m)", title="GPS lap trajectories")
        ax.set_aspect("equal", adjustable="datalim")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25)
        all_figures.append(("gps_trace", fig))

    if "speed_distance" in chosen:
        speed_a = aligned["speed_a_kmh"]
        speed_b = aligned["speed_b_kmh"]
        if np.count_nonzero(np.isfinite(speed_a)) < 3 or np.count_nonzero(np.isfinite(speed_b)) < 3:
            raise ValueError("Aligned speed channels have too few samples")
        fig = _figure()
        ax = fig.subplots()
        ax.plot(distance, speed_a, label=label_a)
        ax.plot(distance, speed_b, label=label_b)
        ax.set(xlabel="Reference lap B distance (m)", ylabel="Speed (km/h)", title="Speed vs physical reference distance")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        all_figures.append(("speed_distance", fig))

    if "delta_time" in chosen:
        delta_t = aligned["elapsed_a_s"] - aligned["elapsed_b_s"]
        fig = _figure()
        ax = fig.subplots()
        ax.plot(distance, delta_t)
        ax.axhline(0, linewidth=0.9, color="gray", linestyle="--")
        ax.set(xlabel="Reference lap B distance (m)", ylabel="A − B elapsed time (s)", title="Cumulative lap delta")
        ax.grid(alpha=0.3)
        all_figures.append(("delta_time", fig))
    result = _save_report(
        output_html, f"Lap comparison: {label_a} vs {label_b}",
        all_figures, skipped={}, notes=note, channel_quality=quality_by_lap,
    )
    result["alignment_quality"] = quality
    result["lap_a"] = lap_a.to_dict()
    result["lap_b"] = lap_b.to_dict()
    result["lap_a_minus_b_total_s"] = lap_a.duration_s - lap_b.duration_s
    return result


def render_session_report(
    session: TelemetrySession,
    lap_number: int,
    output_html: Path,
    *,
    plots: list[str] | None = None,
) -> dict[str, Any]:
    """Render P2 G, driver inputs, and health only when supported by measurements."""
    chosen = _select_plots(plots, SESSION_PLOTS)
    lap = session.lap(lap_number)
    if not lap.is_timed:
        raise ValueError("Session plots require a timed lap")
    all_figures: list[tuple[str, Any]] = []
    skipped: dict[str, str] = {}
    notes = [
        "Each trace is measured channel data plotted on this lap's elapsed-time axis.",
        "Sparse/missing channels are omitted. Lines are broken across large timestamp gaps.",
        "Accelerator pedal and throttle body are separate controls; G source can be sensor-derived or calculated.",
        f"Lateral-G provenance: {session.metadata.get('lateral_accel_source', 'unknown')}.",
    ]
    all_names = tuple(dict.fromkeys(
        (LAT_G, LONG_G)
        + tuple(c[0] for c in _CONTROL_CHANNELS)
        + tuple(c[0] for c in _HEALTH_CHANNELS)
    ))
    channel_quality = _channel_info(session, lap, all_names)

    if "gg_diagram" in chosen:
        lon = _valid_series(session, lap, LONG_G)
        lat = _valid_series(session, lap, LAT_G)
        if lon is None or lat is None:
            skipped["gg_diagram"] = "Requires longitudinal and lateral G covering at least half the lap"
        elif min(_sample_rate(lon[0]) or 0, _sample_rate(lat[0]) or 0) < 5:
            skipped["gg_diagram"] = "G-G pairing requires both acceleration channels sampled at >=5 Hz"
        else:
            t_lon, g_lon = lon
            t_lat, g_lat = lat
            # Pair actual nearby measured points; no free interpolation across gaps.
            nearest = np.searchsorted(t_lat, t_lon).clip(1, len(t_lat) - 1)
            previous = nearest - 1
            use_prev = abs(t_lon - t_lat[previous]) <= abs(t_lon - t_lat[nearest])
            nearest = np.where(use_prev, previous, nearest)
            matched = abs(t_lon - t_lat[nearest]) <= 0.12
            if np.count_nonzero(matched) < 10:
                skipped["gg_diagram"] = "Too few timestamp-matched independent G samples"
            else:
                fig = _figure(height=5.7)
                ax = fig.subplots()
                ax.scatter(g_lat[nearest[matched]], g_lon[matched], s=9, alpha=0.4)
                ax.axhline(0, color="gray", linewidth=0.6)
                ax.axvline(0, color="gray", linewidth=0.6)
                ax.set(xlabel="Lateral acceleration (G)", ylabel="Longitudinal acceleration (G)", title="Measured G-G scatter")
                ax.grid(alpha=0.3)
                ax.set_aspect("equal", adjustable="datalim")
                all_figures.append(("gg_diagram", fig))

    if "g_traces" in chosen:
        available = [
            (name, label, series)
            for name, label in ((LONG_G, "Longitudinal G"), (LAT_G, "Lateral G"))
            if (series := _valid_series(session, lap, name)) is not None
        ]
        if not available:
            skipped["g_traces"] = "No G channels with sufficient measured samples and coverage"
        else:
            fig = _figure()
            ax = fig.subplots()
            for _, label, (t, v) in available:
                _plot_raw(ax, t, v, label=label)
            ax.set(xlabel="Lap elapsed (s)", ylabel="Acceleration (G)", title="Acceleration traces")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            all_figures.append(("g_traces", fig))

    def stacked_plot(plot_name: str, configuration: tuple[tuple[str, str, str], ...]):
        existing = [
            (name, label, units, series)
            for name, label, units in configuration
            if (series := _valid_series(session, lap, name)) is not None
        ]
        if not existing:
            skipped[plot_name] = "No relevant channels with sufficient measured samples and coverage"
            return
        fig = _figure(height=max(4.5, len(existing) * 1.9))
        axes = fig.subplots(len(existing), 1, sharex=True, squeeze=False)
        for i, (_, label, units, (t, v)) in enumerate(existing):
            ax = axes[i, 0]
            _plot_raw(ax, t, v, label=label)
            ax.set_ylabel(f"{label} ({units})" if units else label, fontsize=9)
            ax.grid(alpha=0.25)
        axes[-1, 0].set_xlabel("Lap elapsed (s)")
        fig.suptitle(plot_name.replace("_", " ").title())
        all_figures.append((plot_name, fig))

    if "driver_inputs" in chosen:
        stacked_plot("driver_inputs", _CONTROL_CHANNELS)
    if "vehicle_health" in chosen:
        stacked_plot("vehicle_health", _HEALTH_CHANNELS)

    if skipped and len(skipped) == len(chosen):
        # Do not write a misleading empty report.
        return {
            "output_html": None,
            "plot_files": {},
            "generated_plots": [],
            "skipped_plots": skipped,
            "notes": notes,
            "channel_quality": channel_quality,
            "lap": lap.to_dict(),
        }

    result = _save_report(
        output_html, f"Telemetry: {session.session_id} lap {lap.number}",
        all_figures, skipped=skipped, notes=notes, channel_quality=channel_quality,
    )
    result["lap"] = lap.to_dict()
    return result
