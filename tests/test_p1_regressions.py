"""Regression tests for alignment and honest telemetry source interpretation."""

from __future__ import annotations

import numpy as np
import pytest

from track_telemetry.channels import (
    BRAKE_PRESSURE_KPA,
    GPS_HEADING_DEG,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    SPEED_KMH,
    STEERING_DEG,
    THROTTLE_PCT,
    YAW_RATE_DPS,
)
from track_telemetry.incidents import analyze_incident
from track_telemetry.laps import compare_laps, section_metrics
from track_telemetry.mcp_server import _session_capabilities
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession
from track_telemetry.slip_angle import analyze_slip_angle, yaw_is_independent


def _series(name: str, t: np.ndarray, values: np.ndarray) -> ChannelSeries:
    return ChannelSeries(name, "", t, values)


def _circuit(duration: float, *, time_warp: bool = False, radius_m: float = 100.0) -> TelemetrySession:
    t = np.linspace(0.0, duration, 301)
    fraction = t / duration
    position = np.sqrt(fraction) if time_warp else fraction
    angle = 2.0 * np.pi * position
    lat = 35.0 + (radius_m * np.cos(angle)) / 111_195.0
    lon = -119.0 + (radius_m * np.sin(angle)) / (111_195.0 * np.cos(np.deg2rad(35.0)))
    return TelemetrySession(
        session_id="test-circuit",
        source="synthetic",
        laps=[Lap(1, "1", "Timed", 0.0, duration, duration)],
        channels={
            GPS_LATITUDE_DEG: _series(GPS_LATITUDE_DEG, t, lat),
            GPS_LONGITUDE_DEG: _series(GPS_LONGITUDE_DEG, t, lon),
            SPEED_KMH: _series(SPEED_KMH, t, np.full_like(t, 90.0)),
        },
    )


def test_heading_interpolation_wraps_around_north() -> None:
    ch = ChannelSeries(
        GPS_HEADING_DEG, "deg", np.array([0.0, 1.0]), np.array([359.0, 1.0])
    )
    assert ch.interp(np.array([0.5]))[0] == pytest.approx(0.0, abs=1e-8)
    assert np.isnan(ch.interp(np.array([-1.0]))[0])


def test_reference_alignment_follows_physical_position_not_time_fraction() -> None:
    ref = _circuit(10.0)
    # A reaches the physical midpoint at 25% elapsed time, despite a slower lap.
    a = _circuit(11.0, time_warp=True, radius_m=102.0)
    result = compare_laps(
        a, 1, ref, 1, same_layout_confirmed=True, mini_sectors=10,
        include_profile=True, profile_points=51,
    )
    profile = result["profile"]
    assert result["lap_a_minus_b_total_s"] == pytest.approx(1.0)
    assert sum(s["a_minus_b_s"] for s in result["mini_sectors"]) == pytest.approx(1.0)
    assert profile[0]["delta_t_s"] == pytest.approx(0)
    assert profile[-1]["delta_t_s"] == pytest.approx(1)
    # The relevant comparison must be at the physical midpoint, not 50% elapsed time.
    assert profile[25]["delta_t_s"] < -1.0
    assert profile[-1]["delta_v_kmh"] == pytest.approx(0.0)
    assert result["alignment_quality"]["p95_lateral_deviation_m"] < 5.0


def test_reference_alignment_rejects_wrong_geometry() -> None:
    a = _circuit(10.0, radius_m=160.0)
    b = _circuit(10.0, radius_m=100.0)
    with pytest.raises(ValueError, match="GPS trajectories do not align"):
        compare_laps(a, 1, b, 1, same_layout_confirmed=True)


def _driver_session() -> TelemetrySession:
    t = np.linspace(0, 10, 251)
    progress = t / 10.0
    lat = np.full_like(t, 35.0)
    lon = -119.0 + progress * 0.005
    brake = np.where((t > 1) & (t < 4), 5000.0, 0.0)
    brake[(t >= 3) & (t < 4)] = np.interp(t[(t >= 3) & (t < 4)], [3, 4], [5000, 0])
    steering = np.where((t >= 2) & (t <= 7), 25.0, 0.0)
    throttle = np.where(t >= 6, 100.0, 0.0)
    return TelemetrySession(
        session_id="test-driver",
        source="synthetic",
        metadata={"yaw_rate_source": "can"},
        laps=[Lap(1, "1", "Timed", 0.0, 10.0, 10.0)],
        channels={
            GPS_LATITUDE_DEG: _series(GPS_LATITUDE_DEG, t, lat),
            GPS_LONGITUDE_DEG: _series(GPS_LONGITUDE_DEG, t, lon),
            SPEED_KMH: _series(SPEED_KMH, t, 120 - 60 * np.sin(np.pi * progress)),
            BRAKE_PRESSURE_KPA: _series(BRAKE_PRESSURE_KPA, t, brake),
            STEERING_DEG: _series(STEERING_DEG, t, steering),
            THROTTLE_PCT: _series(THROTTLE_PCT, t, throttle),
            YAW_RATE_DPS: _series(YAW_RATE_DPS, t, np.zeros_like(t)),
        },
    )


def test_corner_driver_input_timeline_reports_ordered_thresholds() -> None:
    result = section_metrics(_driver_session(), 1, 0.0, 1.0)
    steps = result["driver_input_timeline"]
    assert steps["brake_control_source"] == BRAKE_PRESSURE_KPA
    assert steps["brake_onset_progress"] < steps["peak_brake_progress"]
    assert steps["peak_brake_progress"] < steps["brake_release_start_progress"]
    assert steps["brake_release_start_progress"] < steps["brake_end_progress"]
    assert steps["steering_onset_progress"] < steps["steering_unwind_progress"]
    assert steps["first_power_reapply_progress"] <= steps["full_power_reapply_progress"]
    assert steps["brake_steering_overlap_fraction"] > 0


def test_unknown_yaw_is_not_claimed_as_independent() -> None:
    session = _driver_session()
    session.metadata.clear()
    assert not yaw_is_independent("unknown")
    assert not yaw_is_independent("gps_heading_derivative")
    assert yaw_is_independent("rcz_can_12_100_pid_51")
    caps = _session_capabilities(session)
    assert caps["tool_support"]["analyze_slip_angle"] is False
    assert caps["tool_support"]["analyze_incident"] is False
    with pytest.raises(ValueError, match="verified yaw"):
        analyze_incident(session, 0.0, 4.0)
    with pytest.raises(ValueError, match="verified yaw rate"):
        analyze_slip_angle(session, 0.0, 4.0)
