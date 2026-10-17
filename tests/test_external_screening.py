"""External screening must find stable deficits without own-lap variation."""
import numpy as np
import pytest
from test_plot_reports import _session

from track_telemetry.debrief import build_debrief, finalize_debrief
from track_telemetry.external_screening import scan_external_references


def test_reference_scan_independent_of_own_variance_and_practice():
    driver, expert = _session(30., n=1201), _session(25., n=1201)
    scan = scan_external_references(driver, driver.laps[0].number, [expert])
    assert len(scan['windows']) == 20
    assert len(scan['observed_difference_ranking']) >= 18
    assert not scan['practice_ranking']
    for window in scan['windows']:
        for p in window.get('passages', []):
            assert p['core_difference_s'] > 0
            assert abs(sum(p['stage_differences_s']) - p['linked_difference_s']) < 1e-9
            assert np.all(np.diff(p['source_times_s']) > 0)
            assert p['entry_speed_kmh']
            for marker in p['markers']:
                for who in ['driver', 'reference']:
                    values = marker[who]
                    if 'combined_g' in values:
                        assert abs(values['combined_g']-np.hypot(values['lat_g'], values['long_g'])) < 1e-12


def test_different_physical_route_is_excluded():
    driver, expert = _session(30., n=601), _session(25., radius=250., n=601)
    scan = scan_external_references(driver, driver.laps[0].number, [expert])
    assert not scan['observed_difference_ranking']
    assert any(w.get('excluded_passages') for w in scan['windows'])


def test_external_roles_do_not_replace_driver_pb_and_render_first(tmp_path):
    driver, expert = _session(30., n=1201), _session(25., n=1201)
    e = build_debrief([driver], tmp_path, reference_sessions=[expert], plots=False)['evidence']
    assert e['reference']['session'] == 0
    assert len(e['sessions']) == 1
    assert e['external_reference_scan']['references']
    oid = e['external_reference_scan']['observed_difference_ranking'][0]
    finalize_debrief(tmp_path/'evidence.json', {
        'summary': '先验证高速区域的损失位置。', 'language': 'zh-CN',
        'hypotheses': [{'observation_ids': [oid], 'explanation': '检查相同位置的差异',
                        'confidence': 'low', 'confounders': ['车辆配置未确认']}],
        'sections': [{'observation_id': oid, 'interpretation': '先测入口状态', 'cue': '记录三次'}],
        'external_decisions': [{'observation_id': key, 'status': 'validate' if key == oid else 'defer',
                                'reason': '先验证入口状态，其余区域留待下一节'}
                               for key in e['external_reference_scan']['observed_difference_ranking'][:5]],
        'experiments': [], 'validation_plan': '检查该窗口的入口和出口状态。'})
    doc = (tmp_path/'report.html').read_text(encoding='utf-8')
    assert doc.index('id="external-scan"') < doc.index('id="track"')
    assert 'S20' in doc and oid in doc
    import re
    assert len(re.findall(r'<details id="external-\d+" open>', doc)) == 4
    assert '查看其余16段' in doc
    assert '关联窗口差' in doc
    assert '目标段差/关联窗口差' not in doc
    assert '重复支持' not in doc
    assert '<details class="external-other" open' not in doc


def test_finalize_rejects_unreviewed_external_leaders(tmp_path):
    driver, expert = _session(30., n=601), _session(25., n=601)
    build_debrief([driver], tmp_path, reference_sessions=[expert], plots=False)
    with pytest.raises(ValueError, match="five largest"):
        finalize_debrief(tmp_path/'evidence.json', {'summary': 'Review pending',
            'hypotheses': [], 'experiments': [], 'validation_plan': 'Review shared windows'})


def test_fast_area_review_is_independent_of_top_five():
    driver, expert = _session(30., n=1201), _session(25., n=1201)
    driver.channel('speed_kmh').values[:] = 150.
    scan = scan_external_references(driver, driver.laps[0].number, [expert])
    top = set(scan['observed_difference_ranking'][:5])
    assert set(scan['fast_area_review_ids']) - top
    assert set(scan['fast_area_review_ids']) <= set(scan['required_review_ids'])
    assert not scan['practice_ranking']


def test_linked_window_stops_before_earlier_next_brake():
    from track_telemetry.external_screening import _linked_end
    grid = np.arange(6.)*100
    driver_times = np.arange(6.)
    reference_times = np.arange(6.)*.9
    end, bounded = _linked_end(grid, driver_times, reference_times, 200.,
                              [{'start_s': 1.}, {'start_s': 2.8}], [{'start_s': 3.6}])
    assert bounded and abs(end-275.) < 1e-9
    end, bounded = _linked_end(grid, driver_times, reference_times, 200., [], [])
    assert not bounded and end == 500.
