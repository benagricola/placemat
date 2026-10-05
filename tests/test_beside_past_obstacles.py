"""Beside(item, side, align=(own_pad, Past(items, edge, lane=))) over a cutout, a stretch of the board edge, a part or
a cell: the own pad's facing edge stands past each, by the copper-to-edge clearance from a hole or the edge and by
nothing from an envelope (its pads keep their clearance); with `lane=`, by that plus the lane's width and its clearance
to the own pad. A via, a track, a label and a cutout with a freedom are refused: none has its place when a firm part is
placed. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import Beside, Box, Cutout, Edge, Face, Location, Near, Net, PadRef, Part, Past
from tests.fixtures import board_geometry, footprint, pad
from tests.test_beside_lane import CLASSES, G_C, LANE_C, LANE_W, _pad_box

SAG = 0.02
EDGE = 0.4


def _one_pad_part(ref, inst, net, cx, cy):
    p = pad(ref, inst, 1, net, cx, cy, 1.0, 1.0)
    body = Box(cx - 1.0, cy - 1.0, cx + 1.0, cy + 1.0)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board(holes=(), margin=1.0, with_c_in=False):
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
    if with_c_in:
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
