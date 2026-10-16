"""All-lap physical mini-sector matrix and explicitly non-achievable virtual sums."""
from __future__ import annotations

import numpy as np


def _speed(profile, progress):
    if len(profile) < 2:
        return None
    if not profile[0]["progress"] - 1e-9 <= progress <= profile[-1]["progress"] + 1e-9:
        return None
    grid = [p["progress"] for p in profile]
    index = int(np.searchsorted(grid, progress))
    for nearest in (index - 1, index):
        if 0 <= nearest < len(profile) and abs(grid[nearest] - progress) <= 1e-9:
            return profile[nearest].get("lap_a_speed_kmh")
    if not 0 < index < len(profile):
        return None
    values = [profile[i].get("lap_a_speed_kmh") for i in (index - 1, index)]
    if any(value is None for value in values):
        return None
    return float(np.interp(progress, grid[index - 1:index + 1], values))


def _reduce(rows):
    winners = []
    for index in range(20):
        samples = [(row, row["sectors"][index]) for row in rows
                   if row["sectors"][index]["eligible"]]
        if not samples:
            return {"unavailable_reason": f"No eligible samples in sector {index + 1}"}
        samples.sort(key=lambda item: item[1]["duration_s"])
        row, sector = samples[0]
        winners.append({"sector": index + 1, "duration_s": sector["duration_s"],
                        "session": row["session"], "lap": row["lap"], "stint": row["stint"],
                        "entry_speed_kmh": sector["entry_speed_kmh"],
                        "exit_speed_kmh": sector["exit_speed_kmh"],
                        "second_fastest_s": samples[1][1]["duration_s"] if len(samples) > 1 else None,
                        "near_best_count": sum(s["duration_s"] <= sector["duration_s"] + .1 for _, s in samples),
                        "eligible_samples": len(samples)})
    baseline = min((r for r in rows if r["whole_lap_eligible"]),
                   key=lambda r: r["lap_time_s"], default=None)
    transitions = []
    for index, previous in enumerate(winners):
        following = winners[(index + 1) % len(winners)]
        changed_source = (previous["session"], previous["lap"]) != (following["session"], following["lap"])
        before, after = previous["exit_speed_kmh"], following["entry_speed_kmh"]
        jump = after - before if before is not None and after is not None else None
        transitions.append({"after_sector": previous["sector"], "next_sector": following["sector"],
                            "changed_source": changed_source, "speed_jump_kmh": jump,
                            "speed_discontinuity_flag": changed_source and jump is not None and abs(jump) > 5.})
    theoretical = float(sum(w["duration_s"] for w in winners))
    for winner in winners:
        winner["best_whole_lap_deficit_s"] = (
            baseline["sectors"][winner["sector"] - 1]["duration_s"] - winner["duration_s"]
            if baseline else None)
    return {"virtual_best_s": theoretical,
            "second_fastest_composite_s": float(sum(w["second_fastest_s"] for w in winners))
            if all(w["second_fastest_s"] is not None for w in winners) else None,
            "best_whole_lap_s": baseline["lap_time_s"] if baseline else None,
            "best_whole_lap_source": {k: baseline[k] for k in ("session", "lap", "stint")} if baseline else None,
            "arithmetic_gap_s": baseline["lap_time_s"] - theoretical if baseline else None,
            "winners": winners, "transitions": transitions,
            "largest_best_lap_deficits": sorted(winners, key=lambda w: w["best_whole_lap_deficit_s"]
                                                if w["best_whole_lap_deficit_s"] is not None else -np.inf,
                                                reverse=True)[:3]}


def analyze_mini_sectors(comparisons, reference_result, reference_index, selection):
    """Use a shared GPS geometry as coordinates, not as a performance envelope.

    Whole-lap pace does not exclude useful local fast sections. Explicit traffic,
    warmup and cooldown annotations do; unresolved concentrated-loss sections are
    withheld individually. Fast sections on otherwise slow laps remain unconfirmed.
    """
    rows = []
    inputs = [*comparisons, {"session": reference_index, "lap": reference_result["lap_a"]["number"],
                            "result": reference_result, "possible_interruption_sectors": []}]
    for item in inputs:
        result = item["result"]
        if "mini_sectors" not in result:
            continue
        context = selection[item["session"], item["lap"]]
        explicitly_excluded = context["classification"] in {"traffic", "warmup", "cooldown"}
        flagged = {f["sector"] for f in item["possible_interruption_sectors"]}
        sectors = []
        for sector in result["mini_sectors"]:
            duration = sector["lap_a_s"]
            eligible = not explicitly_excluded and sector["sector"] not in flagged and np.isfinite(duration) and duration > 0
            sectors.append({"sector": sector["sector"], "duration_s": duration, "eligible": bool(eligible),
                            "entry_speed_kmh": _speed(result["profile"], sector["start_progress"]),
                            "exit_speed_kmh": _speed(result["profile"], sector["end_progress"]),
                            "exclusion_reason": context["classification"] if explicitly_excluded else
                            "unresolved_concentrated_loss" if sector["sector"] in flagged else None})
        rows.append({"session": item["session"], "lap": item["lap"], "stint": result["lap_a"]["stint"],
                     "lap_time_s": result["lap_a"]["duration_s"], "classification": context["classification"],
                     "whole_lap_eligible": not explicitly_excluded, "sectors": sectors,
                     "alignment_quality": result["alignment_quality"]})
    rows.sort(key=lambda r: (r["session"], r["lap"]))
    usable = [r for r in rows if r["whole_lap_eligible"]]
    return {"sector_count": 20, "rows": rows, "combined": _reduce(usable),
            "by_session": {str(i): _reduce([r for r in usable if r["session"] == i])
                           for i in sorted({r["session"] for r in rows})},
            "near_best_tolerance_s": .1, "boundary_speed_flag_threshold_kmh": 5.,
            "limitations": [
                "Virtual sums combine actual measured intervals but do not form a physically continuous lap.",
                "Boundary speeds are a screening check, not proof of compatible lines, grip or control states.",
                "Source selection is optimistic and vulnerable to GPS timing uncertainty; isolated bests need review.",
                "Near-best counts use 0.1 s tolerance, not a statistical confidence interval.",
                "Traffic and intent remain unconfirmed without external annotations; combined days may have different conditions.",
            ]}


def opportunity_profiles(analysis, comparisons, reference_result, reference_index):
    """Compare the best actual lap to each winning donor on the same GPS grid."""
    combined = analysis["combined"]
    baseline = combined.get("best_whole_lap_source")
    if baseline is None:
        return []
    results = {(c["session"], c["lap"]): c["result"] for c in comparisons
               if "profile" in c["result"]}
    results[reference_index, reference_result["lap_a"]["number"]] = reference_result
    base_profile = results[baseline["session"], baseline["lap"]]["profile"]
    opportunities = []
    for winner in combined["largest_best_lap_deficits"]:
        if winner["best_whole_lap_deficit_s"] <= 1e-6:
            continue
        sector = winner["sector"]
        donor = results[winner["session"], winner["lap"]]["profile"]
        profile = []
        for a, b in zip(base_profile, donor):
            if not (sector - 1) / 20 - 1e-9 <= a["progress"] <= sector / 20 + 1e-9:
                continue
            if not np.isclose(a["reference_distance_m"], b["reference_distance_m"]):
                raise ValueError("Mini-sector profiles must share the same physical reference grid")
            profile.append({"reference_distance_m": a["reference_distance_m"], "progress": a["progress"],
                            "lap_a_elapsed_s": a["lap_a_elapsed_s"], "lap_b_elapsed_s": b["lap_a_elapsed_s"],
                            "lap_a_speed_kmh": a["lap_a_speed_kmh"], "lap_b_speed_kmh": b["lap_a_speed_kmh"]})
        opportunities.append({"id": f"opportunity-{sector}", "sector": sector,
                              "measured": "Best actual lap minus fastest observed sector; not guaranteed gain",
                              "measured_difference_s": winner["best_whole_lap_deficit_s"],
                              "loss_metric": "best_whole_lap_minus_sector_best",
                              "example_session": baseline["session"], "example_lap": baseline["lap"],
                              "section_reference": {"session": winner["session"], "lap": winner["lap"]},
                              "example_selection": "Best whole lap versus this sector's fastest donor, on common GPS coordinates",
                              "physical_section_profile": profile,
                              "repeat_count": winner["near_best_count"], "compared_laps": winner["eligible_samples"],
                              "confidence": "moderate" if winner["near_best_count"] >= 2 else "low"})
    return opportunities
