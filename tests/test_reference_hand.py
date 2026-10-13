"""Hand reference facts accompany module results without changing the placement ratchet."""
import dataclasses
import json
import hashlib
import pathlib
import tomllib

from fixtures.reference import hand, place_ref, prepare, route_ref
from tests.conftest import needs_kicad

VERSIONS = {'placemat': '0', 'krt': '0', 'pcb': '0'}


def test_historical_hand_fixture_integrity_and_protocol_provenance():
    family = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'fairing_hand'
    manifest = json.loads((family / 'source-provenance.json').read_text())
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest['route_omitted_for_prephase_baseline'] is True
    assert manifest['checked_in_route_phase_names'] == ['signals']
    assert tomllib.loads((family / 'placemat.toml').read_text())['route']['phase'] == [{'name': 'signals'}]
    assert len(manifest['modules']) == 11
    for module in manifest['modules']:
        assert digest(family / 'hand' / (module['name'] + '.kicad_pcb')) == module['hand_sha256']
        assert digest(family / 'hand' / (module['name'] + '.kicad_pro')) == module['project_sha256']
        if module.get('hand_rules_sha256'):
            assert digest(family / 'hand' / (module['name'] + '.kicad_dru')) == module['hand_rules_sha256']
        folder = family / 'modules' / module['module']
        assert digest(folder / 'fragment_frame.py') == module['helper_sha256']
        assert digest(folder / (module['name'] + '_layout.py')) == module['checked_in_script_sha256']
        for record in module['staged_dependencies'].values():
            assert digest(family / record['staged_file']) == record['staged_sha256']
    assert not list((family / 'modules').rglob('*.kicad_pcb'))


def test_hand_reference_is_found_beside_family(tmp_path):
    script = tmp_path / 'family' / 'modules' / 'module' / 'Thing_layout.py'
    script.parent.mkdir(parents=True)
    script.write_text('')
    assert hand.reference_of(script) is None
    board = script.parents[2] / 'hand' / 'Thing.kicad_pcb'
    board.parent.mkdir()
    board.write_text('')
    assert hand.reference_of(script) == board


@needs_kicad
def test_area_encloses_every_courtyard(tmp_path):
    import pcbnew
    board = pcbnew.BOARD()
    for ref, x in (('U1', 0), ('U2', 10)):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        shape = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_RECTANGLE)
        shape.SetLayer(pcbnew.F_CrtYd)
        shape.SetStart(pcbnew.VECTOR2I_MM(-1, -1))
        shape.SetEnd(pcbnew.VECTOR2I_MM(1, 2))
        fp.Add(shape)
        fp.SetPosition(pcbnew.VECTOR2I_MM(x, 0))
        board.Add(fp)
        if x == 0:
            fp.BuildCourtyardCaches()
            box = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
            width, height = pcbnew.ToMM(box.GetWidth()), pcbnew.ToMM(box.GetHeight())
    path = tmp_path / 'board.kicad_pcb'
    pcbnew.SaveBoard(str(path), board)
    # KiCad's cached polygon includes the courtyard stroke. Two identical
    # courtyards translated 10 mm enclose (width + 10) by height, rather
    # than the drawing centreline's 12 by 3 mm.
    assert hand.footprint_area(path) == round((width + 10) * height, 2)


def test_hand_failure_preserves_measures_and_source(tmp_path, monkeypatch):
    import placemat.kicad.drc
    import placemat.report
    source = tmp_path / 'original.kicad_pcb'
    source.write_text('source')
    monkeypatch.setattr(prepare, 'strip', lambda src, dst: dst.write_text(src.read_text()))
    monkeypatch.setattr(hand, 'footprint_area', lambda pcb: 80.0)
    monkeypatch.setattr(placemat.kicad.drc, 'run_drc', lambda pcb, out, refill_zones: out.write_text('{}'))
    monkeypatch.setattr(placemat.report, 'airwires_from_drc', lambda report: {'crossings': 3, 'total_mm': 120.0})
    def failed(*args):
        raise RuntimeError('route failed')
    monkeypatch.setattr(route_ref, '_route', failed)
    facts = hand.measure_hand(source, tmp_path / 'work', None)
    assert (facts.area_mm2, facts.crossings, facts.airwire_mm) == (80.0, 3, 120.0)
    assert (facts.failure, facts.detail) == ('RuntimeError', 'route failed')
    assert source.read_text() == 'source'


def test_hand_routing_preserves_full_family_context_without_placement_overrides(tmp_path, monkeypatch):
    import placemat.kicad.drc
    import placemat.report
    from placemat.settings import load
    script = tmp_path / 'family' / 'modules' / 'module' / 'Thing_layout.py'
    script.parent.mkdir(parents=True)
    script.write_text('# original layout script\n')
    family = script.parents[2]
    config = '[check]\nrise_c = 7.0\n[scripts."modules/module/Thing_layout.py".solve]\nenabled = false\n'
    (family / 'placemat.toml').write_text(config)
    source = family / 'hand' / 'Thing.kicad_pcb'
    source.parent.mkdir()
    source.write_text('original copper')
    source.with_suffix('.kicad_pro').write_text('original manufacturing and netclass rules')
    monkeypatch.setattr(prepare, 'strip', lambda src, dst: dst.write_text(src.read_text()))
    monkeypatch.setattr(hand, 'footprint_area', lambda pcb: 80.0)
    monkeypatch.setattr(placemat.kicad.drc, 'run_drc', lambda pcb, out, refill_zones: out.write_text('{}'))
    monkeypatch.setattr(placemat.report, 'airwires_from_drc', lambda report: {'crossings': 3, 'total_mm': 120.0})

    routed_boards = []

    def routed(pcb, work, toml):
        routed_boards.append(pcb)
        assert toml is None
        assert load(pcb.parent) == load(family)
        assert load(pcb.parent).check_rise_c == 7.0
        assert pcb.parent.parent.joinpath('placemat.toml').read_text() == config
        assert pcb.parent.parent.joinpath('modules/module/Thing_layout.py').read_text() == script.read_text()
        assert pcb.with_suffix('.kicad_pro').read_text() == source.with_suffix('.kicad_pro').read_text()
        return {'closure_clean': 1.0, 'open_after': 0}

    monkeypatch.setattr(route_ref, '_route', routed)
    facts = hand.measure_hand(source, tmp_path / 'work', config, script)
    assert facts.failure == '' and facts.closure_clean == 1.0
    again = hand.measure_hand(source, tmp_path / 'work', config, script)
    assert again == facts
    assert len(routed_boards) == 2 and routed_boards[0] == routed_boards[1]
    audit = json.loads((tmp_path / 'work/context-settings.json').read_text())
    assert audit['script_overrides_applied'] is False
    assert audit['copied_settings_equal'] and audit['module_route_check_settings_equal']
    assert source.read_text() == 'original copper'
    assert (family / 'placemat.toml').read_text() == config


def test_hand_context_refuses_ambiguous_module_routing_overrides(tmp_path):
    script = tmp_path / 'family' / 'modules' / 'module' / 'Thing_layout.py'
    script.parent.mkdir(parents=True)
    script.write_text('')
    config = '[scripts."modules/module/Thing_layout.py".route]\nrouter_args = ["--track-width", "0.4"]\n'
    (script.parents[2] / 'placemat.toml').write_text(config)
    source = script.parents[2] / 'hand.kicad_pcb'
    source.write_text('source')
    facts = hand.measure_hand(source, tmp_path / 'work', config, script)
    assert facts.failure == 'ValueError'
    assert 'route_router_args' in facts.detail
    assert source.read_text() == 'source'


def test_hand_route_on_an_invalid_board_is_measured(tmp_path, monkeypatch):
    import placemat.kicad.drc
    import placemat.report
    source = tmp_path / 'hand.kicad_pcb'
    source.write_text('original')
    monkeypatch.setattr(prepare, 'strip', lambda src, dst: dst.write_text(src.read_text()))
    monkeypatch.setattr(hand, 'footprint_area', lambda pcb: 80.0)
    monkeypatch.setattr(placemat.kicad.drc, 'run_drc', lambda pcb, out, refill_zones: out.write_text('{}'))
    monkeypatch.setattr(placemat.report, 'airwires_from_drc', lambda report: {'crossings': 3, 'total_mm': 120.0})
    monkeypatch.setattr(route_ref, '_route', lambda *args: {'valid': False, 'closure_clean': 0.75, 'open_after': 1})
    facts = hand.measure_hand(source, tmp_path / 'work', None)
    assert facts.failure == '' and (facts.closure_clean, facts.open) == (0.75, 1)

def test_module_records_hand_facts_and_same_placed_area_measure(tmp_path, monkeypatch):
    script = tmp_path / 'family' / 'modules' / 'module' / 'Thing_layout.py'
    script.parent.mkdir(parents=True)
    script.write_text('')
    board = script.parents[2] / 'hand' / 'Thing.kicad_pcb'
    board.parent.mkdir()
    board.write_text('')
    monkeypatch.setattr(place_ref, 'generation_inputs', lambda script: 'd1')
    monkeypatch.setattr(place_ref, 'krt_version', lambda folder: 'k')
    monkeypatch.setattr(hand, 'measure_hand', lambda *args: hand.HandFacts(80.0, 3, 120.0, 1.0, 0))
    monkeypatch.setattr(hand, 'footprint_area', lambda path: 90.0)
    monkeypatch.setattr(place_ref, '_placed_board', lambda script: board)
    monkeypatch.setattr(place_ref, 'placemat_run', lambda *args: ({'status': 'ok', 'metrics': {
        'closure_clean': 1.0, 'extent': [10, 9], 'placed': 4, 'crossings': 5, 'airwire_mm': 150.0}}, 2.0))
    monkeypatch.setattr(place_ref, 'run_score', lambda *args, script: 5.0)
    result = place_ref.run_module('family/Thing', script, tmp_path / 'work', versions=VERSIONS)
    assert result.hand == dataclasses.asdict(hand.HandFacts(80.0, 3, 120.0, 1.0, 0))
    assert result.placed_area_mm2 == 90.0
    line = place_ref.line_module(result, place_ref.compare_module(None, result, {'placemat'}))
    assert 'hand closure_clean 100.0% area 80.0 mm2 crossings 3 airwire 120 mm' in line
    assert 'placed area 90.0 mm2 crossings 5 airwire 150 mm' in line
    board.unlink()
    without = place_ref.run_module('family/Thing', script, tmp_path / 'without', versions=VERSIONS)
    assert without.hand == {} and without.placed_area_mm2 is None
