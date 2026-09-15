from __future__ import annotations

import numpy as np

from track_telemetry.braking import analyze_braking
from track_telemetry.channels import (
    ACCELERATOR_PCT,
    BRAKE_PRESSURE_KPA,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    LONG_G,
    SPEED_KMH,
    STEERING_DEG,
    THROTTLE_PCT,
    YAW_RATE_DPS,
)
from track_telemetry.incidents import analyze_incident
from track_telemetry.laps import compare_laps, lap_summary, section_metrics
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession


def _channel(name: str, t: np.ndarray, values: np.ndarray, units: str = "") -> ChannelSeries:
    return ChannelSeries(name, units, t, values)


def _straight_session(
    duration_s: float = 10.0,
    samples: int = 251,
    *,
    power_channel: str = THROTTLE_PCT,
) -> TelemetrySession:
    t = np.linspace(0.0, duration_s, samples)
    progress = t / duration_s
    lat = np.full_like(t, 35.0)
    lon = -119.0 + progress * 0.01
    speed = 120.0 - 50.0 * np.sin(np.pi * progress)
    power = np.where(progress < 0.55, 20.0, 100.0)
    channels = {
        GPS_LATITUDE_DEG: _channel(GPS_LATITUDE_DEG, t, lat, "deg"),
        GPS_LONGITUDE_DEG: _channel(GPS_LONGITUDE_DEG, t, lon, "deg"),
        SPEED_KMH: _channel(SPEED_KMH, t, speed, "km/h"),
        power_channel: _channel(power_channel, t, power, "%"),
    }
    return TelemetrySession(
        session_id=f"synthetic-{duration_s}",
        source="synthetic",
        laps=[Lap(1, "1", "Timed", 0.0, duration_s, duration_s)],
        channels=channels,
    )


def test_compare_laps_requires_layout_confirmation() -> None:
    a = _straight_session(10.0)
    b = _straight_session(11.0)
    try:
        compare_laps(a, 1, b, 1, same_layout_confirmed=False)
    except ValueError as exc:
        assert "same_layout_confirmed" in str(exc)
    else:
        raise AssertionError("Expected layout guard to reject comparison")

    result = compare_laps(a, 1, b, 1, same_layout_confirmed=True, mini_sectors=10)
    assert result["lap_a_minus_b_total_s"] == -1.0
    assert len(result["mini_sectors"]) == 10


def test_section_metrics_reports_entry_min_exit() -> None:
    session = _straight_session()
    result = section_metrics(session, 1, 0.0, 1.0)
    assert result["entry_speed_kmh"] > result["min_speed_kmh"]
    assert result["exit_speed_kmh"] > result["min_speed_kmh"]
    assert 0.45 < result["min_speed_progress"] < 0.55
    assert result["control_source"] == THROTTLE_PCT
    assert result["full_control_reapply_progress"] is not None
    assert result["full_throttle_reapply_progress"] == result["full_control_reapply_progress"]


def test_accelerator_fallback_is_explicit_and_not_relabelled_as_throttle() -> None:
    session = _straight_session(power_channel=ACCELERATOR_PCT)

    lap = lap_summary(session, 1)
    assert lap["control_source"] == ACCELERATOR_PCT
    assert lap["full_control_fraction"] == lap["full_accelerator_fraction"]
    assert "full_throttle_fraction" not in lap

    section = section_metrics(session, 1, 0.0, 1.0)
    assert section["control_source"] == ACCELERATOR_PCT
    assert section["entry_control_pct"] == section["entry_accelerator_pct"]
    assert section["exit_control_pct"] == section["exit_accelerator_pct"]
    assert section["full_control_reapply_progress"] == section["full_accelerator_reapply_progress"]
    assert "entry_throttle_pct" not in section
    assert "full_throttle_reapply_progress" not in section


def test_throttle_is_preferred_when_both_power_channels_exist() -> None:
    session = _straight_session(power_channel=ACCELERATOR_PCT)
    t = session.channel(ACCELERATOR_PCT).timestamps
    throttle = np.full_like(t, 100.0)
    session.channels[THROTTLE_PCT] = _channel(THROTTLE_PCT, t, throttle, "%")

    lap = lap_summary(session, 1)
    section = section_metrics(session, 1, 0.0, 1.0)

    assert lap["control_source"] == THROTTLE_PCT
    assert lap["full_control_fraction"] == 1.0
    assert lap["full_throttle_fraction"] == 1.0
    assert "full_accelerator_fraction" not in lap
    assert section["control_source"] == THROTTLE_PCT
    assert "entry_throttle_pct" in section
    assert "entry_accelerator_pct" not in section


def test_braking_separates_peak_and_sustained_decel() -> None:
    t = np.arange(0.0, 10.0, 0.02)
    long_g = np.zeros_like(t)
    active = (t >= 2.0) & (t <= 3.2)
    long_g[active] = -0.9
    pressure = np.zeros_like(t)
    ramp = (t >= 2.0) & (t < 2.2)
    pressure[ramp] = (t[ramp] - 2.0) / 0.2 * 5000.0
    pressure[(t >= 2.2) & (t <= 3.0)] = 5000.0
    speed = np.linspace(130.0, 70.0, len(t))

    session = TelemetrySession(
        session_id="braking",
        source="synthetic",
        laps=[Lap(1, "1", "Timed", 0.0, 9.98, 9.98)],
        channels={
            LONG_G: _channel(LONG_G, t, long_g, "G"),
            BRAKE_PRESSURE_KPA: _channel(BRAKE_PRESSURE_KPA, t, pressure, "kPa"),
            SPEED_KMH: _channel(SPEED_KMH, t, speed, "km/h"),
        },
    )
    result = analyze_braking(session, 1)
    assert result["event_count"] == 1
    assert result["peak_brake_pressure_kpa"] == 5000.0
    assert result["raw_peak_decel_g"] == 0.9
    assert result["sustained_0_5s_decel_g"] > 0.85
    assert result["events"][0]["control_ramp_per_s"] > 0


def _incident_session(power_channel: str = THROTTLE_PCT) -> TelemetrySession:
    t = np.arange(0.0, 10.0, 0.04)
    lat = np.full_like(t, 35.0)
    lon = -119.0 + np.linspace(0.0, 0.01, len(t))
    speed = np.full_like(t, 150.0)
    yaw = np.zeros_like(t)
    yaw[(t >= 2.0) & (t < 4.0)] = 25.0
    yaw[(t >= 4.5) & (t < 6.5)] = -40.0
    steering = np.zeros_like(t)
    steering[(t >= 2.4) & (t < 4.2)] = -30.0
    power = np.full_like(t, 100.0)
    power[t >= 2.8] = 40.0
    brake = np.zeros_like(t)
    brake[t >= 4.8] = 500.0

    return TelemetrySession(
        session_id="incident",
        source="synthetic",
        channels={
            GPS_LATITUDE_DEG: _channel(GPS_LATITUDE_DEG, t, lat, "deg"),
            GPS_LONGITUDE_DEG: _channel(GPS_LONGITUDE_DEG, t, lon, "deg"),
            SPEED_KMH: _channel(SPEED_KMH, t, speed, "km/h"),
            YAW_RATE_DPS: _channel(YAW_RATE_DPS, t, yaw, "deg/s"),
            STEERING_DEG: _channel(STEERING_DEG, t, steering, "deg"),
            power_channel: _channel(power_channel, t, power, "%"),
            BRAKE_PRESSURE_KPA: _channel(BRAKE_PRESSURE_KPA, t, brake, "kPa"),
        },
    )


def test_incident_detects_recovery_and_snap_back() -> None:
    result = analyze_incident(
        _incident_session(),
        1.0,
        8.0,
        anchor_s=1.2,
        surface_change_s=5.0,
    )
    types = [event["type"] for event in result["timeline"]]
    assert result["control_source"] == THROTTLE_PCT
    assert "yaw_excursion_onset" in types
    assert "opposite_steering_sign_onset" in types
    assert "initial_yaw_arrested" in types
    assert "snap_back" in types
    assert "throttle_reduction" in types
    assert "brake_onset" in types
    assert "surface_change_user_marked" in types


def test_incident_accelerator_fallback_remains_semantically_distinct() -> None:
    result = analyze_incident(
        _incident_session(ACCELERATOR_PCT),
        1.0,
        8.0,
        anchor_s=1.2,
        include_samples=True,
    )
    types = [event["type"] for event in result["timeline"]]
    assert result["control_source"] == ACCELERATOR_PCT
    assert "accelerator_reduction" in types
    assert "throttle_reduction" not in types
    assert "accelerator_pct" in result["samples"][0]
    assert "throttle_pct" not in result["samples"][0]
    assert "control_pct" in result["samples"][0]
