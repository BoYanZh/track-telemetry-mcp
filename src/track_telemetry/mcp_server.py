"""MCP tool wrapper around deterministic telemetry analysis."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from .braking import analyze_braking as braking_metrics
from .incidents import analyze_incident as incident_metrics
from .laps import (
    compare_laps as compare_lap_data,
    fastest_timed_lap,
    lap_summary,
    section_metrics,
)
from .models import TelemetrySession
from .motec_adapter import load_rcz

mcp = MCPServer("track-telemetry")


def _resolve_rcz(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    root_value = os.getenv("TRACK_TELEMETRY_ROOT")
    if root_value:
        root = Path(root_value).expanduser().resolve()
        if not path.is_relative_to(root):
            raise PermissionError(f"Path is outside TRACK_TELEMETRY_ROOT: {path}")
    if path.suffix.lower() != ".rcz":
        raise ValueError("Only .rcz files are accepted by the file-backed MCP tools")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> TelemetrySession:
    del mtime_ns
    return load_rcz(path)


def _load(raw_path: str) -> TelemetrySession:
    path = _resolve_rcz(raw_path)
    return _load_cached(str(path), path.stat().st_mtime_ns)


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
def analyze_incident(
    path: str,
    start_s: float,
    end_s: float,
    anchor_s: float | None = None,
    surface_change_s: float | None = None,
    yaw_sign: float = 1.0,
    include_samples: bool = False,
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
