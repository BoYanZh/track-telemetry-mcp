"""Independent, whole-route screening of externally recorded local passages.

GPS matches establish local observational scope only, never full-layout identity.
Every baseline sector is visited, independently of own-lap opportunity selection.
"""
from __future__ import annotations

import numpy as np

from .alignment import _gps_trace
from .braking import analyze_braking
from .geometry import cumulative_distance_m, latlon_to_xy_m


def _project_passage(points, times, base, distance, *, margin=5., max_offset=15.):
    """Find one continuous forward passage, rejecting jumps and ambiguous repeats."""
    vector = np.diff(base, axis=0)
    lengths = np.sum(vector * vector, axis=1)
    valid_segments = lengths > .0001
    if not np.any(valid_segments):
        raise ValueError("No finite reference segments")
    starts = base[:-1][valid_segments]
    vectors = vector[valid_segments]
    lens = lengths[valid_segments]
    ds = distance[:-1][valid_segments]
    segment_lengths = np.sqrt(lens)
    positions, offsets = [], []
    for chunk in np.array_split(points, max(1, len(points) // 128)):
        frac = np.clip(np.sum((chunk[:, None] - starts) * vectors, axis=2) / lens, 0, 1)
        residual = np.linalg.norm(chunk[:, None] - starts - frac[:, :, None] * vectors, axis=2)
        idx = residual.argmin(axis=1)
        row = np.arange(len(chunk))
        positions.extend(ds[idx] + frac[row, idx] * segment_lengths[idx])
        offsets.extend(residual[row, idx])
    pos, off = np.array(positions), np.array(offsets)
    use = np.flatnonzero((off <= max_offset) & (pos > .1) & (pos < distance[-1] - .1))
    groups = np.split(use, np.flatnonzero(np.diff(times[use]) > .5) + 1) if len(use) else []
    accepted = []
    for indices in groups:
        if len(indices) < 8:
            continue
        s, t = pos[indices], times[indices]
        if np.any(np.diff(t) <= 0) or np.any(np.diff(s) < -3):
            continue
        forward = np.r_[True, np.diff(np.maximum.accumulate(s)) > .05]
        s, t = s[forward], t[forward]
        if len(s) < 8 or s[0] > margin or s[-1] < distance[-1] - margin:
            continue
        if np.any(np.diff(t) > .5):
            continue
        accepted.append((s, t, float(np.quantile(off[indices], .95))))
    if len(accepted) != 1:
        raise ValueError("No unique continuous forward passage covering physical endpoints")
    return accepted[0]


def _signals(session, times):
    result = {}
    for name in ("speed_kmh", "brake_pressure_kpa", "steering_deg", "lat_g", "long_g",
                 "accelerator_pct", "throttle_pct"):
        ch = session.optional_channel(name)
        if ch is None:
            continue
        values = ch.interp(times)
        if not np.all(np.isfinite(values)):
            continue
        if name == "brake_pressure_kpa":
            if ch.units == "bar":
                values = values * 100
            elif ch.units != "kPa":
                continue
        if name in {"lat_g", "long_g"} and ch.units.lower() != "g":
            continue
        if name in {"accelerator_pct", "throttle_pct"}:
            semantics = session.metadata.get("control_semantics", {}).get(name)
            if semantics == "unverified" or (
                    str(session.metadata.get("source_format", "")).startswith("AiM") and
                    semantics not in {"accelerator_pedal", "throttle_body"}):
                continue
        result[name] = values.tolist()
    if "lat_g" in result and "long_g" in result:
        result["combined_g"] = np.hypot(result["lat_g"], result["long_g"]).tolist()
    return result



def _brake_events(session, lap_number):
    pressure = session.optional_channel("brake_pressure_kpa")
    if pressure is None or pressure.units != "kPa":
        return []
    try:
        return analyze_braking(session, lap_number)["events"]
    except (KeyError, ValueError):
        return []


def _linked_end(grid, driver_times, reference_times, core_end, driver_events, reference_events):
    endpoints = []
    for times, events in ((driver_times, driver_events), (reference_times, reference_events)):
        target_end_time = float(np.interp(core_end, grid, times))
        following = next((event for event in events if event["start_s"] > target_end_time), None)
        if following and following["start_s"] <= times[-1]:
            # Stop before the first recorded onset in either passage.
            endpoint = float(np.interp(following["start_s"] - .05, times, grid))
            endpoints.append(max(core_end, endpoint))
    return min(endpoints) if endpoints else float(grid[-1]), bool(endpoints)

def scan_external_references(driver, lap_number, references, *, sectors=20):
    """Rank observed external differences; leave practice selection to the agent."""
    lap = driver.lap(lap_number)
    t, lat, lon, _ = _gps_trace(driver, lap)
    origin = {"origin_lat_deg": float(np.median(lat)), "origin_lon_deg": float(np.median(lon))}
    x, y = latlon_to_xy_m(lat, lon, **origin)
    xy = np.c_[x, y]
    distance = cumulative_distance_m(x, y)
    traces, exclusions = [], []
    inventory = []
    for index, session in enumerate(references):
        inventory.append({"index": index, "summary": session.to_summary(), "metadata": session.metadata})
        for other in session.laps:
            if not other.is_timed or not np.isfinite(other.duration_s) or other.duration_s <= 0:
                continue
            try:
                et, elat, elon, _ = _gps_trace(session, other)
                ex, ey = latlon_to_xy_m(elat, elon, **origin)
                traces.append((index, session, other, et, np.c_[ex, ey]))
            except ValueError as exc:
                exclusions.append({"reference": index, "lap": other.number, "reason": str(exc)})
    driver_events = _brake_events(driver, lap_number)
    event_cache = {(i, other.number): _brake_events(session, other.number)
                   for i, session, other, _, _ in traces}
    windows = []
    for sector in range(sectors):
        lo, hi = sector / sectors, (sector + 1) / sectors
        # Linked context is clamped at the lap boundaries; never invent cross-lap continuity.
        mask = (distance >= max(0, lo - 1 / sectors) * distance[-1]) & (
            distance <= min(1, hi + 1 / sectors) * distance[-1])
        idx = np.flatnonzero(mask)
        base, bd = xy[idx], distance[idx] - distance[idx[0]]
        if len(idx) < 8 or bd[-1] < 30:
            windows.append({"id": f"external-{sector+1:02}", "sector": sector+1,
                            "unavailable_reason": "Insufficient baseline GPS coverage"})
            continue
        grid = np.linspace(6, bd[-1] - 6, 121)
        bt = np.interp(grid, bd, t[idx])
        core = np.clip(np.array([lo, hi]) * distance[-1] - distance[idx[0]], grid[0], grid[-1])
        limits = np.unique([grid[0], *core, grid[-1]])
        baseline = _signals(driver, bt)
        if "speed_kmh" not in baseline:
            windows.append({"id": f"external-{sector+1:02}", "sector": sector+1,
                            "unavailable_reason": "Missing finite baseline speed"})
            continue
        passages, rejected = [], []
        for index, session, other, et, points in traces:
            try:
                pos, times, error = _project_passage(points, et, base, bd)
                rt = np.interp(grid, pos, times)
                measured = _signals(session, rt)
                if "speed_kmh" not in measured:
                    raise ValueError("Missing finite speed data")
                delta = (bt - bt[0]) - (rt - rt[0])
                linked_end, brake_bounded = _linked_end(grid, bt, rt, core[1], driver_events,
                                                        event_cache[index, other.number])
                limits = np.unique([grid[0], *core, linked_end])
                stages = np.diff(np.interp(limits, grid, delta))
                core_delta = float(np.interp(core[1], grid, delta) - np.interp(core[0], grid, delta))
                rx, ry = latlon_to_xy_m(session.channel("gps_latitude_deg").interp(rt),
                                        session.channel("gps_longitude_deg").interp(rt), **origin)
                core_mask = (grid >= core[0]) & (grid <= core[1])
                markers = []
                for g in np.unique([grid[0], core[0], (core[0]+core[1])/2, core[1], linked_end]):
                    markers.append({"distance_m": float(g),
                        "driver_time_s": float(np.interp(g, grid, bt)),
                        "reference_time_s": float(np.interp(g, grid, rt)),
                        "delta_s": float(np.interp(g, grid, delta)),
                        "driver": {k: float(np.interp(g, grid, v)) for k, v in baseline.items()},
                        "reference": {k: float(np.interp(g, grid, v)) for k, v in measured.items()}})
                for marker in markers:
                    for who in ("driver", "reference"):
                        v = marker[who]
                        if "lat_g" in v and "long_g" in v:
                            v["combined_g"] = float(np.hypot(v["lat_g"], v["long_g"]))
                passages.append({"reference": index, "lap": other.number, "reference_lap_duration_s": other.duration_s,
                    "core_difference_s": core_delta,
                    "linked_difference_s": float(np.interp(linked_end, grid, delta)),
                    "linked_end_m": linked_end,
                    "linked_end_reason": "before_next_braking" if brake_bounded else "screening_boundary_fallback",
                    "upstream_difference_s": float(np.interp(core[0], grid, delta)),
                    "target_difference_s": core_delta,
                    "downstream_difference_s": float(np.interp(linked_end, grid, delta)-np.interp(core[1], grid, delta)),
                    "target_entry_brake_kpa": {"driver": float(np.interp(core[0], grid, baseline["brake_pressure_kpa"])) if "brake_pressure_kpa" in baseline else None,
                                                "reference": float(np.interp(core[0], grid, measured["brake_pressure_kpa"])) if "brake_pressure_kpa" in measured else None},
                    "stage_differences_s": stages.tolist(), "stage_boundaries_m": limits.tolist(),
                    "entry_speed_kmh": measured["speed_kmh"][0],
                    "exit_speed_kmh": float(np.interp(linked_end, grid, measured["speed_kmh"])),
                    "source_times_s": rt.tolist(), "signals": measured,
                    "delta_s": delta.tolist(), "p95_cross_track_m": error,
                    "core_min_speed_kmh": float(np.min(np.array(measured["speed_kmh"])[core_mask])),
                    "reference_route_xy": np.c_[rx, ry].tolist(), "markers": markers})
            except ValueError as exc:
                rejected.append({"reference": index, "lap": other.number, "reason": str(exc)})
        passages.sort(key=lambda p: p["core_difference_s"], reverse=True)
        windows.append({"id": f"external-{sector+1:02}", "sector": sector+1,
            "start_progress": lo, "end_progress": hi, "grid_m": grid.tolist(),
            "baseline_times_s": bt.tolist(), "baseline_signals": baseline,
            "core_limits_m": core.tolist(),
            "baseline_core_min_speed_kmh": float(np.min(np.array(baseline["speed_kmh"])[
                (grid >= core[0]) & (grid <= core[1])])),
            "baseline_entry_speed_kmh": baseline["speed_kmh"][0],
            "baseline_exit_speed_kmh": baseline["speed_kmh"][-1],
            "passages": passages, "excluded_passages": rejected,
            "best_core_difference_s": passages[0]["core_difference_s"] if passages else None,
            "positive_passages": sum(p["core_difference_s"] > 0 for p in passages),
            "route_xy": base.tolist(),
            "driver_route_xy": np.c_[
                np.interp(bt, t, x), np.interp(bt, t, y)].tolist()})
    ranked = sorted((w for w in windows if w.get("best_core_difference_s") is not None),
                    key=lambda w: w["best_core_difference_s"], reverse=True)
    # A descriptive review trigger, not an estimate of driving risk or available grip.
    fast_ids = [w["id"] for w in ranked if w["baseline_core_min_speed_kmh"] >= 120
                and w["best_core_difference_s"] >= .2]
    required = list(dict.fromkeys([w["id"] for w in ranked[:5]] + fast_ids))
    result = {"scope": "individually GPS-matched local windows; full-layout identity unconfirmed",
            "baseline_lap": lap_number, "references": inventory, "windows": windows,
            "observed_difference_ranking": [w["id"] for w in ranked],
            "practice_ranking": [], "practice_selection_status": "awaiting_agent_interpretation",
            "required_review_ids": required, "fast_area_review_ids": fast_ids,
            "fast_review_rule": "Core minimum >=120 km/h and observed core difference >=0.2s; review flag only",
            "excluded_laps": exclusions,
            "limitations": ["Core windows do not overlap; linked context windows do. Do not sum linked differences.",
                "Ranking measures observed differences, not recoverable gains or practice priority.",
                "GPS proximity is local matching evidence, not full-layout confirmation.",
                "Pace, traffic, vehicle, axes and sensor calibration require interpretation."]}
    candidates, focuses = rank_linked_candidates(result)
    result["candidate_ranking"] = [{"id": item["window"]["id"],
        "typical_difference_s": item["typical_difference_s"],
        "reference_passages": item["reference_passages"], "positive_passages": item["positive_passages"],
        "representative_lap": item["representative"]["lap"],
        "repeatable": item["repeatable"], "pace_pool_fallback": item["pace_pool_fallback"]} for item in candidates]
    result["default_focus_ids"] = [item["window"]["id"] for item in focuses]
    return result


def rank_linked_candidates(scan):
    """Rank repeatable linked differences on comparable reference pace, without manual favorites."""
    best = {}
    for w in scan["windows"]:
        for p in w.get("passages", []):
            duration = p.get("reference_lap_duration_s")
            if duration is not None:
                best[p["reference"]] = min(best.get(p["reference"], duration), duration)
    items = []
    for w in scan["windows"]:
        pool = [p for p in w.get("passages", []) if p.get("reference_lap_duration_s") is None or
                p["reference_lap_duration_s"] <= best[p["reference"]] + max(1., best[p["reference"]]*.02)]
        fallback = not pool
        if fallback:
            pool = w.get("passages", [])
        if not pool:
            continue
        typical = float(np.median([p["linked_difference_s"] for p in pool]))
        positive = sum(p["core_difference_s"] > 0 and p["linked_difference_s"] > 0 for p in pool)
        representative = min(pool, key=lambda p: abs(p["linked_difference_s"]-typical))
        items.append({"window": w, "typical_difference_s": typical,
                      "reference_passages": len(pool), "positive_passages": positive,
                      "repeatable": not fallback and positive >= 2 and positive > len(pool)/2,
                      "pace_pool_fallback": fallback,
                      "representative": representative})
    items.sort(key=lambda item: (item["repeatable"], item["typical_difference_s"]), reverse=True)
    selected = []
    for item in items:
        w = item["window"]
        scale = (w["end_progress"]-w["start_progress"]) / np.ptp(w["core_limits_m"])
        lo = w["start_progress"] + (w["grid_m"][0]-w["core_limits_m"][0])*scale
        hi = w["start_progress"] + (item["representative"].get("linked_end_m", w["grid_m"][-1])-w["core_limits_m"][0])*scale
        item["physical_limits"] = (float(lo), float(hi))
        if len(selected) == 4 or item["typical_difference_s"] <= 0:
            continue
        if any(max(0., min(hi, s["physical_limits"][1])-max(lo, s["physical_limits"][0])) >
               .5*min(hi-lo, s["physical_limits"][1]-s["physical_limits"][0])+1e-9 for s in selected):
            continue
        selected.append(item)
    return items, selected
