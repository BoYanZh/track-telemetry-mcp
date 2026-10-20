"""Local acceptance against reviewed recordings and distinct held-out real laps.

Raw sessions remain outside this repository. This check has no optional skip path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from track_telemetry.corner_catalog import locate_section, match_lap
from track_telemetry.ttc_adapter import load_telemetry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Reviewed v3 directory in TrackTelemetryConverter')
    parser.add_argument('--output', type=Path,
                        default=Path('.local-corner-validation/acceptance.json'))
    args = parser.parse_args()
    source = args.source.resolve()
    ttc = source.parents[2]
    verified = json.loads((source / 'measurements/verified.json').read_text(encoding='utf-8'))
    rows = []
    for layout, meta in verified.items():
        session = load_telemetry(ttc / meta['source_rcz'])
        selected = meta['selection']['number']
        heldout = sorted((c for c in meta['lap_candidates']
                          if c['geometrically_clean'] and c['number'] != selected),
                         key=lambda c: c['duration_s'])[0]['number']
        for role, lap in [('source', selected), ('held_out', heldout)]:
            start = perf_counter()
            result = match_lap(session, lap)
            row = {'expected': layout, 'role': role, 'lap': lap,
                   'status': result['status'], 'actual': result.get('layout_id'),
                   'elapsed_s': round(perf_counter() - start, 3),
                   'quality': result.get('quality'),
                   'reason': result.get('reason'), 'candidates': result.get('candidates'),
                   'corners': [{k: c.get(k) for k in
                                ['id', 'official', 'lap_progress', 'reference_distance_m',
                                 'distance_m', 'confidence']} for c in result.get('corners', [])]}
            rows.append(row)
            print(f'{layout}: {role} lap {lap}: {result["status"]} '
                  f'{result.get("layout_id")} ({row["elapsed_s"]:.3f}s)', flush=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({'rows': rows}, ensure_ascii=False, indent=2),
                                   encoding='utf-8')
            assert result['status'] == 'matched' and result.get('layout_id') == layout, row
            names = {c['official'] for c in result['corners']}
            if layout == 'thill-east-bypass':
                assert 'T5A' in names and 'T5' not in names
            if layout == 'thill-east-cyclone':
                assert {'T5', 'T5A'} <= names
            if layout.startswith('bw-') and layout != 'bw-circuit':
                assert 'Phil Hill' in names and 'Drag Strip' not in names
            if role == 'source' and layout == 'thill-east-cyclone':
                corners = {c['official']: c for c in result['corners']}
                lo = corners['T14']['lap_progress']
                hi = corners['T15']['lap_progress']
                location = locate_section(result, lo, hi)
                assert {'T14', 'T15'} <= set(location['official_names']), location
                row['linked_section_example'] = location
    args.output.write_text(json.dumps({'status': 'passed', 'real_laps': len(rows), 'rows': rows},
                                     ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'PASS: {len(rows)} real-lap matches across {len(verified)} layouts.')


if __name__ == '__main__':
    main()
