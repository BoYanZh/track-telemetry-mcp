"""Quantitative reference comparison built on the existing physical GPS alignment."""

from __future__ import annotations

from .gg import analyze_gg_usage
from .laps import compare_laps
from .models import TelemetrySession


def compare_reference_laps(
    driver: TelemetrySession, driver_lap: int, reference: TelemetrySession, reference_lap: int,
    *, same_layout_confirmed: bool = False, mini_sectors: int = 20,
) -> dict:
    result = compare_laps(driver, driver_lap, reference, reference_lap,
                          same_layout_confirmed=same_layout_confirmed,
                          mini_sectors=mini_sectors, include_profile=True)
    result["sign_convention"] = "Positive delta means driver slower than reference."
    result["largest_loss_sectors"] = sorted(
        (s for s in result["mini_sectors"] if s["a_minus_b_s"] > 0),
        key=lambda s: s["a_minus_b_s"], reverse=True,
    )[:3]
    result["gg_usage"] = {}
    for label, session, number in (("driver", driver, driver_lap), ("reference", reference, reference_lap)):
        try:
            result["gg_usage"][label] = analyze_gg_usage(session, number)
        except (KeyError, ValueError) as exc:
            result["gg_usage"][label] = {"unavailable_reason": str(exc)}
    result["limitations"] = [
        "Vehicle, tires, weather, traffic and sensor calibration comparability require external confirmation.",
        "Time losses are measured differences, not guaranteed gains or proof of driver causation.",
    ]
    return result
