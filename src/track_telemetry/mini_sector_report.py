"""Localized all-lap sector matrix presentation."""
from __future__ import annotations

import html


def render_mini_sectors(analysis, session_name, format_time, zh):
    def tr(cn, en):
        return cn if zh else en
    def esc(value):
        return html.escape(str(value), quote=True)
    combined = analysis["combined"]
    if "virtual_best_s" not in combined:
        return "", []
    winners = combined["winners"]
    count = analysis.get("sector_count", len(winners))
    html_parts = ['<section><h2>' + tr("把各圈最快区段拼在一起", "Combine the fastest measured sections") + '</h2><p>' + tr(
        "每一行是一整圈，每一列是同一个物理区段。先看每列最快来自哪圈，再看整圈最快的圈在哪些位置仍留有差异。空间参考轨迹只统一坐标，不代表每一段都最快。",
        "Rows are laps; columns are matched physical sections. Geometry reference is a coordinate system, not the performance envelope.") + '</p><table><thead><tr><th>'
        + tr("样本范围", "Scope") + '</th><th>' + tr("实测整圈最快", "Best actual lap") + '</th><th>'
        + tr("各段最优拼接", "Combined sector best") + '</th><th>' + tr("拼接快多少（秒）", "Combined advantage s") + '</th></tr></thead><tbody>']
    summaries = [(tr("所有记录合并", "All recordings"), combined)] + [
        (session_name(int(index)), result) for index, result in analysis["by_session"].items()]
    md = ["", "## " + tr("各段最优拼接", "Combined sector best"),
          tr("候选圈是整圈接近最快的圈；拼接可用所有有效区段（含慢圈的局部快段），两者范围不同。",
             "Candidates are near-best whole laps; sector donors may come from slower laps."), ""]
    for label, result in summaries:
        if "virtual_best_s" not in result:
            continue
        gap = result["arithmetic_gap_s"]
        gap_text = f"{gap:.3f}" if gap is not None else "—"
        values = [label, format_time(result["best_whole_lap_s"]), format_time(result["virtual_best_s"]), gap_text]
        html_parts.append('<tr>' + "".join(f'<td>{esc(v)}</td>' for v in values) + '</tr>')
        md.append(f"- {label}：实测最快 {values[1]} / 拼接 {values[2]} / 差 {gap_text} 秒")
    html_parts.append('</tbody></table><p class="notice">' + tr(
        "拼接圈不是实际跑过的一圈，也不是保证能达到的目标。不同来源圈在接缝处可能有不同速度、路线和车辆状态；跨天合并还混有轮胎、天气与油量差异。",
        "A virtual lap was never driven. Boundary speeds, lines, vehicle states and cross-day conditions may be incompatible; the gap is not guaranteed improvement.") + '</p>')
    flags = [t for t in combined["transitions"] if t["speed_discontinuity_flag"]]
    html_parts.append('<p>' + tr(
        f"发现 {len(flags)} 处换圈接缝的速度差超过 5 公里/小时。这是需要检查的状态差，不是自动判定可拼或不可拼。",
        f"{len(flags)} source changes have boundary-speed differences above 5 km/h; this is a screening flag, not a feasibility verdict.") + '</p>')
    if flags:
        html_parts.append('<ul>')
        for flag in flags:
            html_parts.append('<li>' + tr(
                f"区段 {flag['after_sector']} → {flag['next_sector']}：换圈接缝速度跳变 {flag['speed_jump_kmh']:+.1f} 公里/小时。",
                f"Sector {flag['after_sector']} → {flag['next_sector']}: boundary speed jump {flag['speed_jump_kmh']:+.1f} km/h.") + '</li>')
        html_parts.append('</ul>')
    html_parts.append('<div class="sector-matrix"><table><thead><tr><th>' + tr("圈次", "Lap") + '</th>')
    html_parts.extend(f'<th id="zone-{i}">{i}</th>' for i in range(1, count + 1))
    html_parts.append('</tr></thead><tbody>')
    for row in analysis["rows"]:
        label = session_name(row["session"]) + tr(f" 第{row['lap']}圈", f" L{row['lap']}")
        html_parts.append(f'<tr><th>{esc(label)}</th>')
        for sector, winner in zip(row["sectors"], winners):
            delta = sector["duration_s"] - winner["duration_s"]
            if not sector["eligible"]:
                cell, color = "—", "#e6e9eb"
            else:
                cell = f"{sector['duration_s']:.2f}"
                color = "#d4ede4" if delta <= .1 else "#f6ead4" if delta <= .5 else "#f2d9d4"
            title = tr(f"本段 {sector['duration_s']:.3f} 秒；比本段最快慢 {delta:.3f} 秒",
                       f"{sector['duration_s']:.3f} s; delta to section best {delta:.3f} s")
            html_parts.append(f'<td style="background:{color}" title="{esc(title)}">{cell}</td>')
        html_parts.append('</tr>')
    html_parts.append('</tbody></table></div><p class="note">' + tr(
        "单元格是实测区段用时，单位为秒。绿色：距本段最快不超过 0.1 秒；浅黄：不超过 0.5 秒；浅红：更慢。灰色为暂不使用的样本。颜色仅供筛查，不表示统计置信度。",
        "Cells show measured seconds. Green: within 0.1 s of best; yellow: within 0.5 s; red: slower; gray: withheld. Colors are screening, not statistical confidence.") + '</p><details><summary>'
        + tr("展开：每段最快来源与接缝速度", "Expand: winning sources and boundary speeds") + '</summary><table><thead><tr>')
    labels = [tr("区段", "Sector"), tr("最快秒数", "Best s"), tr("来源圈", "Source lap"), tr("接近最快的次数", "Near-best count"),
              tr("整圈最快在此慢多少秒", "Best lap deficit s"), tr("进入 / 离开速度", "Entry / exit km/h")]
    html_parts += [''.join(f'<th>{v}</th>' for v in labels), '</tr></thead><tbody>']
    notable = []
    for winner in winners:
        entry, exit_ = winner["entry_speed_kmh"], winner["exit_speed_kmh"]
        speeds = f"{entry:.1f} / {exit_:.1f}" if entry is not None and exit_ is not None else "—"
        source = session_name(winner["session"]) + tr(f" 第{winner['lap']}圈", f" L{winner['lap']}")
        deficit = winner["best_whole_lap_deficit_s"]
        values = [winner["sector"], f"{winner['duration_s']:.3f}", source, winner["near_best_count"],
                  f"{deficit:.3f}" if deficit is not None else "—", speeds]
        html_parts.append('<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in values) + '</tr>')
        if deficit is not None and deficit > 0.1:
            notable.append((winner, deficit, source, speeds))
    notable.sort(key=lambda item: item[1], reverse=True)
    for winner, deficit, source, speeds in notable[:8]:
        md.append(f"- 区段{winner['sector']}：整圈最快在此慢 {deficit:.2f} 秒，最快来源{source}（进/出 {speeds} km/h）")
    if len(notable) > 8:
        md.append(f"- 其余 {len(notable) - 8} 段差距均小于上述，详见 report.html 拼接矩阵。")
    html_parts.append('</tbody></table><p class="note">' + tr(
        "接近最快指本段最快后 0.1 秒以内的不同圈样本。单次最快可能受定位和计时误差影响；这里只做核查，不把孤立最好值当成已掌握的稳定能力。局部快段可以来自整圈较慢的圈，但仍需确认驾驶意图。",
        "Near-best counts use a 0.1 s tolerance. Isolated bests require GPS/timing review; fast sections from slower laps still need intent/context confirmation.") + '</p></details></section>')
    return "".join(html_parts), md
