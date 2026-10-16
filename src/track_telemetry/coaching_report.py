"""Human-facing report presentation; measurements and AI interpretation stay separate."""
from __future__ import annotations

import html
import re

import numpy as np

from .channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG
from .geometry import latlon_to_xy_m
from .laps import _lap_gps_progress


def reference_geometry(session, lap_number):
    """Keep sampled reference geometry for location-aware reports without reloading files."""
    lap = session.lap(lap_number)
    times, progress, distance = _lap_gps_progress(session, lap)
    x, y = latlon_to_xy_m(session.channel(GPS_LATITUDE_DEG).interp(times),
                         session.channel(GPS_LONGITUDE_DEG).interp(times))
    indices = np.unique(np.linspace(0, len(times) - 1, min(900, len(times)), dtype=int))
    return {"points": [{"x_m": float(x[i]), "y_m": float(y[i]), "progress": float(progress[i])}
                       for i in indices], "length_m": float(distance[-1]),
            "display_note": "Sampled GPS trajectory, display-decimated; not a track boundary."}


def _escape(value):
    return html.escape(str(value), quote=True)


def _time(value):
    if value is None:
        return "—"
    return f"{int(value // 60)}:{value % 60:06.3f}"


def _session_name(session, zh):
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", session["summary"]["source_name"])
    if match:
        return f"{int(match[2])}月{int(match[3])}日" if zh else f"{match[2]}/{match[3]}"
    return f"记录 {session['index'] + 1}" if zh else f"Recording {session['index'] + 1}"


def _zones(evidence, zh):
    points = evidence.get("reference_geometry", {}).get("points", [])
    observations = [o for o in evidence["observations"] if "sector" in o]
    zones = []
    for index, observation in enumerate(observations):
        profile = observation["physical_section_profile"]
        lo, hi = profile[0]["progress"], profile[-1]["progress"]
        location = "图上高亮位置" if zh else "Highlighted location"
        if points:
            selected = [p for p in points if lo <= p["progress"] <= hi]
            if selected:
                xs, ys = [p["x_m"] for p in points], [p["y_m"] for p in points]
                x = np.mean([p["x_m"] for p in selected])
                y = np.mean([p["y_m"] for p in selected])
                horizontal = "左" if x < min(xs) + np.ptp(xs) / 3 else "右" if x > min(xs) + np.ptp(xs) * 2 / 3 else "中"
                vertical = "下" if y < min(ys) + np.ptp(ys) / 3 else "上" if y > min(ys) + np.ptp(ys) * 2 / 3 else ""
                location = ("地图中央" if horizontal == "中" and not vertical else
                            f"地图{horizontal}侧" if not vertical else f"地图{horizontal}{vertical}方") if zh else "Highlighted GPS section"
        zones.append({"letter": chr(65 + index), "location": location, "lo": lo, "hi": hi,
                      "observation": observation, "color": ("#ba4a20", "#126d82", "#74529a")[index % 3]})
    return zones


def _map(evidence, zones, zh, selected=None):
    points = evidence.get("reference_geometry", {}).get("points", [])
    if not points:
        return '<p class="notice">' + ("缺少可定位的参考轨迹，无法绘制区段地图。" if zh else "Reference geometry unavailable.") + "</p>"
    xs, ys = [p["x_m"] for p in points], [p["y_m"] for p in points]
    scale = min(730 / max(np.ptp(xs), 1), 490 / max(np.ptp(ys), 1))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    def xy(point):
        return 450 + (point["x_m"] - cx) * scale, 310 - (point["y_m"] - cy) * scale
    def path(items):
        return " ".join(("M" if i == 0 else "L") + f"{xy(p)[0]:.1f},{xy(p)[1]:.1f}"
                        for i, p in enumerate(items))
    pieces = [f'<svg viewBox="0 0 900 620" role="img" aria-label="{("赛道轨迹与分析位置" if zh else "Track and analysis locations")}">',
              f'<path d="{path(points)}" fill="none" stroke="#b9c3c9" stroke-width="9" stroke-linejoin="round"/>']
    # Direction arrows follow the recorded sample order. No official corner geometry is inferred.
    for fraction in (.18, .38, .65, .9):
        i = int((len(points) - 5) * fraction)
        a, b = xy(points[i]), xy(points[i + 4])
        angle = np.arctan2(b[1] - a[1], b[0] - a[0])
        coords = [(b[0] + 12 * np.cos(angle), b[1] + 12 * np.sin(angle)),
                  (b[0] + 8 * np.cos(angle + 2.5), b[1] + 8 * np.sin(angle + 2.5)),
                  (b[0] + 8 * np.cos(angle - 2.5), b[1] + 8 * np.sin(angle - 2.5))]
        pieces.append('<polygon points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in coords) + '" fill="#405765"/>')
    for zone in zones:
        if selected and zone["letter"] != selected:
            continue
        highlighted = [p for p in points if zone["lo"] - 1e-9 <= p["progress"] <= zone["hi"] + 1e-9]
        if not highlighted:
            continue
        x, y = xy(highlighted[len(highlighted) // 2])
        pieces.append(f'<a href="#zone-{zone["letter"]}"><path d="{path(highlighted)}" fill="none" '
                      f'stroke="{zone["color"]}" stroke-width="12" stroke-linecap="round"/>'
                      f'<circle cx="{x:.1f}" cy="{y:.1f}" r="22" fill="{zone["color"]}" stroke="white" stroke-width="3"/>'
                      f'<text x="{x:.1f}" y="{y + 8:.1f}" text-anchor="middle" fill="white" font-size="25" font-weight="700">{zone["letter"]}</text></a>')
    x, y = xy(points[0])
    pieces.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="#1b303d"/>'
                  f'<text x="{x + 14:.1f}" y="{y - 14:.1f}" font-size="20" fill="#1b303d">'
                  + ("起终点附近" if zh else "Near start / finish") + '</text>'
                  '<text x="830" y="42" font-size="20">' + ("北 ↑" if zh else "N ↑") + '</text></svg>')
    return "".join(pieces)


def render_report(evidence, coaching):
    """Build localized, illustrated reports without dumping machine evidence into prose."""
    zh = coaching.get("language", "zh" if re.search(r"[\u4e00-\u9fff]", coaching["summary"]) else "en").startswith("zh")
    def tr(chinese, english):
        return chinese if zh else english
    title = coaching.get("title", tr("赛道驾驶复盘", "Track coaching debrief"))
    sessions = {s["index"]: s for s in evidence["sessions"]}
    zones = _zones(evidence, zh)
    zone_by_id = {z["observation"]["id"]: z for z in zones}
    bodies, md = [], [f"# {title}", "", coaching["summary"], ""]
    def paragraphs(text):
        return "".join(f"<p>{_escape(p)}</p>" for p in text.split("\n\n") if p.strip())
    bodies.append('<header><p class="brand">' + tr("驾驶复盘 · 下一节练习", "Debrief · next-session practice")
                  + f'</p><h1>{_escape(title)}</h1>{paragraphs(coaching["summary"])}</header>')
    composite = evidence.get("mini_sector_analysis", {}).get("combined", {})
    if composite.get("virtual_best_s") is not None:
        source = composite["best_whole_lap_source"]
        name = _session_name(sessions[source["session"]], zh)
        text = tr(
            f"实际最快 {name}第{source['lap']}圈 {_time(composite['best_whole_lap_s'])}；分段理论最佳 {_time(composite['virtual_best_s'])}；算术差 {composite['arithmetic_gap_s']:.3f} 秒。下面直接定位最值得检查的三个弯区。理论最佳来自不同圈，不能视为下一节必然能跑出的圈速。",
            f"Best actual lap {_time(composite['best_whole_lap_s'])}; mini-sector theoretical best {_time(composite['virtual_best_s'])}; arithmetic gap {composite['arithmetic_gap_s']:.3f} s. The composite is not a guaranteed achievable lap.")
        bodies.append('<section><h2>' + tr("最快圈与分段理论最佳", "Best lap versus mini-sector theoretical best") + '</h2>' + paragraphs(text) + '</section>')
        md += ["", text, ""]
    calculation_details = ""
    mini_md = []
    if evidence.get("mini_sector_analysis"):
        from .mini_sector_report import render_mini_sectors

        mini_html, mini_md = render_mini_sectors(evidence["mini_sector_analysis"],
                                              lambda i: _session_name(sessions[i], zh), _time, zh)
        sector_map = [{"letter": str(i), "lo": (i - 1) / 20, "hi": i / 20,
                       "color": "#126d82" if i % 2 else "#507c8a"} for i in range(1, 21)]
        calculation_details = ('<details class="calculations"><summary>'
                      + tr("计算依据：逐圈区段、拼接圈时与接缝检查", "Calculation details: sector matrix and virtual lap")
                      + '</summary><section><h2>' + tr("二十个区段在这里", "Locate the twenty mini-sectors")
                      + '</h2>' + _map(evidence, sector_map, zh)
                      + '<p class="note">' + tr("数字对应下方矩阵的列，不是官方弯号。", "Numbers match matrix columns, not official corners.") + '</p></section>' + mini_html)
        calculation_details += '</details>'
    bodies.append('<section id="track"><h2>' + tr("先找到位置，再看诊断", "Locate each finding") + '</h2>'
                  + _map(evidence, zones, zh) + '<div class="map-key">'
                  + "".join(f'<a href="#zone-{z["letter"]}" style="--zone:{z["color"]}">{z["letter"]} · {_escape(z["location"])}</a>' for z in zones)
                  + '</div><p class="note">' + tr(
                      "北朝上；箭头按记录顺序表示行驶方向。彩色段是本次分析位置，灰线是采样轨迹，不是赛道边界。A/B/C 是本报告的位置标记，不是官方弯号。",
                      "North up; arrows follow sample order. Highlights locate the findings. GPS lines are not track boundaries; letters are not official corner names.") + '</p></section>')
    descriptions = {item["observation_id"]: item for item in coaching.get("sections", [])}
    section_order = {key: index for index, key in enumerate(descriptions)}
    for zone in sorted(zones, key=lambda z: section_order.get(z["observation"]["id"], len(descriptions))):
        o = zone["observation"]
        difference = o.get("measured_difference_s", o.get("median_loss_s"))
        composite = o.get("loss_metric") == "best_whole_lap_minus_sector_best"
        description = descriptions.get(o["id"], {})
        heading = description.get("title", zone["location"])
        reference = o.get("section_reference", evidence["reference"])
        driver_label = _session_name(sessions[o["example_session"]], zh) + tr(f"第{o['example_lap']}圈", f" L{o['example_lap']}")
        ref_label = _session_name(sessions[reference["session"]], zh) + tr(f"第{reference['lap']}圈", f" L{reference['lap']}")
        bodies.append(f'<section class="zone" id="zone-{zone["letter"]}" style="--zone:{zone["color"]}">'
                      f'<h2><span class="letter">{zone["letter"]}</span>{_escape(heading)}</h2>'
                      '<div class="zone-layout"><div>' + _map(evidence, zones, zh, zone["letter"])
                      + '</div><div><p class="finding">' + tr(
                          f"整圈最快在此仍差约 {difference:.2f} 秒" if composite else f"候选样本的中位差约 {difference:.2f} 秒",
                          f"Best-lap section deficit: {difference:.2f} s" if composite else f"Median candidate difference: {difference:.2f} s") + '</p>'
                      + paragraphs(description.get("what_happened", tr(
                          f"本段有 {o['compared_laps']} 个可用样本，其中 {o['repeat_count']} 个位于本段最快后 0.1 秒以内。曲线比较整圈最快圈与本段最快来源，不是虚拟圈可实现的证明。",
                          f"{o['compared_laps']} eligible samples; {o['repeat_count']} within 0.1 s of sector best. This comparison does not establish feasibility of the virtual lap.")))
                      + '</div></div><figure>'
                      + '<figcaption><span class="driver">' + tr("整圈最快：" if composite else "对照：", "Best whole lap: " if composite else "Compared: ") + _escape(driver_label)
                      + '</span>　<span class="reference">' + tr("本段最快：" if composite else "参考：", "Sector best: " if composite else "Reference: ") + _escape(ref_label)
                      + '</span> · ' + tr("两条曲线对应图上同一物理区段", "Both traces use matched physical locations") + '</figcaption></figure>')
        from .corner_report import render_corner

        bodies.append(render_corner(o, lambda i, lap: _session_name(sessions[i], zh)
                                    + tr(f"第{lap}圈", f" L{lap}"), zh, description=description))
        for key, label in (("interpretation", tr("怎样理解", "Interpretation")), ("cue", tr("先做什么", "First action")),
                           ("watch_out", tr("不要据此推断", "Limits"))):
            if description.get(key):
                bodies.append(f'<h3>{label}</h3>{paragraphs(description[key])}')
        if not description.get("interpretation"):
            for h in coaching["hypotheses"]:
                if o["id"] in h["observation_ids"]:
                    bodies.append(paragraphs(h["explanation"]))
        linked = [h for h in coaching["hypotheses"] if o["id"] in h["observation_ids"]]
        if linked:
            confidence = {"low": tr("偏低", "low"), "moderate": tr("中等", "moderate"), "high": tr("较高", "high")}
            bodies.append('<p class="note">' + tr("原因判断的把握：", "Interpretation confidence: ")
                          + " / ".join(confidence[h["confidence"]] for h in linked) + '</p>')
        bodies.append('<p class="note">' + tr("这些是均分区段，不一定覆盖完整弯道。区段最低速度不等于弯心速度。", "Sections may not cover a whole corner; section minima are not apex speeds.") + '</p></section>')
        md += ["", f"## {zone['letter']} · {heading}", "", description.get("what_happened", ""),
               tr(f"实测区段差约 {difference:.2f} 秒。", f"Measured section difference: {difference:.2f} s."),
               description.get("interpretation", ""), description.get("cue", ""), description.get("watch_out", "")]
        md.extend(description[key] for key in ("braking_analysis", "steering_analysis", "power_analysis", "g_analysis")
                  if description.get(key))
        if not description.get("interpretation"):
            md.extend(h["explanation"] for h in linked)
    bodies.append('<section><h2>' + tr("下一节只做这些练习", "Next-session experiments") + '</h2>')
    md += ["", "## " + tr("下一节练习", "Next-session experiments"), ""]
    for index, experiment in enumerate(coaching["experiments"], 1):
        located = [zone_by_id[key] for key in experiment["observation_ids"] if key in zone_by_id]
        location = " / ".join(f"{z['letter']} · {z['location']}" for z in located) if located else experiment["location"]
        bodies.append(f'<article class="practice"><h3>{index}. {_escape(location)}</h3><dl>')
        md += [f"### {index}. {location}", ""]
        for key, label in (("change", tr("只改这一项", "One change")), ("baseline", tr("当前基线", "Baseline")),
                           ("success_measure", tr("怎样判断有效", "Success measure")), ("abort_condition", tr("何时停止", "Abort condition")),
                           ("re_test", tr("下次怎样复测", "Re-test"))):
            bodies.append(f'<dt>{label}</dt><dd>{_escape(experiment[key])}</dd>')
            md.append(f"- {label}：{experiment[key]}")
        bodies.append('</dl></article>')
    bodies.append('</section><section><h2>' + tr("哪些结论还不能下", "What remains uncertain") + '</h2><p>' + tr(
        "交通、旗号、轮胎、天气、油量与驾驶意图没有全部确认。速度差不能直接证明技术错误，也不能把各段差异相加当作保证收益。没有视频佐证的路线或让车原因，仍需保留不确定性。",
        "Traffic, flags, tires, weather, fuel and intent remain confounders. Differences do not establish driver causation or guaranteed gains.") + '</p>')
    for hypothesis in coaching["hypotheses"]:
        if not any(key in zone_by_id for key in hypothesis["observation_ids"]):
            bodies.append(paragraphs(hypothesis["explanation"]))
            md += ["", hypothesis["explanation"]]
    bodies.append('</section>')
    bodies.append(calculation_details)
    if mini_md:
        md += ["", "<details>", "<summary>" + tr("计算依据", "Calculation details") + "</summary>",
               "", *mini_md, "", "</details>"]
    bodies.append('<details><summary>' + tr("查看圈次筛选和测量依据", "Inspect selection and evidence") + '</summary>')
    classifications = {"candidate_push": tr("候选快圈，意图未确认", "Pace candidate"),
                       "unclassified_slow": tr("较慢圈，原因未确认", "Unclassified slower lap"),
                       "confirmed_push": tr("已外部确认全力驾驶", "Confirmed push"),
                       "traffic": tr("已标注交通影响", "Traffic annotation"), "warmup": tr("已标注暖胎", "Warmup"),
                       "cooldown": tr("已标注冷却", "Cooldown")}
    for session in sessions.values():
        bodies.append(f'<h3>{_session_name(session, zh)}</h3><p>' + tr("候选圈：", "Candidates: ")
                      + "、".join(str(lap["lap"]) for lap in session["lap_selection"] if lap["coaching_eligible"]) + '</p><ul>')
        for stint in session["stints"]:
            stats = stint["consistency"]
            bodies.append('<li>' + tr(f"记录段 {stint['stint']}：{stats['count']} 个计时圈；最快 {_time(stats.get('best_s'))}。",
                                     f"Stint {stint['stint']}: {stats['count']} timed laps; best {_time(stats.get('best_s'))}.") + '</li>')
        bodies.append('</ul><p class="note">' + tr("记录段编号沿用记录器；没有计时圈不代表没有录制。", "Recorder stint identifiers are preserved; no timed laps does not mean no recording.") + '</p><table><thead><tr><th>'
                      + tr("圈次", "Lap") + '</th><th>' + tr("筛选状态", "Status") + '</th></tr></thead><tbody>')
        bodies.extend(f'<tr><td>{lap["lap"]}</td><td>{classifications.get(lap["classification"], tr("未确认", "Unconfirmed"))}</td></tr>' for lap in session["lap_selection"])
        bodies.append('</tbody></table>')
        for comparison in evidence["comparisons"]:
            if comparison["session"] == session["index"] and comparison.get("coaching_eligible") and comparison.get("possible_interruption_sectors"):
                bodies.append('<p class="note">' + tr(
                    f"第 {comparison['lap']} 圈存在局部集中损失，原因未确认；对应区段未用于技术排名。不能自动认定为交通或技术失误。",
                    f"Lap {comparison['lap']} has unresolved concentrated loss; affected sectors are withheld from technique ranking.") + '</p>')
    bodies.append('<p><a href="evidence.json">' + tr("完整测量数据（JSON）", "Full measurement evidence (JSON)") + '</a></p></details>')
    css = """body{margin:0;background:#f3f5f6;color:#26343c;font:17px/1.8 'Microsoft YaHei','PingFang SC',sans-serif}main{max-width:1050px;margin:auto;padding:46px 28px}header{padding:12px 0 24px;border-bottom:4px solid #243c49}h1{font-size:clamp(28px,5vw,44px);line-height:1.3;margin:12px 0 24px}h2{font-size:27px;line-height:1.5;margin:0 0 20px}h3{font-size:19px;margin:24px 0 8px}p{max-width:48em;margin:12px 0}.brand,.note,figcaption{color:#5a6a73;font-size:14px}.brand{letter-spacing:.12em}section{padding:36px 0;border-bottom:1px solid #ced7dc}svg{width:100%;height:auto;display:block;background:white;border-radius:5px}svg text{font-family:'Microsoft YaHei',sans-serif}table{border-collapse:collapse;width:100%;background:white;font-variant-numeric:tabular-nums}td,th{text-align:left;border-bottom:1px solid #dce3e7;padding:13px}th{font-size:14px;color:#52636e}a{color:#126d82}.map-key{display:flex;gap:20px;flex-wrap:wrap;margin:18px 0}.map-key a{color:var(--zone);font-weight:bold;text-decoration:none}.letter{display:inline-grid;place-items:center;background:var(--zone);color:white;width:40px;height:40px;margin-right:12px;font-size:23px;border-radius:50%}.zone-layout{display:grid;grid-template-columns:1fr 1fr;gap:28px;align-items:center}.finding{font-size:24px;line-height:1.5;color:var(--zone);font-weight:700}figure{margin:24px 0}figcaption{margin-top:8px}.driver{color:#ba4a20}.reference{color:#126d82}.practice{padding:8px 24px 22px;margin:24px 0;background:white;border-left:4px solid #126d82}dt{font-weight:bold;color:#344d5a;margin-top:16px}dd{margin:4px 0}details{margin:30px 0;font-size:14px}summary{cursor:pointer;font-size:17px}header p{max-width:45em}@media(max-width:650px){main{padding:24px 16px}.zone-layout{grid-template-columns:1fr}table{font-size:13px}td,th{padding:8px}h2{font-size:23px}.practice{padding:8px 15px 20px}}@media print{body{background:white}main{padding:0}.zone,.practice{break-inside:avoid}details{display:none}}"""
    css += '.sector-matrix{overflow-x:auto;margin-top:25px}.sector-matrix table{font-size:12px;white-space:nowrap}.sector-matrix td,.sector-matrix th{padding:6px;min-width:37px}.sector-matrix th:first-child{position:sticky;left:0;background:#f3f5f6;min-width:110px}.notice{border-left:4px solid #ba4a20;padding:12px 18px;background:#fff3e7}'
    css += '.route-canvas{height:760px;max-height:85vh;min-height:420px;touch-action:none;cursor:grab;overflow:hidden}.route-canvas:active{cursor:grabbing}.route-toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:15px}.route-toolbar button{font:inherit;padding:8px 16px;background:white;border:1px solid #9baeb7;border-radius:5px;cursor:pointer}.input-traces figure{margin:16px 0}.input-analysis{border-left:3px solid #126d82;padding:1px 20px;margin:18px 0;background:#fff}.input-traces{clear:both}'
    from .corner_report import ROUTE_SCRIPT

    document = f'<!doctype html><html lang="{"zh-CN" if zh else "en"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_escape(title)}</title><style>{css}</style></head><body><main>' + "".join(bodies) + '</main>' + ROUTE_SCRIPT + '</body></html>'
    md += ["", tr("路线、横纵向 G 和控制输入图见同目录 report.html；完整测量见 evidence.json。", "See report.html for routes, lateral/longitudinal G and control figures; full measurements are in evidence.json.")]
    return "\n".join(md), document
