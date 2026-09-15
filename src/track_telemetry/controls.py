"""Helpers for selecting semantically distinct driver/power control channels."""

from __future__ import annotations

from .channels import ACCELERATOR_PCT, THROTTLE_PCT
from .models import ChannelSeries, TelemetrySession


def select_power_control(
    session: TelemetrySession,
) -> tuple[str | None, ChannelSeries | None]:
    """Return the best available power-control channel and its explicit source.

    ``throttle_pct`` is preferred when present because it represents throttle-body
    position in sources that expose it. ``accelerator_pct`` is a fallback representing
    accelerator pedal position. The two are intentionally not relabeled as each other.
    """
    throttle = session.optional_channel(THROTTLE_PCT)
    if throttle is not None:
        return THROTTLE_PCT, throttle

    accelerator = session.optional_channel(ACCELERATOR_PCT)
    if accelerator is not None:
        return ACCELERATOR_PCT, accelerator

    return None, None
