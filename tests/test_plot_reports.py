"""Smoke-test P1/P2 output artifacts and source-quality guards."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from mcp import Client

from track_telemetry import mcp_server
from track_telemetry.channels import (
    ACCELERATOR_PCT,
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
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession
from track_telemetry.report_plots import _style_gg_axes, render_lap_comparison, render_session_report


def _session(
    duration: float = 20.0,
    *,
    radius: float = 100.0,
    warped: bool = False,
    n: int = 301,
    controls: bool = True,
) -> TelemetrySession:
    t = np.linspace(0.0, duration, n)
    fraction = np.sqrt(t / duration) if warped else t / duration
    angle = 2 * np.pi * fraction
    latitude = 35.0 + radius * np.cos(angle) / 111_195.0
    longitude = -119 + radius * np.sin(angle) / (111_195.0 * np.cos(np.deg2rad(35.0)))
    fields = {
        GPS_LATITUDE_DEG: ChannelSeries(GPS_LATITUDE_DEG, "deg", t, latitude),
        GPS_LONGITUDE_DEG: ChannelSeries(GPS_LONGITUDE_DEG, "deg", t, longitude),
        SPEED_KMH: ChannelSeries(SPEED_KMH, "km/h", t, 100 + 8 * np.cos(angle)),
    }
    if controls:
        values = {
            LAT_G: ("G", np.sin(angle) * 0.9),
            LONG_G: ("G", -np.cos(angle) * 0.7),
            BRAKE_PRESSURE_KPA: ("kPa", np.maximum(0, 5000 * np.cos(angle))),
            ACCELERATOR_PCT: ("%", 50 + 40 * np.sin(angle)),
            THROTTLE_PCT: ("%", 40 + 30 * np.sin(angle)),
            STEERING_DEG: ("deg", 35 * np.sin(angle)),
            ENGINE_RPM: ("rpm", 5500 + 750 * np.sin(angle)),
            GEAR: ("", np.full_like(t, 3)),
            ENGINE_OIL_PRESSURE_KPA: ("kPa", 370 + 25 * np.sin(angle)),
            ENGINE_OIL_TEMP_C: ("C", 106 + np.sin(angle)),
            COOLANT_TEMP_C: ("C", 94 + 2 * np.sin(angle)),
            GEARBOX_TEMP_C: ("C", 109 + 3 * np.sin(angle)),
        }
        fields.update(
            {
                name: ChannelSeries(name, unit, t, data)
                for name, (unit, data) in values.items()
            }
        )
    return TelemetrySession(
        session_id="synthetic",
        source="synthetic.rcz",
        metadata={"lateral_accel_source": "rcz_accelerometer_test"},
        laps=[Lap(1, "1", "Timed", 0.0, duration, duration)],
        channels=fields,
    )


def _verify_png_files(result: dict) -> None:
    assert result["output_html"] is not None
    html_path = Path(result["output_html"])
    assert html_path.is_file()
    assert "data:image/png;base64," in html_path.read_text()
    for path in result["plot_files"].values():
        assert Path(path).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_p1_generates_three_real_figures_and_honest_delta(tmp_path: Path) -> None:
    a = _session(21, warped=True, radius=102)
    b = _session(20)
    result = render_lap_comparison(
        a, 1, b, 1, tmp_path / "comparison.html",
        same_layout_confirmed=True,
    )
    assert result["generated_plots"] == ["gps_trace", "speed_distance", "delta_time"]
    assert result["lap_a_minus_b_total_s"] == pytest.approx(1)
    assert result["alignment_quality"]["p95_lateral_deviation_m"] < 5
    _verify_png_files(result)


def test_p1_refuses_unconfirmed_or_incompatible_layout(tmp_path: Path) -> None:
    a = _session(radius=160)
    b = _session()
    with pytest.raises(ValueError, match="same_layout_confirmed"):
        render_lap_comparison(a, 1, b, 1, tmp_path / "no.html", same_layout_confirmed=False)
    with pytest.raises(ValueError, match="GPS trajectories do not align"):
        render_lap_comparison(a, 1, b, 1, tmp_path / "no.html", same_layout_confirmed=True)
    assert not (tmp_path / "no.html").exists()


def test_p1_labels_sparse_gps_without_inventing_25hz(tmp_path: Path) -> None:
    a = _session(30, radius=102, n=31)
    b = _session(30, n=31)
    result = render_lap_comparison(
        a, 1, b, 1, tmp_path / "low-rate.html",
        same_layout_confirmed=True,
    )
    assert result["channel_quality"]["lap_a"][GPS_LATITUDE_DEG]["rate_hz"] == pytest.approx(1)
    assert any("Low GPS sample rate (1.0 Hz)" in note for note in result["notes"])
    _verify_png_files(result)


def test_p2_generates_gg_g_traces_controls_and_health(tmp_path: Path) -> None:
    result = render_session_report(_session(), 1, tmp_path / "diagnostics.html")
    assert set(result["generated_plots"]) == {
        "gg_diagram", "g_traces", "driver_inputs", "vehicle_health"
    }
    assert result["skipped_plots"] == {}
    assert result["channel_quality"][ENGINE_OIL_PRESSURE_KPA]["samples"] == 301
    _verify_png_files(result)
    assert result["plot_files"]["vehicle_health"].endswith("_vehicle_health.png")


def test_gg_axes_have_equal_units_symmetric_bounds_and_half_g_rings() -> None:
    from matplotlib.figure import Figure
    from matplotlib.patches import Circle

    fig = Figure(figsize=(7, 7))
    ax = fig.subplots()
    limit = _style_gg_axes(
        ax, np.array([-1.27, 0.35]), np.array([-1.7, 1.45])
    )
    assert limit == pytest.approx(2.0)
    assert ax.get_xlim() == pytest.approx((-2.0, 2.0))
    assert ax.get_ylim() == pytest.approx((-2.0, 2.0))
    assert ax.get_aspect() == pytest.approx(1.0)
    circles = [patch for patch in ax.patches if isinstance(patch, Circle)]
    assert [circle.radius for circle in circles] == pytest.approx([0.5, 1.0, 1.5, 2.0])
    assert all(circle.get_fill() is False for circle in circles)
    assert all(circle.get_linestyle() != "solid" for circle in circles)
    texts = {item.get_text() for item in ax.texts}
    assert {"0.5g", "1.0g", "1.5g", "2.0g"}.issubset(texts)
    assert {
        "ACCELERATING (+G)", "BRAKING (−G)", "LEFT TURN (−G)", "RIGHT TURN (+G)"
    }.issubset(texts)
    assert len(ax.lines) == 2  # the horizontal and vertical zero axes


def test_gg_axes_have_minimum_half_g_range() -> None:
    from matplotlib.figure import Figure
    from matplotlib.patches import Circle

    ax = Figure().subplots()
    limit = _style_gg_axes(ax, np.array([0.1]), np.array([-0.2]))
    assert limit == pytest.approx(0.5)
    assert len([p for p in ax.patches if isinstance(p, Circle)]) == 1


def test_p2_skips_missing_g_and_health_without_fake_values(tmp_path: Path) -> None:
    session = _session(controls=False)
    result = render_session_report(
        session, 1, tmp_path / "empty.html",
        plots=["gg_diagram", "g_traces", "vehicle_health"],
    )
    assert result["generated_plots"] == []
    assert set(result["skipped_plots"]) == {"gg_diagram", "g_traces", "vehicle_health"}
    assert result["output_html"] is None
    assert not (tmp_path / "empty.html").exists()


def test_p2_does_not_call_speed_only_a_driver_input(tmp_path: Path) -> None:
    session = _session(controls=False)
    result = render_session_report(
        session, 1, tmp_path / "no-controls.html", plots=["driver_inputs"]
    )
    assert result["generated_plots"] == []
    assert "No actual driver-input channels" in result["skipped_plots"]["driver_inputs"]
    assert result["output_html"] is None


def test_p2_refuses_sparse_gg_but_keeps_health(tmp_path: Path) -> None:
    session = _session()
    sparse = np.linspace(0, 20, 21)
    session.channels[LAT_G] = ChannelSeries(LAT_G, "G", sparse, np.ones_like(sparse))
    result = render_session_report(
        session, 1, tmp_path / "partial.html",
        plots=["gg_diagram", "vehicle_health"],
    )
    assert result["generated_plots"] == ["vehicle_health"]
    assert "gg_diagram" in result["skipped_plots"]
    _verify_png_files(result)


def test_mcp_render_tools_are_exposed_and_confined_to_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "telemetry"
    root.mkdir()
    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)
    synthetic = _session()
    monkeypatch.setattr(mcp_server, "_load", lambda *args, **kwargs: synthetic)

    async def run() -> None:
        async with Client(mcp_server.mcp, raise_exceptions=True) as client:
            listing = await client.list_tools()
            names = {item.name for item in listing.tools}
            assert {"render_lap_comparison", "render_session_report"}.issubset(names)
            rendered = await client.call_tool(
                "render_lap_comparison",
                {
                    "path_a": "synthetic.rcz",
                    "lap_a": 1,
                    "path_b": "synthetic.rcz",
                    "lap_b": 1,
                    "output_html": "plots/comparison.html",
                    "same_layout_confirmed": True,
                },
            )
            assert rendered.is_error is False
            assert (root / "plots" / "comparison.html").is_file()
            health = await client.call_tool(
                "render_session_report",
                {"path": "synthetic.rcz", "lap_number": 1, "output_html": "plots/health.html"},
            )
            assert health.is_error is False
            assert "vehicle_health" in health.structured_content["generated_plots"]

    asyncio.run(run())
    with pytest.raises(PermissionError, match="outside TRACK_TELEMETRY_ROOT"):
        mcp_server.render_session_report(
            "synthetic.rcz", 1, str(tmp_path / "outside.html")
        )
