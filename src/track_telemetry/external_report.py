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
    pieces = ['<section id="external-scan"><h2>' + tr("高手对照：全路线时间差排名", "External reference: whole-route difference ranking") + '</h2><p>' + tr(
        "逐一检查所有区段，独立于自己的圈间排名。下表是实测差距；下一节练习由后面的计划单独选择。区段编号固定对应赛道位置，不是官方弯号。",
        "Every sector is screened independently of own-lap ranking. Observed differences and practice selection are separate. Sector IDs locate windows, not official corners.") + '</p><table><tr><th>' + tr("位置", "Location") + '</th><th>' + tr("目标段差/关联窗口差", "Core/linked difference") + '</th><th>' + tr("目标段最低速：你/参考", "Core minimum speed: you/reference") + '</th><th>' + tr("重复支持", "Repeated support") + '</th><th>' + tr("本节状态", "Practice status") + '</th></tr>']
    sources = ' / '.join(html.escape(str(item['summary'].get('source_name', item['summary'].get('session_id', item['index']))))
                         for item in scan['references'])
    missing = [f"S{w['sector']:02}" for w in scan['windows'] if not w.get('passages')]
    coverage = tr(f"匹配覆盖：{len(ranked)}/{len(windows)} 段。", f"Coverage: {len(ranked)}/{len(windows)} windows.")
    coverage += tr(f"你的基线：第{scan['baseline_lap']}圈；参考文件：", f"Baseline lap {scan['baseline_lap']}; reference files: ") + sources
    if missing:
        coverage += tr("；未匹配：", "; unmatched: ") + ', '.join(missing)
    pieces[0] = pieces[0].replace('</h2>', '</h2><p>'+coverage+'</p>', 1)
    md = ['## ' + tr("高手全路线时间差排名（独立于练习排序）", "External differences, independent of practice ranking"), '']
    for w in ranked:
        p = w['passages'][0]
        state = tr("已选，见练习/验证计划", "Selected; see practice/validation plan") if w['id'] in selected else tr("待评估；未据此自动排除", "Pending review; not automatically excluded")
        if w['id'] in decisions:
            decision = decisions[w['id']]
            labels = {"practice": tr("练习", "Practice"), "validate": tr("验证", "Validate"), "defer": tr("暂缓", "Defer")}
            state = labels[decision['status']] + ': ' + decision['reason']
        low = w['baseline_core_min_speed_kmh']
        ref_low = p['core_min_speed_kmh']
        pieces.append(f'<tr><td><a href="#{w["id"]}">S{w["sector"]:02}</a></td><td>{p["core_difference_s"]:+.3f} / {p["linked_difference_s"]:+.3f} s</td><td>{low:.1f} / {ref_low:.1f}</td><td>{w["positive_passages"]}/{len(w["passages"])}</td><td>{html.escape(state)}</td></tr>')
        md.append(f'- S{w["sector"]:02}: '+tr('目标段 ', 'Core ')+f'{p["core_difference_s"]:+.3f} '+tr('秒；关联窗口 ', 's; linked ')+f'{p["linked_difference_s"]:+.3f} '+tr('秒；', 's; ')+state)
    pieces.append('</table><p>'+tr('橙色：你；蓝色：参考；浅黄：目标计时段，前后为关联窗口。',
                                  'Orange: you; blue: reference; yellow: core timing window, with linked context.')+'</p>')
    pieces.append('<p>' + tr("排名较前的高速区域也必须评估；暂缓练习需给出具体理由。点击任一位置查看地图及对照。", "Review high-speed areas near the top too; deferral requires a reason. Open any location for maps and traces.") + '</p>')
    for rank, w in enumerate(ranked):
        p = w['passages'][0]
        title = f'S{w["sector"]:02} · ' + tr(f'高手参考{p["reference"]+1}第{p["lap"]}圈', f'Reference {p["reference"]+1}, lap {p["lap"]}')
        pieces.append(f'<details id="{w["id"]}"'+(' open' if rank < 3 or w['id'] in selected else '')+'><summary>'+title+'</summary>')
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
        pieces.append('<table><tr><th>'+tr('同步位置','Shared marker')+'</th><th>'+tr('速度：你/参考','Speed: you/reference')+'</th><th>'+tr('刹车 kPa','Brake kPa')+'</th><th>'+tr('转向 度','Steering deg')+'</th><th>'+tr('总G','Combined G')+'</th></tr>')
        for index, marker in enumerate(p['markers'], 1):
            cells = [str(index)]
            for channel in ('speed_kmh', 'brake_pressure_kpa', 'steering_deg', 'combined_g'):
                pair = [marker[who].get(channel) for who in ('driver', 'reference')]
                cells.append(' / '.join(f'{v:.2f}' if v is not None else '—' for v in pair))
            pieces.append('<tr>'+''.join('<td>'+value+'</td>' for value in cells)+'</tr>')
        pieces.append('</table>')
        pieces.append('</details>')
    pieces.append('</section>')
    return ''.join(pieces), md
