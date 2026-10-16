"""Inline trajectory and measured acceleration figures for corner evidence."""
import html

import numpy as np


def render_corner(observation, label, zh):
    passages = observation.get("corner_passages", {}).get("passages", [])
    if not passages:
        return ""
    baseline = observation["example_session"], observation["example_lap"]
    donor = observation["section_reference"]
    donor = donor["session"], donor["lap"]
    selected = [p for key in (baseline, donor) for p in passages if (p["session"], p["lap"]) == key]
    points = [point for p in passages for path in p["gps_paths"] for point in path]
    if not points:
        return ""
    xs, ys = np.array(points).T
    scale = min(640 / max(np.ptp(xs), 1), 330 / max(np.ptp(ys), 1))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    pieces = ['<figure><h3>' + ("每次过弯的真实路线" if zh else "Every recorded passage")
              + '</h3><svg viewBox="0 0 760 410" role="img" aria-label="GPS passages">']
    for index, p in enumerate(passages + selected):
        key = p["session"], p["lap"]
        highlight = index >= len(passages)
        # Draw all muted first, then selected traces on top.
        color = "#ba4a20" if key == baseline else "#126d82" if key == donor else "#98a6ad"
        title = html.escape(label(p["session"], p["lap"]))
        for path in p["gps_paths"]:
            d = " ".join(("M" if i == 0 else "L") + f"{380 + (x-cx)*scale:.2f},{205-(y-cy)*scale:.2f}"
                         for i, (x, y) in enumerate(path))
            pieces.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{2.5 if highlight else 1}" opacity="{1 if highlight else .25}"><title>{title}</title></path>')
    pieces.append('</svg><figcaption>' + (f"共 {len(passages)} 次实际通过。橙：整圈最快；蓝：本段最快；灰：其他圈。北朝上、等比例；轨迹散布包含 GPS 漂移，不能据此断言赛车线优劣。"
                   if zh else "Orange: best whole lap; blue: sector donor; grey: other passages. Equal scale, north up. GPS scatter includes drift.") + '</figcaption></figure>')
    lo = observation["corner_passages"]["context_start_progress"]
    hi = observation["corner_passages"]["context_end_progress"]
    charts = [("lat_g", "横向 G" if zh else "Lateral G"), ("long_g", "纵向 G" if zh else "Longitudinal G")]
    for name, title in (("accelerator_pct", "加速踏板 · %" if zh else "Accelerator pedal · %"),
                        ("throttle_pct", "节气门体 · %" if zh else "Throttle body · %"),
                        ("brake_pressure_kpa", "制动压力 · kPa" if zh else "Brake pressure · kPa"),
                        ("steering_deg", "方向盘角度 · 度" if zh else "Steering · degrees")):
        if any(name in p.get("controls", {}) for p in selected):
            charts.append((name, title))
    pieces.append('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px">')
    for chart_index, (name, title) in enumerate(charts):
        if chart_index == 2:
            pieces.append('</div><details><summary>' + ("查看踏板、节气门、制动与转向" if zh else "Inspect controls") + '</summary>')
        def trace(p):
            if name in ("lat_g", "long_g"):
                return [(s["time_s"], s["progress"], s[name]) for s in p["g_samples"]]
            return [(s["time_s"], s["progress"], s["value"]) for s in p.get("controls", {}).get(name, {}).get("samples", [])]

        samples = [v for p in selected for _, _, v in trace(p) if v is not None]
        pieces.append('<figure><h3>' + title + '</h3>')
        if not samples:
            pieces.append('<p>' + ("缺少来源和质量合格的实测 G，无法比较。" if zh else "Verified measured G unavailable.") + '</p></figure>')
            continue
        extent = max(.2, max(abs(v) for v in samples)) * 1.1
        pieces.append('<svg viewBox="0 0 760 230" role="img" aria-label="' + title + '">')
        target_lo = 60 + (observation["physical_section_profile"][0]["progress"] - lo) / (hi-lo) * 670
        target_width = (observation["physical_section_profile"][-1]["progress"] - observation["physical_section_profile"][0]["progress"]) / (hi-lo) * 670
        pieces.append(f'<rect x="{target_lo:.1f}" y="25" width="{target_width:.1f}" height="160" fill="#f1eadb"/>')
        for value in (-extent, 0, extent):
            y = 105 - value / extent * 75
            pieces.append(f'<path d="M60,{y:.1f}H730" stroke="#dbe2e6"/><text x="50" y="{y+5:.1f}" text-anchor="end">{value:.2f}</text>')
        for p, color in zip(selected, ("#ba4a20", "#126d82")):
            d, previous = [], None
            for time, progress, value in trace(p):
                if value is None:
                    previous = None
                    continue
                # G samples use physical alignment only for their horizontal location.
                connected = previous is not None and 0 < time - previous <= .25
                d.append(("L" if connected else "M") + f'{60+(progress-lo)/(hi-lo)*670:.1f},{105-value/extent*75:.1f}')
                previous = time
            pieces.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="2"/>')
        pieces.append('<text x="60" y="215">' + ("前一区段 → 高亮区段 → 后一区段（物理位置对齐）" if zh else "Previous → target → following sector, physically aligned") + '</text></svg></figure>')
    pieces.append('</details>' if len(charts) > 2 else '</div>')
    pieces.append('<p class="note">'  + ("路线和 G 图包含前后相邻区段，速度图和计时差只对应高亮区段。G 是记录到的加速度，不代表轮胎抓地极限；坡度、倾角和传感器安装都会影响读数。"
                  if zh else "Route and G include adjacent sectors; speed and timing cover the highlighted sector. Measured G is not available grip; grade, banking and mounting affect readings.") + '</p>')
    return "".join(pieces)
