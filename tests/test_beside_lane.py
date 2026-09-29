"""Beside(item, side, align=(own_pad, Past(pads, edge, lane=))): the part
stands on `side` of `item` as any Beside does, and across the side its own
pad's facing edge stands past the pads' `edge` - by the clearance, or with
`lane=` a net, by room for one track of it between them. Pure: synthetic
boards."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint, NetClass
from placemat.layout import Board
from placemat.values import Beside, Box, CopperLayer, Edge, Face, Location, Net, PadRef, Part, Past
from tests.fixtures import board_geometry, footprint, pad

# net classes: the lane's track width and each net's clearance, all different so each term shows
LANE_W, LANE_C, VIN_C, G_C = 0.25, 0.1, 0.25, 0.2
CLASSES = {"L": NetClass("L", LANE_W, LANE_C, 0.6, 0.3),
           "VIN": NetClass("VIN", 0.2, VIN_C, 0.6, 0.3),
           "G": NetClass("G", 0.2, G_C, 0.6, 0.3)}
# the lane: VIN to L (the larger of the two classes), L's width, L to G
LANE = max(VIN_C, LANE_C) + LANE_W + max(LANE_C, G_C)       # 0.7


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board():
    fps = [footprint("CV", 20, 20, w=4, h=2, inst="c_vdd", nets=("VDD", "GND")),
           _one_pad_part("CI", "c_in", "VIN", 26.0, 26.0, 1.0, 1.0),       # pad west edge at 25.5
           footprint("Q", 40, 40, w=3, h=1.5, inst="q", nets=("G", "OUT"))]
    geom = board_geometry(fps, width=60, height=60, extra_nets=["L"])
    netclasses = dict(geom.netclasses)
    netclasses.update(CLASSES)
    b = Board(dataclasses.replace(geom, netclasses=netclasses), edge_margin=1.0)
    b.place(Part("c_vdd"), at=Location(20, 20))
    b.place(Part("c_in"), at=Location(26.0, 26.0))
    return b


def _pad_box(plan, ref, number):
    return Box.union([s.box for s in plan.occupancy.items[ref].shapes if s.label == str(number) and s.kind == "pad"])


def _plain_south(b=None):
    """Where a Beside south of c_vdd puts q with no align: its y."""
    b = _board()
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH))
    return b.resolve().box("q")


def test_a_pad_stands_a_lane_past_another_parts_pad():
    b = _board()
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                 align=(1, Past([PadRef(Part("c_in"), 1)], Edge.WEST, lane=Net("L")))))
    plan = b.resolve()
    assert _pad_box(plan, "Q", 1).right == pytest.approx(25.5 - LANE)
    assert plan.box("q").top == pytest.approx(_plain_south().top)          # Beside still decides the y


def test_without_lane_the_pad_stands_the_clearance_off():
    b = _board()
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                 align=(1, Past([PadRef(Part("c_in"), 1)], Edge.WEST))))
    plan = b.resolve()
    assert _pad_box(plan, "Q", 1).right == pytest.approx(25.5 - max(VIN_C, G_C))


def test_east_west_beside_takes_a_north_south_past_over_the_items_own_pad():
    b = _board()
    # q east of c_vdd, its pad 1's top edge a lane below c_vdd's pad 2 (bottom 20.5, net VDD at the default
    # 0.2 clearance)
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.EAST,
                                 align=(1, Past([PadRef(Part("c_vdd"), 2)], Edge.SOUTH, lane=Net("L")))))
    plan = b.resolve()
    assert _pad_box(plan, "Q", 1).top == pytest.approx(20.5 + max(0.2, LANE_C) + LANE_W + max(LANE_C, G_C))


def test_a_via_in_besides_past_is_refused():
    b = _board()
    v = b.via(Net("VIN"), at=Location(30.0, 30.0))
    with pytest.raises(TypeError, match="decided before copper is planned"):
        b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([v], Edge.WEST))))


def test_across_in_besides_past_is_refused():
    b = _board()
    with pytest.raises(TypeError, match="across"):
        b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(
            1, Past([PadRef(Part("c_in"), 1)], Edge.WEST, across=PadRef(Part("c_in"), 1)))))


def test_a_past_on_the_axis_beside_decides_is_refused():
    b = _board()
    with pytest.raises(ValueError, match="EAST or WEST"):
        b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                     align=(1, Past([PadRef(Part("c_in"), 1)], Edge.SOUTH))))


def test_a_past_over_a_searched_parts_pad_is_refused_when_placed():
    fps = [footprint("CV", 20, 20, w=4, h=2, inst="c_vdd", nets=("VDD", "GND")),
           _one_pad_part("CI", "c_in", "VIN", 26.0, 26.0, 1.0, 1.0),
           footprint("Q", 40, 40, w=3, h=1.5, inst="q", nets=("G", "OUT"))]
    b = Board(board_geometry(fps, width=60, height=60, extra_nets=["L"]), edge_margin=1.0)
    b.place(Part("c_vdd"), at=Location(20, 20))
    b.place(Part("c_in"))                                   # searched
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                 align=(1, Past([PadRef(Part("c_in"), 1)], Edge.WEST))))
    with pytest.raises(ValueError, match="CI"):
        b.resolve()


def test_migration_a_pad_a_lane_past_matches_the_hand_computed_offset():
    """A module's hand arithmetic: a part south of a capacitor, its pad's
    centre offset west of another capacitor's pad by that pad's half width,
    the lane (clearance, track, clearance) and its own pad's half width.
    The same relation as a Past with lane= must land within 0.01 mm."""
    hand = _board()
    offset = 0.5 + LANE + 0.5                               # c_in's half pad, the lane, q's half pad
    hand.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                    align=(1, PadRef(Part("c_in"), 1).offset(dx=-offset))))
    hand_box = hand.resolve().box("q")

    intent = _board()
    intent.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                      align=(1, Past([PadRef(Part("c_in"), 1)], Edge.WEST, lane=Net("L")))))
    intent_box = intent.resolve().box("q")
    for a, b in ((hand_box.left, intent_box.left), (hand_box.top, intent_box.top),
                 (hand_box.right, intent_box.right), (hand_box.bottom, intent_box.bottom)):
        assert abs(a - b) < 0.01


def test_a_lane_may_be_as_wide_as_its_current_needs():
    """width= replaces the lane net's track width: a part stands clear of
    the copper its current needs, a pour's width rather than a track's."""
    b = _board()
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                 align=(1, Past([PadRef(Part("c_in"), 1)], Edge.WEST, lane=Net("L"), width=1.13))))
    plan = b.resolve()
    assert _pad_box(plan, "Q", 1).right == pytest.approx(25.5 - (max(VIN_C, LANE_C) + 1.13 + max(LANE_C, G_C)))


def test_a_width_without_a_lane_is_refused():
    with pytest.raises(TypeError, match="lane"):
        Past([PadRef(Part("c_in"), 1)], Edge.WEST, width=1.0)
