"""Helpers for selecting semantically distinct driver/power control channels."""

from __future__ import annotations

import numpy as np

from .channels import ACCELERATOR_PCT, THROTTLE_PCT
from .models import ChannelSeries, TelemetrySession


def _usable(channel: ChannelSeries | None) -> bool:
    return (
        channel is not None
        and len(channel.timestamps) > 0
        and np.any(np.isfinite(channel.values))
    )


def select_power_control(
    session: TelemetrySession,
) -> tuple[str | None, ChannelSeries | None]:
    """Return the best usable power-control channel and its explicit source.

    ``throttle_pct`` is preferred when it has finite samples because it represents
    throttle-body position in sources that expose it. ``accelerator_pct`` is a fallback
    representing accelerator pedal position. The two are intentionally not relabeled as
    each other. An empty/all-NaN throttle channel does not block accelerator fallback.
    """
    throttle = session.optional_channel(THROTTLE_PCT)
    if _usable(throttle):
        return THROTTLE_PCT, throttle

    accelerator = session.optional_channel(ACCELERATOR_PCT)
    if _usable(accelerator):
        return ACCELERATOR_PCT, accelerator

    return None, None
