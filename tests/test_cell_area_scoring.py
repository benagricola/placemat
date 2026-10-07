"""Candidate and committed cell keepouts follow the same current pose."""
from dataclasses import replace

import pytest

from placemat.board_geometry import RuleArea
from placemat.layout import Board, _CopperContext
from placemat.score_delta import Delta
from placemat.values import Cell, CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint


@pytest.mark.parametrize('excludes', [('parts', 'vias', 'fill'), ('vias',)])
def test_cell_via_area_moves_flips_allows_and_restores_across_candidate_and_commit(excludes):
    part = footprint('U1', 10, 10, cell='module', inst='module.u1')
    source = RuleArea('via window', 'module', ((12, 12), (14, 12), (14, 14), (12, 14)),
                      frozenset({CopperLayer.F}), frozenset(excludes), allow=frozenset({'ALLOWED'}))
    geometry = replace(board_geometry([part], cells=['module'], width=50, height=50), rule_areas=(source,))
    board = Board(geometry, keep_going=True)
    board.rect(width=50, height=50)
    board.place(Cell('module'), at=Location(10, 10))
    plan = board.resolve()
    occ, item = plan.occupancy, geometry.cells['module']

    def verdict(view, point, layer, net='OTHER'):
        context = _CopperContext(board, view)
        context.plan = plan
        return board._via_site_why(context, point, net, 0.6, 0.3,
                                   board._via_obstacles(context), span=(layer,))

    assert verdict(occ, Location(13, 13), CopperLayer.F) is not None
    assert verdict(occ, Location(13, 13), CopperLayer.B) is None
    assert verdict(occ, Location(13, 13), CopperLayer.F, 'ALLOWED') is None
    for location, face in [(Location(20, 20), Face.BACK), (Location(30, 30), Face.BACK),
                           (Location(10, 10), Face.FRONT)]:
        reference = occ._geometry(item).reference
        candidate = replace(reference, location=location, face=face)
        transform = occ._transform(occ._geometry(item), candidate)
        old_area = next(s for s in occ.copper if s.owner == 'module' and s.kind == 'viaban')
        old_point = old_area.box.center
        new_point = Location(*transform.apply((old_point.x, old_point.y)))
        originals = dict(occ._cell_rule_areas), dict(occ._cell_fill_areas)
        occ.lift({'U1'})
        delta = Delta(board, occ, item, plan.links, plan=plan)
        view, _, _ = delta._view(candidate)
        layer, = old_area.layers
        if face != reference.face:
            layer = CopperLayer.B if layer == CopperLayer.F else CopperLayer.F
        other = CopperLayer.F if layer == CopperLayer.B else CopperLayer.B
        assert verdict(view, new_point, layer) is not None
        assert verdict(view, new_point, other) is None
        assert verdict(view, new_point, layer, 'ALLOWED') is None
        assert verdict(view, old_point, CopperLayer.F) is None
        assert (occ._cell_rule_areas, occ._cell_fill_areas) == originals
        candidate_areas = view._cell_rule_areas, view._cell_fill_areas
        occ.commit(item, candidate)
        occ.unlift({'U1'})
        assert (occ._cell_rule_areas, occ._cell_fill_areas) == candidate_areas
        assert verdict(occ, new_point, layer) is not None
        assert verdict(occ, new_point, other) is None
        assert verdict(occ, new_point, layer, 'ALLOWED') is None
        assert source.polygon == ((12, 12), (14, 12), (14, 14), (12, 14))
        assert source.layers == frozenset({CopperLayer.F})


def test_candidate_arrangement_area_selection_and_default_pose_preserve_current_arrangement():
    from tests.arrangement_support import east_doc, with_arrangement
    g = with_arrangement(doc=east_doc(ops=[]))
    cell = g.cells['mod']
    default = RuleArea('default', 'mod', ((30, 16), (32, 16), (32, 18), (30, 18)),
                       frozenset({CopperLayer.F}), frozenset({'parts', 'vias'}))
    alternate = replace(default, name='alternate', polygon=((33, 16), (35, 16), (35, 18), (33, 18)))
    arrangements = tuple(replace(a, rule_areas=(alternate,)) for a in cell.arrangements)
    cell = replace(cell, arrangements=arrangements)
    g = replace(g, cells={**g.cells, 'mod': cell}, rule_areas=(default,))
    board = Board(g, keep_going=True)
    board.rect(width=80, height=60)
    board.place(Cell('mod'), at=Location(35, 25))
    plan = board.resolve()
    occ = plan.occupancy
    original_metadata = dict(occ._cell_rule_areas)
    for arrangement, location in [('c_in.east', Location(45, 25)), ('', Location(50, 30))]:
        reference = occ._geometry(cell).reference
        candidate = replace(reference, location=location, arrangement=arrangement)
        occ.lift({fp.ref for fp in cell.members})
        delta = Delta(board, occ, cell, plan.links, plan=plan)
        view, _, _ = delta._view(candidate)
        area, = view._cell_rule_areas['mod']
        assert area.source.name == 'alternate'
        if arrangement:
            source_geometry = occ._geometry(cell.arranged(arrangement))
            transform = occ._transform(source_geometry, candidate)
            assert area.polygon == tuple(transform.apply(p) for p in alternate.polygon)
        assert occ._cell_rule_areas == original_metadata
        occ.commit(cell, candidate)
        occ.unlift({fp.ref for fp in cell.members})
        assert occ._cell_rule_areas == view._cell_rule_areas
        original_metadata = dict(occ._cell_rule_areas)


def test_cell_rule_area_blocker_move_changes_other_parts_declared_via_lane(monkeypatch):
    from placemat import score
    from placemat.values import Part
    from tests.escape_fixtures import qfn
    monkeypatch.setattr(Board, '_report_turns', lambda *args: None)
    part = footprint('C1', 10, 10, cell='module', inst='module.c1')
    rule = RuleArea('south via ban', 'module', ((10, 32), (50, 32), (50, 75), (10, 75)),
                    frozenset({CopperLayer.F}), frozenset({'vias'}))
    g = replace(board_geometry([qfn(), part], cells=['module'], width=80, height=80), rule_areas=(rule,))
    board = Board(g, keep_going=True)
    board.rect(width=80, height=80)
    board.place(Part('pd'), at=Location(30, 30))
    board.place(Cell('module'), at=Location(10, 10))
    board.escape(Part('pd'), [9], vias=[9], why='south lane')
    plan = board.resolve()
    occ, item = plan.occupancy, g.cells['module']
    original = occ._geometry(item).reference
    assert board._declared_lanes_blocked(occ, plan) == 1
    occ.lift({'C1'})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    base = score.whole(board, occ, plan)
    candidate = replace(original, location=Location(70, 10))
    view, _, _ = delta._view(candidate)
    assert board._declared_lanes_blocked(view, plan) == 0
    change = delta(candidate)
    assert change.terms['escape_lane'] == score.whole(board, view, plan)['escape_lane'] - base['escape_lane']
    occ.commit(item, candidate)
    occ.unlift({'C1'})
    assert board._declared_lanes_blocked(occ, plan) == 0
    assert score.whole(board, occ, plan)['escape_lane'] == score.whole(board, view, plan)['escape_lane']
