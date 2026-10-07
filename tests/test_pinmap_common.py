"""Pin finalists retain the current physical copper and original intent."""
from dataclasses import replace

import pytest

from placemat.layout import Board
from placemat.pinmap import placed_from_plan
from placemat.pinmap_common import Finalists, mapped_geometry
from placemat.pinmap_core import study_group
from placemat.values import Part, PadRef, Cell, Location, Face, Near
from tests.fixtures import board_geometry, footprint, pad, track
from tests.pinmap_boards import input_of, quad_footprint, settings


def scene(copper=(), *, points=None, paired=False, source_nets=('A', 'B', 'C', 'D'), cell='', fields=None,
          either=False):
    parts = [quad_footprint('U1', 10, 10, {'E': source_nets},
                            fields={'Pm.PinPool': '1-4', **(fields or {})}, cell=cell or None,
                            inst='module.u1' if cell else 'u1')]
    targets = list(zip('ABCD', points)) if points is not None else [
        (net, (20, 8.5 + index)) for index, net in enumerate('DCBA')]
    for index, (net, (x, y)) in enumerate(targets):
        ref = f'TP{index + 1}'
        pin = pad(ref, ref.lower(), '1', net, x, y, w=.3, h=.3)
        box = pin.box.inflate(.1)
        parts.append(replace(footprint(ref, x, y), pads=(pin,),
                             body_box=box, courtyard_box=box, phys_box=box))
    cfg = settings(pins_rotations=(0.0,), cleanup_enabled=False)
    geometry = board_geometry(parts, cells=(cell,) if cell else (), copper=copper,
                              extra_nets=('OTHER',) if paired else ())
    if paired:
        pair = replace(geometry.netclasses['A'], name='Pair', diff_pair_width=.2, diff_pair_gap=.2)
        geometry = replace(geometry, netclasses={**geometry.netclasses, 'A': pair, 'OTHER': pair})
    board = Board(geometry, keep_going=True, settings=cfg)
    board.pin_study = False
    board.rect(width=50, height=50)
    for part in parts:
        if part.cell:
            board.place(Cell(part.cell), at=Location(10, 10))
            continue
        if either and part.ref == 'U1':
            board.place(Part(part.inst), at=Near(part.location), radius=.01, rotations=(0,), face=Face.EITHER)
            continue
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    placed = placed_from_plan(board, plan)
    inp, problems = input_of(placed.pads, placed.parts, cells=placed.cells,
                             partners={'A': 'OTHER', 'OTHER': 'A'} if paired else {},
                             netclasses=geometry.netclasses, names=geometry.pin_names)
    assert not problems
    group = study_group(inp, ('U1',), cfg, native=False)
    return board, plan, inp, group


def test_reverse_map_common_judgment_and_source_restoration():
    board, plan, inp, group = scene()
    occ = plan.occupancy
    before = dict(occ.items), tuple(occ.copper), set(occ.pending)
    judge = Finalists(board, plan)
    baseline = judge.evaluate(inp)
    candidate = judge.evaluate(inp, ((('U1',), group.results[0]),))
    assert not baseline.reasons and not candidate.reasons
    assert candidate.key < baseline.key
    assert (dict(occ.items), tuple(occ.copper), set(occ.pending)) == before


def test_fixed_copper_is_not_retagged_to_make_remap_safe():
    copper = track('A', 11.7, 8.5, 12.2, 8.5, owner='drawn')
    board, plan, inp, group = scene((copper,))
    judge = Finalists(board, plan)
    baseline = judge.evaluate(inp)
    candidate = judge.evaluate(inp, ((('U1',), group.results[0]),))
    assert not candidate.reasons
    assert candidate.validity.key() > baseline.validity.key()
    mapped = mapped_geometry(plan.occupancy, {('U1', '1'): 'D'})
    assert mapped.copper == plan.occupancy.copper
    assert any(shape.net == 'A' for shape in mapped.copper)


@pytest.mark.parametrize('key,value', [('score_crossing', 50.0), ('place_escape_depth', 3.0)])
def test_effective_settings_bound_to_detached_board_and_occupancy(key, value):
    board, plan, inp, group = scene()
    effective = replace(board.settings, **{key: value})
    result = Finalists(board, plan, effective).evaluate(inp)
    assert not result.reasons
    assert result.occupancy.settings is effective
    assert getattr(plan.occupancy.settings, key) != value
    if key == 'score_crossing':
        assert result.terms['crossings'] == 6 * value


def test_foreign_endpoint_refused_before_source_mutation():
    board, plan, inp, group = scene()
    candidate = group.results[0]
    assignment = dict(candidate.assign)
    assignment['A'] = assignment['A'] + (('TP4', '1'),)
    before = dict(plan.occupancy.items), tuple(plan.occupancy.copper)
    result = Finalists(board, plan).evaluate(inp, ((('U1',), replace(candidate, assign=assignment)),))
    assert result.reasons == ('pin finalist changes a held or unrelated logical terminal',)
    assert (dict(plan.occupancy.items), tuple(plan.occupancy.copper)) == before


def test_supported_pose_matches_exact_occupancy_transform():
    board, plan, inp, group = scene()
    cfg = replace(board.settings, pins_rotations=(0.0, 90.0))
    candidate = replace(group.results[0], poses=(('U1', 90.0, False),))
    result = Finalists(board, plan, cfg).evaluate(inp, ((('U1',), candidate),))
    assert not result.reasons
    occ = mapped_geometry(plan.occupancy, {('U1', str(k)): net for k, net in enumerate('DCBA', 1)})
    fp = occ.geometry.footprint('U1')
    expected = replace(occ._geometry(fp).reference, rotation=90.0)
    geoms, _ = occ.placed_geometries(fp, expected)
    actual = result.occupancy.items['U1']
    assert actual.reference == expected
    assert actual.shapes == geoms['U1'].shapes


def test_carried_copper_pose_refused_without_source_mutation():
    board, plan, inp, group = scene((track('A', 11.7, 8.5, 12.2, 8.5, owner='U1'),))
    candidate = replace(group.results[0], poses=(('U1', 90.0, False),))
    before = dict(plan.occupancy.items), tuple(plan.occupancy.copper), set(plan.occupancy.pending)
    result = Finalists(board, plan, replace(board.settings, pins_rotations=(0.0, 90.0))).evaluate(
        inp, ((('U1',), candidate),))
    assert result.reasons == ('pin finalist pose would move fixed current copper',)
    assert (dict(plan.occupancy.items), tuple(plan.occupancy.copper), set(plan.occupancy.pending)) == before


@pytest.mark.parametrize('selector,refused', [(1, True), ('A', False)])
def test_fixed_pad_links_and_logical_net_links_remain_distinct(selector, refused):
    board, _, inp, group = scene()
    board.link(PadRef(Part('u1'), selector), PadRef(Part('tp4'), 1))
    plan = board.resolve()
    result = Finalists(board, plan).evaluate(inp, ((('U1',), group.results[0]),))
    if refused:
        assert result.reasons == ('pin finalist changes an explicit fixed pad link obligation',)
        assert result.refusals[0]['code'] == 'fixed_pad_link_changed'
        assert result.refusals[0]['facts']['original_endpoint'] == ['U1', '1']
    else:
        assert not result.reasons
        assert result.occupancy.pad_shapes('U1', '4')[0].net == 'A'


def test_all_lands_of_one_physical_pin_get_same_net():
    board, plan, inp, group = scene()
    occ = plan.occupancy
    fp = occ.geometry.footprint('U1')
    first = fp.pads[0]
    extra = replace(first, outlines=tuple(tuple((x + .1, y) for x, y in poly)
                                        for poly in first.outlines))
    geometry = replace(occ.geometry, footprints=tuple(replace(part, pads=part.pads + (extra,))
                                                      if part.ref == 'U1' else part
                                                      for part in occ.geometry.footprints), _by_ref={}, _by_inst={})
    original = occ.geometry
    occ.geometry = geometry
    try:
        mapped = mapped_geometry(occ, {('U1', '1'): 'D'})
    finally:
        occ.geometry = original
    assert [p.net for p in mapped.geometry.footprint('U1').pads if p.number == '1'] == ['D', 'D']
    assert all(shape.net == 'D' for shape in mapped.items['U1'].shapes
               if shape.kind in ('pad', 'through') and shape.label == '1')


def test_required_electrical_intent_never_inherits_stale_success():
    board, plan, inp, group = scene()
    geometry = plan.occupancy.geometry
    changed = replace(geometry, footprints=tuple(replace(fp, fields={**fp.fields, 'Pm.I': 'A:3A'})
                                                 if fp.ref == 'U1' else fp for fp in geometry.footprints),
                      _by_ref={}, _by_inst={})
    plan.occupancy.geometry = changed
    plan.geometry = changed
    board.geometry = changed
    result = Finalists(board, plan).evaluate(inp, ((('U1',), group.results[0]),))
    assert result.validity.unmeasured == ('final electrical geometry unavailable: U1',)
    assert not result.validity.valid


def test_bend_generator_gain_can_hide_a_common_objective_loss():
    board, plan, inp, _ = scene(points=[(11, 22), (18, 12), (9, 26), (8, 25)],
                                paired=True, source_nets=('B', 'D', 'C', 'A'))
    cfg = replace(board.settings, score_crossing_pair_net=1.0)
    group = study_group(inp, ('U1',), cfg, native=False)
    candidate = group.results[0]
    assert candidate.breakdown.total < group.present.total
    judge = Finalists(board, plan, cfg)
    baseline = judge.evaluate(inp)
    final = judge.evaluate(inp, ((('U1',), candidate),))
    assert final.validity == baseline.validity
    assert final.total > baseline.total + 20
    selection = judge.select(inp, group)
    assert not selection.actionable
    assert selection.gain < -20
    assert selection.reason == 'no common improvement'


def test_shared_pair_price_changes_actual_common_finalist_choice():
    board, plan, inp, group = scene(points=[(19, 8), (14, 16), (32, 12), (12.8, 12.8)], paired=True)
    candidates = [replace(group.results[0], assign={net: (('U1', pin),)
                                                  for net, pin in zip('ABCD', pins)})
                  for pins in ('3412', '1423')]
    winners = []
    for price in (.1, 80.0):
        cfg = replace(board.settings, score_crossing_pair_net=price, score_escape_crossed=0,
                      score_escape_closed=0, score_escape_via=0)
        judge = Finalists(board, plan, cfg)
        selection = judge.select(inp, replace(group, results=tuple(candidates)))
        assert all(result.validity.valid for result in selection.finalists)
        winners.append(selection.best)
    assert winners == [0, 1]


def test_via_only_current_copper_pose_refused_before_mutation():
    from tests.test_vias_give_way import _via
    board, plan, inp, group = scene((_via('A', 12, 8.5, owner='U1'),))
    before = dict(plan.occupancy.items), tuple(plan.occupancy.copper), set(plan.occupancy.pending)
    assert any(shape.kind == 'through' for shape in plan.occupancy.copper)
    candidate = replace(group.results[0], poses=(('U1', 90.0, False),))
    result = Finalists(board, plan, replace(board.settings, pins_rotations=(0.0, 90.0))).evaluate(
        inp, ((('U1',), candidate),))
    assert result.reasons == ('pin finalist pose would move fixed current copper',)
    assert (dict(plan.occupancy.items), tuple(plan.occupancy.copper), set(plan.occupancy.pending)) == before


def test_supported_cell_pose_and_pad_mapping_match_full_physical_transform():
    board, plan, inp, group = scene(cell='module')
    assert inp.part('U1').cell == 'module'
    candidate = replace(group.results[0], poses=(('U1', 90.0, False),))
    cfg = replace(board.settings, pins_rotations=(0.0, 90.0))
    result = Finalists(board, plan, cfg).evaluate(inp, ((('U1',), candidate),))
    assert not result.reasons
    occ = mapped_geometry(plan.occupancy, {('U1', str(k)): net for k, net in enumerate('DCBA', 1)})
    cell = occ.geometry.cells['module']
    expected = replace(occ._geometry(cell).reference, rotation=90.0)
    geoms, copper = occ.placed_geometries(cell, expected)
    assert result.occupancy.items['U1'] == geoms['U1']
    assert result.occupancy.copper == copper


def test_item_hosted_fixed_copper_pose_is_refused():
    board, plan, inp, group = scene()
    occ = plan.occupancy
    own = occ.items['U1']
    shape, = occ._copper_shapes((track('A', 11.7, 8.5, 12.2, 8.5, owner='U1'),), {})
    hosted = replace(own, shapes=own.shapes + (shape,))
    occ.items['U1'] = hosted
    occ._pristine['U1'] = hosted
    before = dict(occ.items), dict(occ._pristine), tuple(occ.copper), set(occ.pending)
    candidate = replace(group.results[0], poses=(('U1', 90.0, False),))
    result = Finalists(board, plan, replace(board.settings, pins_rotations=(0.0, 90.0))).evaluate(
        inp, ((('U1',), candidate),))
    assert result.reasons == ('pin finalist pose would move fixed current copper',)
    assert (dict(occ.items), dict(occ._pristine), tuple(occ.copper), set(occ.pending)) == before


def test_common_tie_retains_current_board_and_never_claims_gain():
    board, plan, inp, group = scene()
    current = replace(group.results[0], assign=group.present_assign)
    selection = Finalists(board, plan).select(inp, replace(group, results=(current,)))
    assert selection.gain == 0
    assert selection.reason == 'no common improvement'
    assert not selection.actionable


def test_validity_repair_exposes_negative_common_gain_separately():
    board, plan, inp, _ = scene(points=[(11, 22), (18, 12), (9, 26), (8, 25)], paired=True,
                                source_nets=('B', 'D', 'C', 'A'), fields={'Pm.PinDeny': 'A:4'})
    cfg = replace(board.settings, score_crossing_pair_net=1.0)
    group = study_group(inp, ('U1',), cfg, native=False)
    selection = Finalists(board, plan, cfg).select(inp, group)
    assert selection.actionable
    assert selection.reason == 'validity repair'
    assert selection.gain < -20
    assert selection.finalists[selection.best].validity.critical < selection.baseline.validity.critical


def test_combined_maps_must_agree_in_one_physical_board():
    board, plan, inp, group = scene()
    current = replace(group.results[0], assign=group.present_assign)
    result = Finalists(board, plan).evaluate(inp, ((('U1',), group.results[0]), (('U1',), current)))
    assert result.reasons == ('combined pin finalists disagree on a physical pad net',)


@pytest.mark.parametrize('change', ['net', 'pool', 'duplicate'])
def test_stale_input_and_ambiguous_source_refuse(change):
    board, plan, inp, group = scene()
    geometry = plan.occupancy.geometry
    first = geometry.footprints[0]
    if change == 'net':
        first = replace(first, pads=tuple(replace(pad, net='OTHER') if pad.number == '1' else pad
                                          for pad in first.pads))
        item = plan.occupancy.items['U1']
        shapes = tuple(replace(shape, net='OTHER') if shape.kind == 'pad' and shape.label == '1' else shape
                       for shape in item.shapes)
        item = replace(item, shapes=shapes, nets=frozenset(shape.net for shape in shapes if shape.net))
        plan.occupancy.items['U1'] = plan.occupancy._pristine['U1'] = item
    elif change == 'pool':
        first = replace(first, fields={**first.fields, 'Pm.PinPool': '1-2'})
    parts = (first,) + geometry.footprints[1:]
    if change == 'duplicate':
        parts += (replace(first, inst='duplicate'),)
    geometry = replace(geometry, footprints=parts, _by_ref={}, _by_inst={})
    board.geometry = plan.geometry = plan.occupancy.geometry = geometry
    before = dict(plan.occupancy.items), tuple(plan.occupancy.copper)
    result = Finalists(board, plan).evaluate(inp, ((('U1',), group.results[0]),))
    assert result.reasons
    assert result.refusals[0]['code'] == ('ambiguous_reference' if change == 'duplicate' else 'study_context_stale')
    assert not result.validity.valid
    assert (dict(plan.occupancy.items), tuple(plan.occupancy.copper)) == before


@pytest.mark.parametrize('source_face,flip', [(Face.FRONT, True), (Face.BACK, False), (Face.BACK, True)])
def test_full_supported_back_and_flipped_pose_equivalence(source_face, flip):
    board, plan, _, _ = scene(either=True)
    occ = plan.occupancy
    fp = occ.geometry.footprint('U1')
    source = replace(occ._geometry(fp).reference, rotation=37.0, face=source_face)
    occ.commit(fp, source)
    plan.steps = [replace(step, placement=source, back_face=source_face is Face.BACK)
                  if step.item == fp.inst else step for step in plan.steps]
    placed = placed_from_plan(board, plan)
    inp, problems = input_of(placed.pads, placed.parts, cells=placed.cells, netclasses=board.geometry.netclasses,
                             names=board.geometry.pin_names)
    assert not problems
    cfg = replace(board.settings, pins_faces=True, pins_rotations=(0.0, 90.0))
    group = study_group(inp, ('U1',), cfg, native=False)
    candidate = replace(group.results[0], poses=(('U1', 90.0, flip),), assign=group.present_assign)
    result = Finalists(board, plan, cfg).evaluate(inp, ((('U1',), candidate),))
    assert not result.reasons
    target_face = (Face.BACK if source_face is Face.FRONT else Face.FRONT) if flip else source_face
    expected = replace(source, rotation=90.0 - 37.0 if flip else 37.0 + 90.0, face=target_face)
    geoms, _ = occ.placed_geometries(fp, expected)
    assert result.occupancy.items['U1'] == geoms['U1']
    assert result.terms['back_face'] == cfg.score_back_face * int(target_face is Face.BACK)


def test_map_only_never_retags_item_hosted_given_through_shape():
    board, plan, _, _ = scene()
    occ = plan.occupancy
    original = next(shape for shape in occ.items['U1'].shapes if shape.kind == 'pad' and shape.label == '1')
    fixed = replace(original, kind='through', given='fixed-via', wire=True)
    item = replace(occ.items['U1'], shapes=occ.items['U1'].shapes + (fixed,))
    occ.items['U1'] = occ._pristine['U1'] = item
    placed = placed_from_plan(board, plan)
    inp, problems = input_of(placed.pads, placed.parts, cells=placed.cells,
                             netclasses=board.geometry.netclasses, names=board.geometry.pin_names)
    assert not problems
    group = study_group(inp, ('U1',), board.settings, native=False)
    before = dict(occ.items), dict(occ._pristine), tuple(occ.copper)
    result = Finalists(board, plan).evaluate(inp, ((('U1',), group.results[0]),))
    assert not result.reasons
    retained = [shape for shape in result.occupancy.items['U1'].shapes if shape.given == 'fixed-via']
    assert retained == [fixed]
    assert result.validity.critical > 0
    assert (dict(occ.items), dict(occ._pristine), tuple(occ.copper)) == before
