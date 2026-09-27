from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

import pytest
from mcp import Client

from track_telemetry import mcp_server
from track_telemetry.channels import (
    BRAKE_PRESSURE_KPA,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    LONG_G,
    SPEED_KMH,
    YAW_RATE_DPS,
)
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession


def test_root_is_secure_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACK_TELEMETRY_ROOT", raising=False)
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    with pytest.raises(RuntimeError, match="TRACK_TELEMETRY_ROOT is required"):
        mcp_server._root()


def test_unsafe_any_path_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACK_TELEMETRY_ROOT", raising=False)
    monkeypatch.setenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", "1")

    assert mcp_server._root() is None
    result = mcp_server._list_sessions_data()
    assert result["discovery_available"] is False
    assert result["sessions"] == []


def test_list_sessions_returns_stable_opaque_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "telemetry"
    nested = root / "weekend"
    nested.mkdir(parents=True)
    first = root / "session-a.rcz"
    second = nested / "session-b.rcz"
    first.write_bytes(b"")
    second.write_bytes(b"")

    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    result = mcp_server._list_sessions_data()
    assert result["discovery_available"] is True
    assert result["session_count"] == 2
    assert {item["source_name"] for item in result["sessions"]} == {
        "session-a.rcz",
        "session-b.rcz",
    }
    assert all(len(item["session_id"]) == 16 for item in result["sessions"])
    assert all(str(root) not in item["session_id"] for item in result["sessions"])

    again = mcp_server._list_sessions_data()
    assert again["sessions"] == result["sessions"]

    by_name = {item["source_name"]: item["session_id"] for item in result["sessions"]}
    assert mcp_server._resolve_rcz(by_name["session-a.rcz"]) == first.resolve()
    assert mcp_server._resolve_rcz(by_name["session-b.rcz"]) == second.resolve()


def test_relative_paths_resolve_inside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "telemetry"
    root.mkdir()
    session = root / "session.rcz"
    session.write_bytes(b"")

    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    assert mcp_server._resolve_rcz("session.rcz") == session.resolve()


def test_paths_outside_root_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "telemetry"
    root.mkdir()
    outside = tmp_path / "outside.rcz"
    outside.write_bytes(b"")

    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    with pytest.raises(PermissionError, match="outside TRACK_TELEMETRY_ROOT"):
        mcp_server._resolve_rcz(str(outside))



def _synthetic_session(*, yaw_source: str = "can") -> TelemetrySession:
    ts = np.linspace(0.0, 10.0, 101)
    return TelemetrySession(
        session_id="synthetic",
        source="synthetic.rcz",
        metadata={"yaw_rate_source": yaw_source},
        laps=[Lap(1, "1", "Timed", 0.0, 10.0, 10.0)],
        channels={
            GPS_LATITUDE_DEG: ChannelSeries(GPS_LATITUDE_DEG, "deg", ts, np.full_like(ts, 35.0)),
            GPS_LONGITUDE_DEG: ChannelSeries(
                GPS_LONGITUDE_DEG, "deg", ts, -119.0 + ts * 0.0001
            ),
            SPEED_KMH: ChannelSeries(SPEED_KMH, "km/h", ts, np.full_like(ts, 100.0)),
            LONG_G: ChannelSeries(LONG_G, "G", ts, np.full_like(ts, -0.5)),
            BRAKE_PRESSURE_KPA: ChannelSeries(
                BRAKE_PRESSURE_KPA, "kPa", ts, np.zeros_like(ts)
            ),
            YAW_RATE_DPS: ChannelSeries(YAW_RATE_DPS, "deg/s", ts, np.zeros_like(ts)),
        },
    )


def test_session_capabilities_gate_specialized_tools() -> None:
    supported = mcp_server._session_capabilities(_synthetic_session(yaw_source="can"))
    assert supported["tool_support"]["analyze_lap"] is True
    assert supported["tool_support"]["analyze_section"] is True
    assert supported["tool_support"]["analyze_braking"] is True
    assert supported["tool_support"]["analyze_slip_angle"] is True
    assert supported["tool_support"]["analyze_incident"] is True

    gps_derived = mcp_server._session_capabilities(
        _synthetic_session(yaw_source="gps_heading_derivative")
    )
    assert gps_derived["channels"]["independent_yaw_rate"] is False
    assert gps_derived["tool_support"]["analyze_slip_angle"] is False
    assert "analyze_slip_angle" in gps_derived["unsupported_reasons"]


def test_prepare_session_is_lazy_and_capability_aware() -> None:
    result = mcp_server._prepare_session_data(_synthetic_session())
    assert result["fastest_timed_lap_number"] == 1
    assert result["timed_lap_numbers"] == [1]
    assert "analyze_lap" in result["recommended_tools"]
    assert "analyze_section" in result["recommended_tools"]
    assert "analyze_incident" not in result["recommended_tools"]
    assert "analyze_incident" in result["available_specialized_tools"]
    assert "Do not call every supported tool" in result["guidance"]


def test_mcp_client_round_trip_lists_and_calls_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "telemetry"
    root.mkdir()
    (root / "session.rcz").write_bytes(b"")
    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    async def run() -> None:
        async with Client(mcp_server.mcp, raise_exceptions=True) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "list_sessions" in names
            assert "prepare_session" in names
            assert "analyze_section" in names

            result = await client.call_tool("list_sessions", {})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["session_count"] == 1
            session = result.structured_content["sessions"][0]
            assert session["source_name"] == "session.rcz"
            assert len(session["session_id"]) == 16

    asyncio.run(run())
