"""Import the owner's reviewed corner references without bundling real recordings.

Usage: python tools/import_corner_catalog.py --source ../TrackTelemetryConverter/data/corner_db/v3
The runtime reads the packaged catalog and never needs this source checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

LAYOUTS = {
    'thill-east-bypass': 'Thunderhill East Bypass',
    'thill-east-cyclone': 'Thunderhill East Cyclone',
    'thill-west': 'Thunderhill West',
    'sonoma': 'Sonoma Carousel',
    'laguna': 'Laguna Seca',
    'bw-13cw': 'Buttonwillow Classic 13CW',
    'bw-1a-ccw': 'Buttonwillow Classic 1A-CCW',
    'bw-25ccw': 'Buttonwillow Classic 25CCW',
    'bw-circuit': 'Buttonwillow The Circuit',
}


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _reproject(points, origin, target_origin, shift=(0, 0)):
    xy = np.asarray(points, dtype=float).copy()
    xy -= origin.get('evidence_frame_translation_m', [0, 0])
    xy[..., 0] *= np.cos(np.deg2rad(target_origin['latitude_deg'])) / np.cos(
        np.deg2rad(origin['latitude_deg']))
    xy += [np.deg2rad(origin['longitude_deg'] - target_origin['longitude_deg']) *
           6371000 * np.cos(np.deg2rad(target_origin['latitude_deg'])),
           np.deg2rad(origin['latitude_deg'] - target_origin['latitude_deg']) * 6371000]
    return xy + shift


def _geodetic(xy, origin):
    return [float(origin['latitude_deg'] + np.rad2deg(xy[1] / 6371000)),
            float(origin['longitude_deg'] + np.rad2deg(
                xy[0] / (6371000 * np.cos(np.deg2rad(origin['latitude_deg'])))))]


def import_catalog(source: Path):
    verified = _read(source / 'measurements/verified.json')
    classic = _read(source / 'bw-classic.json')
    classic_corners = {c['official']: c for c in classic['corners']}
    layouts = []
    for key, title in LAYOUTS.items():
        reviewed = _read(source / f'{key}.json')
        data = np.load(source / 'measurements' / f'{key}.npz')
        raw_origin = verified[key]['origin']
        shift = [0, 0]
        if key.startswith('thill-east-'):
            origin = reviewed['shared_corner_reference']['coordinate_frame']
            shift = (verified[key].get('cross_file_alignment') or {}).get(
                'translation_after_geodetic_reprojection_m', [0, 0])
        elif key in {'bw-13cw', 'bw-1a-ccw', 'bw-25ccw'}:
            origin = classic['coordinate_frame']
            shift = (verified[key].get('cross_file_alignment') or {}).get(
                'translation_after_geodetic_reprojection_m', [0, 0])
        else:
            origin = raw_origin
        trace = _reproject(data['xy'], raw_origin, origin, shift)
        distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(trace, axis=0), axis=1))]
        grid = np.r_[np.arange(0, distance[-1], 5.), distance[-1]]
        sampled = np.c_[np.interp(grid, distance, trace[:, 0]),
                        np.interp(grid, distance, trace[:, 1])]
        if 'uses' in reviewed:
            observations = reviewed['verification']['corner_observations']
            corner_sources = [(name, observations[name]) for name in reviewed['uses']]
        else:
            corner_sources = [(c['official'], c) for c in reviewed['corners']]
        corners = []
        for name, c in corner_sources:
            if key.startswith('thill-east-'):
                xy = np.asarray(c['reference_xy_m'])
                identity = c['corner_id']
            elif key in {'bw-13cw', 'bw-1a-ccw', 'bw-25ccw'}:
                xy = np.asarray(classic_corners[name]['apex_xy_m'] or
                                classic_corners[name]['location_hint']['xy_m'])
                identity = 'bw-classic:' + name
            else:
                # Owner approval confirms the displayed location, including known
                # numbered kinks whose local signal did not pass peak detection.
                point = c['apex_xy_m'] or c['location_hint']['xy_m']
                xy = _reproject(point, raw_origin, origin, shift)
                identity = key + ':' + name
            lat, lon = _geodetic(xy, origin)
            nearest = int(np.argmin(np.linalg.norm(sampled - xy, axis=1)))
            corners.append({
                'id': identity, 'official': name, 'direction': c['direction'],
                'x_m': float(xy[0]), 'y_m': float(xy[1]),
                'latitude_deg': lat, 'longitude_deg': lon,
                'reference_s_m': float(grid[nearest]),
                'reference_trace_offset_m': float(np.linalg.norm(sampled[nearest] - xy)),
                'identity_status': 'owner_confirmed',
                'feature_type': 'named_segment' if c.get('detection') == 'named_segment' else 'corner',
                'source_map': c.get('official_source'),
            })
        corners.sort(key=lambda c: c['reference_s_m'])
        layouts.append({
            'id': key, 'name': title, 'direction': reviewed['direction'],
            'origin_latitude_deg': origin['latitude_deg'],
            'origin_longitude_deg': origin['longitude_deg'],
            'length_m': float(distance[-1]), 'reference_trace': sampled.tolist(),
            'corners': corners,
            'source': {'reviewed_json_sha256': hashlib.sha256(
                (source / f'{key}.json').read_bytes()).hexdigest(),
                'recording_sha256': reviewed['source_sha256'],
                'source_lap': reviewed['selection']['original_number']},
            'route_constraints': {'mutually_exclusive': [['Phil Hill', 'Drag Strip']]}
            if key.startswith('bw-') and key != 'bw-circuit' else {},
        })
    # Unobserved alternatives remain in the inventory, never silently attached to
    # a GPS route or used to manufacture a location match.
    unobserved = [{'id': 'bw-classic:' + c['official'], 'official': c['official'],
                   'identity_status': 'owner_confirmed', 'gps_binding': 'unobserved',
                   'mutually_exclusive_with': c.get('mutually_exclusive_with', [])}
                  for c in classic['corners'] if not c.get('observations_by_layout')]
    return {
        'schema_version': 1,
        'approval': {'status': 'owner_confirmed', 'date': '2026-10-20',
                     'scope': 'Reviewed corner identities, map locations and route topology. GPS traces are driving lines, not surveyed boundaries or geometric apexes.'},
        'identity_contract': 'GPS position + ordered route geometry identify corners. Reference distance describes location on the matched route; per-lap distance/progress never identifies corners across files.',
        'layouts': layouts, 'unobserved_features': unobserved,
        'sources': [{'file': x['file'], 'url': x.get('url'), 'sha256': x.get('sha256')}
                    for x in _read(source / 'sources/manifest.json')
                    if x['status'] in {'downloaded', 'provided'} and not x['file'].endswith('.html')],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(
        'src/track_telemetry/data/corner_catalog.json'))
    args = parser.parse_args()
    result = import_catalog(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'),
                                      allow_nan=False) + '\n', encoding='utf-8')
    print(f'Imported {len(result["layouts"])} layouts, '
          f'{sum(len(x["corners"]) for x in result["layouts"])} route corner references, '
          f'{len(result["unobserved_features"])} unobserved branch names.')


if __name__ == '__main__':
    main()
