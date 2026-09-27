"""MCP tool wrapper around deterministic telemetry analysis."""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from mcp.server import MCPServer

from .braking import analyze_braking as braking_metrics
from .channels import (
    ACCELERATOR_PCT,
    BRAKE_POS_PCT,
    BRAKE_PRESSURE_KPA,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    LONG_G,
    SPEED_KMH,
    STEERING_DEG,
    THROTTLE_PCT,
    YAW_RATE_DPS,
)
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


def _unsafe_allow_any_path() -> bool:
    value = os.getenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _root() -> Path | None:
    root_value = os.getenv("TRACK_TELEMETRY_ROOT")
    if root_value:
        root = Path(root_value).expanduser().resolve()
        if not root.is_dir():
            raise RuntimeError(f"TRACK_TELEMETRY_ROOT is not a directory: {root}")
        return root
    if _unsafe_allow_any_path():
        return None
    raise RuntimeError(
        "TRACK_TELEMETRY_ROOT is required. For deliberate unrestricted local development "
        "only, set TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH=1."
    )


def _inside_root(path: Path) -> None:
    root = _root()
    if root is not None and not path.is_relative_to(root):
        raise PermissionError(f"Path is outside TRACK_TELEMETRY_ROOT: {path}")


def _session_id(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]


def _session_index() -> dict[str, Path]:
    root = _root()
    if root is None:
        return {}
    sessions: dict[str, Path] = {}
    for candidate in root.rglob("*.rcz"):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            continue
        sessions[_session_id(resolved, root)] = resolved
    return sessions


def _resolve_existing(raw_path: str, allowed_suffixes: set[str]) -> Path:
    candidate = Path(raw_path).expanduser()
    root = _root()
    if root is not None and not candidate.is_absolute():
        candidate = root / candidate
    path = candidate.resolve()
    _inside_root(path)
    if path.suffix.lower() not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"Expected one of {allowed}, got {path.suffix!r}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _resolve_output(raw_path: str, expected_suffix: str) -> Path:
    candidate = Path(raw_path).expanduser()
    root = _root()
    if root is not None and not candidate.is_absolute():
        candidate = root / candidate
    path = candidate.resolve()
    _inside_root(path)
    if path.suffix.lower() != expected_suffix:
        raise ValueError(f"Output must end in {expected_suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_rcz(raw_path: str) -> Path:
    session = _session_index().get(raw_path)
    if session is not None:
        return session
    return _resolve_existing(raw_path, {".rcz"})


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> TelemetrySession:
    del mtime_ns
    return load_rcz(path)


def _load(raw_path: str) -> TelemetrySession:
    path = _resolve_rcz(raw_path)
    return _load_cached(str(path), path.stat().st_mtime_ns)


def _session_capabilities(session: TelemetrySession) -> dict[str, Any]:
    channels = set(session.channels)
    timed_laps = [lap for lap in session.laps if lap.is_timed]
    yaw_source = str(session.metadata.get("yaw_rate_source", "unknown"))
    has_gps_trace = {GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG}.issubset(channels)
    has_speed = SPEED_KMH in channels
    has_yaw = YAW_RATE_DPS in channels
    has_brake_control = BRAKE_PRESSURE_KPA in channels or BRAKE_POS_PCT in channels
    has_power_control = THROTTLE_PCT in channels or ACCELERATOR_PCT in channels
    independent_yaw = has_yaw and yaw_source != "gps_heading_derivative"

    channel_capabilities = {
        "timed_laps": bool(timed_laps),
        "gps_trace": has_gps_trace,
        "speed": has_speed,
        "longitudinal_g": LONG_G in channels,
        "yaw_rate": has_yaw,
        "independent_yaw_rate": independent_yaw,
        "steering": STEERING_DEG in channels,
        "brake_control": has_brake_control,
        "power_control": has_power_control,
    }
    tool_support = {
        "analyze_lap": bool(timed_laps),
        "analyze_section": bool(timed_laps) and has_gps_trace and has_speed,
        "analyze_braking": LONG_G in channels,
        "analyze_slip_angle": has_gps_trace and has_speed and independent_yaw,
        "analyze_incident": has_gps_trace and has_speed and has_yaw,
        "compare_laps": bool(timed_laps) and has_gps_trace,
    }
    reasons: dict[str, str] = {}
    requirements = {
        "analyze_lap": "requires at least one timed lap",
        "analyze_section": "requires timed laps, GPS latitude/longitude, and speed",
        "analyze_braking": "requires longitudinal G; brake/speed channels enrich event metrics",
        "analyze_slip_angle": (
            "requires GPS latitude/longitude, speed, and yaw rate independent of GPS course"
        ),
        "analyze_incident": "requires GPS latitude/longitude, speed, and yaw rate",
        "compare_laps": "requires timed laps and GPS latitude/longitude",
    }
    for tool_name, supported in tool_support.items():
        if not supported:
            reasons[tool_name] = requirements[tool_name]

    return {
        "channels": channel_capabilities,
        "yaw_rate_source": yaw_source,
        "tool_support": tool_support,
        "unsupported_reasons": reasons,
    }


def _prepare_session_data(session: TelemetrySession) -> dict[str, Any]:
    pb = fastest_timed_lap(session)
    capabilities = _session_capabilities(session)
    general_order = ["analyze_lap", "compare_laps", "analyze_section"]
    specialized_order = ["analyze_braking", "analyze_slip_angle", "analyze_incident"]
    recommended = [
        name for name in general_order if capabilities["tool_support"].get(name, False)
    ]
    specialized = [
        name for name in specialized_order if capabilities["tool_support"].get(name, False)
    ]
    return {
        "session_id": session.session_id,
        "source_name": Path(session.source).name,
        "fastest_timed_lap_number": pb.number if pb is not None else None,
        "timed_lap_numbers": [lap.number for lap in session.laps if lap.is_timed],
        "capabilities": capabilities,
        "recommended_tools": recommended,
        "available_specialized_tools": specialized,
        "guidance": (
            "Start with the recommended general tools only as needed. Use specialized tools "
            "only when the user's question specifically concerns braking, sliding, or an incident. "
            "Do not call every supported tool by default."
        ),
    }


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


def _list_sessions_data() -> dict[str, Any]:
    root = _root()
    if root is None:
        return {
            "discovery_available": False,
            "sessions": [],
            "reason": "Session discovery requires TRACK_TELEMETRY_ROOT.",
        }
    sessions = [
        {
            "session_id": session_id,
            "source_name": path.name,
        }
        for session_id, path in sorted(
            _session_index().items(),
            key=lambda item: item[1].relative_to(root).as_posix().lower(),
        )
    ]
    return {
        "discovery_available": True,
        "session_count": len(sessions),
        "sessions": sessions,
    }


@mcp.tool()
def list_sessions() -> dict[str, Any]:
    """Discover RCZ sessions under TRACK_TELEMETRY_ROOT without exposing absolute paths."""
    return _list_sessions_data()


@mcp.tool()
def inspect_session(path: str) -> dict[str, Any]:
    """Inspect a session before choosing analysis tools.

    Use first for RCZ analysis after list_sessions. Returns channels, sample rates, laps,
    PB, and a capability matrix. Do not infer that an analysis is valid merely because a
    similarly named channel exists; consult capabilities/tool_support.
    """
    session = _load(path)
    result = session.to_summary()
    pb = fastest_timed_lap(session)
    result["fastest_timed_lap"] = pb.to_dict() if pb is not None else None
    result["capabilities"] = _session_capabilities(session)
    return result


@mcp.tool()
def prepare_session(path: str) -> dict[str, Any]:
    """Prepare an agent to analyze one RCZ session with minimal tool calls.

    Use after list_sessions when the agent needs a concise PB/lap/capability summary.
    The returned recommended_tools are availability hints, not an instruction to call all
    of them. Choose only tools relevant to the user's question.
    """
    return _prepare_session_data(_load(path))


@mcp.tool()
def list_laps(path: str) -> dict[str, Any]:
    """List laps and PB for a selected RCZ session.

    Use when lap selection matters. Prefer inspect_session/prepare_session first when the
    agent has not yet checked available channels or analysis capabilities.
    """
    session = _load(path)
    pb = fastest_timed_lap(session)
    return {
        "session_id": session.session_id,
        "fastest_timed_lap_number": pb.number if pb is not None else None,
        "laps": [lap.to_dict() for lap in session.laps],
    }


@mcp.tool()
def analyze_lap(path: str, lap_number: int) -> dict[str, Any]:
    """Measure one timed lap's summary metrics.

    Use for a known lap after inspection. Requires a valid timed lap; missing optional
    channels produce null metrics. Do not use this alone to diagnose a specific corner when analyze_section can measure
    entry/minimum/exit behavior directly.
    """
    return lap_summary(_load(path), lap_number)


@mcp.tool()
def analyze_section(
    path: str,
    lap_number: int,
    start_progress: float,
    end_progress: float,
) -> dict[str, Any]:
    """Measure one normalized-distance section of a timed lap.

    Use for corner/section diagnosis after confirming the lap/layout. Requires GPS trace,
    speed, and a timed lap. start_progress/end_progress are lap fractions, not named
    corners. Do not compare different layouts by matching the same progress values.
    """
    return section_metrics(_load(path), lap_number, start_progress, end_progress)


@mcp.tool()
def analyze_braking(path: str, lap_number: int | None = None) -> dict[str, Any]:
    """Measure brake events and raw vs sustained longitudinal deceleration.

    Use when braking/deceleration is the question. Longitudinal G is required; brake
    pressure/pedal enables event detection and speed enriches entry/minimum-speed metrics.
    Do not infer ABS activation from brake pressure alone, and do not call this merely
    because a general session review was requested.
    """
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
    """Estimate bounded-window vehicle sideslip proxy from GPS course and yaw rate.

    Use only when rotation/sliding is relevant and inspect_session reports
    independent_yaw_rate=true. This is not tire slip angle. Choose an anchor where
    sideslip is plausibly near zero; GPS-derived yaw rate is rejected.
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
    """Reconstruct a bounded slide/spin/off-track timeline.

    Use for a known incident window, not routine session review. Requires GPS trace,
    speed, and yaw rate; steering/power/brake channels enrich the result when present.
    A supplied surface_change_s must come from video/observation, not telemetry inference.
    """
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
    """Compare two laps by normalized GPS distance.

    Use only after independently confirming both laps use the same physical layout, then
    set same_layout_confirmed=true. Never use normalized lap progress to compare different
    layouts; compare shared physical sections instead.
    """
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

    Use only when raw reference telemetry is unavailable and a calibrated overlay config
    exists. The result is pseudo telemetry, not RCZ-quality data. Do not invent brake,
    throttle, RPM, gear, or other channels that this extractor did not measure.
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
    """Write a standalone HTML replay for an already identified incident.

    Use after incident analysis when a visual replay helps. The reference lap is only a
    trajectory reference and must not be interpreted as a track/asphalt boundary.
    """
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
    _root()
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
