"""Inline trajectory and measured acceleration figures for corner evidence."""
import html

import numpy as np


def _route_view(passages, selected, baseline, donor, label, zh):
    points = [point for p in selected for path in p.get("gps_core_paths", p["gps_paths"]) for point in path]
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
                          ("reset", text("本段特写", "Target detail")), ("context", text("查看前后弯", "Context"))):
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
    length = max(1., 10 ** np.floor(np.log10(width / 6)))
    x, y, font = x0 + width * .07, y0 + height * .93, width / 48
    pieces.append(f'<path d="M{x:.3f},{y:.3f}h{length:.3f}" stroke="#26343c" stroke-width="3" vector-effect="non-scaling-stroke"/>'
                  f'<text x="{x:.3f}" y="{y-font:.3f}" font-size="{font:.3f}">{length:g} m</text>')
    pieces.append('</svg><figcaption>' + text(
        f"共 {len(passages)} 次通过。橙：整圈最快；蓝：本段最快；灰：其他圈。默认放大目标段，可用按钮缩放、拖动平移，再切换前后弯。北朝上，横纵比例一致；路线散布包含 GPS 漂移，不是赛道边界。",
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
    pieces = [_route_view(passages, selected, baseline, donor, label, zh)]
    timing = observation["corner_passages"].get("timing_check", {})
    if timing:
        difference = timing["context_difference_s"]
        message = (f"把前后相邻段一起算：整圈最快圈相对该来源圈{'慢' if difference >= 0 else '快'} {abs(difference):.3f} 秒。单段差异不能直接作为可拿回的时间。"
                   if zh else f"Adjoining-window signed deficit: {difference:+.3f} s. A sector deficit alone is not a recoverable gain.")
        pieces.insert(0, '<p class="notice">' + message + '</p>')
    lo = observation["corner_passages"]["context_start_progress"]
    hi = observation["corner_passages"]["context_end_progress"]
    charts = [("speed_kmh", "速度 · 公里/小时" if zh else "Speed · km/h")]

    for name, title in (("brake_pressure_kpa", "制动压力 · kPa" if zh else "Brake pressure · kPa"),
                        ("brake_pos_pct", "制动踏板 · %" if zh else "Brake position · %"),
                        ("steering_deg", "方向盘角度 · 度" if zh else "Steering · degrees"),
                        ("accelerator_pct", "加速踏板 · %" if zh else "Accelerator pedal · %"),
                        ("throttle_pct", "节气门体 · %" if zh else "Throttle body · %")):
        if any(name in p.get("controls", {}) for p in selected):
            charts.append((name, title))
    charts += [("lat_g", "横向 G" if zh else "Lateral G"), ("long_g", "纵向 G" if zh else "Longitudinal G")]
    pieces.append('<h3>' + ("动作与车辆响应：同一位置，逐层对照" if zh else "Controls and response at matched locations") + '</h3><div class="input-traces">')
    analysis = {"braking_analysis": ("刹车：起点、力度与松刹", "Braking: onset, pressure and release"),
                "steering_analysis": ("转向：建立、转换与回正", "Steering: build-up, transition and unwind"),
                "power_analysis": ("油门：踏板动作与动力衔接", "Power: pedal and response")}
    written = set()
    def explain(key):
        if key in written or not description.get(key):
            return
        written.add(key)
        title = analysis[key][0 if zh else 1]
        pieces.append('<article class="input-analysis"><h3>' + title + '</h3><p>'
                      + html.escape(description[key]) + '</p></article>')
    for name, title in charts:
        if name in ("brake_pressure_kpa", "brake_pos_pct"):
            explain("braking_analysis")
        elif name == "steering_deg":
            explain("steering_analysis")
        elif name in ("accelerator_pct", "throttle_pct"):
            explain("power_analysis")
        def trace(p):
            if name in ("lat_g", "long_g"):
                return [(s["time_s"], s["progress"], s[name]) for s in p["g_samples"]]
            return [(s["time_s"], s["progress"], s["value"]) for s in p.get("controls", {}).get(name, {}).get("samples", [])]

        samples = [v for p in selected for _, _, v in trace(p) if v is not None]
        pieces.append('<figure><h3>' + title + '</h3>')
        for p in selected:
            if not any(v is not None for _, _, v in trace(p)):
                pieces.append('<p class="note">' + html.escape(label(p["session"], p["lap"])) +
                              ("：此通道缺失或未通过质量检查。" if zh else ": channel missing or quality check failed.") + '</p>')
        if not samples:
            message = ("缺少来源和质量合格的实测 G，无法比较。" if name in ("lat_g", "long_g") else "缺少可比较的控制记录。") if zh else "Comparable verified samples unavailable."
            pieces.append('<p>' + message + '</p></figure>')
            continue
        lower, upper = min(samples), max(samples)
        if name in ("accelerator_pct", "throttle_pct", "brake_pos_pct"):
            lower, upper = 0., max(100., upper)
        elif name in ("lat_g", "long_g", "steering_deg"):
            upper = max(.2, max(abs(lower), abs(upper))) * 1.1
            lower = -upper
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
        pieces.append('<text x="60" y="215">' + ("前一区段 → 高亮区段 → 后一区段（物理位置对齐）" if zh else "Previous → target → following sector, physically aligned") + '</text></svg></figure>')
    for key in analysis:
        explain(key)
    pieces.append('</div>')
    pieces.append('<p class="note">'  + ("所有曲线都包含前后相邻区段，浅色带才是目标计时段；本段差与前后合计差分别列出。路线默认只放大目标段，可切换前后弯。G 是记录到的加速度，不代表轮胎抓地极限；坡度、倾角和传感器安装都会影响读数。"
                  if zh else "Traces include adjacent sectors; shading marks the target. Sector and context deficits are reported separately. The route opens at the target with a context option. Measured G is not available grip; grade, banking and mounting affect readings.") + '</p>')
    return "".join(pieces)
