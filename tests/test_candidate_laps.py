from track_telemetry.coaching_report import _eligible_laps


def _evidence(selection, summaries):
    return {"sessions": [{"index": 0, "summary": {"source_name": "session_20260913_0923_x.rcz"},
                          "lap_selection": selection, "lap_summaries": summaries}]}


def _sel(lap, eligible):
    return {"lap": lap, "classification": "candidate_push" if eligible else "unclassified_slow",
            "coaching_eligible": eligible}


def _sum(lap, duration):
    return {"lap": {"number": lap, "duration_s": duration, "original_number": lap}}


def test_eligible_laps_sorted_by_time():
    evidence = _evidence([_sel(10, True), _sel(11, False), _sel(12, True)],
                         [_sum(10, 146.5), _sum(11, 200.0), _sum(12, 144.4)])
    rows = _eligible_laps(evidence, True)
    assert [seconds for _, seconds in rows] == [144.4, 146.5]
    assert "第12圈" in rows[0][0]


def test_missing_duration_is_skipped():
    evidence = _evidence([_sel(10, True), _sel(11, True)], [_sum(10, 146.5)])
    rows = _eligible_laps(evidence, True)
    assert len(rows) == 1


def test_no_eligible_laps_returns_empty():
    assert _eligible_laps(_evidence([_sel(10, False)], [_sum(10, 200.0)]), True) == []
