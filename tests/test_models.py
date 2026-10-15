"""Regression tests for ChannelSeries timestamp and channel integrity (synthetic only)."""

from __future__ import annotations

import numpy as np
import pytest

from track_telemetry.models import ChannelSeries


def test_rejects_unsorted_timestamps() -> None:
    with pytest.raises(ValueError, match="must be sorted"):
        ChannelSeries("speed_kmh", "km/h", [0.0, 0.5, 0.4], [1.0, 2.0, 3.0])


def test_rejects_timestamp_value_length_mismatch() -> None:
    with pytest.raises(ValueError, match="lengths differ"):
        ChannelSeries("speed_kmh", "km/h", [0.0, 1.0], [1.0])


def test_slice_preserves_inclusive_window() -> None:
    series = ChannelSeries("speed_kmh", "km/h",
                           [0.0, 1.0, 2.0, 3.0], [10.0, 20.0, 30.0, 40.0])

    window = series.slice(1.0, 2.0)

    np.testing.assert_array_equal(window.timestamps, [1.0, 2.0])
    np.testing.assert_array_equal(window.values, [20.0, 30.0])
    assert window.units == "km/h"


def test_interp_returns_nan_outside_source_range() -> None:
    series = ChannelSeries("speed_kmh", "km/h", [1.0, 2.0, 3.0], [10.0, 20.0, 30.0])

    result = series.interp(np.array([0.0, 1.5, 4.0]))

    assert np.isnan(result[0])
    assert result[1] == pytest.approx(15.0)
    assert np.isnan(result[2])


def test_interp_ignores_non_finite_source_samples() -> None:
    series = ChannelSeries("speed_kmh", "km/h",
                           [0.0, 1.0, np.nan, 3.0], [10.0, np.nan, 25.0, 40.0])

    result = series.interp(np.array([0.5, 2.0]))

    assert result[0] == pytest.approx(10.0 + (40.0 - 10.0) * 0.5 / 3.0)
    assert result[1] == pytest.approx(10.0 + (40.0 - 10.0) * 2.0 / 3.0)


def test_interp_single_sample_broadcasts_constant() -> None:
    series = ChannelSeries("speed_kmh", "km/h", [1.0], [88.0])

    result = series.interp(np.array([0.0, 1.0, 5.0]))

    np.testing.assert_array_equal(result, [88.0, 88.0, 88.0])


def test_sample_rate_reflects_median_interval() -> None:
    series = ChannelSeries("speed_kmh", "km/h",
                           [0.0, 0.04, 0.08, 0.12], [1.0, 2.0, 3.0, 4.0])

    assert series.sample_rate_hz == pytest.approx(25.0, rel=0.01)


def test_sample_rate_is_none_without_positive_intervals() -> None:
    assert ChannelSeries("x", "", [1.0], [2.0]).sample_rate_hz is None
    assert ChannelSeries("x", "", [], []).sample_rate_hz is None
