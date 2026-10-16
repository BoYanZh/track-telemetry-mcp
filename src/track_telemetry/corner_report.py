"""Inline trajectory and measured acceleration figures for corner evidence."""
import html

import numpy as np


def _route_view(passages, selected, baseline, donor, label, zh, *, shape_check=None):
    points = [point for p in selected for path in p.get("gps_cause_paths", p.get("gps_core_paths", p["gps_paths"])) for point in path]
    if not points:
        return ""
    def bounds(points):
        xs, ys = np.array(points).T
        width, height = max(np.ptp(xs) * 1.2, 25), max(np.ptp(ys) * 1.2, 25)
        width = max(width, height * 760 / 740)
        height = max(height, width * 740 / 760)
        cx, cy = (min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2
        return f"{cx-width/2:.3f} {cy-height/2:.3f} {width:.3f} {height:.3f}"
    initial = bounds(points)
    context = bounds([point for p in passages for path in p["gps_paths"] for point in path])
    def text(cn, en):
        return cn if zh else en
    pieces = ['<figure class="route-view"><h3>' + text("每次过弯的真实路线", "Every recorded passage")
              + '</h3><div class="route-toolbar">']
    for action, title in (("in", text("放大 ＋", "Zoom in")), ("out", text("缩小 −", "Zoom out")),
                          ("reset", text("相关弯道", "Related corner")), ("context", text("弯道与后续路段", "Corner and downstream"))):
        pieces.append(f'<button type="button" data-route-action="{action}">{title}</button>')
    pieces.append('</div><svg class="route-canvas" viewBox="' + initial + '" data-initial="' + initial
                  + '" data-context="' + context + '" role="img" aria-label="GPS passages">')
    for index, p in enumerate(passages + selected):
        key = p["session"], p["lap"]
        highlight = index >= len(passages)
        color = "#ba4a20" if key == baseline else "#126d82" if key == donor else "#98a6ad"
        for path in p["gps_paths"]:
            d = " ".join(("M" if i == 0 else "L") + f"{x:.3f},{-y:.3f}" for i, (x, y) in enumerate(path))
            pieces.append(f'<path d="{d}" fill="none" stroke="{color}" vector-effect="non-scaling-stroke" '
                          f'stroke-width="{2.5 if highlight else 1}" opacity="{1 if highlight else .2}"><title>'
                          + html.escape(label(p["session"], p["lap"])) + '</title></path>')
    x0, y0, width, height = map(float, initial.split())
    for row in (shape_check or {}).get("passes", []):
        key = row["session"], row["lap"]
        if key not in (baseline, donor):
            continue
        fit = row.get("minimum_fitted_radius_by_span_m", {}).get("30.0")
        if fit:
            color = "#ba4a20" if key == baseline else "#126d82"
            title = text("局部最紧处候选，30米GPS圆拟合半径约", "Local tightest candidate, 30 m GPS fit radius ~") + f"{fit['radius_m']:.0f} m"
            pieces.append(f'<circle cx="{fit["x_m"]:.3f}" cy="{-fit["y_m"]:.3f}" r="{width*.009:.3f}" '
                          f'fill="{color}" stroke="white" stroke-width="2" vector-effect="non-scaling-stroke"><title>{html.escape(title)}</title></circle>')
    length = max(1., 10 ** np.floor(np.log10(width / 6)))
    x, y, font = x0 + width * .07, y0 + height * .93, width / 48
    pieces.append(f'<path d="M{x:.3f},{y:.3f}h{length:.3f}" stroke="#26343c" stroke-width="3" vector-effect="non-scaling-stroke"/>'
                  f'<text x="{x:.3f}" y="{y-font:.3f}" font-size="{font:.3f}">{length:g} m</text>')
    pieces.append('</svg><figcaption>' + text(
        f"共 {len(passages)} 次通过。橙：整圈最快；蓝：本段最快；灰：其他圈。默认查看相关上游动作，可放大、平移或展开后续路段。北朝上，横纵比例一致；路线散布包含 GPS 漂移，不是赛道边界。",
        "Orange: best whole lap; blue: sector donor; grey: other passages. Zoom buttons and drag to pan. North up, equal scale. Scatter includes GPS drift; these are not track boundaries.") + '</figcaption></figure>')
    return "".join(pieces)


ROUTE_SCRIPT = """<script id="route-controls">
document.querySelectorAll('.route-view').forEach(figure => {
 const svg = figure.querySelector('svg');
 const read = () => svg.getAttribute('viewBox').split(/\\s+/).map(Number);
 const set = v => svg.setAttribute('viewBox', v.join(' '));
 figure.querySelectorAll('[data-route-action]').forEach(button => button.addEventListener('click', () => {
  const action = button.dataset.routeAction;
  if (action === 'reset' || action === 'context') {
   svg.setAttribute('viewBox', svg.dataset[action === 'reset' ? 'initial' : 'context']); return;
  }
  const v = read(), factor = action === 'in' ? .65 : 1/.65;
  if (v[2]*factor < 5 || v[2]*factor > 10000) return;
  set([v[0]+v[2]*(1-factor)/2, v[1]+v[3]*(1-factor)/2, v[2]*factor, v[3]*factor]);
 }));
 let drag = null;
 svg.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  drag = {x:event.clientX,y:event.clientY,v:read()}; svg.setPointerCapture(event.pointerId);
 });
 svg.addEventListener('pointermove', event => {
  if (!drag) return;
  const box=svg.getBoundingClientRect(), scale=Math.max(drag.v[2]/box.width,drag.v[3]/box.height);
  set([drag.v[0]-(event.clientX-drag.x)*scale,drag.v[1]-(event.clientY-drag.y)*scale,drag.v[2],drag.v[3]]);
 });
 ['pointerup','pointercancel','lostpointercapture'].forEach(name=>svg.addEventListener(name,()=>{drag=null;}));
});
</script>"""


def render_corner(observation, label, zh, *, description=None):
    description = description or {}
    passages = observation.get("corner_passages", {}).get("passages", [])
    if not passages:
        return ""
    baseline = observation["example_session"], observation["example_lap"]
    donor = observation["section_reference"]
    donor = donor["session"], donor["lap"]
    selected = [p for key in (baseline, donor) for p in passages if (p["session"], p["lap"]) == key]
    pieces = [_route_view(passages, selected, baseline, donor, label, zh, shape_check=observation.get("route_shape_check"))]
    if description.get("line_analysis"):
        pieces.append('<p class="line-finding"><strong>' + ("走线：" if zh else "Line: ")
                      + '</strong>' + html.escape(description["line_analysis"]) + '</p>')
    timing = observation["corner_passages"].get("timing_check", {})
    if timing:
        difference = timing["context_difference_s"]
        message = (f"关联窗口合计：整圈最快圈相对来源圈{'慢' if difference >= 0 else '快'} {abs(difference):.3f} 秒。"
                   if zh else f"Linked-window signed deficit: {difference:+.3f} s.")
        if "upstream_difference_s" in timing:
            parts = [("上游动作", "Upstream", timing["upstream_difference_s"]),
                     ("目标计时段", "Target", timing["core_difference_s"]),
                     ("后续路段", "Downstream", timing["downstream_difference_s"])]
            message += " / ".join(f"{cn if zh else en} {value:+.3f}s" for cn, en, value in parts)
        chain = observation["corner_passages"].get("chain_window", {})
        if chain.get("method") == "braking_to_next_braking":
            message += ("；截至圈末，未跨圈追踪。" if chain["end_progress"] >= 1 else "；截至两圈较早的下一次制动前。") if zh else ""
            if not chain.get("upstream_events_overlap_on_reference") and zh:
                message += "上游制动事件未确认对应，需复核。"
        elif chain.get("method") == "fixed_context_fallback" and zh:
            message += "未识别到可靠动作边界，当前仅为邻近窗口。"
        pieces.insert(0, '<p class="notice">' + message + '</p>')
    lo = observation["corner_passages"]["context_start_progress"]
    hi = observation["corner_passages"]["context_end_progress"]
    def common(preferred, fallback):
        return preferred if all(preferred in p.get("controls", {}) for p in selected) else (
            fallback if all(fallback in p.get("controls", {}) for p in selected) else preferred)
    power = common("accelerator_pct", "throttle_pct")
    brake = common("brake_pressure_kpa", "brake_pos_pct")
    charts = [(power, ("油门 · 加速踏板 %" if power == "accelerator_pct" else "油门 · 节气门体 %") if zh else power),
              (brake, ("刹车 · 压力 bar" if brake == "brake_pressure_kpa" else "刹车 · 踏板 %") if zh else brake),
              ("steering_deg", "转向 · 度" if zh else "Steering · degrees"),
              ("combined_g", "总 G · 平面合成" if zh else "Combined G · planar")]
    pieces.append('<div class="input-traces">')
    analysis = {"braking_analysis": "", "steering_analysis": "", "power_analysis": "", "g_analysis": ""}
    written = set()
    def explain(key):
        if key in written or not description.get(key):
            return
        written.add(key)
        pieces.append('<article class="input-analysis"><p>'
                      + html.escape(description[key]) + '</p></article>')
    for name, title in charts:
        if name in ("brake_pressure_kpa", "brake_pos_pct"):
            explain("braking_analysis")
        elif name == "steering_deg":
            explain("steering_analysis")
        elif name in ("accelerator_pct", "throttle_pct"):
            explain("power_analysis")
        elif name == "combined_g":
            explain("g_analysis")
        def trace(p):
            if name == "combined_g":
                return [(s["time_s"], s["progress"], float(np.hypot(s["lat_g"], s["long_g"]))) for s in p["g_samples"]]
            return [(s["time_s"], s["progress"], (s["value"] / 100 if name == "brake_pressure_kpa" and s["value"] is not None else s["value"]))
                    for s in p.get("controls", {}).get(name, {}).get("samples", [])]

        samples = [v for p in selected for _, _, v in trace(p) if v is not None]
        pieces.append('<figure><h3>' + title + '</h3>')
        for p in selected:
            if not any(v is not None for _, _, v in trace(p)):
                pieces.append('<p class="note">' + html.escape(label(p["session"], p["lap"])) +
                              ("：此通道缺失或未通过质量检查。" if zh else ": channel missing or quality check failed.") + '</p>')
        if not samples:
            message = ("缺少来源和质量合格的实测 G，无法比较。" if name == "combined_g" else "缺少可比较的控制记录。") if zh else "Comparable verified samples unavailable."
            pieces.append('<p>' + message + '</p></figure>')
            continue
        lower, upper = min(samples), max(samples)
        if name in ("accelerator_pct", "throttle_pct", "brake_pos_pct"):
            lower, upper = 0., max(100., upper)
        elif name == "steering_deg":
            upper = max(.2, max(abs(lower), abs(upper))) * 1.1
            lower = -upper
        elif name == "combined_g":
            lower, upper = 0., max(.2, upper * 1.1)
        else:
            padding = max(1., (upper - lower) * .08)
            lower, upper = max(0., lower - padding), upper + padding
        def ordinate(value):
            return 180 - (value - lower) / (upper - lower) * 150
        pieces.append('<svg viewBox="0 0 760 230" role="img" aria-label="' + title + '">')
        target_lo = 60 + (observation["physical_section_profile"][0]["progress"] - lo) / (hi-lo) * 670
        target_width = (observation["physical_section_profile"][-1]["progress"] - observation["physical_section_profile"][0]["progress"]) / (hi-lo) * 670
        pieces.append(f'<rect x="{target_lo:.1f}" y="25" width="{target_width:.1f}" height="160" fill="#f1eadb"/>')
        for value in (lower, (lower+upper)/2, upper):
            y = ordinate(value)
            pieces.append(f'<path d="M60,{y:.1f}H730" stroke="#dbe2e6"/><text x="50" y="{y+5:.1f}" text-anchor="end">{value:.2f}</text>')
        for p, color in zip(selected, ("#ba4a20", "#126d82")):
            d, previous = [], None
            for time, progress, value in trace(p):
                if value is None:
                    previous = None
                    continue
                # G samples use physical alignment only for their horizontal location.
                connected = previous is not None and 0 < time - previous <= .25
                d.append(("L" if connected else "M") + f'{60+(progress-lo)/(hi-lo)*670:.1f},{ordinate(value):.1f}')
                previous = time
            pieces.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="2"/>')
        pieces.append('<text x="60" y="215">' + ("上游动作 → 目标段 → 后续加速" if zh else "Previous → target → following sector, physically aligned") + '</text></svg></figure>')
    for key in analysis:
        explain(key)
    pieces.append('</div>')
    pieces.append('<p class="note">' + ("浅色带是发现差距的计时段，不代表问题所在弯道；总 G = √(横向 G² + 纵向 G²)，不是抓地极限。" if zh else "Shading marks the target. Combined G = hypot(lateral G, longitudinal G), not available grip.") + '</p>')
    return "".join(pieces)
