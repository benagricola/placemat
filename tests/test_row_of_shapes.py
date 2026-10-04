"""board.row(items, edge, of=item) stands the row against the shapes `of`'s envelope is made of, as Beside does
(tests/test_beside_shapes.py), not the box round them: a mark drawn outside the body at one corner holds the row off only if
an item stands over it. The row keeps one line: one distance for all its items, the nearest at which every item clears the
shapes it faces. Synthetic boards."""
import dataclasses

import pytest

from placemat.geometry import poly_distance
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Along, Edge, Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

GAP = 0.2


def _settings(envelope="physical", **kw):
    return dataclasses.replace(Settings(), place_envelope=envelope, **kw)


def _board(mark=True, envelope="physical", **kw):
    """U1 (body 18..22 x 19..21 at (20, 20)) draws a silk line along its north side at y 18.8..18.9 and, at its west end,
    a mark reaching up to y 17.9 (x 18..18.6). R1, 2 mm wide, centred on U1, stands clear of the mark."""
    silk = [(18.0, 18.8, 22.0, 18.9)] + ([(18.0, 17.9, 18.6, 18.9)] if mark else [])
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0, silk_boxes=silk),
           footprint("R1", 40, 40, w=2, h=1.3, inst="r1", nets=("A", "GND"), excess=0.0),
           footprint("R2", 40, 45, w=2, h=0.9, inst="r2", nets=("B", "GND"), excess=0.0)]
    return Board(board_geometry(fps, width=60, height=60, silk_clearance=GAP), edge_margin=1.0,
                 settings=_settings(envelope, **kw), component_spacing=GAP)


def _shapes(plan, ref):
    return [s for s in plan.occupancy.items[ref].shapes if s.kind != "npth"]


def _shape_gap(plan, a, b):
    return min(poly_distance(p.poly, q.poly) for p in _shapes(plan, a) for q in _shapes(plan, b))


def _row(align=Along.MID, mark=True, edge=Edge.NORTH, items=("r1",), **kw):
    b = _board(mark, **kw)
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part(k) for k in items], edge, of=Part("u1"), align=align, rotation=0)
    return b.resolve()


def test_an_item_clear_of_a_corner_mark_stands_at_the_silk_line_s_gap_not_the_box_s():
    plan = _row()
    assert _shape_gap(plan, "U1", "R1") == pytest.approx(GAP, abs=1e-4)
    assert plan.box("r1").center.x == pytest.approx(20.0, abs=1e-6)
    assert plan.box("r1").bottom == pytest.approx(18.8 - GAP, abs=1e-4)        # the line's top, not the mark's 17.9


def test_the_mark_sets_the_distance_where_the_item_stands_over_it():
    plan = _row(align=Along.START)
    assert plan.box("r1").left == pytest.approx(18.0, abs=1e-6)
    assert _shape_gap(plan, "U1", "R1") == pytest.approx(GAP, abs=1e-4)
    assert plan.box("r1").bottom == pytest.approx(17.9 - GAP, abs=1e-4)


def test_an_item_beside_a_part_with_no_mark_stands_where_it_did():
    plan = _row(mark=False)
    assert plan.box("r1").bottom == pytest.approx(18.8 - GAP, abs=1e-4)


def test_every_edge_takes_its_standoff_from_the_shapes():
    for edge in (Edge.NORTH, Edge.SOUTH, Edge.EAST, Edge.WEST):
        plan = _row(edge=edge)
        assert _shape_gap(plan, "U1", "R1") == pytest.approx(GAP, abs=1e-4), edge


def _row_of_two(align, mark=True):
    silk = [(18.0, 18.8, 22.0, 18.9)] + ([(18.0, 17.9, 18.6, 18.9)] if mark else [])
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0, silk_boxes=silk),
           footprint("R1", 40, 40, w=1.4, h=1.3, inst="r1", nets=("A", "GND"), excess=0.0),
           footprint("R2", 40, 45, w=1.4, h=1.3, inst="r2", nets=("B", "GND"), excess=0.0)]
    b = Board(board_geometry(fps, width=60, height=60, silk_clearance=GAP), edge_margin=1.0, settings=_settings(),
              component_spacing=GAP)
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), align=align, rotation=0)
    return b.resolve()


def test_a_row_clear_of_the_mark_stands_at_the_silk_line_on_one_line():
    plan = _row_of_two(Along.END)
    assert plan.box("r1").left > 18.6 and plan.box("r2").left > 18.6          # neither stands over the mark
    for ref in ("R1", "R2"):
        assert _shape_gap(plan, "U1", ref) == pytest.approx(GAP, abs=1e-4)
    assert plan.box("r1").bottom == pytest.approx(18.8 - GAP, abs=1e-4)
    assert plan.box("r1").bottom == pytest.approx(plan.box("r2").bottom, abs=1e-6)


def test_an_item_over_the_mark_holds_the_whole_row_off_by_it_and_the_line_stays_one():
    plan = _row_of_two(Along.START)
    assert plan.box("r1").left == pytest.approx(18.0, abs=1e-6)               # R1 stands over the mark
    assert _shape_gap(plan, "U1", "R1") == pytest.approx(GAP, abs=1e-4)
    assert plan.box("r1").bottom == pytest.approx(17.9 - GAP, abs=1e-4)
    assert plan.box("r2").bottom == pytest.approx(plan.box("r1").bottom, abs=1e-6)       # R2 clear of the mark, on R1's line
    assert _shape_gap(plan, "U1", "R2") > GAP + 0.5


def test_the_line_of_items_of_different_depth_is_kept_when_the_row_stands_at_the_silk_line():
    plan = _row(align=Along.END, items=("r1", "r2"))
    line = GAP + (1.3 - 1.0) / 2.0          # R2 is 0.3 shallower (its pads make it 1.0 deep): the row's centre line puts it that much further out
    assert min(_shape_gap(plan, "U1", "R1"), _shape_gap(plan, "U1", "R2")) >= GAP - 1e-4
    assert plan.box("r1").center.y == pytest.approx(plan.box("r2").center.y, abs=1e-6)


def test_a_courtyard_envelope_is_the_courtyard_box_as_it_was():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", excess=0.5, silk_boxes=[(18.0, 17.0, 18.6, 18.9)]),
           footprint("R1", 40, 40, w=2, h=1.3, inst="r1", excess=0.5)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=_settings("courtyard"))
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1")], Edge.NORTH, of=Part("u1"), align=Along.MID, rotation=0)
    plan = b.resolve()
    assert plan.box("r1").bottom + 0.5 == pytest.approx(plan.box("u1").top - 0.5, abs=1e-6)


def _walled_board(top, keep_going=False):
    """U1 as in _board, a third part T1 east of where R1 stands, its body 0.1 mm off R1's, its south end at y 18.7 and its
    north end at `top`: R1 at the silk line's standoff is within the body spacing of it."""
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0,
                     silk_boxes=[(18.0, 18.8, 22.0, 18.9), (18.0, 17.9, 18.6, 18.9)]),
           footprint("R1", 40, 40, w=2, h=1.3, inst="r1", nets=("A", "GND"), excess=0.0, fab=(39.0, 39.35, 41.0, 40.65)),
           footprint("T1", 22.1, (top + 18.7) / 2, w=2, h=18.7 - top, inst="t1", nets=("C", "D"), excess=0.0,
                     fab=(21.1, top, 23.1, 18.7))]
    return Board(board_geometry(fps, width=60, height=60, silk_clearance=GAP), edge_margin=1.0, settings=_settings(),
                 component_spacing=GAP, keep_going=keep_going)


def _row_with_third(top, keep_going=False):
    b = _walled_board(top, keep_going)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("t1"), at=Location(22.1, (top + 18.7) / 2))
    b.row([Part("r1")], Edge.NORTH, of=Part("u1"), align=Along.MID, rotation=0)
    return b.resolve()


def test_a_third_part_beside_the_path_holds_the_item_off_it_as_it_does_a_beside_part():
    plan = _row_with_third(top=17.0)
    assert _shape_gap(plan, "R1", "T1") >= GAP - 1e-4
    assert _shape_gap(plan, "U1", "R1") >= GAP - 1e-4
    assert plan.box("r1").bottom == pytest.approx(17.0 - (GAP ** 2 - 0.1 ** 2) ** 0.5, abs=2e-3)
    assert plan.box("r1").center.x == pytest.approx(20.0, abs=1e-6)


def test_no_room_within_reach_leaves_the_item_at_the_shapes_standoff_and_the_collision_is_reported():
    plan = _row_with_third(top=2.0, keep_going=True)
    assert plan.box("r1").bottom == pytest.approx(18.8 - GAP, abs=1e-4)
    assert any("T1" in str(f) and "R1" in str(f) for f in plan.findings), plan.findings


@needs_kicad
def test_a_capacitor_row_north_of_a_six_lead_package_stands_at_its_silk_line_not_the_pin_1_dot():
    """The real package of tests/test_beside_shapes.py (fixtures/fairing/beside_marks), the capacitor in a row of one."""
    import pathlib
    from placemat.kicad.read import read_board
    geometry = read_board(str(pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/beside_marks/layout.kicad_pcb"))
    b = Board(geometry, edge_margin=0.5, settings=_settings())
    b.place(Part("revpol"), at=Location(-3.636, -5.674991), rotation=0)
    b.row([Part("c_rev_cap")], Edge.NORTH, of=Part("revpol"), align=Along.MID, rotation=0)
    plan = b.resolve()
    gap = max(geometry.silk_clearance, geometry.default_clearance)
    assert _shape_gap(plan, "U4", "C4") == pytest.approx(gap, abs=1e-4)
    silk = [s for s in _shapes(plan, "C4") if s.kind == "silk"]
    assert max(s.box.bottom for s in silk) == pytest.approx(-7.29 - gap, abs=1e-3)       # a gap above the package's silk line, not the dot (-7.645)
