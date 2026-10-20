"""Official location metadata survives the actual MCP protocol boundary."""
import asyncio

from mcp import Client

from track_telemetry import mcp_server


def test_corner_tools_round_trip_and_preserve_measurements(monkeypatch):
    session = object()
    monkeypatch.setattr(mcp_server, '_load', lambda path: session)
    match = {'status': 'matched', 'layout_id': 'thill-east-bypass',
             'name': 'Thunderhill East Bypass', 'corners': []}
    location = {'status': 'matched', 'label': 'T14–T15',
                'corner_ids': ['thill-east:T14', 'thill-east:T15'],
                'official_names': ['T14', 'T15']}
    seen = []

    def match_lap(actual, lap_number, layout_id=None):
        assert actual is session
        seen.append((lap_number, layout_id))
        return match

    monkeypatch.setattr(mcp_server, 'match_corner_lap', match_lap)
    monkeypatch.setattr(mcp_server, 'locate_corner_section', lambda m, lo, hi: location)
    monkeypatch.setattr(mcp_server, 'section_metrics',
                        lambda *args: {'minimum_speed_kmh': 70.5, 'duration_s': 4.2})

    async def run():
        async with Client(mcp_server.mcp, raise_exceptions=True) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {'list_track_layouts', 'locate_track_corners'} <= names
            catalog = (await client.call_tool('list_track_layouts', {})).structured_content
            assert catalog is not None
            located = (await client.call_tool('locate_track_corners', {
                'path': 'session.rcz', 'lap_number': 7,
                'layout_id': 'thill-east-bypass'})).structured_content
            assert located['layout_id'] == 'thill-east-bypass'
            measured = (await client.call_tool('analyze_section', {
                'path': 'session.rcz', 'lap_number': 7,
                'start_progress': .8, 'end_progress': .9})).structured_content
            assert measured['minimum_speed_kmh'] == 70.5
            assert measured['duration_s'] == 4.2
            assert measured['corner_location']['label'] == 'T14–T15'

    asyncio.run(run())
    assert seen == [(7, 'thill-east-bypass'), (7, None)]


def test_comparison_uses_reference_lap_location_not_driver_progress(monkeypatch):
    reference = object()
    calls = []
    monkeypatch.setattr(mcp_server, 'match_corner_lap',
                        lambda session, lap: calls.append((session, lap)) or
                        {'status': 'ambiguous'})
    monkeypatch.setattr(mcp_server, 'locate_corner_section',
                        lambda match, lo, hi: {'status': 'unresolved', 'label': None})
    result = {'mini_sectors': [{'start_progress': .1, 'end_progress': .2,
                                'a_minus_b_s': .24}]}
    measured = mcp_server._name_comparison_sections(result, reference, 3)
    assert calls == [(reference, 3)]
    assert measured['mini_sectors'][0]['a_minus_b_s'] == .24
    assert measured['mini_sectors'][0]['corner_location']['label'] is None
