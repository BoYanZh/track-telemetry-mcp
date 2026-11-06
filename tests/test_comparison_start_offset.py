from __future__ import annotations

import numpy as np
import pytest

from track_telemetry.channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG, SPEED_KMH
from track_telemetry.laps import compare_laps
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession


def _circular_lap(session_id: str, start_offset_m: float) -> TelemetrySession:
    circumference_m = 5000.0
    duration_s = 100.0
    t = np.linspace(0.0, duration_s, 2501)
    angle = 2 * np.pi * (start_offset_m / circumference_m + t / duration_s)
    radius_m = circumference_m / (2 * np.pi)
    x = radius_m * np.cos(angle)
    y = radius_m * np.sin(angle)
    origin_lat, origin_lon = 35.0, -119.0
    lat = origin_lat + y / 111_195.0
    lon = origin_lon + x / (111_195.0 * np.cos(np.deg2rad(origin_lat)))
    channels = {
        GPS_LATITUDE_DEG: ChannelSeries(GPS_LATITUDE_DEG, "deg", t, lat),
        GPS_LONGITUDE_DEG: ChannelSeries(GPS_LONGITUDE_DEG, "deg", t, lon),
        SPEED_KMH: ChannelSeries(
            SPEED_KMH, "km/h", t, np.full_like(t, circumference_m / duration_s * 3.6)
        ),
    }
    lap = Lap(1, "1", "Timed", 0.0, duration_s, duration_s)
    return TelemetrySession(
        session_id=session_id,
        source="synthetic",
        laps=[lap],
        channels=channels,
    )


@pytest.mark.parametrize(
    ("subject_offset_m", "reference_offset_m"),
    [(65.0, 0.0), (0.0, 65.0)],
)
def test_compare_laps_rejects_65m_lap_start_offset(
    subject_offset_m: float,
    reference_offset_m: float,
) -> None:
    subject = _circular_lap("subject", subject_offset_m)
    reference = _circular_lap("reference", reference_offset_m)

    with pytest.raises(ValueError, match="timing boundaries"):
        compare_laps(subject, 1, reference, 1, same_layout_confirmed=True)


def test_compare_laps_accepts_matched_lap_start_boundaries() -> None:
    subject = _circular_lap("subject", 0.0)
    reference = _circular_lap("reference", 0.0)

    result = compare_laps(subject, 1, reference, 1, same_layout_confirmed=True)

    assert result["lap_a_minus_b_total_s"] == pytest.approx(0.0)
    assert result["alignment_quality"]["p95_lateral_deviation_m"] < 0.01
    assert all(sector["a_minus_b_s"] == pytest.approx(0.0) for sector in result["mini_sectors"])
