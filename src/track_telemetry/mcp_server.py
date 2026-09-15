"""MCP tool wrapper around deterministic telemetry analysis."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from mcp.server import MCPServer

from .braking import analyze_braking as braking_metrics
from .channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG
from .geometry import latlon_to_xy_m
from .incidents import analyze_incident as incident_metrics
from .laps import compare_laps as compare_lap_data
from .laps import fastest_timed_lap, lap_summary, section_metrics
from .models import TelemetrySession
from .motec_adapter import load_rcz
from .reference_video import (
    extract_reference_telemetry,
    load_overlay_config,
    write_reference_csv,
)
from .slip_angle import analyze_slip_angle as slip_angle_metrics
from .visualization import write_incident_html

mcp = MCPServer("track-telemetry")


def _root() -> Path | None:
    root_value = os.getenv("TRACK_TELEMETRY_ROOT")
    return Path(root_value).expanduser().resolve() if root_value else None


def _inside_root(path: Path) -> None:
    root = _root()
    if root is not None and not path.is_relative_to(root):
        raise PermissionError(f"Path is outside TRACK_TELEMETRY_ROOT: {path}")


def _resolve_existing(raw_path: str, allowed_suffixes: set[str]) -> Path:
    path = Path(raw_path).expanduser().resolve()
    _inside_root(path)
    if path.suffix.lower() not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"Expected one of {allowed}, got {path.suffix!r}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _resolve_output(raw_path: str, expected_suffix: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    _inside_root(path)
    if path.suffix.lower() != expected_suffix:
        raise ValueError(f"Output must end in {expected_suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_rcz(raw_path: str) -> Path:
    return _resolve_existing(raw_path, {".rcz"})


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> TelemetrySession:
    del mtime_ns
    return load_rcz(path)


def _load(raw_path: str) -> TelemetrySession:
    path = _resolve_rcz(raw_path)
    return _load_cached(str(path), path.stat().st_mtime_ns)


def _lap_xy_with_origin(
    session: TelemetrySession,
    lap_number: int,
    origin_lat: float,
    origin_lon: float,
) -> list[tuple[float, float]]:
    lap = session.lap(lap_number)
    lat_ch = session.channel(GPS_LATITUDE_DEG)
    lon_ch = session.channel(GPS_LONGITUDE_DEG)
    mask = (lat_ch.timestamps >= lap.start_s) & (lat_ch.timestamps <= lap.end_s)
    t = lat_ch.timestamps[mask]
    lat = lat_ch.values[mask]
    lon = lon_ch.interp(t)
    valid = np.isfinite(lat) & np.isfinite(lon)
    x, y = latlon_to_xy_m(
        lat[valid],
        lon[valid],
        origin_lat_deg=origin_lat,
        origin_lon_deg=origin_lon,
    )
    return [(float(a), float(b)) for a, b in zip(x, y)]


@mcp.tool()
def inspect_session(path: str) -> dict[str, Any]:
    """Inspect one RCZ session: metadata, channels, sampling rates, laps, and PB."""
    session = _load(path)
    result = session.to_summary()
    pb = fastest_timed_lap(session)
    result["fastest_timed_lap"] = pb.to_dict() if pb is not None else None
    return result


@mcp.tool()
def list_laps(path: str) -> dict[str, Any]:
    """Return the compact lap table for an RCZ session."""
    session = _load(path)
    pb = fastest_timed_lap(session)
    return {
        "session_id": session.session_id,
        "fastest_timed_lap_number": pb.number if pb is not None else None,
        "laps": [lap.to_dict() for lap in session.laps],
    }


@mcp.tool()
def analyze_lap(path: str, lap_number: int) -> dict[str, Any]:
    """Return deterministic lap-level speed, input, G, and yaw summary metrics."""
    return lap_summary(_load(path), lap_number)


@mcp.tool()
def analyze_section(
    path: str,
    lap_number: int,
    start_progress: float,
    end_progress: float,
) -> dict[str, Any]:
    """Analyze entry/min/exit and pedal behavior in a normalized-distance lap section."""
    return section_metrics(_load(path), lap_number, start_progress, end_progress)


@mcp.tool()
def analyze_braking(path: str, lap_number: int | None = None) -> dict[str, Any]:
    """Measure brake events, pressure ramp, and raw vs sustained longitudinal deceleration."""
    return braking_metrics(_load(path), lap_number)


@mcp.tool()
def analyze_slip_angle(
    path: str,
    start_s: float,
    end_s: float,
    anchor_s: float | None = None,
    yaw_sign: float = 1.0,
    low_speed_mph: float = 8.0,
    include_samples: bool = False,
    sample_stride: int = 5,
) -> dict[str, Any]:
    """Estimate vehicle sideslip proxy from GPS course and independent yaw rate.

    This is not tire slip angle. Body heading is estimated by integrating yaw rate from
    an anchor where sideslip is assumed near zero. GPS-derived yaw rate is rejected.
    """
    return slip_angle_metrics(
        _load(path),
        start_s,
        end_s,
        anchor_s=anchor_s,
        yaw_sign=yaw_sign,
        low_speed_mph=low_speed_mph,
        include_samples=include_samples,
        sample_stride=sample_stride,
    )


@mcp.tool()
def analyze_incident(
    path: str,
    start_s: float,
    end_s: float,
    anchor_s: float | None = None,
    surface_change_s: float | None = None,
    yaw_sign: float = 1.0,
    include_samples: bool = False,
    sample_stride: int = 5,
) -> dict[str, Any]:
    """Reconstruct a slide/spin timeline from GPS travel direction, yaw, steering, and pedals."""
    return incident_metrics(
        _load(path),
        start_s,
        end_s,
        anchor_s=anchor_s,
        surface_change_s=surface_change_s,
        yaw_sign=yaw_sign,
        include_samples=include_samples,
        sample_stride=sample_stride,
    )


@mcp.tool()
def compare_laps(
    path_a: str,
    lap_a: int,
    path_b: str,
    lap_b: int,
    same_layout_confirmed: bool = False,
    mini_sectors: int = 20,
) -> dict[str, Any]:
    """Compare two laps by normalized GPS distance only after confirming identical layout."""
    return compare_lap_data(
        _load(path_a),
        lap_a,
        _load(path_b),
        lap_b,
        same_layout_confirmed=same_layout_confirmed,
        mini_sectors=mini_sectors,
    )


@mcp.tool()
def extract_reference_overlay(
    video_path: str,
    config_path: str,
    start_s: float = 0.0,
    end_s: float | None = None,
    sample_hz: float = 10.0,
    output_csv: str | None = None,
    include_rows: bool = False,
) -> dict[str, Any]:
    """Recover approximate speed and track-map position from a calibrated onboard overlay.

    The video values are reference/pseudo telemetry, not raw logger data. Configuration
    supplies the speedometer ROI, dial calibration, and optional track-map marker color.
    """
    video = _resolve_existing(video_path, {".mp4", ".mov", ".mkv", ".avi", ".webm"})
    config_file = _resolve_existing(config_path, {".json"})
    config = load_overlay_config(config_file)
    rows = extract_reference_telemetry(
        video,
        config,
        start_s=start_s,
        end_s=end_s,
        sample_hz=sample_hz,
    )
    result: dict[str, Any] = {
        "video_path": str(video),
        "row_count": len(rows),
        "valid_speed_rows": sum(row["speed_mph"] is not None for row in rows),
        "valid_map_rows": sum(
            row["map_x"] is not None and row["map_y"] is not None for row in rows
        ),
        "sample_hz": sample_hz,
        "approximate_reference_telemetry": True,
    }
    if rows:
        result["time_range_s"] = [rows[0]["video_t"], rows[-1]["video_t"]]
    if output_csv is not None:
        output = _resolve_output(output_csv, ".csv")
        write_reference_csv(rows, output)
        result["output_csv"] = str(output)
    if include_rows:
        result["rows"] = rows
    return result


@mcp.tool()
def render_incident_player(
    path: str,
    start_s: float,
    end_s: float,
    output_html: str,
    anchor_s: float | None = None,
    surface_change_s: float | None = None,
    yaw_sign: float = 1.0,
    sample_stride: int = 1,
    reference_lap_number: int | None = None,
) -> dict[str, Any]:
    """Write a standalone interactive HTML incident animation using real GPS samples."""
    session = _load(path)
    incident = incident_metrics(
        session,
        start_s,
        end_s,
        anchor_s=anchor_s,
        surface_change_s=surface_change_s,
        yaw_sign=yaw_sign,
        include_samples=True,
        sample_stride=sample_stride,
    )
    reference_xy = None
    if reference_lap_number is not None:
        origin = incident["projection_origin"]
        reference_xy = _lap_xy_with_origin(
            session,
            reference_lap_number,
            float(origin["latitude_deg"]),
            float(origin["longitude_deg"]),
        )
    output = _resolve_output(output_html, ".html")
    write_incident_html(
        incident,
        output,
        title=f"{session.session_id} · {start_s:.2f}-{end_s:.2f} s",
        clean_reference_xy=reference_xy,
    )
    return {
        "output_html": str(output),
        "sample_count": len(incident.get("samples", [])),
        "event_count": len(incident.get("timeline", [])),
        "reference_lap_number": reference_lap_number,
    }


def main() -> None:
    """Run stdio by default, or Streamable HTTP when requested by environment."""
    transport = os.getenv("TRACK_TELEMETRY_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        mcp.run()
        return
    if transport == "streamable-http":
        mcp.run(transport="streamable-http", json_response=True)
        return
    raise ValueError("TRACK_TELEMETRY_TRANSPORT must be 'stdio' or 'streamable-http'")


if __name__ == "__main__":
    main()
