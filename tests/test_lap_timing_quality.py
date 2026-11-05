import numpy as np

from track_telemetry.laps import fastest_timed_lap, lap_timing_quality
from track_telemetry.mcp_server import _prepare_session_data
from track_telemetry.models import Lap, TelemetrySession


def _session(durations):
    return TelemetrySession("timing", "timing.xrk", laps=[
        Lap(i, str(i), "Timed", 0, duration, duration)
        for i, duration in enumerate(durations, 1)
    ])


def test_long_timed_laps_are_visible_without_relabelling_or_exclusion():
    session = _session([150, 151, 149, 278, 328])
    original = list(session.laps)
    result = _prepare_session_data(session)
    quality = result["lap_timing_quality"]
    assert [warning["lap_number"] for warning in quality["warnings"]] == [4, 5]
    assert quality["median_timed_duration_s"] == 151
    assert quality["long_lap_threshold_s"] == 226.5
    assert result["fastest_timed_lap_number"] == 3
    assert result["timed_lap_numbers"] == [1, 2, 3, 4, 5]
    assert session.laps == original


def test_invalid_durations_cannot_be_personal_bests():
    session = _session([-1, 0, np.nan, np.inf, 150])
    assert fastest_timed_lap(session).number == 5
    warnings = lap_timing_quality(session)["warnings"]
    assert len(warnings) == 4
    assert {warning["reason"] for warning in warnings} == {"invalid_duration"}
    assert warnings[2]["duration_s"] is None
    assert fastest_timed_lap(_session([0, -1, np.nan])) is None


def test_small_sample_does_not_guess_long_lap_threshold():
    quality = lap_timing_quality(_session([150, 328]))
    assert quality["long_lap_threshold_s"] is None
    assert quality["warnings"] == []
    assert lap_timing_quality(_session([]))["warnings"] == []


def test_partial_laps_do_not_set_timing_baseline():
    session = _session([150, 151, 152])
    session.laps.append(Lap(4, "4", "Partial", 0, 900, 900))
    assert lap_timing_quality(session)["median_timed_duration_s"] == 151
