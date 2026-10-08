"""Candidate writing requires a bound combined proof before touching files."""
from dataclasses import replace

import pytest

from placemat.pinmap_common import CandidateRefused
from placemat.pinmap_written import mint, _protected_forms
from tests.test_pinmap_common import scene
from tests.conftest import needs_kicad


def _source(tmp_path):
    path = tmp_path / 'layout.kicad_pcb'
    path.write_text('(kicad_pcb (version 20260101))\n')
    path.with_suffix('.kicad_pro').write_text('{}\n')
    return path


def test_minted_combined_proof_is_immutable_and_binds_current_source_and_settings(tmp_path):
    board, plan, inp, group = scene()
    source = _source(tmp_path)
    before = dict(plan.occupancy.items), tuple(plan.occupancy.copper), source.read_bytes()
    proof = mint(board, plan, inp, ((group.refs, group.results[0]),), source)
    proof.verify(board, plan)
    assert proof.final_pads != proof.source_pads
    assert (dict(plan.occupancy.items), tuple(plan.occupancy.copper), source.read_bytes()) == before
    with pytest.raises(CandidateRefused) as error:
        proof.verify(board, plan, replace(board.settings, score_crossing=99))
    assert error.value.code == 'proof_context_changed'
    source.write_text('(kicad_pcb (version 20260102))\n')
    with pytest.raises(CandidateRefused) as error:
        proof.verify(board, plan)
    assert error.value.code == 'proof_input_changed'


def test_illegal_partial_map_refuses_before_any_artifact_or_occupancy_mutation(tmp_path):
    board, plan, inp, group = scene()
    source = _source(tmp_path)
    candidate = group.results[0]
    assignment = dict(candidate.assign)
    assignment['A'] = ()
    before = dict(plan.occupancy.items), tuple(plan.occupancy.copper), source.read_bytes()
    with pytest.raises(CandidateRefused) as error:
        mint(board, plan, inp, ((group.refs, replace(candidate, assign=assignment)),), source)
    assert error.value.code in ('held_terminal_changed', 'terminal_multiplicity')
    assert (dict(plan.occupancy.items), tuple(plan.occupancy.copper), source.read_bytes()) == before


def test_missing_project_capture_or_colliding_sidecars_refuse_with_stable_codes(tmp_path):
    board, plan, inp, group = scene()
    source = _source(tmp_path)
    source.with_suffix('.kicad_pro').unlink()
    with pytest.raises(CandidateRefused) as error:
        mint(board, plan, inp, (), source)
    assert error.value.code == 'proof_input_missing'
    source.with_suffix('.kicad_pro').write_text('{}')
    with pytest.raises(CandidateRefused) as error:
        mint(board, plan, inp, (), source, context_files=(tmp_path / 'missing.json',))
    assert error.value.code == 'proof_capture_missing'
    with pytest.raises(CandidateRefused) as error:
        mint(board, plan, inp, (), source, context_files=(source,))
    assert error.value.code == 'proof_sidecar_collision'


def test_fixed_copper_and_zone_token_comparison_preserves_escaped_strings_and_exact_values(tmp_path):
    source = tmp_path / 'before.kicad_pcb'
    source.write_text('(kicad_pcb (footprint "old" (at 1 2))\n'
                      '(segment (start 1 2) (end 3 4) (width 0.2) (net 1))\n'
                      '(zone (name "a \\\"quoted\\\" (zone)") (net 1) (polygon (pts (xy 1 2)))))')
    candidate = tmp_path / 'after.kicad_pcb'
    candidate.write_text(source.read_text().replace('"old" (at 1 2)', '"new" (at 3 4)').replace('\n', ' '))
    assert _protected_forms(candidate) == _protected_forms(source)
    candidate.write_text(candidate.read_text().replace('(width 0.2)', '(width 0.21)'))
    assert _protected_forms(candidate) != _protected_forms(source)
    candidate.write_text('(kicad_pcb (via (at 1 2))')
    with pytest.raises(CandidateRefused) as error:
        _protected_forms(candidate)
    assert error.value.code == 'proof_board_malformed'


def test_reconstructed_or_changed_proof_is_refused_before_reader_or_destination_mutation(tmp_path, monkeypatch):
    from placemat import pinmap_written
    board, plan, inp, group = scene()
    source = _source(tmp_path)
    proof = mint(board, plan, inp, ((group.refs, group.results[0]),), source)
    def forbidden(*args, **kwargs):
        raise AssertionError('an unminted proof reached the physical reader')
    monkeypatch.setattr(pinmap_written, '_read_occupancy', forbidden)
    destination = tmp_path / 'written'
    for forged in ({'context': proof.context}, replace(proof), replace(proof, final_pads=proof.source_pads)):
        with pytest.raises(CandidateRefused) as error:
            pinmap_written.write_proved(board, plan, forged, destination)
        assert error.value.code == 'proof_missing'
        assert not destination.exists()
    assert source.read_bytes() == b'(kicad_pcb (version 20260101))\n'


@pytest.mark.slow
@needs_kicad
@pytest.mark.parametrize('attached', [False, True])
def test_saved_map_preserves_fixed_track_via_zone_and_original_project_capture(tmp_path, attached):
    from fixtures.reference.lock import realboard
    from placemat.layout import Board
    from placemat.kicad.read import read_board
    from placemat.pinmap import placed_from_plan
    from placemat.pinmap_core import study_group
    from tests.pinmap_boards import input_of
    from placemat.pinmap_written import write_proved, _read_occupancy, _pads
    from placemat.values import Part
    from tests.test_explore_remap_board import _board
    from tests.pinmap_boards import settings
    import pcbnew
    with realboard():
        source = tmp_path / 'layout.kicad_pcb'
        _board(source)
        pcb = pcbnew.LoadBoard(str(source))
        u1 = next(fp for fp in pcb.GetFootprints() if fp.GetReference() == 'U1')
        u1.SetField('Pm.PinPool', '1-4')
        # The one-pad endpoint is a test point, not a series resistor.
        # Series-following intentionally collapses passives in the generator.
        next(fp for fp in pcb.GetFootprints() if fp.GetReference() == 'R1').SetReference('TP1')
        if not attached:
            # Fixed copper stays physically separate from the reassigned pads.
            # The attached variant remains an explicit no-publication control.
            delta = pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(10))
            for fixed in pcb.GetTracks():
                fixed.Move(delta)
        # Every remapped logical role has an external endpoint. Unused pool
        # slots are not a licence to move a held singleton net as a role.
        for index, net in enumerate(('B', 'C', 'D'), 2):
            endpoint = pcbnew.FOOTPRINT(pcb)
            endpoint.SetReference(f'TP{index}')
            pcb.Add(endpoint)
            at = pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(8.5 + index - 1))
            endpoint.SetPosition(at)
            pad = pcbnew.PAD(endpoint)
            pad.SetNumber('1')
            pad.SetShape(getattr(pcbnew, 'PAD_SHAPE_RECT', None) or pcbnew.PAD_SHAPE_RECTANGLE)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(.6), pcbnew.FromMM(.6)))
            pad.SetLayerSet(pad.SMDMask())
            pad.SetNet(pcb.FindNet(net))
            endpoint.Add(pad)
            pad.SetPosition(at)
        # Even an unfilled zone's complete definition must survive unchanged.
        zone = pcbnew.ZONE(pcb)
        zone.SetNet(pcb.FindNet('D'))
        zone.SetLayer(pcbnew.F_Cu)
        poly = zone.Outline()
        poly.NewOutline()
        for x, y in ((25, 25), (30, 25), (30, 30), (25, 30)):
            poly.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        pcb.Add(zone)
        pcb.Save(str(source))
        source.with_suffix('.kicad_pro').write_text('{}\n')
        capture = tmp_path / 'capture.json'
        capture.write_text('{"interfaces": ["original"]}\n')
        original = {p: p.read_bytes() for p in (source, source.with_suffix('.kicad_pro'), capture)}
        cfg = settings(pins_rotations=(0.0,), cleanup_enabled=False)
        board = Board(read_board(source), keep_going=True, settings=cfg)
        board.pin_study = False
        board.rect(width=50, height=50)
        for fp in board.geometry.footprints:
            board.place(Part(fp.inst), at=fp.location, rotation=fp.rotation, face=fp.face)
        plan = board.resolve()
        placed = placed_from_plan(board, plan)
        inp, problems = input_of(placed.pads, placed.parts, cells=placed.cells,
                                 netclasses=board.geometry.netclasses, names=board.geometry.pin_names)
        assert not problems
        study = study_group(inp, ('U1',), cfg, native=False)
        assignment = {net: tuple((ref, {'1': '2', '2': '1'}.get(number, number)) if ref == 'U1' else (ref, number)
                                 for ref, number in ends) for net, ends in study.present_assign.items()}
        changed = replace(study.results[0], assign=assignment)
        proof = mint(board, plan, inp, ((study.refs, changed),), source, context_files=(capture,))
        if attached:
            with pytest.raises(CandidateRefused) as refusal:
                write_proved(board, plan, proof, tmp_path / 'candidate')
            assert refusal.value.code == 'proof_fixed_board_items_changed'
            assert not (tmp_path / 'candidate').exists()
            assert not list(tmp_path.glob('placemat-remap-*'))
            assert {p: p.read_bytes() for p in original} == original
            return
        emitted, receipt = write_proved(board, plan, proof, tmp_path / 'candidate')
        assert _pads(_read_occupancy(emitted, cfg)) == proof.final_pads
        assert _protected_forms(emitted) == _protected_forms(source)
        assert {p: p.read_bytes() for p in original} == original
        assert emitted.with_suffix('.kicad_pro').read_bytes() == original[source.with_suffix('.kicad_pro')]
        assert (emitted.parent / capture.name).read_bytes() == original[capture]
        assert receipt['scope'] == 'exact written placement; routed comparison unavailable'


@pytest.mark.slow
@needs_kicad
@pytest.mark.parametrize('cell,flip', [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize('rotation', [90.0, 37.0])
def test_saved_supported_pose_matches_every_member_pad_and_full_front_back_pose(tmp_path, cell, flip, rotation):
    from fixtures.reference.lock import realboard
    from placemat.layout import Board
    from placemat.kicad.read import read_board
    from placemat.pinmap import placed_from_plan
    from placemat.pinmap_core import study_group
    from placemat.pinmap_written import write_proved, _read_occupancy, _pads, _poses, _shapes
    from placemat.values import Part, Cell, Face, Near
    from tests.test_explore_remap_board import _board
    from tests.pinmap_boards import settings, input_of
    import pcbnew
    with realboard():
        source = tmp_path / 'layout.kicad_pcb'
        _board(source)
        pcb = pcbnew.LoadBoard(str(source))
        # This positive pose scene has no current fixed copper to move.
        for track in list(pcb.GetTracks()):
            pcb.Delete(track)
        u1 = next(fp for fp in pcb.GetFootprints() if fp.GetReference() == 'U1')
        u1.SetField('Pm.PinPool', '1-4')
        next(fp for fp in pcb.GetFootprints() if fp.GetReference() == 'R1').SetReference('TP1')
        courtyard = pcbnew.PCB_SHAPE(u1)
        courtyard.SetShape(pcbnew.SHAPE_T_RECT)
        courtyard.SetLayer(pcbnew.F_CrtYd)
        courtyard.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(7), pcbnew.FromMM(7)))
        courtyard.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(13), pcbnew.FromMM(13)))
        courtyard.SetWidth(pcbnew.FromMM(.05))
        u1.Add(courtyard)
        if cell:
            group = pcbnew.PCB_GROUP(pcb)
            group.SetName('module')
            pcb.Add(group)
            # Keep the connected endpoint outside the moved cell. A second
            # member makes this a real whole-cell pose, rather than one part.
            member = pcbnew.FOOTPRINT(pcb)
            member.SetReference('TP2')
            member.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(14), pcbnew.FromMM(13)))
            pcb.Add(member)
            pad = pcbnew.PAD(member)
            pad.SetNumber('1')
            pad.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(.6), pcbnew.FromMM(.6)))
            pad.SetLayerSet(pad.SMDMask())
            pad.SetNet(pcb.FindNet('A'))
            member.Add(pad)
            pad.SetPosition(member.GetPosition())
            group.AddItem(u1)
            group.AddItem(member)
        pcb.Save(str(source))
        source.with_suffix('.kicad_pro').write_text('{}\n')
        saved = source.read_bytes()
        cfg = settings(pins_rotations=(0.0, rotation), pins_faces=True, cleanup_enabled=False)
        board = Board(read_board(source), keep_going=True, settings=cfg)
        board.pin_study = False
        board.rect(width=50, height=50)
        if cell:
            item = board.geometry.cells['module']
            board.place(Cell('module'), at=Near(item.box.center), radius=0, rotations=(0,), face=Face.EITHER)
            for fp in board.geometry.footprints:
                if fp.cell is None:
                    board.place(Part(fp.inst), at=Near(fp.location), radius=0, rotations=(0,), face=Face.EITHER)
        else:
            for fp in board.geometry.footprints:
                board.place(Part(fp.inst), at=Near(fp.location), radius=0, rotations=(0,), face=Face.EITHER)
        plan = board.resolve()
        placed = placed_from_plan(board, plan)
        inp, problems = input_of(placed.pads, placed.parts, cells=placed.cells,
                                 netclasses=board.geometry.netclasses, names=board.geometry.pin_names)
        assert inp is not None and not problems, (inp, problems)
        study = study_group(inp, ('U1',), cfg, native=False)
        candidate = replace(study.results[0], poses=(('U1', rotation, flip),), assign=study.present_assign)
        if cell and flip:
            # The study deliberately holds cells on their current face. An
            # unsupported proposal must not reach the writer or publish files.
            with pytest.raises(CandidateRefused) as error:
                mint(board, plan, inp, ((study.refs, candidate),), source)
            assert error.value.code == 'pose_not_allowed'
            assert source.read_bytes() == saved
            assert not (tmp_path / 'candidate').exists()
            assert not list(tmp_path.glob('placemat-remap-*'))
            return
        proof = mint(board, plan, inp, ((study.refs, candidate),), source)
        try:
            emitted, _ = write_proved(board, plan, proof, tmp_path / 'candidate')
        except CandidateRefused as error:
            # Arbitrary-angle nanometre serialization may change the evaluated
            # geometry. Such a result is explicitly unsupported, never adopted
            # through a relaxed numeric tolerance. Quarter-turn gates must pass.
            assert rotation == 37.0, (error.code, error.facts, str(error))
            assert error.code in ('proof_readback_geometry_changed', 'proof_readback_collision_changed')
            assert source.read_bytes() == saved
            assert not (tmp_path / 'candidate').exists()
            assert not list(tmp_path.glob('placemat-remap-*'))
            return
        actual = _read_occupancy(emitted, cfg)
        assert _pads(actual) == proof.final_pads
        assert _poses(actual) == proof.final_poses
        assert _shapes(actual) == proof.final_shapes
        assert source.read_bytes() == saved
        assert any(final != dict(proof.source_poses)[ref] for ref, final in proof.final_poses)
        if cell:
            members = {'U1', 'TP2'}
            assert all(final != dict(proof.source_poses)[ref]
                       for ref, final in proof.final_poses if ref in members)
            assert all(final == dict(proof.source_poses)[ref]
                       for ref, final in proof.final_poses if ref not in members)


@pytest.mark.parametrize('name', ['canonical-source.kicad_pcb', 'placement-proof.json'])
def test_reserved_bundle_input_names_refuse_before_evaluation(tmp_path, name, monkeypatch):
    from placemat import pinmap_written
    board, plan, inp, _ = scene()
    source = _source(tmp_path)
    sidecar = tmp_path / name
    sidecar.write_text('preserved original')
    monkeypatch.setattr(pinmap_written.Finalists, 'evaluate', lambda *a, **k: pytest.fail('reserved name reached evaluation'))
    with pytest.raises(CandidateRefused) as error:
        mint(board, plan, inp, (), source, context_files=(sidecar,))
    assert error.value.code == 'proof_sidecar_reserved'
    assert sidecar.read_text() == 'preserved original'


def test_readback_refusal_leaves_no_destination_and_preserves_all_original_bytes(tmp_path, monkeypatch):
    from placemat import pinmap_written
    board, plan, inp, group = scene()
    source = _source(tmp_path)
    project, rules, capture = source.with_suffix('.kicad_pro'), source.with_suffix('.kicad_dru'), tmp_path / 'capture.json'
    rules.write_text('(version 1)')
    capture.write_text('{"original": true}')
    before = {path: path.read_bytes() for path in (source, project, rules, capture)}
    proof = mint(board, plan, inp, ((group.refs, group.results[0]),), source, context_files=(capture,))
    # Return original pad nets at readback: this cannot certify the remap.
    monkeypatch.setattr(pinmap_written, '_read_occupancy', lambda *a: plan.occupancy)
    def edit(proof, out, canonical):
        canonical.write_bytes(source.read_bytes())
        out.write_bytes(source.read_bytes())
    monkeypatch.setattr(pinmap_written, '_edit_candidate', edit)
    destination = tmp_path / 'candidate'
    with pytest.raises(CandidateRefused) as error:
        pinmap_written.write_proved(board, plan, proof, destination)
    assert error.value.code == 'proof_readback_geometry_changed'
    assert not destination.exists()
    assert not list(tmp_path.glob('placemat-remap-*'))
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize('change', ['drill', 'lib_id', 'net_tie', 'group', 'dnp'])
def test_same_polygons_with_changed_manufacturing_or_identity_refuse_before_edit(tmp_path, monkeypatch, change):
    import copy
    from placemat import pinmap_written

    board, plan, inp, group = scene()
    source = _source(tmp_path)
    proof = mint(board, plan, inp, ((group.refs, group.results[0]),), source)
    fp = plan.occupancy.geometry.footprints[0]
    if change == 'drill':
        changed = replace(fp, pads=(replace(fp.pads[0], drill_mm=fp.pads[0].drill_mm + .1), *fp.pads[1:]))
    elif change == 'lib_id':
        changed = replace(fp, lib_id='different:footprint')
    elif change == 'net_tie':
        changed = replace(fp, net_tie_groups=(('1', '2'),))
    elif change == 'group':
        changed = replace(fp, cell='unrelated-source-group')
    else:
        changed = replace(fp, dnp=not fp.dnp)
    actual = copy.copy(plan.occupancy)
    actual.geometry = replace(actual.geometry, footprints=(changed, *actual.geometry.footprints[1:]),
                              _by_ref={}, _by_inst={})
    monkeypatch.setattr(pinmap_written, '_read_occupancy', lambda *args: actual)
    monkeypatch.setattr(pinmap_written, '_edit_candidate', lambda *args: pytest.fail('changed source reached writer'))
    saved = source.read_bytes(), source.with_suffix('.kicad_pro').read_bytes()
    destination = tmp_path / 'candidate'
    with pytest.raises(CandidateRefused) as error:
        pinmap_written.write_proved(board, plan, proof, destination)
    assert error.value.code == 'proof_source_semantics_changed'
    assert not destination.exists()
    assert (source.read_bytes(), source.with_suffix('.kicad_pro').read_bytes()) == saved


def test_same_polygon_with_changed_analytic_shape_refuses_before_edit(tmp_path, monkeypatch):
    import copy
    from placemat import pinmap_written

    board, plan, inp, group = scene()
    source = _source(tmp_path)
    proof = mint(board, plan, inp, ((group.refs, group.results[0]),), source)
    actual = copy.copy(plan.occupancy)
    actual.items = dict(actual.items)
    ref, item = next(iter(actual.items.items()))
    actual.items[ref] = replace(item, shapes=(replace(item.shapes[0], circle=(1., 2., .3)), *item.shapes[1:]))
    monkeypatch.setattr(pinmap_written, '_read_occupancy', lambda *args: actual)
    monkeypatch.setattr(pinmap_written, '_edit_candidate', lambda *args: pytest.fail('changed collision shape reached writer'))
    with pytest.raises(CandidateRefused) as error:
        pinmap_written.write_proved(board, plan, proof, tmp_path / 'candidate')
    assert error.value.code == 'proof_written_source_mismatch'
    assert not (tmp_path / 'candidate').exists()


def test_same_polygon_with_changed_effective_pad_collision_refuses(tmp_path, monkeypatch):
    import copy
    from placemat import pinmap_written

    board, plan, inp, group = scene()
    source = _source(tmp_path)
    proof = mint(board, plan, inp, ((group.refs, group.results[0]),), source)
    actual = copy.copy(plan.occupancy)
    fp = actual.geometry.footprints[0]
    changed = replace(fp, pads=(replace(fp.pads[0], kshapes=(('c', 100000, 200000, 30000),)), *fp.pads[1:]))
    actual.geometry = replace(actual.geometry, footprints=(changed, *actual.geometry.footprints[1:]),
                              _by_ref={}, _by_inst={})
    monkeypatch.setattr(pinmap_written, '_read_occupancy', lambda *args: actual)
    monkeypatch.setattr(pinmap_written, '_edit_candidate', lambda *args: pytest.fail('changed effective copper reached writer'))
    with pytest.raises(CandidateRefused) as error:
        pinmap_written.write_proved(board, plan, proof, tmp_path / 'candidate')
    assert error.value.code == 'proof_source_collision_changed'
    assert not (tmp_path / 'candidate').exists()


def test_exact_polygon_enumeration_preserves_pad_and_all_shape_identity():
    from placemat.pinmap_written import _pads, _shapes
    from placemat.pinmap_common import detached
    board, plan, _, _ = scene()
    original = plan.occupancy
    changed = detached(original)
    for ref, item in changed.items.items():
        changed.items[ref] = replace(item, shapes=tuple(
            replace(s, poly=tuple(reversed(s.poly[1:] + s.poly[:1]))) if s.poly else s
            for s in item.shapes))
    assert _pads(changed) == _pads(original)
    assert _shapes(changed) == _shapes(original)


@pytest.mark.parametrize('change', ['vertex', 'net', 'layer', 'hole'])
def test_polygon_enumeration_normalization_keeps_physical_differences(change):
    from placemat.pinmap_written import _shapes
    from placemat.pinmap_common import detached
    from placemat.values import CopperLayer
    _, plan, _, _ = scene()
    original = plan.occupancy
    changed = detached(original)
    ref, item = next(iter(changed.items.items()))
    shape = next(s for s in item.shapes if s.kind == 'pad')
    if change == 'vertex':
        altered = replace(shape, poly=((shape.poly[0][0] + .001, shape.poly[0][1]), *shape.poly[1:]))
    elif change == 'net':
        altered = replace(shape, net='different')
    elif change == 'layer':
        altered = replace(shape, layers=frozenset((CopperLayer.B,)))
    else:
        # Analytic hole/circle metadata must remain exact even at same polygon.
        altered = replace(shape, circle=(1., 2., .3))
    changed.items[ref] = replace(item, shapes=tuple(altered if s is shape else s for s in item.shapes))
    assert _shapes(changed) != _shapes(original)


def test_proved_face_transform_preserves_exact_mask_paste_membership_and_other_semantics():
    from placemat.pinmap_written import _semantics
    from placemat.values import Face
    from tests.fixtures import board_geometry, footprint
    fp = footprint('A', 10, 10)
    fp = replace(fp, pads=tuple(replace(p, mask_paste=('F.Paste', 'F.Mask')) for p in fp.pads))
    front = board_geometry((fp,))
    back_fp = replace(fp, face=Face.BACK, pads=tuple(
        replace(p, mask_paste=('B.Mask', 'B.Paste')) for p in fp.pads))
    back = replace(front, footprints=(back_fp,), _by_ref={}, _by_inst={})
    assert _semantics(front, {'A': Face.BACK}) == _semantics(back)
    assert _semantics(back, {'A': Face.FRONT}) == _semantics(front)
    assert _semantics(front, {'A': Face.FRONT}) == _semantics(front)
    changed = replace(back, footprints=(replace(back_fp, pads=(
        replace(back_fp.pads[0], mask_paste=('B.Mask',)), *back_fp.pads[1:])),), _by_ref={}, _by_inst={})
    assert _semantics(front, {'A': Face.BACK}) != _semantics(changed)
    changed_drill = replace(back, footprints=(replace(back_fp, pads=(
        replace(back_fp.pads[0], drill_mm=.3), *back_fp.pads[1:])),), _by_ref={}, _by_inst={})
    assert _semantics(front, {'A': Face.BACK}) != _semantics(changed_drill)


@pytest.mark.parametrize('read_changes_project', [False, True])
def test_save_defaults_restore_exact_sidecars_before_readback(tmp_path, monkeypatch, read_changes_project):
    from placemat import pinmap_written
    board, plan, inp, _ = scene()
    source = _source(tmp_path)
    project = source.with_suffix('.kicad_pro')
    rules = source.with_suffix('.kicad_dru')
    capture = tmp_path / 'capture.json'
    rules.write_text('(version 1)')
    capture.write_text('{"original": true}')
    original = {path: path.read_bytes() for path in (source, project, rules, capture)}
    proof = mint(board, plan, inp, (), source, context_files=(capture,))
    def edit(proof, out, canonical):
        canonical.write_bytes(source.read_bytes())
        out.write_bytes(source.read_bytes())
        out.with_suffix('.kicad_pro').write_text('{"native_defaults": true}')
    def read(path, settings):
        if path != source:
            assert path.with_suffix('.kicad_pro').read_bytes() == original[project]
            assert path.with_suffix('.kicad_dru').read_bytes() == original[rules]
            assert (path.parent / capture.name).read_bytes() == original[capture]
            if read_changes_project:
                path.with_suffix('.kicad_pro').write_text('{"changed_on_read": true}')
        return plan.occupancy
    monkeypatch.setattr(pinmap_written, '_edit_candidate', edit)
    monkeypatch.setattr(pinmap_written, '_read_occupancy', read)
    destination = tmp_path / 'candidate'
    if read_changes_project:
        with pytest.raises(CandidateRefused) as error:
            pinmap_written.write_proved(board, plan, proof, destination)
        assert error.value.code == 'proof_readback_sidecar_changed'
        assert not destination.exists()
    else:
        pinmap_written.write_proved(board, plan, proof, destination)
        for path in (project, rules, capture):
            assert (destination / path.name).read_bytes() == original[path]
    assert {path: path.read_bytes() for path in original} == original


def test_readback_record_is_stable_across_fresh_hash_seed_processes():
    import json
    import os
    import subprocess
    import sys
    code = '''
import json
from dataclasses import replace
from tests.fixtures import board_geometry, footprint
from placemat.occupancy import Occupancy
from placemat.pinmap_written import _readback_record
fp=footprint('U1',10,10,nets=('A','B'))
fp=replace(fp,pads=tuple(replace(p,through=True) for p in fp.pads),net_tie_pads=frozenset(('1','2')))
print(json.dumps(_readback_record(Occupancy(board_geometry([fp]))),sort_keys=True,allow_nan=False))
'''
    records=[]
    for seed in ('1','42','1234'):
        completed=subprocess.run([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':seed},
                                 capture_output=True,text=True,check=True,timeout=10)
        records.append(json.loads(completed.stdout))
    assert records[0] == records[1] == records[2]
    assert records[0]['schema'] == 1
    assert records[0]['shapes']


def test_shared_readback_expectation_checks_all_fields_and_rejects_malformed_schema(tmp_path):
    import copy
    from placemat import pinmap_written
    from placemat.pinmap_common import Finalists
    board,plan,inp,group=scene()
    physical=mint(board,plan,inp,((group.refs,group.results[0]),),_source(tmp_path))
    occ=Finalists(board,plan).evaluate(inp,((group.refs,group.results[0]),)).occupancy
    expected=pinmap_written._readback_expectation(physical)
    pinmap_written._verify_readback_record(expected,occ)
    for key in ('pads','poses','shapes','fixed_copper','rules','semantics','collision','properties'):
        changed=copy.deepcopy(expected)
        changed[key]=['unproved']
        with pytest.raises(CandidateRefused):
            pinmap_written._verify_readback_record(changed,occ)
    for changed in ({}, {**expected,'schema':True}, {**expected,'extra':1}):
        with pytest.raises(CandidateRefused) as error:
            pinmap_written._verify_readback_record(changed,occ)
        assert error.value.code == 'proof_readback_record_malformed'
    with pytest.raises(CandidateRefused) as error:
        pinmap_written._readback_expectation(replace(physical))
    assert error.value.code == 'proof_missing'


def test_readback_nested_nonfinite_or_nonjson_values_are_structured_refusals(tmp_path):
    import copy
    from placemat import pinmap_written
    from placemat.pinmap_common import Finalists
    board,plan,inp,group=scene()
    physical=mint(board,plan,inp,((group.refs,group.results[0]),),_source(tmp_path))
    occ=Finalists(board,plan).evaluate(inp,((group.refs,group.results[0]),)).occupancy
    expected=pinmap_written._readback_expectation(physical)
    for invalid in (float('nan'), object()):
        changed=copy.deepcopy(expected)
        changed['shapes'][0][1][0][1]=invalid
        with pytest.raises(CandidateRefused) as error:
            pinmap_written._verify_readback_record(changed,occ)
        assert error.value.code == 'proof_readback_record_malformed'
    changed=copy.deepcopy(expected)
    fields=dict(changed['shapes'][0][1])
    assert type(fields['wire']) is bool
    for pair in changed['shapes'][0][1]:
        if pair[0]=='wire': pair[1]=int(pair[1])
    with pytest.raises(CandidateRefused) as error:
        pinmap_written._verify_readback_record(changed,occ)
    assert error.value.code == 'proof_readback_geometry_changed'


@pytest.mark.parametrize('identity', ['source_shapes','final_shapes','rules','semantics','final_semantics'])
def test_nested_minted_identity_mutation_cannot_change_expected_readback(tmp_path,identity):
    from placemat import pinmap_written
    board,plan,inp,group=scene()
    proof=mint(board,plan,inp,((group.refs,group.results[0]),),_source(tmp_path))
    def mutate(value):
        if isinstance(value,list):
            value.append('unproved')
            return True
        if isinstance(value,dict):
            value['unproved']=1
            return True
        if isinstance(value,tuple):
            return any(mutate(member) for member in value)
        return False
    assert mutate(getattr(proof,identity))
    with pytest.raises(CandidateRefused) as error:
        proof.verify(board,plan)
    assert error.value.code == 'proof_changed'
    with pytest.raises(CandidateRefused) as error:
        pinmap_written._readback_expectation(proof)
    assert error.value.code == 'proof_changed'
    with pytest.raises(CandidateRefused) as error:
        pinmap_written.write_proved(board,plan,proof,tmp_path/'written')
    assert error.value.code == 'proof_changed'
    assert not (tmp_path/'written').exists()


def test_retained_minted_identity_does_not_keep_proof_alive(tmp_path):
    import gc
    import weakref
    from placemat import pinmap_written
    board,plan,inp,group=scene()
    proof=mint(board,plan,inp,((group.refs,group.results[0]),),_source(tmp_path))
    key=id(proof);reference=weakref.ref(proof)
    assert key in pinmap_written._PROOF_RECORDS
    del proof
    gc.collect()
    assert reference() is None
    assert key not in pinmap_written._PROOF_RECORDS
    assert key not in pinmap_written._MINTED


def test_declared_rotation_float_canonicalizes_equal_integer_source_angle():
    from placemat.placement import Placement
    from placemat.values import Location
    from placemat.pinmap_written import _pose_records
    source = Placement(Location(1.0, 2.0), 0)
    read = replace(source, rotation=0.0)
    assert _pose_records((('U1', source),)) == _pose_records((('U1', read),))
    assert type(_pose_records((('U1', source),))[0][1]['rotation']) is float
    assert _pose_records((('U1', source),)) != _pose_records((('U1', replace(source, rotation=0.000000001)),))


@pytest.mark.parametrize('rotation', (True, False, float('nan'), float('inf'), -float('inf'), '0'))
def test_rotation_transport_refuses_invalid_values(rotation):
    from placemat.placement import Placement
    from placemat.values import Location
    from placemat.pinmap_written import _pose_records
    with pytest.raises(CandidateRefused) as error:
        _pose_records((('U1', Placement(Location(1.0, 2.0), rotation)),))
    assert error.value.code == 'proof_pose_malformed'
