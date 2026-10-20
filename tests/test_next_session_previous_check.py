from track_telemetry.next_session_report import render_next_session


def _evidence():
    windows = [{"id": "external-09", "sector": 9, "start_progress": 0.4, "end_progress": 0.45,
                "baseline_core_min_speed_kmh": 88.0, "positive_passages": 2, "passages": []}]
    return {
        "external_reference_scan": {
            "windows": windows,
            "observed_difference_ranking": ["external-09"],
            "required_review_ids": ["external-09"],
            "candidate_ranking": [{"id": "external-09", "typical_difference_s": 0.9}],
        },
        "observations": [{"id": "external-09", "values": {"best_core_difference_s": 1.0}}],
        "reference_geometry": {"points": [
            {"x_m": float(i) * 3.0, "y_m": float(i * i) * 0.05, "progress": i / 100.0}
            for i in range(101)]},
    }


def _plan(**extra):
    plan = {"language": "zh-CN", "observation_ids": ["external-09"], "location": "S09",
            "why": "w", "action": "a", "keep_fixed": "k", "success": "s", "abort": "b",
            "review_next": "r"}
    plan.update(extra)
    return plan


def test_previous_check_renders_in_markdown_and_html():
    md, doc = render_next_session(_plan(previous_check={"text": "昨日 S15 已稳定，本项关闭。"}), _evidence())
    assert "上次练习回顾" in md and "昨日 S15 已稳定" in md
    assert "上次练习回顾" in doc and "昨日 S15 已稳定" in doc


def test_missing_previous_check_renders_nothing_extra():
    md, doc = render_next_session(_plan(), _evidence())
    assert "上次练习回顾" not in md
    assert "上次练习回顾" not in doc


def test_blank_previous_check_is_ignored():
    md, _ = render_next_session(_plan(previous_check={"text": "   "}), _evidence())
    assert "上次练习回顾" not in md
