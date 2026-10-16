"""Recorded control measurements for a passage; causal interpretation belongs to the host."""
import numpy as np

from .braking import analyze_braking


def summarize_inputs(session, lap_number, passage, progress, elapsed, lap_start):
    """Reuse brake events and quantify raw controls without inventing a driver intention."""
    start, end = passage["start_s"], passage["end_s"]
    summary = {"window_s": [start, end], "controls": {},
               "thresholds": {"brake_pressure_kpa": 100., "brake_position_pct": 3.,
                              "minimum_brake_event_s": .15, "high_pedal_pct": 90.},
               "limitations": ["Window extrema and threshold crossings are not corner apexes or driver intent.",
                               "Boundary values are first/last recorded finite samples, not exact boundary estimates.",
                               "Peak steering angle does not measure understeer or steering corrections."]}
    speed = passage["controls"].get("speed_kmh", {}).get("samples", [])
    finite_speed = [s for s in speed if s["value"] is not None]
    minimum = min(finite_speed, key=lambda s: s["value"]) if finite_speed else None
    summary["context_minimum_speed"] = minimum
    for name, control in passage["controls"].items():
        samples = control["samples"]
        finite = [s for s in samples if s["value"] is not None]
        if not finite:
            summary["controls"][name] = {"unavailable_reason": "No finite recorded samples"}
            continue
        peak = max(finite, key=lambda s: abs(s["value"]))
        stats = {"first_sample_value": finite[0]["value"], "last_sample_value": finite[-1]["value"],
                 "minimum": min(s["value"] for s in finite), "maximum": max(s["value"] for s in finite),
                 "peak_absolute": peak, "source": control["source"],
                 "native_sample_rate_hz": control["native_sample_rate_hz"]}
        core = [s for s in finite if passage["core_start_s"] <= s["time_s"] <= passage["core_end_s"]]
        stats["core_samples"] = ({"first": core[0], "last": core[-1],
                                  "minimum": min(s["value"] for s in core),
                                  "maximum": max(s["value"] for s in core)} if core else None)
        if name in ("accelerator_pct", "throttle_pct") and minimum:
            after = [s for s in finite if s["time_s"] >= minimum["time_s"]]
            stats["at_least_90_after_minimum"] = next((s for s in after if s["value"] >= 90), None)
            stats["first_sample_after_minimum"] = after[0] if after else None
            # Count only intervals whose two endpoints are valid and close in time.
            high = valid = 0.
            for a, b in zip(samples, samples[1:]):
                dt = b["time_s"] - a["time_s"]
                if a["value"] is not None and b["value"] is not None and 0 < dt <= .25:
                    valid += dt
                    if a["value"] >= 90 and b["value"] >= 90:
                        high += dt
            stats["at_least_90_duration_s"] = high
            stats["valid_interval_duration_s"] = valid
        summary["controls"][name] = stats
    try:
        events = analyze_braking(session, lap_number)["events"]
        summary["brake_events"] = []
        for event in events:
            if event["end_s"] < start or event["start_s"] > end:
                continue
            event = dict(event)
            event["clipped_by_context"] = event["start_s"] < start or event["end_s"] > end
            pedal = passage["controls"].get("accelerator_pct", {}).get("samples", [])
            event["first_recorded_pedal_90_after_end"] = next((s for s in pedal
                if s["time_s"] >= event["end_s"] and s["value"] is not None and s["value"] >= 90), None)
            for name in ("start_s", "end_s", "peak_control_time_s"):
                if event[name] is not None:
                    event[name.replace("_s", "_progress")] = float(
                        np.interp(event[name] - lap_start, elapsed, progress))
            summary["brake_events"].append(event)
    except (KeyError, ValueError) as error:
        summary["brake_events_unavailable_reason"] = str(error)
    return summary
