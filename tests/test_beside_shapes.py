"""Beside(item, side) stands a part against the shapes `item`'s envelope is made of (pads, mask, silk, body, or the
courtyard), not the box round them: a mark drawn outside the body at one corner holds a part off only where the part
stands over it. Synthetic boards, and a real six-lead package with a pin 1 dot and the capacitor beside it
(fixtures/fairing/beside_marks, as a board's session of 2026-10-03 laid them out)."""
import dataclasses
import pathlib

import pytest

from placemat.geometry import poly_distance
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Along, Beside, Edge, Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

GAP = 0.2
BOARD = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/beside_marks/layout.kicad_pcb"


def _settings(envelope="physical"):
    return dataclasses.replace(Settings(), place_envelope=envelope)


def _marked_board(mark=True):
    """U1 (body 18..22 x 19..21 at (20, 20)) draws a silk line along its north side at y 18.8..18.9 and, at its west end,
    a mark reaching up to y 17.9 (x 18..18.6). R1, 2 mm wide, centred on U1, stands clear of the mark."""
    silk = [(18.0, 18.8, 22.0, 18.9)] + ([(18.0, 17.9, 18.6, 18.9)] if mark else [])
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0, silk_boxes=silk),
           footprint("R1", 40, 40, w=2, h=1.3, inst="r1", nets=("A", "GND"), excess=0.0)]
    return Board(board_geometry(fps, width=60, height=60, silk_clearance=GAP), edge_margin=1.0, settings=_settings(),
                 component_spacing=GAP)


def _shapes(plan, ref):
    return [s for s in plan.occupancy.items[ref].shapes if s.kind != "npth"]


def _shape_gap(plan, a, b):
    """The least distance between a shape of `a` and one of `b`: what the envelope keeps apart."""
    return min(poly_distance(p.poly, q.poly) for p in _shapes(plan, a) for q in _shapes(plan, b))


def _marked(align=None, mark=True):
    b = _marked_board(mark)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.NORTH, **({} if align is None else {"align": align})))
    return b.resolve()


def test_a_part_clear_of_a_corner_mark_stands_at_the_silk_line_s_gap_not_the_box_s():
    plan = _marked()
    assert _shape_gap(plan, "U1", "R1") == pytest.approx(GAP, abs=1e-4)
    assert plan.box("r1").center.x == pytest.approx(20.0, abs=1e-6)            # level with U1's middle, off the mark
    assert plan.box("r1").bottom == pytest.approx(18.8 - GAP, abs=1e-4)        # the line's top, not the mark's 17.9


def test_the_mark_set_the_distance_when_the_part_stands_over_it():
    plan = _marked(align=Along.START)
    assert plan.box("r1").left == pytest.approx(18.0, abs=1e-6)
    assert _shape_gap(plan, "U1", "R1") == pytest.approx(GAP, abs=1e-4)
    assert plan.box("r1").bottom == pytest.approx(17.9 - GAP, abs=1e-4)


def test_a_part_without_a_mark_stands_where_it_did():
    plan = _marked(mark=False)
    assert plan.box("r1").bottom == pytest.approx(18.8 - GAP, abs=1e-4)


def test_every_side_takes_its_standoff_from_the_shapes():
    for side in (Edge.NORTH, Edge.SOUTH, Edge.EAST, Edge.WEST):
        b = _marked_board()
        b.place(Part("u1"), at=Location(20, 20))
        b.place(Part("r1"), at=Beside(Part("u1"), side))
        plan = b.resolve()
        assert _shape_gap(plan, "U1", "R1") == pytest.approx(GAP, abs=1e-4), side


def test_a_courtyard_envelope_is_the_courtyard_box_as_it_was():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", excess=0.5, silk_boxes=[(18.0, 17.0, 18.6, 18.9)]),
           footprint("R1", 40, 40, w=2, h=1.3, inst="r1", excess=0.5)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=_settings("courtyard"))
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.NORTH))
    plan = b.resolve()
    assert plan.box("r1").bottom + 0.5 == pytest.approx(plan.box("u1").top - 0.5, abs=1e-6)


@needs_kicad
def test_the_capacitor_north_of_a_six_lead_package_stands_at_its_silk_line_not_the_pin_1_dot():
    from placemat.kicad.read import read_board
    geometry = read_board(str(BOARD))
    b = Board(geometry, edge_margin=0.5, settings=_settings())
    b.place(Part("revpol"), at=Location(-3.636, -5.674991), rotation=0)
    b.place(Part("c_rev_cap"), at=Beside(Part("revpol"), Edge.NORTH), rotation=0)
    plan = b.resolve()
    gap = max(geometry.silk_clearance, geometry.default_clearance)
    assert _shape_gap(plan, "U4", "C4") == pytest.approx(gap, abs=1e-4)
    # the capacitor's lowest drawing is its silk, a gap above the package's silk line (its top is y -7.29),
    # not above the pin 1 dot (-7.645), which it does not stand over
    silk = [s for s in _shapes(plan, "C4") if s.kind == "silk"]
    assert max(s.box.bottom for s in silk) == pytest.approx(-7.29 - gap, abs=1e-3)


def _walled_board(top, keep_going=False):
    """U1 as in _marked_board, a third part T1 east of where R1 stands, its body 0.1 mm off R1's, its south end at y 18.7 and
    its north end at `top`: R1 at the silk line's standoff is within the body spacing of it."""
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0,
                     silk_boxes=[(18.0, 18.8, 22.0, 18.9), (18.0, 17.9, 18.6, 18.9)]),
           footprint("R1", 40, 40, w=2, h=1.3, inst="r1", nets=("A", "GND"), excess=0.0, fab=(39.0, 39.35, 41.0, 40.65)),
           footprint("T1", 22.1, (top + 18.7) / 2, w=2, h=18.7 - top, inst="t1", nets=("C", "D"), excess=0.0,
                     fab=(21.1, top, 23.1, 18.7))]
    return Board(board_geometry(fps, width=60, height=60, silk_clearance=GAP), edge_margin=1.0, settings=_settings(),
                 component_spacing=GAP, keep_going=keep_going)


def _beside_with_third(top, keep_going=False):
    b = _walled_board(top, keep_going)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("t1"), at=Location(22.1, (top + 18.7) / 2))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.NORTH))
    return b.resolve()


def test_a_third_part_beside_the_path_holds_the_part_off_it():
    plan = _beside_with_third(top=17.0)
    assert _shape_gap(plan, "R1", "T1") >= GAP - 1e-4
    assert _shape_gap(plan, "U1", "R1") >= GAP - 1e-4
    assert plan.box("r1").bottom == pytest.approx(17.0 - (GAP ** 2 - 0.1 ** 2) ** 0.5, abs=2e-3)   # clear of its corner, no further
    assert plan.box("r1").center.x == pytest.approx(20.0, abs=1e-6)          # still level with U1's middle


def test_no_room_within_reach_leaves_the_part_at_the_item_s_standoff_and_the_collision_is_reported():
    plan = _beside_with_third(top=2.0, keep_going=True)
    assert plan.box("r1").bottom == pytest.approx(18.8 - GAP, abs=1e-4)
    assert any("T1" in str(f) and "R1" in str(f) for f in plan.findings), plan.findings
