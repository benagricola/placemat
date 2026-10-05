"""Beside(item, side, align=(own_pad, Past(items, edge, lane=))) over a cutout, a stretch of the board edge, a part or
a cell: the own pad's facing edge stands past each, by the copper-to-edge clearance from a hole or the edge and by
nothing from an envelope (its pads keep their clearance); with `lane=`, by that plus the lane's width and its clearance
to the own pad. A via, a track, a label and a cutout with a freedom are refused: none has its place when a firm part is
placed. Pure: synthetic boards."""
import dataclasses
import math

import pytest

from placemat.board_geometry import Footprint
from placemat.cutouts import Circle, Path
from placemat.layout import Board
from placemat.values import (Beside, Box, Cell, Centre, Corner, Cutout, Edge, Face, Location, Near, Net, PadRef, Part,
                             Past, X, Y)
from tests.fixtures import board_geometry, footprint, pad
from tests.test_beside_lane import CLASSES, G_C, LANE_C, LANE_W, _pad_box

SAG = 0.02
EDGE = 0.4


def _one_pad_part(ref, inst, net, cx, cy):
    p = pad(ref, inst, 1, net, cx, cy, 1.0, 1.0)
    body = Box(cx - 1.0, cy - 1.0, cx + 1.0, cy + 1.0)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board(holes=(), margin=1.0, with_c_in=False, place_c_in=True):
    fps = [footprint("CV", 20, 20, w=4, h=2, inst="c_vdd", nets=("VDD", "GND")),
           footprint("Q", 40, 40, w=3, h=1.5, inst="q", nets=("G", "OUT"))]
    if with_c_in:
        fps.append(_one_pad_part("CI", "c_in", "VIN", 26.0, 26.0))        # pad west side 25.5, courtyard 24.9
    geom = board_geometry(fps, width=60, height=60, extra_nets=["L"])
    classes = dict(geom.netclasses)
    classes.update(CLASSES)
    b = Board(dataclasses.replace(geom, netclasses=classes), edge_margin=margin)
    b.rect(width=60.0, height=60.0, holes=list(holes))
    b.place(Part("c_vdd"), at=Location(20, 20))
    if with_c_in and place_c_in:
        b.place(Part("c_in"), at=Location(26.0, 26.0))
    return b


VENT = Cutout(Circle(1.5), "vent", at=Location(26.0, 26.0))              # grown box west side 25.25 - 0.02


def test_beside_stands_its_pad_the_edge_clearance_past_a_cutout():
    b = _board([VENT])
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([VENT], Edge.WEST))))
    assert _pad_box(b.resolve(), "Q", 1).right == pytest.approx(26.0 - 0.75 - SAG - EDGE)


def test_beside_stands_its_pad_a_lane_past_a_cutout():
    b = _board([VENT])
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([VENT], Edge.WEST, lane=Net("L")))))
    # the hole to the lane, the lane's width, the lane to pad 1's net G
    assert _pad_box(b.resolve(), "Q", 1).right == pytest.approx(26.0 - 0.75 - SAG - (EDGE + LANE_W + max(LANE_C, G_C)))


def test_beside_stands_its_pad_on_an_envelope_where_its_courtyard_reaches_past_its_pads_clearance():
    b = _board(with_c_in=True)
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([Part("c_in")], Edge.WEST))))
    # the courtyard's west side 24.9 by 0; the pad's 25.5 by G to VIN, 0.25: 25.25; the outer is the courtyard's
    assert _pad_box(b.resolve(), "Q", 1).right == pytest.approx(24.9)


def test_beside_stands_its_pad_past_the_board_edge():
    b = _board(margin=0.0)
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([b.edge(facing=Edge.WEST)], Edge.EAST))))
    assert _pad_box(b.resolve(), "Q", 1).left == pytest.approx(EDGE)


def test_a_cutout_with_a_freedom_and_a_label_in_besides_past_are_refused():
    b = _board([Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("c_vdd"), 1)), why="air")])
    with pytest.raises(ValueError, match="freedom"):
        b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([b.cutout("vent")], Edge.WEST))))
    key = b.label(Part("c_vdd"), "VDD")
    with pytest.raises(TypeError, match="gives way"):
        b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([key], Edge.WEST))))


SQUARE = Path(((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)))           # straight sides: no arc allowance


def test_beside_stands_its_pad_on_a_cells_envelope():
    member = _one_pad_part("U1", "pd.u1", "VIN", 26.0, 26.0)
    member = dataclasses.replace(member, cell="pd")
    fps = [footprint("CV", 20, 20, w=4, h=2, inst="c_vdd", nets=("VDD", "GND")), member,
           footprint("Q", 40, 40, w=3, h=1.5, inst="q", nets=("G", "OUT"))]
    geom = board_geometry(fps, cells=["pd"], width=60, height=60)
    b = Board(geom, edge_margin=1.0)
    b.rect(width=60.0, height=60.0)
    b.place(Part("c_vdd"), at=Location(20, 20))
    b.place(Cell("pd"), at=Location(26.0, 26.0))
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([Cell("pd")], Edge.WEST))))
    plan = b.resolve()
    # the cell's courtyard west side by 0; its member's pad by the clearance, 0.2, is nearer the pad
    assert _pad_box(plan, "U1", 1).left == pytest.approx(25.5)
    assert _pad_box(plan, "Q", 1).right == pytest.approx(24.9)


def _settles_late(stretch: bool, below: float = 6.0):
    """A cutout whose place is decided (`below` south of c_in's centre) but which is cut only once c_in is down, and
    c_in is placed after q in the script: q's Beside waits for the cutout."""
    at = Centre(X(Part("c_in")), Y(Part("c_in"), below))
    b = _board([Cutout(SQUARE, "vent", at=at)], with_c_in=True, place_c_in=False)
    item = b.cutout("vent").edge(Edge.EAST) if stretch else b.cutout("vent")
    edge = Edge.EAST if stretch else Edge.WEST                  # a stretch is passed on the board's side of it
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([item], edge))))
    b.place(Part("c_in"), at=Location(26.0, 26.0))
    return b, item


def test_beside_waits_for_a_decided_cutout_that_settles_later():
    b, _ = _settles_late(stretch=False)
    # the square's west side 25, by the copper-to-edge clearance
    assert _pad_box(b.resolve(), "Q", 1).right == pytest.approx(25.0 - EDGE)


def test_beside_stands_its_pad_past_a_stretch_of_a_cutout():
    b, item = _settles_late(stretch=True)
    assert type(item).__name__ == "CutoutEdge"                  # a promise: the cutout has no place yet
    # the stretch is the square's east side, x = 27, with the hole to its west: the pad stands east of it
    assert _pad_box(b.resolve(), "Q", 1).left == pytest.approx(27.0 + EDGE)


def test_beside_past_a_cutout_that_was_refused_is_refused():
    b, _ = _settles_late(stretch=False, below=0.0)              # milled through c_in: the cutout is not cut
    with pytest.raises(ValueError, match="nothing to stand past"):
        b.resolve()


def test_beside_at_a_corner_passes_each_groups_own_corner():
    near = Cutout(SQUARE, "near", at=Location(36.0, 14.0))     # box 35..37 x 13..15: its SE corner (37, 15)
    far = Cutout(SQUARE, "far", at=Location(40.0, 6.0))        # box 39..41 x 5..7: its SE corner (41, 7)
    b = _board([near, far])
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([near, far], Corner.SE))))
    pad = _pad_box(b.resolve(), "Q", 1)
    # the pad's corner facing back across the 45 (its NW) stands past each square's SE corner, along the diagonal, by
    # at least the copper-to-edge clearance; the near square decides it, not the union's corner (41, 15)
    past = {name: (pad.left - cx) + (pad.top - cy) for name, cx, cy in (("near", 37.0, 15.0), ("far", 41.0, 7.0))}
    assert past["near"] == pytest.approx(EDGE * math.sqrt(2.0), abs=2e-6)
    assert past["far"] > EDGE * math.sqrt(2.0)
