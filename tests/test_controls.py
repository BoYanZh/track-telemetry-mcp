from __future__ import annotations

import numpy as np

from track_telemetry.channels import ACCELERATOR_PCT, THROTTLE_PCT
from track_telemetry.controls import select_power_control
from track_telemetry.models import ChannelSeries, TelemetrySession


def _channel(name: str, timestamps, values) -> ChannelSeries:
    return ChannelSeries(name, "%", np.asarray(timestamps), np.asarray(values))


def test_empty_throttle_does_not_block_accelerator_fallback() -> None:
    session = TelemetrySession(
        session_id="fallback-empty",
        source="synthetic",
        channels={
            THROTTLE_PCT: _channel(THROTTLE_PCT, [], []),
            ACCELERATOR_PCT: _channel(ACCELERATOR_PCT, [0.0, 1.0], [10.0, 90.0]),
        },
    )
    source, channel = select_power_control(session)
    assert source == ACCELERATOR_PCT
    assert channel is session.channels[ACCELERATOR_PCT]


def test_all_nan_throttle_does_not_block_accelerator_fallback() -> None:
    session = TelemetrySession(
        session_id="fallback-nan",
        source="synthetic",
        channels={
            THROTTLE_PCT: _channel(THROTTLE_PCT, [0.0, 1.0], [np.nan, np.nan]),
            ACCELERATOR_PCT: _channel(ACCELERATOR_PCT, [0.0, 1.0], [20.0, 100.0]),
        },
    )
    source, channel = select_power_control(session)
    assert source == ACCELERATOR_PCT
    assert channel is session.channels[ACCELERATOR_PCT]
