"""Final routed copper replaces placement-era electrical/escape evidence."""
from pathlib import Path

import pytest

from placemat import final_board, score
from placemat.layout import Board
from placemat.values import Part
from tests.fixtures import board_geometry, footprint, track
from tests.conftest import needs_kicad


def _placed(geometry):
    board = Board(geometry, keep_going=True)
    board.rect(width=50, height=50)
    for fp in geometry.footprints:
        board.place(Part(fp.inst), at=fp.location, rotation=fp.rotation, face=fp.face)
    return board, board.resolve()


@pytest.mark.parametrize('weakened', [False, True], ids=['preserved-intent', 'weakened-output'])
def test_final_narrow_copper_creates_current_path_failure(monkeypatch, weakened):
    from dataclasses import replace
    parts = [footprint('U1', 10, 10, nets=('VIN', 'X'), fields={'Pm.I': 'vin:3A'}),
             footprint('C1', 30, 10, nets=('VIN', 'GND'), fields={'Pm.I': 'vin:3A'})]
    board, plan = _placed(board_geometry(parts))
    before = score.plan_measures(board, plan)
    copper = [track('VIN', 8.6, 10, 15, 10, w=1.5),
              track('VIN', 15, 10, 21, 10, w=0.3),
              track('VIN', 21, 10, 28.6, 10, w=1.5)]
    routed_parts = [replace(fp, fields={'Pm.I': 'vin:0.1A'}) for fp in parts] if weakened else parts
    routed = board_geometry(routed_parts, copper=copper)
    reads = []
    def read(path):
        reads.append(path)
        return routed
    monkeypatch.setattr('placemat.kicad.read.read_board', read)
    final = final_board.judge(board, plan, Path('routed.kicad_pcb'), before)
    assert reads == [Path('routed.kicad_pcb')]
    failure = next(v for v in final.verdicts if v.check == 'current-path' and v.subject == 'VIN')
    assert failure.ok is False and failure.severity == 'critical'
    assert final.measures['critical_checks'] == 1
    assert not score.Validity.of(final.measures).valid
    assert 'critical_checks' not in before
    assert final.evidence()['critical_checks'] == 1
    assert bool([r for r in final.measures['critical_unknown']
                 if r['check'] == 'captured-intent']) == weakened


def test_final_check_read_failure_cannot_return_stale_placement_evidence(monkeypatch):
    board, plan = _placed(board_geometry([footprint('U1', 10, 10)]))
    before = score.plan_measures(board, plan)
    def unreadable(path):
        raise OSError('unreadable final PCB')
    monkeypatch.setattr('placemat.kicad.read.read_board', unreadable)
    with pytest.raises(OSError, match='unreadable final PCB'):
        final_board.judge(board, plan, Path('routed.kicad_pcb'), before)
    assert 'critical_checks' not in before


def test_later_back_layer_copper_resolves_a_placement_escape_wall(monkeypatch):
    import math
    from placemat.values import CopperLayer
    from tests.test_cell_drops import _via
    from tests.test_surface_escapes import _part_of, _round_pad
    from tests.fixtures import pad
    main = _part_of('P1', 'p1', [_round_pad('P1', 'p1', 1, 'S', 30, 30, 1.0)], 30, 30)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 30, 1.0, 1.0)], 10, 30)
    ring = []
    for i in range(96):
        a = 2 * math.pi * i / 96
        x, y = 30 + 1.3 * math.cos(a), 30 + 1.3 * math.sin(a)
        ring.append(track('Z', x, y, x + 0.001, y, w=0.1))
    board, plan = _placed(board_geometry([main, target], copper=ring))
    before = score.plan_measures(board, plan)
    assert before['findings'].get('escape_walled', 0) >= 1
    copper = ring + [_via('S', 30, 30, owner=''), _via('S', 10, 30, owner=''),
                     track('S', 30, 30, 10, 30, layer=CopperLayer.B)]
    routed = board_geometry([main, target], copper=copper)
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda path: routed)
    final = final_board.judge(board, plan, Path('routed.kicad_pcb'), before)
    assert final.measures['findings']['escape_walled'] == 0
    assert before['findings'].get('escape_walled', 0) >= 1
    assert not any(f.kind == 'escape_walled' for f in final.findings)


@pytest.mark.slow
@needs_kicad
def test_saved_final_pcb_preserves_current_intent_and_is_checked(tmp_path):
    import pcbnew
    from fixtures.reference.lock import realboard
    from placemat.kicad.read import read_board
    from tests.test_pour_current_vias import _written
    with realboard():
        source = _written(tmp_path)
        geometry = read_board(source)
        assert geometry.layers and not geometry.cells
        assert {fp.ref: fp.fields['Pm.I'] for fp in geometry.footprints} == {'J1': '3A', 'U2': '3A'}
        board, plan = _placed(geometry)
        before = score.plan_measures(board, plan)
        pcb = pcbnew.LoadBoard(str(source))
        for copper in pcb.GetTracks():
            copper.SetWidth(pcbnew.FromMM(0.3))
        path = tmp_path / 'routed-narrow.kicad_pcb'
        pcb.Save(str(path))
        final_geometry = read_board(path)
        assert {fp.ref: fp.fields['Pm.I'] for fp in final_geometry.footprints} == {'J1': '3A', 'U2': '3A'}
        assert final_geometry.layers == geometry.layers and final_geometry.cells == geometry.cells
        observed = []
        original = board._report_escapes
        def report(occ, result, *, final=False):
            observed.append((occ.settings, set(occ.pending), occ.geometry.layers, occ.geometry.cells))
            return original(occ, result, final=final)
        board._report_escapes = report
        final = final_board.judge(board, plan, path, before)
        assert observed == [(board.settings, set(plan.occupancy.pending), geometry.layers, geometry.cells)]
        current = [v for v in final.verdicts if v.check == 'current-path']
        assert current and any(v.ok is False and v.severity == 'critical' for v in current)
        assert final.measures['critical_checks'] > 0


@pytest.mark.parametrize('fields', [{}, {'Pm.I': 'vin:0.1A'}], ids=['missing', 'weakened'])
def test_changed_captured_current_intent_is_unmeasured_not_no_checks_success(monkeypatch, fields):
    from dataclasses import replace
    parts = [footprint('U1', 10, 10, nets=('VIN', 'X'), fields={'Pm.I': 'vin:3A'}),
             footprint('C1', 30, 10, nets=('VIN', 'GND'), fields={'Pm.I': 'vin:3A'})]
    board, plan = _placed(board_geometry(parts))
    before = score.plan_measures(board, plan)
    lost = board_geometry([replace(fp, fields=fields) for fp in parts])
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda path: lost)
    final = final_board.judge(board, plan, Path('routed.kicad_pcb'), before)
    assert final.measures['critical_checks'] == 0
    assert {(r['subject'], r.get('field')) for r in final.measures['critical_unknown']
            if r['check'] == 'captured-intent'} == {
        ('U1', 'Pm.I'), ('C1', 'Pm.I')}
    report = {'drc_new': 0, 'widths_failed': 0, 'closure_clean': 1.0, 'phases': [], **final.evidence()}
    standing = score.Standing.of_route(before, report)
    assert not standing.validity.valid
    assert 'critical_unknown' in standing.validity.unmeasured


def test_unjudged_critical_check_retains_which_subject_is_unknown(monkeypatch):
    parts = [footprint('U1', 10, 10, nets=('VIN', 'X'), fields={'Pm.I': 'vin:3A'}),
             footprint('C1', 30, 10, nets=('VIN', 'GND'), fields={'Pm.I': 'vin:3A'})]
    geometry = board_geometry(parts)
    board, plan = _placed(geometry)
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda path: geometry)
    final = final_board.judge(board, plan, Path('routed.kicad_pcb'), score.plan_measures(board, plan))
    assert final.measures['critical_checks'] == 0
    assert any(r['check'] == 'current-path' and r['subject'] == 'VIN'
               for r in final.measures['critical_unknown'])


@pytest.mark.parametrize('current', [False, True], ids=['informational-only', 'missing-load'])
def test_only_required_unjudged_current_prevents_final_certification(monkeypatch, current):
    fields = {'Pm.Loop': 'hot', **({'Pm.I': 'vin:3A'} if current else {})}
    geometry = board_geometry([footprint('U1', 10, 10, nets=('VIN', 'GND'), fields=fields)])
    board, plan = _placed(geometry)
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda path: geometry)
    before = score.plan_measures(board, plan)
    final = final_board.judge(board, plan, Path('routed.kicad_pcb'), before)
    informational = [v for v in final.verdicts if v.check == 'hot-loop']
    assert informational and all(v.ok is None and v.limit is None for v in informational)
    assert final.measures['critical_checks'] == 0
    unknown = final.measures['critical_unknown']
    assert bool(unknown) is current
    if current:
        assert unknown == [{'check': 'current-path', 'subject': 'VIN', 'reason': 'not judged'}]
    report = {'drc_new': 0, 'widths_failed': 0, 'closure_clean': 1.0, 'phases': [], **final.evidence()}
    standing = score.Standing.of_route(before, report)
    assert ('critical_unknown' in standing.validity.unmeasured) is current


def test_pending_part_has_no_final_captured_intent_obligation(monkeypatch):
    from dataclasses import replace
    part = footprint('U1', 10, 10, fields={'Pm.note': 'inactive fixture intent'})
    board, plan = _placed(board_geometry([part]))
    plan.occupancy.pending.add(part.ref)
    monkeypatch.setattr('placemat.kicad.read.read_board',
                        lambda path: board_geometry([replace(part, fields={})]))
    final = final_board.judge(board, plan, Path('routed.kicad_pcb'), score.plan_measures(board, plan))
    assert not any(r['check'] == 'captured-intent' for r in final.measures['critical_unknown'])


def test_explicit_current_path_acceptance_is_not_a_critical_failure(monkeypatch):
    from placemat import checks
    parts = [footprint('U1', 10, 10, nets=('VIN', 'X'), fields={'Pm.I': 'vin:3A'}),
             footprint('C1', 30, 10, nets=('VIN', 'GND'), fields={'Pm.I': 'vin:3A'})]
    board, plan = _placed(board_geometry(parts))
    plan.acceptances = [checks.accept('current-path', 'VIN', at_least=0.2, why='fixture accepted neck')]
    routed = board_geometry(parts, copper=[track('VIN', 8.6, 10, 28.6, 10, w=0.3)])
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda path: routed)
    final = final_board.judge(board, plan, Path('routed.kicad_pcb'), score.plan_measures(board, plan))
    assert final.measures['critical_checks'] == 0
    assert final.measures['critical_unknown'] == []
    assert any(v.check == 'current-path' and v.accepted for v in final.verdicts)
