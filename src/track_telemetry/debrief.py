"""Provider-independent session measurements and hosting-agent coaching handoff."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np

from .alignment import align_laps
from .braking import analyze_braking
from .channels import GPS_LATITUDE_DEG
from .gg import analyze_gg_usage
from .laps import _lap_gps_progress, lap_summary, section_metrics
from .motec_adapter import load_all_rcz_stints
from .quality import channel_source, native_rate
from .reference import compare_reference_laps
from .report_plots import render_lap_comparison, render_session_report
from .ttc_adapter import load_telemetry
from .vehicle_response import (
    analyze_braking_efficiency,
    analyze_steering_response,
    analyze_wheel_speeds,
)

CONFOUNDERS = [
    "Traffic, flags, tires, fuel, weather, setup and driver intent are unverified.",
    "Measured differences are not guaranteed gains or proof of driver causation.",
    "GPS trajectories are not boundaries; interpolation adds no native samples.",
]
HANDOFF = """Read evidence.json and plots. Finish report.md and report.html with coaching.
Cite observation IDs and measured values for every diagnosis and experiment.
Separate observations, hypotheses, confidence, confounders and unavailable data.
Select at most three experiments. Each needs a location, one changed behavior, baseline,
success measurement, safety/abort condition and next-session re-test.
Distinguish early braking, overslow, weak/long braking, late power, weak exit,
line issues and already-good-enough. Do not infer causation, ABS, sideslip,
surface or available grip. Preserve accelerator-pedal versus throttle-body semantics.
Prefer repeatability and small steps in fast sections; never prescribe added slide.
Do not promise theoretical gains. If layout is unconfirmed, obtain independent
confirmation before comparing. Do not stop at plots. Mark coaching complete only
after updating both reports, evidence hypotheses and the practice plan.
All-timed-lap spread includes yielding, traffic, warmup and cooldown; it is not
driver consistency. Use candidate-push laps for whole-lap execution review, but
use all eligible local mini-sectors for virtual-best analysis, including good
sections on otherwise slower laps. Inspect context and interruption flags.
Pace screening cannot confirm intent or a clean lap. Prefer driver/video lap_context
annotations when available, and never label an excluded slow lap as traffic by inference.
Use finalize_session_debrief with the evidence path and coaching object to
validate evidence references and write matching completed Markdown/HTML reports.
Coaching fields: summary, hypotheses and experiments. Each hypothesis needs
observation_ids, explanation, confidence and confounders. Each experiment needs
observation_ids, location, change, baseline, success_measure, abort_condition and re_test.
Match the user's language throughout. Optional language (zh-CN/en), title and
sections entries (observation_id, title, what_happened, interpretation, cue,
watch_out) produce a localized illustrated report. Explain locations using the
report's highlighted GPS map, not distance-only descriptions or unverified
official corner names. Keep raw fields and provenance in JSON, not human prose.
"""


def _attempt(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (KeyError, ValueError, ImportError) as exc:
        return {"unavailable_reason": str(exc)}


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def _consistency(laps):
    times = np.array([lap.duration_s for lap in laps])
    if not len(times):
        return {"count": 0, "unavailable_reason": "No valid timed laps"}
    median = float(np.median(times))
    return {"count": len(times), "median_s": median,
            "mad_s": float(np.median(np.abs(times - median))),
            "best_s": float(times.min()), "worst_s": float(times.max()),
            "p90_minus_p10_s": float(np.percentile(times, 90) - np.percentile(times, 10))}


def _physical_section(session, number, profile, label):
    """Map physical reference boundaries to this lap before using section metrics."""
    lap = session.lap(number)
    times, progress, _ = _lap_gps_progress(session, lap)
    start = lap.start_s + profile[0][f"lap_{label}_elapsed_s"]
    end = lap.start_s + profile[-1][f"lap_{label}_elapsed_s"]
    lo, hi = np.interp([start, end], times, progress)
    return section_metrics(session, number, float(lo), float(hi))


def _lap_selection(sessions, lap_context):
    """Separate pace candidates from intent confirmed by external annotations."""
    allowed = {"confirmed_push", "traffic", "warmup", "cooldown", "unknown"}
    annotations = {}
    for item in lap_context or []:
        key = (item["session"], item["lap"])
        if key in annotations or item.get("classification") not in allowed:
            raise ValueError("Duplicate lap context or invalid classification")
        if not isinstance(key[0], int) or not 0 <= key[0] < len(sessions):
            raise ValueError("Lap context session index is invalid")
        try:
            sessions[key[0]].lap(key[1])
        except KeyError as exc:
            raise ValueError("Lap context lap number is invalid") from exc
        if not item.get("note"):
            raise ValueError("Lap context requires an external evidence note")
        annotations[key] = item
    selection = {}
    for index, session in enumerate(sessions):
        timed = [lap for lap in session.laps if lap.is_timed
                 and np.isfinite(lap.duration_s) and lap.duration_s > 0]
        known_exclusions = {"traffic", "warmup", "cooldown"}
        pool = [lap for lap in timed if annotations.get((index, lap.number), {}).get(
            "classification") not in known_exclusions]
        best = min((lap.duration_s for lap in pool), default=None)
        cutoff = best + max(1., best * .02) if best is not None else None
        for lap in timed:
            annotation = annotations.get((index, lap.number))
            classification = annotation["classification"] if annotation else "unknown"
            if classification in known_exclusions:
                selected = False
            elif classification == "confirmed_push":
                selected = True
            else:
                selected = cutoff is not None and lap.duration_s <= cutoff
                classification = "candidate_push" if selected else "unclassified_slow"
            selection[index, lap.number] = {
                "lap": lap.number, "classification": classification,
                "coaching_eligible": selected, "pace_cutoff_s": cutoff,
                "intent_confirmed": bool(annotation and annotation["classification"] == "confirmed_push"),
                "external_context": annotation,
                "reason": "External context overrides screening" if annotation and annotation["classification"] != "unknown"
                else "Within best + max(1 s, 2% of best)" if selected
                else "Outside pace screen; reason unknown, not automatically traffic",
            }
    return selection


def _interruption_sectors(result):
    """Flag unusually concentrated loss; do not assign traffic or driver causation."""
    sectors = result.get("mini_sectors", [])
    if not sectors:
        return []
    delta = np.array([s["a_minus_b_s"] for s in sectors])
    median = float(np.median(delta))
    mad = float(np.median(np.abs(delta - median)))
    threshold = max(.75, median + 4 * 1.4826 * mad)
    return [{"sector": s["sector"], "loss_s": s["a_minus_b_s"], "screening_threshold_s": threshold,
             "reason": "Concentrated loss; traffic, yielding, mistake or technique remain unresolved"}
            for s in sectors if s["a_minus_b_s"] > threshold]


def build_debrief(sessions, output_dir: Path, *, same_layout_confirmed=False, plots=True,
                  lap_context=None):
    """Measure recordings separately, preserving clocks, stint boundaries and source gates."""
    if not sessions:
        raise ValueError("At least one telemetry file is required")
    selection = _lap_selection(sessions, lap_context)
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"schema_version": 1, "status": "awaiting_agent_interpretation",
                "same_layout_confirmed": same_layout_confirmed,
                "confounders": CONFOUNDERS, "sessions": [], "observations": [],
                "hypotheses": [], "unavailable_data": [], "plots": [],
                "practice_plan": [], "agent_instructions": HANDOFF}
    candidates = []
    for index, session in enumerate(sessions):
        laps = [lap for lap in session.laps if lap.is_timed
                and np.isfinite(lap.duration_s) and lap.duration_s > 0]
        stint_ids = list(dict.fromkeys(
            [item["stint"] for item in session.metadata.get("stints", [])]
            + [lap.stint for lap in session.laps]))
        candidates.extend((index, lap) for lap in laps)
        evidence["sessions"].append({
            "index": index, "summary": session.to_summary(),
            "lap_summaries": [lap_summary(session, lap.number) for lap in laps],
            "excluded_laps": [lap.to_dict() for lap in session.laps if lap not in laps],
            "consistency": _consistency(laps),
            "lap_selection": [selection[index, lap.number] for lap in laps],
            "candidate_push_consistency": _consistency(
                [lap for lap in laps if selection[index, lap.number]["coaching_eligible"]]),
            "stints": [{"stint": stint, "consistency": _consistency(
                [lap for lap in laps if lap.stint == stint])}
                for stint in stint_ids],
            "provenance": {str(lap.number): {
                name: {"source": channel_source(session, name, lap.number),
                       "native_rate_hz": native_rate(session, name, lap.number)}
                for name in session.channels} for lap in laps},
        })
        evidence["observations"].append({
            "id": f"session-{index}", "measured": "All timed-lap timing spread, not driver consistency",
            "values": _consistency(laps), "confidence": "low" if len(laps) < 3 else "moderate",
            "confounders": CONFOUNDERS})
        evidence["observations"].append({
            "id": f"push-pool-{index}", "measured": "Pace-screened candidate-push laps; intent/traffic unverified",
            "values": {"lap_numbers": [lap.number for lap in laps
                                       if selection[index, lap.number]["coaching_eligible"]],
                       "consistency": evidence["sessions"][-1]["candidate_push_consistency"]},
            "confidence": "low", "confounders": CONFOUNDERS})
    eligible = []
    for index, lap in sorted(candidates, key=lambda item: item[1].duration_s):
        check = _attempt(align_laps, sessions[index], lap, sessions[index], lap, grid_points=201)
        if "unavailable_reason" not in check:
            gps = sessions[index].channel(GPS_LATITUDE_DEG).slice(lap.start_s, lap.end_s)
            dt = np.diff(gps.timestamps)
            if (gps.timestamps[0] - lap.start_s > 1 or lap.end_s - gps.timestamps[-1] > 1
                    or np.max(dt) > max(1., 5 * np.median(dt))):
                check = {"unavailable_reason": "GPS boundary coverage or timestamp gaps are insufficient"}
        if "unavailable_reason" in check:
            evidence["unavailable_data"].append({"session": index, "lap": lap.number,
                                                "reference_eligibility": check})
        else:
            eligible.append((index, lap))
    reference_pool = [(i, lap) for i, lap in eligible if selection[i, lap.number]["coaching_eligible"]]
    confirmed_pool = [(i, lap) for i, lap in reference_pool if selection[i, lap.number]["intent_confirmed"]]
    reference = (confirmed_pool or reference_pool or [None])[0]
    evidence["reference"] = ({"session": reference[0], "lap": reference[1].number,
                             "selection": "Fastest externally confirmed push lap if supplied; otherwise fastest pace candidate with valid GPS. Clean status unverified."}
                             if reference else None)
    if reference:
        from .coaching_report import reference_geometry

        evidence["reference_geometry"] = _attempt(reference_geometry, sessions[reference[0]],
                                                    reference[1].number)
    comparisons = []
    if not same_layout_confirmed:
        evidence["unavailable_data"].append({"comparison": "Independent same-layout confirmation required"})
    elif reference:
        ri, ref = reference
        for index, lap in eligible:
            if (index, lap.number) == (ri, ref.number):
                continue
            result = _attempt(compare_reference_laps, sessions[index], lap.number,
                              sessions[ri], ref.number, same_layout_confirmed=True)
            flags = _interruption_sectors(result)
            comparisons.append({"session": index, "lap": lap.number, "result": result,
                                "coaching_eligible": selection[index, lap.number]["coaching_eligible"],
                                "possible_interruption_sectors": flags})
    evidence["comparisons"] = comparisons
    if same_layout_confirmed and reference:
        from .mini_sectors import analyze_mini_sectors

        self_comparison = _attempt(compare_reference_laps, sessions[ri], ref.number,
                                   sessions[ri], ref.number, same_layout_confirmed=True)
        if "mini_sectors" in self_comparison:
            evidence["mini_sector_analysis"] = analyze_mini_sectors(
                comparisons, self_comparison, ri, selection)
            composite = evidence["mini_sector_analysis"]["combined"]
            evidence["observations"].append({"id": "mini-sector-composite",
                "measured": "Sum of eligible fastest measured mini-sectors; not a continuous or guaranteed lap",
                "values": {key: composite.get(key) for key in
                           ("virtual_best_s", "best_whole_lap_s", "arithmetic_gap_s")},
                "confidence": "low", "confounders": CONFOUNDERS})
    if evidence.get("mini_sector_analysis"):
        from .mini_sectors import opportunity_profiles

        for observation in opportunity_profiles(evidence["mini_sector_analysis"], comparisons,
                                                self_comparison, ri):
            profile = observation["physical_section_profile"]
            donor = observation["section_reference"]
            observation["confounders"] = CONFOUNDERS
            observation["section_diagnostics"] = {
                "driver": _attempt(_physical_section, sessions[observation["example_session"]],
                                   observation["example_lap"], profile, "a"),
                "reference": _attempt(_physical_section, sessions[donor["session"]], donor["lap"], profile, "b")}
            evidence["observations"].append(observation)
            evidence["practice_plan"].append({
                "observation_id": observation["id"], "status": "agent_to_tailor",
                "location": f"Mini-sector {observation['sector']}, locate on GPS map",
                "experiment": "Review why the best actual lap differs from the recorded sector donor.",
                "measure": "Compare entry, exit and the adjoining sector before changing one action.",
                "abort": "Traffic, flags, reduced control margin or instructor concern.",
                "success": "Repeatable execution without degrading the adjoining section."})
    evidence["time_loss_ranking"] = [o["id"] for o in evidence["observations"] if "sector" in o]
    diagnostic_laps = list(dict.fromkeys(
        [(o["example_session"], o["example_lap"]) for o in evidence["observations"] if "sector" in o]
        + [(o["section_reference"]["session"], o["section_reference"]["lap"])
           for o in evidence["observations"] if "section_reference" in o]
        + ([(reference[0], reference[1].number)] if reference else [])))
    fallback = [(i, lap) for i, lap in candidates if selection[i, lap.number]["coaching_eligible"]]
    if not diagnostic_laps and fallback:
        index, lap = min(fallback, key=lambda item: item[1].duration_s)
        diagnostic_laps = [(index, lap.number)]
    evidence["diagnostics"] = []
    for index, number in diagnostic_laps:
        session = sessions[index]
        evidence["diagnostics"].append({
            "session": index, "lap": number,
            **{name: _attempt(fn, session, number) for name, fn in (
                ("braking", analyze_braking), ("gg", analyze_gg_usage),
                ("braking_efficiency", analyze_braking_efficiency),
                ("wheel_speeds", analyze_wheel_speeds),
                ("steering", analyze_steering_response))}})
        if plots:
            evidence["plots"].append(_attempt(render_session_report, session, number,
                output_dir / f"session-{index}-lap-{number}.html"))
    if plots and reference and comparisons:
        ri, ref = reference
        valid = [c for c in comparisons if c["coaching_eligible"] and "mini_sectors" in c["result"]]
        if valid:
            median_delta = float(np.median([c["result"]["lap_a_minus_b_total_s"] for c in valid]))
            example = min(valid, key=lambda c: abs(c["result"]["lap_a_minus_b_total_s"] - median_delta))
            evidence["plots"].append(_attempt(render_lap_comparison,
                sessions[example["session"]], example["lap"], sessions[ri], ref.number,
                output_dir / "comparison.html", same_layout_confirmed=True))
    if not evidence["practice_plan"]:
        evidence["practice_plan"] = [{
            "status": "baseline", "experiment": "Record three clear, repeatable laps with instructor feedback.",
            "measure": "Compare lap-time MAD per stint; confirm layout before section comparisons.",
            "abort": "Traffic, flags, fatigue or instructor concern.",
            "success": "Comparable data with maintained safety margin."}]
    evidence = _clean(evidence)
    (output_dir / "evidence.json").write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "agent-handoff.md").write_text(HANDOFF, encoding="utf-8")
    lines = ["# Track coaching debrief", "", "Status: awaiting hosting-agent interpretation.", "",
             "## Measured session evidence", ""]
    for entry in evidence["sessions"]:
        lines.append(f"- Recording {entry['index']}: {json.dumps(entry['consistency'])}")
    lines += ["", "## Prioritized measured differences", ""]
    for obs in evidence["observations"]:
        if "sector" not in obs:
            continue
        lines.append(f"- {obs['id']}: sector {obs['sector']}, best-lap section deficit "
                     f"{obs['measured_difference_s']:.3f} s, confidence {obs['confidence']}.")
    lines += ["", "## Hypotheses and uncertainty", "", *CONFOUNDERS,
              "No driver-causation hypothesis has been established automatically.",
              "", "## Next-session practice plan", ""]
    lines += [f"{i}. {json.dumps(plan)}" for i, plan in enumerate(evidence["practice_plan"], 1)]
    lines += ["", "## Unavailable data", "", json.dumps(evidence["unavailable_data"]),
              "", "See evidence.json for per-tool source gates and unavailable diagnostics.",
              "", "## Hosting-agent completion", "", HANDOFF]
    markdown = "\n".join(lines)
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    links = "".join(f'<li><a href="{html.escape(p.name)}">{html.escape(p.name)}</a></li>'
                    for p in sorted(output_dir.glob("*.html")) if p.name != "report.html")
    document = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Track coaching</title>'
                '<style>body{max-width:1000px;margin:2em auto;font:16px system-ui;padding:1em}'
                'pre{white-space:pre-wrap}</style><h1>Track coaching debrief</h1><ul>'
                + links + "</ul><pre>" + html.escape(markdown) + "</pre></html>")
    (output_dir / "report.html").write_text(document, encoding="utf-8")
    return {"output_dir": str(output_dir), "report_md": str(output_dir / "report.md"),
            "report_html": str(output_dir / "report.html"),
            "evidence_json": str(output_dir / "evidence.json"), "evidence": evidence}


def finalize_debrief(evidence_path: Path, coaching: dict):
    """Validate the host's structured interpretation, then publish matching local reports."""
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    ids = {o["id"] for o in evidence["observations"]}
    if not isinstance(coaching.get("summary"), str) or not coaching["summary"].strip():
        raise ValueError("Coaching requires a nonempty summary")
    hypotheses = coaching.get("hypotheses")
    experiments = coaching.get("experiments")
    if not isinstance(hypotheses, list) or not isinstance(experiments, list) or not 1 <= len(experiments) <= 3:
        raise ValueError("Provide hypotheses and one to three experiments")
    for items, required in (
        (hypotheses, ("explanation", "confidence", "confounders")),
        (experiments, ("location", "change", "baseline", "success_measure", "abort_condition", "re_test")),
    ):
        for item in items:
            refs = item.get("observation_ids")
            if not isinstance(refs, list) or not refs or any(ref not in ids for ref in refs):
                raise ValueError("Each interpretation must cite existing observation_ids")
            if any(not item.get(key) for key in required):
                raise ValueError(f"Missing coaching fields: {required}")
    if any(h["confidence"] not in {"low", "moderate", "high"} for h in hypotheses):
        raise ValueError("Confidence must be low, moderate or high")
    sections = coaching.get("sections", [])
    if "language" in coaching and (not isinstance(coaching["language"], str) or
                                  not coaching["language"].startswith(("zh", "en"))):
        raise ValueError("Report language must start with zh or en")
    if not isinstance(sections, list) or any(not isinstance(section, dict) or
            section.get("observation_id") not in ids for section in sections):
        raise ValueError("Report sections must reference existing observation IDs")
    for section in sections:
        if any(key in section and not isinstance(section[key], str) for key in
               ("title", "what_happened", "interpretation", "cue", "watch_out")):
            raise ValueError("Report section text must be strings")
    evidence.update(status="coaching_complete", hypotheses=hypotheses,
                    practice_plan=experiments, coaching_summary=coaching["summary"])
    from .coaching_report import render_report

    markdown, document = render_report(evidence, coaching)
    evidence["report_presentation"] = {key: coaching[key] for key in
                                       ("language", "title", "sections") if key in coaching}
    directory = evidence_path.parent
    (directory / "report.md").write_text(markdown, encoding="utf-8")
    (directory / "report.html").write_text(document, encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding="utf-8")
    return {"status": evidence["status"], "report_md": str(directory / "report.md"),
            "report_html": str(directory / "report.html")}


def analyze_files(paths, output_dir: Path, **kwargs):
    sessions = [load_all_rcz_stints(p) if p.suffix.lower() == ".rcz" else load_telemetry(p)
                for p in paths]
    return build_debrief(sessions, output_dir, **kwargs)


def main():
    parser = argparse.ArgumentParser(description="Measure sessions and prepare hosting-agent coaching")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("files", nargs="+", type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    analyze.add_argument("--same-layout-confirmed", action="store_true")
    analyze.add_argument("--no-plots", action="store_true")
    analyze.add_argument("--lap-context", type=Path,
                         help="Optional JSON array of external push/traffic/warmup/cooldown annotations")
    finalize = sub.add_parser("finalize", help="Publish structured hosting-agent coaching")
    finalize.add_argument("evidence", type=Path)
    finalize.add_argument("coaching", type=Path)
    args = parser.parse_args()
    if args.command == "finalize":
        print(json.dumps(finalize_debrief(args.evidence, json.loads(args.coaching.read_text(encoding="utf-8")))))
        return
    result = analyze_files(args.files, args.output,
                           same_layout_confirmed=args.same_layout_confirmed, plots=not args.no_plots,
                           lap_context=json.loads(args.lap_context.read_text(encoding="utf-8"))
                           if args.lap_context else None)
    print(json.dumps({k: v for k, v in result.items() if k != "evidence"}))
    print("Hosting agent: complete both reports using agent-handoff.md; coaching is pending.")


if __name__ == "__main__":
    main()
