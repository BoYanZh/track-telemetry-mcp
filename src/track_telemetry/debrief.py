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
Use finalize_session_debrief with the evidence path and coaching object to
validate evidence references and write matching completed Markdown/HTML reports.
Coaching fields: summary, hypotheses and experiments. Each hypothesis needs
observation_ids, explanation, confidence and confounders. Each experiment needs
observation_ids, location, change, baseline, success_measure, abort_condition and re_test.
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


def build_debrief(sessions, output_dir: Path, *, same_layout_confirmed=False, plots=True):
    """Measure recordings separately, preserving clocks, stint boundaries and source gates."""
    if not sessions:
        raise ValueError("At least one telemetry file is required")
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
            "stints": [{"stint": stint, "consistency": _consistency(
                [lap for lap in laps if lap.stint == stint])}
                for stint in stint_ids],
            "provenance": {str(lap.number): {
                name: {"source": channel_source(session, name, lap.number),
                       "native_rate_hz": native_rate(session, name, lap.number)}
                for name in session.channels} for lap in laps},
        })
        evidence["observations"].append({
            "id": f"session-{index}", "measured": "Recorded timed-lap consistency",
            "values": _consistency(laps), "confidence": "low" if len(laps) < 3 else "moderate",
            "confounders": CONFOUNDERS})
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
    reference = eligible[0] if eligible else None
    evidence["reference"] = ({"session": reference[0], "lap": reference[1].number,
                             "selection": "Fastest positive timed lap with valid GPS; clean status unverified"}
                             if reference else None)
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
            comparisons.append({"session": index, "lap": lap.number, "result": result})
    evidence["comparisons"] = comparisons
    ranking = []
    for sector in range(1, 21):
        values = [(c, s) for c in comparisons for s in c["result"].get("mini_sectors", [])
                  if s["sector"] == sector]
        if not values:
            continue
        losses = np.array([s["a_minus_b_s"] for _, s in values])
        rates = []
        for index, lap in eligible:
            observed = sessions[index].channel(GPS_LATITUDE_DEG).slice(lap.start_s, lap.end_s).sample_rate_hz
            native = native_rate(sessions[index], GPS_LATITUDE_DEG, lap.number)
            rates.append(min(observed, native) if observed and native else observed)
        timing_floor = max((1 / rate for rate in rates if rate), default=1.)
        median = float(np.median(losses))
        support = int(np.count_nonzero(losses > timing_floor))
        if median <= timing_floor:
            continue
        ranking.append({"sector": sector, "median_loss_s": median,
                        "screening_resolution_s": timing_floor,
                        "resolution_note": "One GPS interval screening floor using the lower observed/native rate where known; not a statistical error bound. Unknown native rates remain unknown.",
                        "repeat_count": support, "compared_laps": len(values),
                        "confidence": "moderate" if support >= 2 and support / len(values) >= .75 else "low",
                        "confounders": CONFOUNDERS,
                        "example": min(values, key=lambda item: abs(item[1]["a_minus_b_s"] - median))[0]})
    ranking.sort(key=lambda item: item["median_loss_s"], reverse=True)
    for rank in ranking[:3]:
        example = rank.pop("example")
        lo, hi = (rank["sector"] - 1) / 20, rank["sector"] / 20
        observation = {"id": f"loss-{len(evidence['observations']) + 1}", **rank,
                       "measured": "Median signed mini-sector difference from selected reference",
                       "example_selection": "Closest measured loss to the sector median, not the worst outlier",
                       "example_session": example["session"], "example_lap": example["lap"],
                       "physical_section_profile": [p for p in example["result"]["profile"]
                                                    if lo <= p["progress"] <= hi]}
        evidence["observations"].append(observation)
        profile = observation["physical_section_profile"]
        if len(profile) >= 2:
            ri, ref = reference
            observation["section_diagnostics"] = {
                "driver": _attempt(_physical_section, sessions[example["session"]],
                                   example["lap"], profile, "a"),
                "reference": _attempt(_physical_section, sessions[ri], ref.number, profile, "b")}
        evidence["practice_plan"].append({
            "observation_id": observation["id"], "status": "agent_to_tailor",
            "location": f"Reference GPS progress {lo:.2f}-{hi:.2f}",
            "experiment": "Establish repeatable baseline using one consistent visual marker.",
            "measure": "Compare section time and spread over three clear, comparable laps.",
            "abort": "Traffic, flags, reduced control margin or instructor concern.",
            "success": "Reduced spread while maintaining control margin."})
    evidence["time_loss_ranking"] = [o["id"] for o in evidence["observations"] if "sector" in o]
    diagnostic_laps = list(dict.fromkeys(
        [(o["example_session"], o["example_lap"]) for o in evidence["observations"] if "sector" in o]
        + ([(reference[0], reference[1].number)] if reference else [])))
    if not diagnostic_laps and candidates:
        index, lap = min(candidates, key=lambda item: item[1].duration_s)
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
        valid = [c for c in comparisons if "mini_sectors" in c["result"]]
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
        lines.append(f"- {obs['id']}: sector {obs['sector']}, median difference "
                     f"{obs['median_loss_s']:.3f} s, confidence {obs['confidence']}.")
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


def _report_html(markdown: str, evidence: dict) -> str:
    """Render the report's limited Markdown structure, escaping all host-provided text."""
    blocks = []
    in_list = in_table = False
    for line in markdown.splitlines():
        if in_list and not line.startswith("- "):
            blocks.append("</ul>")
            in_list = False
        if in_table and not line.startswith("|"):
            blocks.append("</tbody></table></div>")
            in_table = False
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            if not in_table:
                blocks.append('<div class="table-wrap"><table><tbody>')
                in_table = True
                tag = "th"
            else:
                tag = "td"
            blocks.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
        elif line.startswith("#"):
            level = min(3, len(line) - len(line.lstrip("#")))
            blocks.append(f"<h{level}>{html.escape(line.lstrip('# ').strip())}</h{level}>")
        elif line.startswith("- "):
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip():
            blocks.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        blocks.append("</ul>")
    if in_table:
        blocks.append("</tbody></table></div>")
    blocks.append('<h2>Plots / 图表</h2>')
    for bundle in evidence["plots"]:
        if "output_html" in bundle:
            name = html.escape(Path(bundle["output_html"]).name, quote=True)
            blocks.append(f'<p><a href="{name}">{name}</a></p>')
        for name, path in bundle.get("plot_files", {}).items():
            src = html.escape(Path(path).name, quote=True)
            caption = html.escape(name.replace("_", " "))
            blocks.append(f'<figure><img loading="lazy" src="{src}" alt="{caption}">'
                          f'<figcaption>{caption}</figcaption></figure>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Track coaching debrief</title><style>'
            'body{max-width:1100px;margin:40px auto;padding:0 24px;font:16px/1.7 system-ui,sans-serif;'
            'color:#243343;background:#f6f8fa}h1,h2,h3{line-height:1.3;color:#132b41}'
            'h1{border-bottom:4px solid #197f82;padding-bottom:20px}h2{margin-top:40px}'
            'h3{border-left:4px solid #197f82;padding-left:14px}li{margin:10px 0}'
            '.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;background:white}'
            'td,th{padding:10px 14px;border-bottom:1px solid #dce3e9;text-align:left}'
            'th{background:#e5eff2}figure{margin:24px 0;background:white;padding:12px}'
            'img{width:100%;height:auto}figcaption{color:#536778}a{color:#126a77}'
            '@media print{body{background:white;margin:0}figure{break-inside:avoid}}'
            '</style></head><body><main>' + "".join(blocks) + '</main></body></html>')


def _timing_tables(evidence: dict) -> list[str]:
    def seconds(value):
        return f"{value:.3f}" if value is not None else "unavailable"

    lines = ["", "## Session and stint timing", "",
             "| Recording | Stint | Timed laps | Best s | Median s | MAD s |",
             "| --- | --- | --- | --- | --- | --- |"]
    for session in evidence["sessions"]:
        for label, stats in [("all", session["consistency"])] + [
                (str(s["stint"]), s["consistency"]) for s in session["stints"]]:
            lines.append(f"| {session['index']} | {label} | {stats['count']} | "
                         f"{seconds(stats.get('best_s'))} | {seconds(stats.get('median_s'))} | "
                         f"{seconds(stats.get('mad_s'))} |")
    lines += ["", "Stint numbers are recorder identifiers. Zero timed laps does not mean zero recording.",
              "", "| Recording | Source file |", "| --- | --- |"]
    lines += [f"| {s['index']} | {s['summary']['source_name']} |" for s in evidence["sessions"]]
    return lines


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
    evidence.update(status="coaching_complete", hypotheses=hypotheses,
                    practice_plan=experiments, coaching_summary=coaching["summary"])
    lines = ["# Track coaching debrief", "", coaching["summary"]]
    lines += _timing_tables(evidence)
    lines += ["", "## Measured evidence", ""]
    for obs in evidence["observations"]:
        if "sector" in obs:
            lines += [f"- {obs['id']}: sector {obs['sector']}, median measured difference "
                      f"{obs['median_loss_s']:.3f} s across {obs['compared_laps']} laps, "
                      f"{obs['repeat_count']} repeat observations above screening resolution. "
                      f"Confidence: {obs['confidence']}."]
        else:
            lines += [f"- {obs['id']}: {obs['measured']}. {json.dumps(obs['values'])}"]
    lines += ["", "## Hypotheses", ""]
    lines += [f"- {h['explanation']} Confidence: {h['confidence']}. "
              f"Evidence: {', '.join(h['observation_ids'])}. Confounders: {h['confounders']}."
              for h in hypotheses]
    lines += ["", "## Next-session experiments", ""]
    for i, experiment in enumerate(experiments, 1):
        lines += [f"### {i}. {experiment['location']}", ""]
        lines += [f"- {key.replace('_', ' ')}: {experiment[key]}" for key in
                  ("change", "baseline", "success_measure", "abort_condition", "re_test", "observation_ids")]
        lines += [""]
    lines += ["## Confounders and unavailable data", "", *evidence["confounders"],
              json.dumps(evidence["unavailable_data"]),
              "See evidence.json for diagnostic and plot-specific unavailable reasons."]
    markdown = "\n".join(lines)
    directory = evidence_path.parent
    (directory / "report.md").write_text(markdown, encoding="utf-8")
    (directory / "report.html").write_text(_report_html(markdown, evidence), encoding="utf-8")
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
    finalize = sub.add_parser("finalize", help="Publish structured hosting-agent coaching")
    finalize.add_argument("evidence", type=Path)
    finalize.add_argument("coaching", type=Path)
    args = parser.parse_args()
    if args.command == "finalize":
        print(json.dumps(finalize_debrief(args.evidence, json.loads(args.coaching.read_text(encoding="utf-8")))))
        return
    result = analyze_files(args.files, args.output,
                           same_layout_confirmed=args.same_layout_confirmed, plots=not args.no_plots)
    print(json.dumps({k: v for k, v in result.items() if k != "evidence"}))
    print("Hosting agent: complete both reports using agent-handoff.md; coaching is pending.")


if __name__ == "__main__":
    main()
