import pytest

from track_telemetry.next_session_report import render_next_session


def test_short_report_escapes_agent_text_and_links_evidence():
    fields = ("location", "why", "action", "keep_fixed", "success", "abort", "review_next")
    plan = dict.fromkeys(fields, "<test>")
    plan["observation_ids"] = ["zone-a"]
    md, doc = render_next_session(plan, {"observations": [{"id": "zone-a"}]})
    assert "&lt;test&gt;" in doc and "<test>" not in doc
    assert "report.html#zone-a" in doc and "report.html#zone-a" in md
    del plan["success"]
    with pytest.raises(ValueError, match="success"):
        render_next_session(plan, {})
