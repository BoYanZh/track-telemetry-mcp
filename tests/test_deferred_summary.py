from track_telemetry.coaching_report import summarize_deferred


def test_trivial_gaps_collapse_into_one_clause():
    skipped = [(0.09, "B（S10）"), (0.04, "C（S08）"), (0.04, "D（S05）"), (0.12, "E（S16）"), (0.42, "F（S06）")]
    parts = summarize_deferred(skipped, True)
    assert parts[0] == "F（S06）"
    assert any("其余4段差均≤0.12秒" in p for p in parts)


def test_material_gaps_sorted_descending_and_capped():
    skipped = [(0.2, "low"), (0.9, "high"), (0.5, "mid"), (0.3, "extra")]
    parts = summarize_deferred(skipped, True)
    assert parts[:3] == ["high", "mid", "extra"]


def test_no_aggregate_clause_when_all_gaps_material():
    parts = summarize_deferred([(0.4, "A"), (0.6, "B")], True)
    assert parts == ["B", "A"]


def test_english_aggregate_clause():
    parts = summarize_deferred([(0.05, "A")], False)
    assert "ignorable" in parts[-1]


def test_large_remainder_is_not_called_ignorable():
    parts = summarize_deferred([(0.9, "a"), (0.8, "b"), (0.7, "c"), (0.3, "d"), (0.28, "e")], True)
    tail = parts[-1]
    assert "0.30秒" in tail and "可忽略" not in tail
