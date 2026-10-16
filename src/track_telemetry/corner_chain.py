"""Provisional action windows on a shared physical grid, not official corner detection."""
import numpy as np

from .braking import analyze_braking
from .quality import channel_source, measured_source, native_rate


def select_chain_window(sessions, observation, results):
    """Trace a loss upstream to braking and downstream to the next recorded braking zone."""
    core = observation["physical_section_profile"]
    start, end = core[0]["progress"], core[-1]["progress"]
    fallback = max(0., start - .05), min(1., end + .05)
    donor = observation.get("section_reference", {})
    keys = [(observation.get("example_session"), observation.get("example_lap")),
            (donor.get("session"), donor.get("lap"))]
    anchors = []
    for key in keys:
        if key not in results:
            continue
        session, number = sessions[key[0]], key[1]
        lap = session.lap(number)
        profile = results[key]["profile"]
        progress = np.array([p["progress"] for p in profile])
        elapsed = np.array([p["lap_a_elapsed_s"] for p in profile])
        core_start, core_end = lap.start_s + np.interp([start, end], progress, elapsed)
        try:
            events = analyze_braking(session, number)["events"]
            events = [e for e in events if measured_source(channel_source(session, e["control_channel"], number))
                      and (native_rate(session, e["control_channel"], number) is None
                           or native_rate(session, e["control_channel"], number) >= 5)]
            inside = [e for e in events if core_start <= e["start_s"] < core_end]
            previous = [e for e in events if e["start_s"] < core_start]
            pedal = session.optional_channel("accelerator_pct")
            at_entry = pedal.slice(core_start, core_start + .15) if pedal is not None else None
            power_on_entry = at_entry is not None and len(at_entry.values) and np.all(at_entry.values >= 90)
            event = inside[0] if inside and power_on_entry else previous[-1] if previous else inside[0] if inside else None
            if event is None or event["start_s"] <= lap.start_s or event["end_s"] >= lap.end_s:
                continue
            beginning = float(np.interp(max(lap.start_s, event["start_s"] - .5) - lap.start_s, elapsed, progress))
            following = next((e for e in events if e["start_s"] > core_end), None)
            finish = float(np.interp(following["start_s"] - lap.start_s, elapsed, progress)) if following else 1.
            anchors.append({"session": key[0], "lap": number, "start_progress": beginning,
                            "brake_start_progress": float(np.interp(event["start_s"] - lap.start_s, elapsed, progress)),
                            "brake_end_progress": float(np.interp(event["end_s"] - lap.start_s, elapsed, progress)),
                            "end_progress": finish, "brake_start_s": event["start_s"],
                            "end_reason": "next_braking_onset" if following else "lap_boundary_no_next_brake"})
        except (KeyError, ValueError):
            continue
    if not anchors:
        return {"start_progress": fallback[0], "end_progress": fallback[1], "method": "fixed_context_fallback",
                "anchors": [], "limitation": "Verified bounded brake events unavailable; causative corner unresolved."}
    return {"start_progress": min(start, *(a["start_progress"] for a in anchors)),
            "end_progress": max(end, min(a["end_progress"] for a in anchors)),
            "method": "braking_to_next_braking", "anchors": anchors,
            "upstream_events_overlap_on_reference": (len(anchors) == 2 and
                max(a["brake_start_progress"] for a in anchors) <= min(a["brake_end_progress"] for a in anchors)),
            "limitation": "Heuristic action window; not an identified corner or proof that downstream travel is straight. No lap wrapping."}
