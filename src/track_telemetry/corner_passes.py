"""Measured individual passages around a physical mini-sector, without a synthetic line."""
from __future__ import annotations

import numpy as np

from .channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG, LAT_G, LONG_G
from .corner_chain import select_chain_window
from .corner_inputs import summarize_inputs
from .geometry import latlon_to_xy_m
from .gg import analyze_gg_usage
from .mini_sectors import _speed
from .quality import channel_source, matched_window, native_rate
from .route_geometry import route_geometry_profile


def _geometry(passage, positions):
    rates = [v["native_sample_rate_hz"] for v in passage["gps_provenance"].values()]
    if any(r is None or not np.isfinite(r) or r < 5 for r in rates):
        passage["local_gps_geometry_unavailable_reason"] = "Verified native GPS >=5 Hz required; output rate cannot qualify geometry"
        return []
    return route_geometry_profile(passage["gps_position_samples"], positions, native_rate_hz=min(rates))


def measure_passages(sessions, observation, comparisons, self_result, reference_index, *, mini_sector_analysis=None):
    """Retain all aligned passages and independently gate measured G in each window."""
    results = {(c["session"], c["lap"]): c["result"] for c in comparisons
               if "profile" in c["result"]}
    results[reference_index, self_result["lap_a"]["number"]] = self_result
    core = observation["physical_section_profile"]
    chain = select_chain_window(sessions, observation, results)
    lo, hi = chain["start_progress"], chain["end_progress"]
    ref = sessions[reference_index]
    lap = ref.lap(self_result["lap_a"]["number"])
    lat = ref.channel(GPS_LATITUDE_DEG).slice(lap.start_s, lap.end_s).values
    lon = ref.channel(GPS_LONGITUDE_DEG).slice(lap.start_s, lap.end_s).values
    origin = dict(origin_lat_deg=float(np.nanmedian(lat)), origin_lon_deg=float(np.nanmedian(lon)))
    passages = []
    for (index, number), result in sorted(results.items()):
        session = sessions[index]
        lap = session.lap(number)
        profile = result["profile"]
        progress = np.array([p["progress"] for p in profile])
        elapsed = np.array([p["lap_a_elapsed_s"] for p in profile])
        # Alignment elapsed arithmetic can overshoot the exact lap end by roundoff.
        start, end = np.clip(lap.start_s + np.interp([lo, hi], progress, elapsed), lap.start_s, lap.end_s)
        core_start, core_end = np.clip(lap.start_s + np.interp(
            [core[0]["progress"], core[-1]["progress"]], progress, elapsed), lap.start_s, lap.end_s)
        entry = {"session": index, "lap": number, "start_s": float(start), "end_s": float(end),
                 "core_start_s": float(core_start), "core_end_s": float(core_end),
                 "core_duration_s": float(core_end - core_start), "context_duration_s": float(end - start),
                 "upstream_duration_s": float(core_start - start), "downstream_duration_s": float(end - core_end),
                 "alignment_quality": result.get("alignment_quality", {})}
        entry["chain_speeds_kmh"] = {name: _speed(profile, p) for name, p in
            (("upstream_start", lo), ("target_start", core[0]["progress"]),
             ("target_end", core[-1]["progress"]), ("downstream_end", hi))}
        latitude = session.channel(GPS_LATITUDE_DEG).slice(start, end)
        times = latitude.timestamps
        longitude_series = session.channel(GPS_LONGITUDE_DEG).slice(start, end)
        longitude = np.full(len(times), np.nan)
        if len(longitude_series.timestamps):
            right = np.clip(np.searchsorted(longitude_series.timestamps, times),
                            0, len(longitude_series.timestamps) - 1)
            left = np.maximum(right - 1, 0)
            nearest = np.where(abs(longitude_series.timestamps[left] - times)
                               < abs(longitude_series.timestamps[right] - times), left, right)
            matched = abs(longitude_series.timestamps[nearest] - times) <= .02
            longitude[matched] = longitude_series.values[nearest[matched]]
        x, y = latlon_to_xy_m(latitude.values, longitude, **origin)
        valid = np.isfinite(x) & np.isfinite(y)
        segments = np.cumsum(~valid | np.r_[False, np.diff(times) > .25])
        entry["gps_position_samples"] = [{"time_s": float(t), "progress": float(np.interp(t-lap.start_s, elapsed, progress)),
            "x_m": float(px), "y_m": float(py), "segment_id": int(segment)}
            for t, px, py, good, segment in zip(times, x, y, valid, segments) if good]
        # Split at missing samples or logger gaps; display decimation never bridges either.
        paths, path = [], []
        for i in range(len(times)):
            if not valid[i] or (i and times[i] - times[i - 1] > .25):
                if path:
                    paths.append(path)
                path = []
            if valid[i]:
                path.append([float(x[i]), float(y[i])])
        if path:
            paths.append(path)
        entry["gps_paths"] = [p[::max(1, len(p) // 400)] for p in paths]
        core_paths, path = [], []
        for i in range(len(times)):
            inside = valid[i] and core_start <= times[i] <= core_end
            if not inside or (i and times[i] - times[i - 1] > .25):
                if path:
                    core_paths.append(path)
                path = []
            if inside:
                path.append([float(x[i]), float(y[i])])
        if path:
            core_paths.append(path)
        entry["gps_core_paths"] = core_paths
        cause_paths, path = [], []
        cause_end = core_start if core_start - start >= 1 else core_end
        for i in range(len(times)):
            inside = valid[i] and times[i] <= cause_end
            if not inside or (i and times[i] - times[i - 1] > .25):
                if path:
                    cause_paths.append(path)
                path = []
            if inside:
                path.append([float(x[i]), float(y[i])])
        if path:
            cause_paths.append(path)
        entry["gps_cause_paths"] = cause_paths
        entry["gps_provenance"] = {name: {"source": channel_source(session, name, number),
            "native_sample_rate_hz": native_rate(session, name, number),
            "output_sample_rate_hz": session.channel(name).sample_rate_hz}
            for name in (GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG)}
        entry["controls"] = {}
        for name in ("speed_kmh", "accelerator_pct", "throttle_pct", "brake_pressure_kpa", "brake_pos_pct", "steering_deg"):
            if name not in session.channels:
                continue
            series = session.channel(name).slice(start, end)
            entry["controls"][name] = {
                "units": series.units, "source": channel_source(session, name, number),
                "native_sample_rate_hz": native_rate(session, name, number),
                "output_sample_rate_hz": series.sample_rate_hz,
                "samples": [{"time_s": float(t), "progress": float(np.interp(t - lap.start_s, elapsed, progress)),
                             "value": float(v) if np.isfinite(v) else None}
                            for t, v in zip(series.timestamps, series.values)]}
        entry["input_analysis"] = summarize_inputs(session, number, entry, progress, elapsed, lap.start_s)
        try:
            entry["core_g_usage"] = analyze_gg_usage(session, number, start_s=core_start, end_s=core_end)
        except (KeyError, ValueError) as error:
            entry["core_g_usage"] = {"unavailable_reason": str(error)}
        try:
            entry["g_usage"] = analyze_gg_usage(session, number, start_s=start, end_s=end)
            t, values, _, _ = matched_window(session, number, (LAT_G, LONG_G), start_s=start, end_s=end)
            entry["g_samples"] = [{"time_s": float(time), "progress": float(np.interp(time - lap.start_s, elapsed, progress)),
                                    "lat_g": float(v[0]), "long_g": float(v[1])}
                                   for time, v in zip(t, values)]
        except (KeyError, ValueError) as error:
            entry["g_usage"] = {"unavailable_reason": str(error)}
            entry["g_samples"] = []
        passages.append(entry)
    timing_check = {}
    positions = np.linspace(lo, hi, 81)
    baseline = next((p for p in passages if (p["session"], p["lap"]) ==
                     (observation.get("example_session"), observation.get("example_lap"))), None)
    donor = observation.get("section_reference", {})
    donor = next((p for p in passages if (p["session"], p["lap"]) ==
                  (donor.get("session"), donor.get("lap"))), None)
    if baseline and donor:
        for passage in (baseline, donor):
            passage["local_gps_geometry"] = _geometry(passage, positions)
        core_difference = baseline["core_duration_s"] - donor["core_duration_s"]
        context_difference = baseline["context_duration_s"] - donor["context_duration_s"]
        timing_check = {"core_difference_s": core_difference, "context_difference_s": context_difference,
                        "upstream_difference_s": baseline["upstream_duration_s"] - donor["upstream_duration_s"],
                        "downstream_difference_s": baseline["downstream_duration_s"] - donor["downstream_duration_s"],
                        "adjacent_only_difference_s": context_difference - core_difference,
                        "sign_convention": "Positive means best whole lap took longer than this donor; not a guaranteed gain."}
    near_best = []
    if mini_sector_analysis:
        first, last = observation.get("start_sector", observation["sector"])-1, observation.get("end_sector", observation["sector"])
        rows = [r for r in mini_sector_analysis["rows"] if all(s["eligible"] for s in r["sectors"][first:last])]
        def duration(row):
            return sum(s["duration_s"] for s in row["sectors"][first:last])
        best = min((duration(r) for r in rows), default=None)
        tolerance = mini_sector_analysis["near_best_tolerance_s"]
        for row in rows:
            if duration(row) > best + tolerance:
                continue
            p = next((p for p in passages if (p["session"], p["lap"]) == (row["session"], row["lap"])), None)
            if p:
                if "local_gps_geometry" not in p:
                    p["local_gps_geometry"] = _geometry(p, positions)
                upstream = [b for b in p["input_analysis"].get("brake_events", []) if b["end_s"] <= p["core_start_s"]]
                near_best.append({key: p[key] for key in ("session", "lap", "core_duration_s", "context_duration_s")}
                                 | {"last_upstream_brake": upstream[-1] if upstream else None})
    return {"context_start_progress": lo, "context_end_progress": hi, "passages": passages,
            "chain_window": chain,
            "timing_check": timing_check,
            "near_best_passages": near_best,
            "limitations": ["Provisional action-linked window or explicit fixed fallback; not an identified complete corner or straight.",
                            "GPS scatter includes drift; line differences do not establish causation.",
                            "Each trace is a real passage; no continuous theoretical-best trajectory exists."]}
