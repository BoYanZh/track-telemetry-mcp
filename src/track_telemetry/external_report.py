"""Render external scan separately from the agent's practice priority."""
import html

import numpy as np


def render_external_scan(scan, coaching, evidence, zh):
    from .coaching_report import _map
    def tr(cn, en):
        return cn if zh else en
    windows = {w["id"]: w for w in scan["windows"]}
    ranked = [windows[key] for key in scan["observed_difference_ranking"]]
    selected = {key for p in coaching.get("experiments", []) for key in p["observation_ids"]}
    descriptions = {s["observation_id"]: s for s in coaching.get("sections", [])}
    decisions = {d["observation_id"]: d for d in scan.get("practice_decisions", [])}
    selected |= set(descriptions) & set(windows)
    focus_ids = [key for key in scan.get("practice_ranking", []) if key in windows]
    if not focus_ids:
        focus_ids = [w["id"] for w in ranked if w["id"] in selected]
    focus = [windows[key] for key in focus_ids[:4]]
    by_linked = sorted(ranked, key=lambda w: (w['id'] in decisions,
                       w['passages'][0]['linked_difference_s']), reverse=True)
    def context(w):
        padding = 1 / max(len(windows), 1)
        return max(0., w['start_progress']-padding), min(1., w['end_progress']+padding)
    for candidate in by_linked:
        if len(focus) >= 4:
            break
        if candidate in focus:
            continue
        lo, hi = context(candidate)
        overlaps = False
        for existing in focus:
            a, b = context(existing)
            if max(0., min(hi, b)-max(lo, a)) > .5 * min(hi-lo, b-a) + 1e-9:
                overlaps = True
        if not overlaps:
            focus.append(candidate)
    # Very short layouts may not contain four distinct linked areas.
    if not focus:
        focus = by_linked[:4]
    focus_keys = {w["id"] for w in focus}
    other = [w for w in ranked if w["id"] not in focus_keys]
    pieces = ['<section id="external-scan"><h2>' + tr("高手对照：先看这几个位置", "Reference comparison: start here") + '</h2><p>' + tr(
        "先看四个改进候选。时间差包含前弯、本段和后续加速，作为把整套动作做好后的改善空间参考；重叠区间不相加。",
        "Start with four improvement candidates. Linked differences cover entry, target and downstream acceleration; they guide opportunity assessment. Overlapping differences are not additive.") + '</p>']
    md = ['## ' + tr("高手对照：先看这几个位置", "Reference comparison: start here"), '']

    def table(items):
        rows = ['<table><tr><th>'+tr('位置','Location')+'</th><th>'+tr('关联窗口差','Linked-window difference')+'</th><th>'+tr('怎么安排','Plan')+'</th></tr>']
        for w in items:
            p = w['passages'][0]
            decision = decisions.get(w['id'])
            state = decision['reason'] if decision else tr('留作后续分析','Review later')
            rows.append(f'<tr><td><a href="#{w["id"]}">S{w["sector"]:02}</a></td><td>{p["linked_difference_s"]:+.2f} '+tr('秒','s')+'</td><td>'+html.escape(state)+'</td></tr>')
        rows.append('</table>')
        return ''.join(rows)

    pieces.append(table(focus))
    for w in focus:
        p = w['passages'][0]
        state = decisions.get(w['id'], {}).get('reason', tr('后续分析','Review later'))
        md.append(f'- S{w["sector"]:02}: '+tr('本段慢 ', 'Local difference ')+f'{p["core_difference_s"]:.2f} '+tr('秒。','s. ')+state)
    pieces.append('<p>'+tr('橙色：你；蓝色：参考；浅黄：本段。','Orange: you; blue: reference; yellow: target segment.')+'</p>')
    detail_order = focus + other
    for rank, w in enumerate(detail_order):
        if other and rank == len(focus):
            pieces.append('<details class="external-other"><summary>'+tr(f'查看其余{len(other)}段',f'Other {len(other)} windows')+'</summary>'+table(other))
        p = w['passages'][0]
        title = f'S{w["sector"]:02} · ' + tr(f'高手参考{p["reference"]+1}第{p["lap"]}圈', f'Reference {p["reference"]+1}, lap {p["lap"]}')
        pieces.append(f'<details id="{w["id"]}"'+(' open' if w['id'] in focus_keys else '')+'><summary>'+title+'</summary>')
        zone = {"letter": f'S{w["sector"]:02}', "lo": w["start_progress"], "hi": w["end_progress"], "color": "#126d82"}
        pieces.append(_map(evidence, [zone], zh))
        xy = np.asarray(w['route_xy'])
        ref_xy = np.asarray(p['reference_route_xy'])
        both = np.vstack([xy, ref_xy])
        minimum = both.min(axis=0)
        span = max(float(np.ptp(both[:, 0])), float(np.ptp(both[:, 1])), 1.)
        coords = (xy-minimum)/span*500+40
        route = ' '.join(f'{a:.1f},{560-b:.1f}' for a,b in coords)
        ref_coords = (ref_xy-minimum)/span*500+40
        reference_route = ' '.join(f'{a:.1f},{560-b:.1f}' for a,b in ref_coords)
        pieces.append('<svg viewBox="0 0 600 600"><polyline fill="none" stroke="#c45b25" stroke-width="3" points="'+route+'"/>'
                      + '<polyline fill="none" stroke="#126d82" stroke-width="3" points="'+reference_route+'"/>'
                      + f'<text x="{coords[0,0]:.1f}" y="{560-coords[0,1]:.1f}">'+tr('入口 →','Entry →')+'</text>'
                      + f'<text x="{coords[-1,0]:.1f}" y="{560-coords[-1,1]:.1f}">'+tr('出口','Exit')+'</text></svg>')
        desc = descriptions.get(w['id'], {})
        for key in ('title', 'what_happened', 'interpretation', 'braking_analysis', 'steering_analysis',
                    'power_analysis', 'g_analysis', 'line_analysis', 'cue', 'watch_out'):
            if desc.get(key):
                pieces.append('<p>'+html.escape(desc[key])+'</p>')
        pieces.append('<p>'+tr('入口速度（你/参考）：','Entry speed (you/reference): ')+f'{w["baseline_entry_speed_kmh"]:.1f}/{p["entry_speed_kmh"]:.1f} km/h; '
                      +tr('出口：','Exit: ')+f'{w["baseline_exit_speed_kmh"]:.1f}/{p["exit_speed_kmh"]:.1f} km/h.</p>')
        names = [('speed_kmh',tr('速度 · 公里/小时','Speed · km/h')),
                 ('brake_pressure_kpa',tr('制动压力 · kPa','Brake · kPa')),
                 ('steering_deg',tr('转向 · 度','Steering · degrees')),
                 ('accelerator_pct',tr('加速踏板 · %','Accelerator pedal · %')),
                 ('combined_g',tr('平面总G','Planar combined G')),
                 ('delta',tr('本窗口新增时间差 · 秒','Incremental delta · s'))]
        for name, label in names:
            if name == 'delta':
                pairs = [(p['delta_s'], '#654478')]
            elif name in w['baseline_signals'] and name in p['signals']:
                pairs = [(w['baseline_signals'][name], '#c45b25'), (p['signals'][name], '#126d82')]
            else:
                continue
            values = np.asarray([v for v, _ in pairs])
            lo = float(values.min())
            scale = max(float(np.ptp(values)), .01)
            pieces.append('<h3>'+label+'</h3><svg viewBox="0 0 900 190">')
            left, right = [(g-w['grid_m'][0])/(w['grid_m'][-1]-w['grid_m'][0])*860+20
                           for g in w['core_limits_m']]
            pieces.append(f'<rect x="{left:.1f}" y="20" width="{right-left:.1f}" height="150" fill="#fff1be"/>')
            for vals, color in pairs:
                pts=' '.join(f'{20+i/(len(vals)-1)*860:.1f},{170-(v-lo)/scale*140:.1f}' for i,v in enumerate(vals))
                pieces.append('<polyline fill="none" stroke="'+color+'" stroke-width="2" points="'+pts+'"/>')
            pieces.append(f'<text x="20" y="15">{lo:.2f}–{lo+scale:.2f}</text></svg>')
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
    if other:
        pieces.append('</details>')
    pieces.append('</section>')
    return ''.join(pieces), md
