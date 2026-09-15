from __future__ import annotations

import numpy as np
import pytest

from track_telemetry.channels import (
    GPS_HEADING_DEG,
    GPS_LATITUDE_DEG,
    GPS_LONGITUDE_DEG,
    SPEED_KMH,
    YAW_RATE_DPS,
)
from track_telemetry.models import ChannelSeries, TelemetrySession
from track_telemetry.slip_angle import analyze_slip_angle


def _channel(name: str, t: np.ndarray, values: np.ndarray, units: str) -> ChannelSeries:
    return ChannelSeries(name, units, t, values)


def _session(*, yaw_source: str, yaw_rate_dps: float = 10.0) -> TelemetrySession:
    t = np.linspace(0.0, 1.0, 26)
    lat = np.full_like(t, 35.0)
    lon = -119.0 + np.linspace(0.0, 0.0003, len(t))
    return TelemetrySession(
        session_id="slip-angle-synthetic",
        source="synthetic",
        metadata={"yaw_rate_source": yaw_source},
        channels={
            GPS_LATITUDE_DEG: _channel(GPS_LATITUDE_DEG, t, lat, "deg"),
            GPS_LONGITUDE_DEG: _channel(GPS_LONGITUDE_DEG, t, lon, "deg"),
            GPS_HEADING_DEG: _channel(
                GPS_HEADING_DEG, t, np.full_like(t, 90.0), "deg"
            ),
            SPEED_KMH: _channel(SPEED_KMH, t, np.full_like(t, 100.0), "km/h"),
            YAW_RATE_DPS: _channel(
                YAW_RATE_DPS, t, np.full_like(t, yaw_rate_dps), "deg/s"
            ),
        },
    )


def test_slip_angle_proxy_uses_course_minus_integrated_body_heading() -> None:
    result = analyze_slip_angle(
        _session(yaw_source="rcz_gyro_3_302"),
        0.0,
        1.0,
        anchor_s=0.0,
        include_samples=True,
        sample_stride=1,
    )

    assert result["sources"]["travel_heading"] == "gps_bearing_channel"
    assert result["sources"]["yaw_rate"] == "rcz_gyro_3_302"
    assert result["summary"]["max_abs_slip_angle_proxy_deg"] == pytest.approx(10.0, abs=0.15)
    assert result["samples"][-1]["slip_angle_proxy_deg"] == pytest.approx(-10.0, abs=0.15)


def test_slip_angle_rejects_yaw_derived_from_same_gps_course() -> None:
    with pytest.raises(ValueError, match="independent of GPS course"):
        analyze_slip_angle(
            _session(yaw_source="gps_heading_derivative"),
            0.0,
            1.0,
            anchor_s=0.0,
        )


def test_slip_angle_masks_low_speed_course_heading() -> None:
    session = _session(yaw_source="rcz_can_12_100_pid_51")
    speed = session.channels[SPEED_KMH]
    speed.values[:] = 5.0

    result = analyze_slip_angle(
        session,
        0.0,
        1.0,
        anchor_s=0.0,
        include_samples=True,
        sample_stride=1,
    )

    assert result["summary"]["max_abs_slip_angle_proxy_deg"] is None
    assert all(row["slip_angle_proxy_deg"] is None for row in result["samples"])
