"""Helpers for selecting semantically distinct driver/power control channels."""

from __future__ import annotations

import numpy as np

from .channels import ACCELERATOR_PCT, THROTTLE_PCT
from .models import ChannelSeries, TelemetrySession


def _usable(
    channel: ChannelSeries | None,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
) -> bool:
    if channel is None or len(channel.timestamps) == 0:
        return False
    valid = np.isfinite(channel.timestamps) & np.isfinite(channel.values)
    if start_s is not None:
        valid &= channel.timestamps >= float(start_s)
    if end_s is not None:
        valid &= channel.timestamps <= float(end_s)
    return bool(np.any(valid))


def select_power_control(
    session: TelemetrySession,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
) -> tuple[str | None, ChannelSeries | None]:
    """Return the best usable power-control channel and its explicit source.

    ``throttle_pct`` is preferred when it has finite samples in the requested time
    window because it represents throttle-body position in sources that expose it.
    ``accelerator_pct`` is a fallback representing accelerator pedal position. The two
    are intentionally not relabeled as each other. Empty/all-NaN/out-of-window throttle
    data does not block accelerator fallback.
    """
    throttle = session.optional_channel(THROTTLE_PCT)
    if _usable(throttle, start_s=start_s, end_s=end_s):
        return THROTTLE_PCT, throttle

    accelerator = session.optional_channel(ACCELERATOR_PCT)
    if _usable(accelerator, start_s=start_s, end_s=end_s):
        return ACCELERATOR_PCT, accelerator

    return None, None
