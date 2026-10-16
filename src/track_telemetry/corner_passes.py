"""Measured individual passages around a physical mini-sector, without a synthetic line."""
from __future__ import annotations

import numpy as np

from .channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG, LAT_G, LONG_G
from .geometry import latlon_to_xy_m
from .gg import analyze_gg_usage
from .quality import channel_source, matched_window, native_rate


def measure_passages(sessions, observation, comparisons, self_result, reference_index):
    """Retain all aligned passages and independently gate measured G in each window."""
    results = {(c["session"], c["lap"]): c["result"] for c in comparisons
               if "profile" in c["result"]}
    results[reference_index, self_result["lap_a"]["number"]] = self_result
    core = observation["physical_section_profile"]
    lo, hi = max(0., core[0]["progress"] - .05), min(1., core[-1]["progress"] + .05)
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
        start, end = lap.start_s + np.interp([lo, hi], progress, elapsed)
        core_start, core_end = lap.start_s + np.interp(
            [core[0]["progress"], core[-1]["progress"]], progress, elapsed)
        entry = {"session": index, "lap": number, "start_s": float(start), "end_s": float(end),
                 "alignment_quality": result.get("alignment_quality", {})}
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
        entry["gps_provenance"] = {name: {"source": channel_source(session, name, number),
            "native_sample_rate_hz": native_rate(session, name, number),
            "output_sample_rate_hz": session.channel(name).sample_rate_hz}
            for name in (GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG)}
        entry["controls"] = {}
        for name in ("accelerator_pct", "throttle_pct", "brake_pressure_kpa", "steering_deg"):
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
    return {"context_start_progress": lo, "context_end_progress": hi, "passages": passages,
            "limitations": ["Context includes adjacent mini-sectors, not an identified complete corner.",
                            "GPS scatter includes drift; line differences do not establish causation.",
                            "Each trace is a real passage; no continuous theoretical-best trajectory exists."]}
