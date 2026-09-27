from __future__ import annotations

from pathlib import Path

import pytest

from track_telemetry import mcp_server


def test_root_is_secure_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACK_TELEMETRY_ROOT", raising=False)
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    with pytest.raises(RuntimeError, match="TRACK_TELEMETRY_ROOT is required"):
        mcp_server._root()


def test_unsafe_any_path_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACK_TELEMETRY_ROOT", raising=False)
    monkeypatch.setenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", "1")

    assert mcp_server._root() is None
    result = mcp_server._list_sessions_data()
    assert result["discovery_available"] is False
    assert result["sessions"] == []


def test_list_sessions_returns_stable_opaque_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "telemetry"
    nested = root / "weekend"
    nested.mkdir(parents=True)
    first = root / "session-a.rcz"
    second = nested / "session-b.rcz"
    first.write_bytes(b"")
    second.write_bytes(b"")

    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    result = mcp_server._list_sessions_data()
    assert result["discovery_available"] is True
    assert result["session_count"] == 2
    assert {item["source_name"] for item in result["sessions"]} == {
        "session-a.rcz",
        "session-b.rcz",
    }
    assert all(len(item["session_id"]) == 16 for item in result["sessions"])
    assert all(str(root) not in item["session_id"] for item in result["sessions"])

    again = mcp_server._list_sessions_data()
    assert again["sessions"] == result["sessions"]

    by_name = {item["source_name"]: item["session_id"] for item in result["sessions"]}
    assert mcp_server._resolve_rcz(by_name["session-a.rcz"]) == first.resolve()
    assert mcp_server._resolve_rcz(by_name["session-b.rcz"]) == second.resolve()


def test_relative_paths_resolve_inside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "telemetry"
    root.mkdir()
    session = root / "session.rcz"
    session.write_bytes(b"")

    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    assert mcp_server._resolve_rcz("session.rcz") == session.resolve()


def test_paths_outside_root_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "telemetry"
    root.mkdir()
    outside = tmp_path / "outside.rcz"
    outside.write_bytes(b"")

    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)

    with pytest.raises(PermissionError, match="outside TRACK_TELEMETRY_ROOT"):
        mcp_server._resolve_rcz(str(outside))
