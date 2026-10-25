"""Beside(item, SideOf(pads)) with the pads' part turned off the right angles: the item stands in the part's own
frame - the gap off the part (or its escape's risers, lanes and vias), centred along the row on the named pads, square
to the row - and is turned with the part. At right-angle turns it is the compass Beside. Pure: synthetic boards."""
import dataclasses
import math

import pytest

from placemat.board_geometry import NetClass
from placemat.copper import Track, Via
from placemat.geometry import Transform
from placemat.layout import Board
from placemat.placer import way_out_side
from placemat.values import Beside, Box, Cell, Edge, Location, Mid, PadRef, Part, Past, SideOf, Turned, X
from tests.escape_fixtures import CLEAR, DRILL, TRACK, VIA, qfn
from tests.fixtures import board_geometry, footprint
from tests.test_facing_grids_rows_sides import _board as _board_of, _part

NETS = {21: "SIG_A", 22: "SIG_B", 23: "SIG_C", 24: "SIG_D"}     # the east row's four upper pads, 22 and 23 the middle two
MCU = Part("pd")
SIDE = SideOf(PadRef(MCU, 22))
MID = Mid(PadRef(MCU, 22), PadRef(MCU, 23))


def _terms():
    """Four 0201-ish two-pad parts in a cell, pads along x."""
    return [footprint("T%d" % k, 5 + 3 * k, 10, w=1.0, h=0.5, inst="terms.t%d" % k, nets=("TN%d" % k, "GND"), cell="terms")
            for k in range(1, 5)]


def _board(turn, cell=True, part=True):
    fps = [qfn(nets=NETS)]
    if part:
        fps.append(footprint("C1", 5, 5, w=2.0, h=1.0, inst="cap", nets=("SIG_B", "GND")))
    if cell:
        fps += _terms()
    geom = board_geometry(fps, cells=["terms"] if cell else [], width=80, height=80, clearance=CLEAR)
    classes = {n: NetClass("Default", TRACK, CLEAR, VIA, DRILL) for n in geom.nets}
    b = Board(dataclasses.replace(geom, netclasses=classes), edge_margin=1.0, via_size=VIA, via_drill=DRILL)
    b.place(MCU, at=Location(40, 40), rotation=turn)
    return b


def _escape(b):
    return b.escape(MCU, [21, 22, 23, 24], vias=[22, 24], why="east row")


def _frame(turn, point):
    return Transform.rotate(-turn).apply((point.x, point.y))


def _members_pads(plan, refs):
    return [plan.occupancy.pad_location(r, str(n)) for r in refs for n in (1, 2)]


def _part_frame_box(plan, ref, turn):
    """The part's pad and body shapes' box in the part's frame."""
    pts = [q for s in plan.occupancy.items[ref].shapes if s.kind != "npth" for q in s.poly]
    return Box.of_points([Transform.rotate(-turn).apply(q) for q in pts])


def _laid_frame_box(b, plan, turn):
    laid = b._escape_laid[0]
    pts = [q for op in laid.ops() for q in op.polygon]
    return Box.of_points([Transform.rotate(-turn).apply(q) for q in pts])


GAP = 0.5


def _expected_gap(b, esc, item):
    return b._beside_gap(Beside(esc, SIDE), item)


def _cell_frame_box(plan, turn):
    pts = [q for r in ("T1", "T2", "T3", "T4") for s in plan.occupancy.items[r].shapes if s.kind != "npth" for q in s.poly]
    return Box.of_points([Transform.rotate(-turn).apply(q) for q in pts])


def _mid_y(plan, turn):
    ys = [_frame(turn, plan.occupancy.pad_location("U1", str(n)))[1] for n in (22, 23)]
    return sum(ys) / 2.0


def _clean(plan):
    return [f for f in plan.findings if f.kind in ("fixed", "unplaced")]


@pytest.mark.parametrize("turn", [0.0, 90.0, 45.0])
def test_a_part_stands_the_gap_outward_of_the_lanes_centred_on_the_named_pads(turn):
    b = _board(turn, cell=False)
    esc = _escape(b)
    b.place(Part("cap"), at=Beside(esc, SIDE, align=(Mid(1, 2), MID)), rotation=Turned(MCU, 0.0))
    plan = b.resolve()
    assert _clean(plan) == []
    assert plan.placement("cap").rotation == pytest.approx(turn)
    lanes = _laid_frame_box(b, plan, turn)
    own = _part_frame_box(plan, "C1", turn)
    assert own.left - lanes.right == pytest.approx(_expected_gap(b, esc, Part("cap")), abs=1e-5)
    assert own.center.y == pytest.approx(_mid_y(plan, turn), abs=1e-5)


@pytest.mark.parametrize("turn", [0.0, 90.0, 45.0])
def test_a_cell_stands_the_gap_outward_of_the_lanes_centred_on_the_named_pads_in_a_line_along_the_normal(turn):
    b = _board(turn, part=False)
    esc = _escape(b)
    b.place(Cell("terms"), at=Beside(esc, SIDE, align=MID), rotation=Turned(MCU, 0.0))
    plan = b.resolve()
    assert _clean(plan) == []
    lanes = _laid_frame_box(b, plan, turn)
    own = _cell_frame_box(plan, turn)
    assert own.left - lanes.right == pytest.approx(_expected_gap(b, esc, Cell("terms")), abs=1e-5)
    assert own.center.y == pytest.approx(_mid_y(plan, turn), abs=1e-5)
    # the members' pads stand in a line along the row's normal, as they do in the cell
    rows = {round(_frame(turn, plan.occupancy.pad_location(r, "1"))[1], 5) for r in ("T1", "T2", "T3", "T4")}
    assert len(rows) == 1
    xs = [_frame(turn, plan.occupancy.pad_location(r, "1"))[0] for r in ("T1", "T2", "T3", "T4")]
    assert xs == sorted(xs)


@pytest.mark.parametrize("turn", [0.0, 90.0, 30.0, 45.0])
def test_a_part_stands_beside_a_part_turned_at_any_angle(turn):
    b = _board(turn, cell=False)
    b.place(Part("cap"), at=Beside(MCU, SIDE, align=(Mid(1, 2), MID), gap=GAP), rotation=Turned(MCU, 0.0))
    plan = b.resolve()
    assert _clean(plan) == []
    me = _part_frame_box(plan, "U1", turn)
    own = _part_frame_box(plan, "C1", turn)
    assert own.left - me.right == pytest.approx(GAP, abs=1e-5)
    assert own.center.y == pytest.approx(_mid_y(plan, turn), abs=1e-5)
    assert plan.placement("cap").rotation == pytest.approx(turn)


@pytest.mark.parametrize("turn", [0.0, 90.0])
def test_at_a_right_angle_turn_the_result_is_the_compass_beside(turn):
    edge = way_out_side((1.0, 0.0), turn)
    out = {}
    for name, side in (("sideof", SIDE), ("compass", edge)):
        b = _board(turn)
        esc = _escape(b)
        b.place(Part("cap"), at=Beside(esc, side, align=(Mid(1, 2), MID)), rotation=Turned(MCU, 0.0))
        b.place(Cell("terms"), at=Beside(MCU, side, align=MID), rotation=Turned(MCU, 90.0))
        plan = b.resolve()
        out[name] = (plan.placement("cap"), plan.placement("terms"))
    assert out["sideof"] == out["compass"]


def test_an_item_not_square_to_the_row_is_refused():
    for rotation in (0.0, Turned(MCU, 30.0)):
        b = _board(45.0, cell=False)
        b.place(Part("cap"), at=Beside(MCU, SIDE, align=(Mid(1, 2), MID), gap=GAP), rotation=rotation)
        with pytest.raises(ValueError, match="plus a multiple of 90"):
            b.resolve()


def test_an_item_a_right_angle_off_the_part_s_turn_stands_square_to_the_row():
    b = _board(45.0, cell=False)
    b.place(Part("cap"), at=Beside(MCU, SIDE, align=(Mid(1, 2), MID), gap=GAP), rotation=Turned(MCU, 90.0))
    plan = b.resolve()
    own = _part_frame_box(plan, "C1", 45.0)
    me = _part_frame_box(plan, "U1", 45.0)
    assert own.left - me.right == pytest.approx(GAP, abs=1e-5)
    assert own.center.y == pytest.approx(_mid_y(plan, 45.0), abs=1e-5)
    assert own.height > own.width                       # the capacitor is turned a right angle in the frame


def test_an_axis_point_for_a_cell_s_centre_is_refused_on_a_turned_part():
    b = _board(45.0, part=False)
    b.place(Cell("terms"), at=Beside(MCU, SIDE, align=X(PadRef(MCU, 22)), gap=GAP), rotation=Turned(MCU, 0.0))
    with pytest.raises(ValueError, match="board axis"):
        b.resolve()


def test_a_past_or_a_lane_in_align_is_refused_with_a_side_of_whatever_the_turn():
    b = _board(45.0, cell=False)
    with pytest.raises(TypeError, match="SideOf"):
        b.place(Part("cap"), at=Beside(MCU, SIDE, align=(1, Past([PadRef(MCU, 22)], Edge.NORTH))), rotation=Turned(MCU, 0.0))


def test_a_corner_pad_whose_way_out_is_diagonal_in_the_part_s_frame_is_still_ambiguous():
    grid = _part("G", [(1, "A1", -0.5, -0.5, 0.4, 0.4), (2, "A2", 0.5, -0.5, 0.4, 0.4),
                       (3, "B1", -0.5, 0.5, 0.4, 0.4), (4, "B2", 0.5, 0.5, 0.4, 0.4)], 40.0, 40.0)
    cap = footprint("C", 0, 0, w=2, h=1, inst="c", nets=("X", "Y"))
    for turn in (0.0, 45.0):
        b = _board_of([grid, cap])
        b.place(Part("g"), at=Location(40, 40), rotation=turn)
        b.place(Part("c"), at=Beside(Part("g"), SideOf(PadRef(Part("g"), 1))), rotation=Turned(Part("g"), 0.0))
        with pytest.raises(ValueError, match="diagonal"):
            b.resolve()
