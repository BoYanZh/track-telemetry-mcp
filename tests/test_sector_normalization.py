from track_telemetry.next_session_report import _normalize_sectors


def test_single_digit_sector_padded():
    assert _normalize_sectors("通过S2，再回S05") == "通过S02，再回S05"


def test_already_padded_untouched():
    assert _normalize_sectors("S09 与 S15") == "S09 与 S15"


def test_non_sector_s_tokens_untouched():
    assert _normalize_sectors("S15.3 与 ABC") == "S15.3 与 ABC"
    assert _normalize_sectors("AS2") == "AS2"
