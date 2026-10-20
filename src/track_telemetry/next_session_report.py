"""Render agent-authored practice decisions; Python does not invent coaching."""
import html

from .coaching_report import _map


def render_next_session(plan, evidence):
    fields = ("location", "why", "action", "keep_fixed", "success", "abort", "review_next")
    if any(not isinstance(plan.get(key), str) or not plan[key].strip() for key in fields):
        raise ValueError("next_session requires nonempty " + ", ".join(fields))
    ids = plan.get("observation_ids", [])
    windows = {w["id"]: w for w in evidence.get("external_reference_scan", {}).get("windows", [])}
    observations = {o["id"]: o for o in evidence.get("observations", [])}
    if not ids or any(key not in windows and key not in observations for key in ids):
        raise ValueError("next_session requires known observation_ids")
    zh = plan.get("language", "zh").startswith("zh")
    labels = ("位置", "为什么先练这里", "本节只试这一件事", "保持不变", "怎样算有效", "何时恢复原走法", "下次先检查") if zh else (
        "Location", "Why this focus", "One change", "Keep fixed", "Success", "Abort", "Review next")
    title = "下一节练什么" if zh else "Next-session focus"
    md = ["# " + title, ""]
    body = []
    for key, label in zip(fields, labels):
        value = plan[key]
        md.extend([f"**{label}：** {value}", ""])
        body.append(f"<h2>{label}</h2><p>{html.escape(value)}</p>")
    zones = [{"letter": f'S{windows[key]["sector"]:02}', "lo": windows[key]["start_progress"],
              "hi": windows[key]["end_progress"], "color": "#126d82"} for key in ids if key in windows]
    shape_note = ""
    if ids[0] in windows:
        from .section_shape import shape_sentence

        window = windows[ids[0]]
        points = (evidence.get("reference_geometry") or {}).get("points", [])
        shape_note = shape_sentence(points, window["start_progress"], window["end_progress"],
                                    window.get("baseline_core_min_speed_kmh"), zh)
    if shape_note:
        label = "区段形态" if zh else "Section shape"
        md.insert(4, f"**{label}：** {shape_note}")
        md.insert(5, "")
        body.insert(1, f"<h2>{label}</h2><p>{html.escape(shape_note)}</p>")
    locator = _map(evidence, zones, zh) if zones else ""
    local = ""
    if ids[0] in windows:
        from .external_report import render_external_scan
        local, _ = render_external_scan(evidence["external_reference_scan"], {}, evidence, zh, route_only_id=ids[0], include_speed_evidence=True)
        # The shared renderer includes the same full-track locator and local Vmin route.
        locator = local
    link = "完整报告与对照图" if zh else "Full report and figures"
    md.append(f"[{link}](report.html#{ids[0]})")
    document = ('<!doctype html><html lang="'+('zh-CN' if zh else 'en')+'"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1"><title>'+title+'</title>'
                '<style>body{max-width:820px;margin:32px auto;padding:0 24px;font:18px/1.65 system-ui;background:#f6f7f8;color:#24343d}'
                'h1{font-size:32px}h2{font-size:18px;margin-bottom:4px}p{margin-top:0}svg{width:100%;background:white}details>svg:first-of-type{max-height:260px}details>svg:nth-of-type(2){max-height:600px}summary{display:none}svg text{font-family:system-ui}'
                'a{color:#126d82}</style><h1>'+title+'</h1>'+locator+''.join(body)
                +f'<p><a href="report.html#{html.escape(ids[0], quote=True)}">{link}</a></p></html>')
    return "\n".join(md), document
