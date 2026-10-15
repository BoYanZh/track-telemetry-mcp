"""Synthetic measurements with known values and explicit failure boundaries."""

import json

import numpy as np
import pytest

from track_telemetry.gg import analyze_gg_usage
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession
from track_telemetry.quality import matched_window
from track_telemetry.reference import compare_reference_laps


def session(duration=10.0):
    t = np.linspace(0, duration, 501)
    values = {"lat_g": np.full_like(t, 0.6), "long_g": np.full_like(t, -0.8),
              "gps_latitude_deg": np.full_like(t, 35),
              "gps_longitude_deg": -119 + t / duration * 0.01,
              "speed_kmh": np.full_like(t, 100)}
    return TelemetrySession("synthetic", "synthetic", metadata={
        "lateral_accel_source": "imu", "longitudinal_accel_source": "can"},
        laps=[Lap(7, "7", "Timed", 0, duration, duration, original_number=27)],
        channels={k: ChannelSeries(k, "G" if k.endswith("_g") else "", t, v)
                  for k, v in values.items()})


def test_gg_known_vector_and_duration():
    result = analyze_gg_usage(session(), 7)
    assert result["observed_combined_g_p95"] == pytest.approx(1)
    assert result["occupancy_fraction"]["combined_braking_cornering"] == pytest.approx(1)
    assert result["quality"]["coverage_fraction"] == pytest.approx(1)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("failure", ["nan", "gap", "duplicate", "sparse", "source", "units"])
def test_gg_rejects_bad_evidence(failure):
    s = session()
    c = s.channel("lat_g")
    if failure == "nan":
        c.values[50:400] = np.nan
    elif failure == "gap":
        c.timestamps = c.timestamps[[*range(50), *range(400, 501)]]
        c.values = c.values[[*range(50), *range(400, 501)]]
    elif failure == "duplicate":
        c.timestamps[1] = c.timestamps[0]
    elif failure == "sparse":
        c.timestamps, c.values = c.timestamps[::50], c.values[::50]
    elif failure == "source":
        s.metadata["lateral_accel_source"] = "gps_heading_derivative"
    else:
        c.units = "m/s2"
    with pytest.raises(ValueError):
        analyze_gg_usage(s, 7)


def test_reference_delta_and_optional_g_failure():
    a, b = session(11), session(10)
    del b.channels["lat_g"]
    with pytest.raises(ValueError, match="same_layout"):
        compare_reference_laps(a, 7, b, 7)
    result = compare_reference_laps(a, 7, b, 7, same_layout_confirmed=True)
    assert result["lap_a_minus_b_total_s"] == pytest.approx(1)
    assert sum(s["a_minus_b_s"] for s in result["mini_sectors"]) == pytest.approx(1)
    assert "unavailable_reason" in result["gg_usage"]["reference"]
    assert result["lap_a"]["original_number"] == 27
    json.dumps(result, allow_nan=False)


def test_matching_does_not_bridge_missing_points():
    s = session()
    s.channel("lat_g").values[100:105] = np.nan
    _, _, weights, quality = matched_window(s, 7, ("lat_g", "long_g"))
    assert 0 < weights.sum() < 10
    assert quality["coverage_fraction"] < 1


def test_matching_does_not_weight_reused_samples_on_irregular_clocks():
    base = np.arange(0, 9.991, 0.03)
    irregular = np.r_[np.arange(0, 1, 0.05), np.arange(1, 10, 0.02)]
    s = TelemetrySession("irregular", "synthetic",
        laps=[Lap(1, "1", "Timed", 0, 9.99, 9.99)],
        channels={"base": ChannelSeries("base", "", base, base),
                  "irregular": ChannelSeries("irregular", "", irregular, irregular)})
    _, values, weights, quality = matched_window(s, 1, ("base", "irregular"))
    assert np.all(np.diff(values[:, 1])[weights > 0] > 0)
    assert quality["coverage_fraction"] >= 0.8
