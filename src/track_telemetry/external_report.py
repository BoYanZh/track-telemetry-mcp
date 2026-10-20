"""Render external scan separately from the agent's practice priority."""
import datetime
import html
import re

import numpy as np

from .speed_minima import place_label, speed_minima_indices


def _filename_date(name):
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", name or "")
    if not match:
        return None
    return datetime.date(int(match[1]), int(match[2]), int(match[3]))


def render_external_scan(scan, coaching, evidence, zh, *, route_only_id=None, include_speed_evidence=False):
    from .coaching_report import _map
    def tr(cn, en):
        return cn if zh else en
    windows = {w["id"]: w for w in scan["windows"]}
    ranked = [windows[key] for key in scan["observed_difference_ranking"]]
    selected = {key for p in coaching.get("experiments", []) for key in p["observation_ids"]}
    descriptions = {s["observation_id"]: s for s in coaching.get("sections", [])}
    decisions = {d["observation_id"]: d for d in scan.get("practice_decisions", [])}
    selected |= set(descriptions) & set(windows)
    from .external_screening import rank_linked_candidates
    candidates, focuses = rank_linked_candidates(scan)
    summaries = {item["window"]["id"]: item for item in candidates}
    ranked = [item["window"] for item in candidates]
    focus = [item["window"] for item in focuses]
    coached = [w for w in ranked if w["id"] in set(scan.get("practice_ranking", []))]
    focus = coached + [w for w in focus if w["id"] not in {x["id"] for x in coached}]
    priorities = {item["window"]["id"]: i for i, item in enumerate(focuses, 1)}
    focus_keys = {w["id"] for w in focus}
    remaining = [w for w in ranked if w["id"] not in focus_keys]
    pieces = ['<section id="external-scan"><h2>' + tr("高手对照：先看这几个位置", "Reference comparison: start here") + '</h2><p>' + tr(
        f"按参考车手多次快圈的典型时间差排序，先展开{len(focus)}处；教练指定的练习位置排在最前。入口状态和练习动作在各处说明。",
        "Start with four improvement candidates. Linked differences cover entry, target and downstream acceleration; they guide opportunity assessment. Overlapping differences are not additive.") + '</p>'
              '<p class="note">' + tr("口径说明：S号是20等分物理区段，与拼接矩阵的区段号同一套；“最大单圈差”是核心窗口内相对本日基线圈的单圈最大值，“典型关联差”是含上下游的整段关联窗口多圈中位值（窗口更大，数值可以更大）。A–F是自车机会排序，括号内标注对应的S号。",
                                     "Sectors share one 20-way physical grid with the sector matrix; largest single-lap gap is the core-window max, typical gap the wider linked-window median.") + '</p>']
    md = ['## ' + tr("高手对照：先看这几个位置", "Reference comparison: start here"), '',
          tr("口径：S号与拼接矩阵区段号是同一套20等分物理分段；“最大单圈差”取核心窗口内相对本日基线圈的单圈最大值，"
             "“典型关联差”取含上下游的整段关联窗口多圈中位值（窗口更大，数值可以更大，两者不是同一窗口的统计量）。",
             "Sectors share one 20-way grid with the sector matrix; largest gap is the single-lap max in the core window, typical gap the median over the wider linked window.") + tr(
             " 练习位置一旦选定，暂缓列中同位置条目自动移出并注记。",
             " Practiced sectors are excluded from the deferred list."), '']
    own_date = _filename_date((evidence.get("sessions") or [{}])[0].get("summary", {}).get("source_name", ""))
    stale = sorted({(r.get("summary", {}).get("source_name", "?"), abs((_filename_date(r.get("summary", {}).get("source_name", "")) - own_date).days))
                    for r in scan.get("references", []) if own_date and _filename_date(r.get("summary", {}).get("source_name", ""))},
                   key=lambda item: -item[1])
    if stale and stale[0][1] > 180:
        names = "、".join(f"{name}（相隔约{days}天）" for name, days in stale)
        warning = tr(f"注意：参照与本日相隔较久（{names}），车辆、轮胎与气温可能不可比，差距数字仅供方向参考。",
                     f"Note: the reference is much older/newer than this session ({names}); treat gaps as directional only.")
        pieces.append('<p class="notice">' + html.escape(warning) + '</p>')
        md += [warning, '']
    md += [tr("口径：S号与拼接矩阵区段号是同一套20等分物理分段；“最大单圈差”取多次参照通过相对本日基线圈的最大值，“典型关联差”取多次通过的中位值。",
              "Sectors share one 20-way grid with the sector matrix; largest gap is the max over reference passages, typical gap its median."), '']

    def table(items):
        rows = ['<table><tr><th>'+tr('位置','Location')+'</th><th>'+tr('典型关联窗口差','Typical linked difference')+'</th><th>'+tr('下节怎么练','Next-session cue')+'</th></tr>']
        for w in items:
            decision = decisions.get(w['id'])
            state = (decision.get('cue') if decision else None) or descriptions.get(w['id'], {}).get('cue') or tr('纳入对照，供参考', 'Listed for reference')
            rows.append(f'<tr><td><a href="#{w["id"]}">{str(priorities[w["id"]])+" · " if w["id"] in priorities else ""}S{w["sector"]:02}</a></td><td>{summaries[w["id"]]["typical_difference_s"]:+.2f} '+tr('秒','s')+'</td><td>'+html.escape(state)+'</td></tr>')
        rows.append('</table>')
        return ''.join(rows)

    pieces.append(table(focus))
    pieces.append('<details><summary>'+tr('排序怎么算','Ranking method')+'</summary><p>'+tr('先筛参考车手自身最快圈后max(1秒，2%)以内的候选圈，再用关联窗口差的中位数排序；优先保留至少两次更快的区域，并合并高度重叠窗口。这个筛选只表示配速相近。','Use reference pace candidates within best + max(1 s, 2%), rank median linked differences with repeated positive support, and merge overlapping windows.')+'</p></details>')
    for w in focus:
        p = summaries[w['id']]['representative']
        typical = summaries[w['id']]['typical_difference_s']
        best = next((o.get("values", {}).get("best_core_difference_s")
                     for o in evidence.get("observations", []) if o.get("id") == w["id"]), None)
        gap = f'{best:.2f} ' if best is not None else ''
        state = decisions.get(w['id'], {}).get('cue') or descriptions.get(w['id'], {}).get('cue') or tr('纳入对照，供参考', 'Listed for reference')
        md.append(f'- S{w["sector"]:02}: '+tr('本段最大单圈慢 ', 'Largest single-lap local difference ')+gap
                  +tr('秒（典型关联差 ', 's (typical linked ')+f'{typical:.2f} '+tr('秒）。','s). ')+state
                  + tr(f'（路线与速度曲线见 report.html #{w["id"]}）', f' (see report.html #{w["id"]})'))
    pieces.append('<p>'+tr('橙色：你；蓝色：参考；灰色：其它圈路线；浅黄：本段。','Orange: you; blue: reference; yellow: target segment.')+'</p>')
    detail_order = focus + remaining
    if route_only_id:
        detail_order = [w for w in detail_order if w['id'] == route_only_id]
        pieces = []
        remaining = []
    for rank, w in enumerate(detail_order):
        if remaining and rank == len(focus):
            pieces.append('<details class="external-other"><summary>'+tr(f'查看其余{len(remaining)}段',f'Other {len(remaining)} windows')+'</summary>'+table(remaining))
        p = summaries[w['id']]['representative']
        title = (tr(f'第{rank+1}优先 · ', f'Priority {rank+1} · ') if w['id'] in focus_keys else '') + f'S{w["sector"]:02} · ' + tr(f'高手参考{p["reference"]+1}第{p["lap"]}圈', f'Reference {p["reference"]+1}, lap {p["lap"]}')
        pieces.append(f'<details id="{w["id"]}"'+(' open' if route_only_id or w['id'] in focus_keys else '')+'><summary>'+title+'</summary>')
        zone = {"letter": f'S{w["sector"]:02}', "lo": w["start_progress"], "hi": w["end_progress"], "color": "#126d82"}
        pieces.append(_map(evidence, [zone], zh))
        original_grid = np.asarray(w['grid_m'])
        endpoint = p.get('linked_end_m', original_grid[-1])
        display_grid = np.unique(np.r_[original_grid[original_grid < endpoint], endpoint])
        def shown(values):
            return np.interp(display_grid, original_grid, values)
        driver_route = np.asarray(w.get('driver_route_xy', w['route_xy']))
        if len(driver_route) == len(original_grid):
            xy = np.c_[shown(driver_route[:, 0]), shown(driver_route[:, 1])]
        else:
            xy = driver_route
        minima = []
        for values, color, label in (
                (w['baseline_signals']['speed_kmh'], '#c45b25', tr('你', 'You')),
                (p['signals']['speed_kmh'], '#126d82', tr('参考', 'Reference'))):
            speeds = shown(values)
            for number, index in enumerate(speed_minima_indices(speeds), 1):
                minima.append((index, color, label+f' Vmin{number}', float(speeds[index])))
        raw_reference = np.asarray(p['reference_route_xy'])
        ref_xy = np.c_[shown(raw_reference[:, 0]), shown(raw_reference[:, 1])]
        background = []
        for other in w.get('background_routes', []):
            raw = np.asarray(other['route_xy'])
            background.append(np.c_[shown(raw[:, 0]), shown(raw[:, 1])])
        for other in w['passages']:
            if other is p:
                continue
            raw = np.asarray(other['reference_route_xy'])
            background.append(np.c_[shown(raw[:, 0]), shown(raw[:, 1])])
        both = np.vstack([xy, ref_xy, *background])
        minimum = both.min(axis=0)
        span = max(float(np.ptp(both[:, 0])), float(np.ptp(both[:, 1])), 1.)
        coords = (xy-minimum)/span*500+40
        route = ' '.join(f'{a:.1f},{560-b:.1f}' for a,b in coords)
        ref_coords = (ref_xy-minimum)/span*500+40
        reference_route = ' '.join(f'{a:.1f},{560-b:.1f}' for a,b in ref_coords)
        grey_routes = ''
        for other in background:
            grey = (other-minimum)/span*500+40
            points = ' '.join(f'{a:.1f},{560-b:.1f}' for a,b in grey)
            grey_routes += '<polyline class="background-lap" fill="none" stroke="#999" stroke-opacity="0.35" stroke-width="1.5" points="'+points+'"/>'
        vmin_route = ''
        occupied = []
        for index, color, label, speed in minima:
            route_coords = coords if color == '#c45b25' else ref_coords
            a, b = route_coords[index]
            text = f'{label} {speed:.1f}'
            tx, ty = place_label(a+9, 560-b-10 if color == '#c45b25' else 560-b+22, text, occupied)
            vmin_route += (f'<line x1="{a:.1f}" y1="{560-b:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="{color}" stroke-opacity=".6"/>' + f'<g class="vmin-route"><circle cx="{a:.1f}" cy="{560-b:.1f}" r="6" fill="{color}" stroke="white" stroke-width="2"/>'
                           f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{color}" font-size="15">{label} {speed:.1f}</text></g>')
        pieces.append('<svg viewBox="0 0 600 600">'+grey_routes+'<polyline fill="none" stroke="#c45b25" stroke-width="3" points="'+route+'"/>'
                      + '<polyline fill="none" stroke="#126d82" stroke-width="3" points="'+reference_route+'"/>'
                      + vmin_route
                      + f'<text x="{coords[0,0]:.1f}" y="{560-coords[0,1]:.1f}">'+tr('入口 →','Entry →')+'</text>'
                      + f'<text x="{coords[-1,0]:.1f}" y="{560-coords[-1,1]:.1f}">'+tr('出口','Exit')+'</text></svg>')
        pieces.append('<p>'+tr('Vmin1、2…：按行驶顺序标出局部最低速，单位为公里/小时；同色虚线贯穿下方曲线。编号仅表示各圈先后顺序。',
                              'Vmin1, 2, ...: local speed minima in travel order per lap (km/h); matching dashed lines mark the same positions below. Numbers do not establish corner correspondence.')+'</p>')
        if route_only_id and not include_speed_evidence:
            pieces.append('</details>')
            return ''.join(pieces), []
        if route_only_id and include_speed_evidence:
            gap = summaries[w['id']]['typical_difference_s']
            pieces.append('<h3>'+tr('可争取的时间空间', 'Time opportunity')+f'：{gap:.2f} '+tr('秒', 's')+'</h3><p>'+tr(
                '这是整个弯组到下一次制动前，与参考多次快圈的典型差距；不是只改Vmin2就能全部拿回。',
                'Typical linked-window gap to repeated reference passes, not a predicted gain from one minimum.')+'</p>')
            pieces.append('<p>'+tr('橙色：你；蓝色：参考。下图按同一物理位置对齐，虚线对应路线图中的Vmin。',
                                  'Orange: you; blue: reference. Traces align by physical position; dashed lines locate route Vmin markers.')+'</p>')
        desc = descriptions.get(w['id'], {})
        for key in ('title', 'what_happened', 'interpretation', 'braking_analysis', 'steering_analysis',
                    'power_analysis', 'g_analysis', 'line_analysis', 'cue', 'watch_out'):
            if desc.get(key):
                pieces.append('<p>'+html.escape(desc[key])+'</p>')
        if 'upstream_difference_s' in p:
            pieces.append('<p>'+tr('差距从哪里来：进入本段前 ', 'Loss location: before target ')
                          +f'{p["upstream_difference_s"]:+.2f}'+tr('秒，本段新增 ', ' s; target ')
                          +f'{p["target_difference_s"]:+.2f}'+tr('秒，出弯后 ', ' s; after target ')
                          +f'{p["downstream_difference_s"]:+.2f}'+tr('秒。', ' s.')+'</p>')
            brake = p['target_entry_brake_kpa']
            if any(value is not None and value >= 100 for value in brake.values()):
                values = ' / '.join(f'{brake[key]/100:.1f}' if brake[key] is not None else '—'
                                    for key in ('driver', 'reference'))
                pieces.append('<p>'+tr('本段起点已涉及制动，压力（你/参考）：',
                                      'Braking is already involved at target entry (you/reference): ')+values+' bar。</p>')
            boundary = tr('计时止于两圈较早的下一次制动前。', 'Timing stops before the earlier next brake onset.') if p['linked_end_reason']=='before_next_braking' else tr('未找到下一次制动，暂以图示边界截止。', 'No next brake found; using the displayed screening boundary.')
            pieces.append('<p>'+boundary+'</p>')
        pieces.append('<p>'+tr('入口速度（你/参考）：' ,'Entry speed (you/reference): ')+f'{w["baseline_entry_speed_kmh"]:.1f}/{p["entry_speed_kmh"]:.1f} km/h; '
                      +tr('出口：','Exit: ')+f'{np.interp(endpoint, original_grid, w["baseline_signals"]["speed_kmh"]):.1f}/{p["exit_speed_kmh"]:.1f} km/h.</p>')
        names = [('speed_kmh',tr('速度 · 公里/小时','Speed · km/h')),
                 ('brake_pressure_kpa',tr('制动压力 · kPa','Brake · kPa')),
                 ('steering_deg',tr('转向 · 度','Steering · degrees')),
                 ('accelerator_pct',tr('加速踏板 · %','Accelerator pedal · %')),
                 ('combined_g',tr('平面总G','Planar combined G')),
                 ('delta',tr('本窗口新增时间差 · 秒','Incremental delta · s'))]
        if route_only_id and include_speed_evidence:
            names = [item for item in names if item[0] in ('speed_kmh', 'delta')]
        plot_grid = display_grid
        if route_only_id and include_speed_evidence:
            plot_grid = shown(w['baseline_times_s'])
            plot_grid = plot_grid-plot_grid[0]
            pieces.append('<p>'+tr('横轴：你的窗口经过时间（秒）；参考按相同赛道位置对齐。',
                                  'X: your elapsed window time (s); reference aligned at matching physical positions.')+'</p>')
        def plot_x(distance):
            position = np.interp(distance, display_grid, plot_grid)
            return 20+(position-plot_grid[0])/(plot_grid[-1]-plot_grid[0])*860
        for name, label in names:
            if name == 'delta':
                pairs = [(shown(p['delta_s']), '#654478')]
            elif name in w['baseline_signals'] and name in p['signals']:
                pairs = [(shown(w['baseline_signals'][name]), '#c45b25'), (shown(p['signals'][name]), '#126d82')]
            else:
                continue
            values = np.asarray([v for v, _ in pairs])
            lo = float(values.min())
            scale = max(float(np.ptp(values)), .01)
            pieces.append('<h3>'+label+'</h3><svg viewBox="0 0 900 190">')
            left, right = [plot_x(g) for g in w['core_limits_m']]
            pieces.append(f'<rect x="{left:.1f}" y="20" width="{right-left:.1f}" height="150" fill="#fff1be"/>')
            for vals, color in pairs:
                pts=' '.join(f'{plot_x(display_grid[i]):.1f},{170-(v-lo)/scale*140:.1f}' for i,v in enumerate(vals))
                pieces.append('<polyline fill="none" stroke="'+color+'" stroke-width="2" points="'+pts+'"/>')
            occupied = []
            for minimum_number, (index, color, label, speed) in enumerate(minima):
                marker_x = plot_x(display_grid[index])
                tx, ty = place_label(marker_x+5, 35+(minimum_number%2)*18,
                                     f'{label} {speed:.1f}', occupied, font=13., bounds=(20., 20., 895., 165.))
                pieces.append(f'<g class="vmin-marker" data-distance-m="{display_grid[index]:.6f}"><line x1="{marker_x:.1f}" x2="{marker_x:.1f}" y1="20" y2="170" stroke="{color}" stroke-dasharray="5 4"/>'
                              f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{color}" font-size="13">{label} {speed:.1f}</text></g>')
            if route_only_id and include_speed_evidence:
                for elapsed in np.linspace(plot_grid[0], plot_grid[-1], 5):
                    tick_x = 20+(elapsed-plot_grid[0])/(plot_grid[-1]-plot_grid[0])*860
                    pieces.append(f'<text x="{tick_x:.1f}" y="188" text-anchor="middle" font-size="12">{elapsed:.1f}s</text>')
            pieces.append(f'<text x="20" y="15">{lo:.2f}–{lo+scale:.2f}</text></svg>')
        if route_only_id:
            pieces.append('</details>')
            return ''.join(pieces), []
        if w['id'] in decisions:
            pieces.append('<details><summary>'+tr('优先级说明','Priority rationale')+'</summary><p>'+html.escape(decisions[w['id']]['reason'])+'</p></details>')
        pieces.append('<details><summary>'+tr('查看样本与计算','Samples and calculations')+'</summary><p>'+tr(
            f'参考车手{len(w["passages"])}次通过中，{w["positive_passages"]}次比你的基线快。前后路段合计差{p["linked_difference_s"]:+.3f}秒。',
            f'{w["positive_passages"]} of {len(w["passages"])} reference passages were faster. Linked difference {p["linked_difference_s"]:+.3f} s.')+'</p>')
        pieces.append('<table><tr><th>'+tr('同步位置','Shared marker')+'</th><th>'+tr('速度：你/参考','Speed: you/reference')+'</th><th>'+tr('刹车 kPa','Brake kPa')+'</th><th>'+tr('转向 度','Steering deg')+'</th><th>'+tr('总G','Combined G')+'</th></tr>')
        for index, marker in enumerate(p['markers'], 1):
            cells = [str(index)]
            for channel in ('speed_kmh', 'brake_pressure_kpa', 'steering_deg', 'combined_g'):
                pair = [marker[who].get(channel) for who in ('driver', 'reference')]
                cells.append(' / '.join(f'{v:.2f}' if v is not None else '—' for v in pair))
            pieces.append('<tr>'+''.join('<td>'+value+'</td>' for value in cells)+'</tr>')
        pieces.append('</table></details>')
        pieces.append('</details>')
    if remaining:
        pieces.append('</details>')
    pieces.append('</section>')
    return ''.join(pieces), md
