"""Screen every mini-sector and real contiguous interval before coaching selection."""
import numpy as np


def screen_training_opportunities(analysis):
    rows = analysis["rows"]
    count = analysis["sector_count"]
    source = analysis["combined"].get("best_whole_lap_source")
    baseline = next((r for r in rows if source and (r["session"], r["lap"]) ==
                     (source["session"], source["lap"])), None)
    if not baseline:
        return {"unavailable_reason": "No best whole-lap source"}
    def span(first, last):
        if first <= last:
            return list(range(first, last + 1))
        return list(range(first, count + 1)) + list(range(1, last + 1))
    def interval(first, last):
        if first > last:
            return {"start_sector": first, "end_sector": last, "wraps_finish_line": True,
                    "unavailable_reason": "Cross-lap chronology requires adjacent recorded laps; same-row endpoints are not contiguous"}
        sectors = span(first, last)
        eligible = [r for r in rows if r["whole_lap_eligible"] and
                    all(r["sectors"][s - 1]["eligible"] for s in sectors)]
        def duration(row):
            return float(sum(row["sectors"][s - 1]["duration_s"] for s in sectors))
        ordered = sorted(eligible, key=duration)
        if not ordered:
            return {"start_sector": first, "end_sector": last, "wraps_finish_line": first > last,
                    "unavailable_reason": "No eligible real interval"}
        donor = ordered[0]
        return {"start_sector": first, "end_sector": last, "wraps_finish_line": first > last,
                "baseline_interval_s": duration(baseline),
                "best_actual_interval_s": duration(donor), "observed_deficit_s": duration(baseline)-duration(donor),
                "source": {"session": donor["session"], "lap": donor["lap"]},
                "cross_session": donor["session"] != baseline["session"], "eligible_samples": len(ordered),
                "near_best_count": sum(duration(r) <= duration(donor)+analysis["near_best_tolerance_s"] for r in ordered)}
    def linked_net(target):
        if target in {1, count}:
            return None, None
        window = span(target - 1 if target > 1 else count, target + 1 if target < count else 1)
        if not all(baseline["sectors"][s - 1]["eligible"] for s in window):
            return None, None
        pool = [r for r in rows if r["whole_lap_eligible"] and
                all(r["sectors"][s - 1]["eligible"] for s in window)]
        if not pool:
            return None, None
        donor = min(pool, key=lambda r: r["sectors"][target - 1]["duration_s"])
        def total(row):
            return float(sum(row["sectors"][s - 1]["duration_s"] for s in window))
        return total(baseline) - total(donor), {"session": donor["session"], "lap": donor["lap"]}
    sectors = []
    for first in range(1, count + 1):
        entry = interval(first, first)
        net, donor = linked_net(first)
        entry["linked_net_s"] = net
        entry["linked_window_reversed"] = net is not None and net <= 0
        entry["linked_window_source"] = donor
        entry["candidate_execution_by_session"] = {}
        for index in sorted({r["session"] for r in rows}):
            pool = [r for r in rows if r["session"] == index and r["classification"] in
                    {"candidate_push", "confirmed_push"} and r["sectors"][first-1]["eligible"]]
            values = [r["sectors"][first-1]["duration_s"] for r in pool]
            if values:
                entry["candidate_execution_by_session"][str(index)] = {
                    "count": len(values), "best_s": float(min(values)), "median_s": float(np.median(values)),
                    "median_minus_best_s": float(np.median(values)-min(values)),
                    "laps": [r["lap"] for r in pool]}
        sectors.append(entry)
    linear = [interval(first, first+length-1) for length in (2, 3, 4)
              for first in range(1, count-length+2)]
    wraps = []
    for length in (2, 3, 4):
        for first in range(count-length+2, count+1):
            last = ((first + length - 2) % count) + 1
            if len(span(first, last)) != length:
                continue
            wraps.append(interval(first, last))
    measured = [s for s in sectors if "observed_deficit_s" in s]
    netted = sorted((s for s in measured if s.get("linked_net_s") is not None),
                    key=lambda s: (s["linked_net_s"], s["near_best_count"]), reverse=True)
    unnetted = sorted((s for s in measured if s.get("linked_net_s") is None),
                      key=lambda s: s["observed_deficit_s"], reverse=True)
    shortlist = (netted + unnetted)[:6]
    return {"sectors": sectors,
            "contiguous_real_intervals": linear + wraps,
            "ranked_shortlist": [{"sector": s["start_sector"], "observed_deficit_s": s["observed_deficit_s"],
                                  "linked_net_s": s["linked_net_s"],
                                  "linked_window_reversed": s["linked_window_reversed"],
                                  "source": s["source"], "cross_session": s["cross_session"],
                                  "eligible_samples": s["eligible_samples"],
                                  "near_best_count": s["near_best_count"]} for s in shortlist],
            "limitations": ["Intervals use one actual lap each, not stitched sector minima.",
                "Overlapping intervals are alternatives; never sum their deficits.",
                "Linked net compares the sector donor's own adjoining window against the baseline's; a reversed net means the single-sector advantage disappears across adjoining sectors.",
                "Wrap intervals remain unavailable until adjacent-lap chronology is verified; no same-row end/start sum.",
                "Execution spread is descriptive pace-screened data, not proven clean-lap inconsistency or guaranteed gain.",
                "Sector numbers are not corner numbers. Best sector status does not exclude an adjoining corner problem.",
                "The agent must rank linked corners by repeatable net gain, downstream influence, evidence and HPDE risk; speed alone is not priority."]}
