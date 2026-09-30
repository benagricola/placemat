"""Past(items, Corner.X): a point on the outward diagonal off a corner of
the items' combined copper box, the clearance plus half the track's width
from it, so a 45 through it across that diagonal passes the corner at the
clearance. As a track waypoint the track takes that 45 through it where
the points either side allow one; in Beside's align pair the part's own
pad stands off the 45. Pure: synthetic boards."""
import dataclasses
import math

import pytest

from placemat.board_geometry import Footprint, NetClass
from placemat.copper import Track
from placemat.geometry import poly_distance
from placemat.layout import Board
from placemat.values import (Along, Bend, Beside, Box, CopperLayer, Corner, Edge, Face, Location, Net, PadRef, Part,
                             Past, X, Y)
from tests.fixtures import board_geometry, declared_findings, footprint, pad

W, C = 0.2, 0.2                       # the fixture's track width and clearance
OFF = C + W / 2                       # the lane's centreline off the corner
D = OFF / math.sqrt(2)                # that, on each axis


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board():
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 1.0, 1.0)       # box (9.5, 19.5)-(10.5, 20.5)
    return Board(board_geometry([pa], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)


def _legs(plan):
    return [op for op in plan.copper if isinstance(op, Track)]


def _pad_poly(plan, ref, number):
    return next(s.poly for s in plan.occupancy.items[ref].shapes if s.label == str(number) and s.kind == "pad")


def _up(v):
    return math.ceil(v * 1e6 - 1e-3) / 1e6


def _down(v):
    return math.floor(v * 1e6 + 1e-3) / 1e6


# (corner, the pad box's corner, the expected point rounded away from the pad, the lane's direction)
CORNERS = [
    (Corner.NE, (10.5, 19.5), (_up(10.5 + D), _down(19.5 - D)), (1, 1)),
    (Corner.NW, (9.5, 19.5), (_down(9.5 - D), _down(19.5 - D)), (1, -1)),
    (Corner.SE, (10.5, 20.5), (_up(10.5 + D), _up(20.5 + D)), (1, -1)),
    (Corner.SW, (9.5, 20.5), (_down(9.5 - D), _up(20.5 + D)), (1, 1)),
]


@pytest.mark.parametrize("corner,box_corner,point,lane", CORNERS, ids=[c[0].name for c in CORNERS])
def test_each_corner_is_the_clearance_and_half_the_width_out_on_its_diagonal(corner, box_corner, point, lane):
    b = _board()
    px, py = point
    lx, ly = lane
    # the ends a few mm up and down the lane, a little off it, so each leg has a 45 to place
    a = Location(round(px - 5 * lx, 3), round(py - 5 * ly + 0.4, 3))
    e = Location(round(px + 5 * lx, 3), round(py + 5 * ly + 0.4, 3))
    b.track(Net("SIG"), [a, Past([PadRef(Part("pa"), 1)], corner), e], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan), declared_findings(plan)
    ends = {t.start for t in _legs(plan)} | {t.end for t in _legs(plan)}
    assert Location(px, py) in ends
    cx, cy = box_corner
    assert math.hypot(px - cx, py - cy) == pytest.approx(OFF, abs=2e-6)
    # the drawn copper passes the corner at the clearance
    gap = min(poly_distance(t.polygon, _pad_poly(plan, "PA", 1)) for t in _legs(plan))
    assert C - 1e-6 <= gap <= C + 0.01


def test_the_track_takes_the_45_through_the_point_over_the_scripts_bend():
    """From the north, bend=START would put the leg's 45 at its far end and
    come into the point on a straight. The corner makes the leg arrive on
    the lane's 45 instead: the 45 is at the point, the straight before it."""
    b = _board()
    px, py = CORNERS[0][2]
    b.track(Net("SIG"), [Location(10.0, 12.0), Past([PadRef(Part("pa"), 1)], Corner.NE), Location(20.0, py)],
            layer=CopperLayer.F, chamfer=0, bend=Bend.START)
    plan = b.resolve()
    assert not declared_findings(plan), declared_findings(plan)
    into = next(t for t in _legs(plan) if t.end == Location(px, py))
    assert into.end.x - into.start.x == pytest.approx(into.end.y - into.start.y, abs=1e-6)   # the 45, NW to SE
    gap = min(poly_distance(t.polygon, _pad_poly(plan, "PA", 1)) for t in _legs(plan))
    assert C - 1e-6 <= gap <= C + 0.01


def test_a_route_that_cannot_take_the_45_is_a_finding_naming_the_corner():
    """Due south out of the point: the one leg there is passes the NE
    corner nearer than the clearance, and nothing can change that."""
    b = _board()
    px, py = CORNERS[0][2]
    b.track(Net("SIG"), [Location(3.0, 12.0), Past([PadRef(Part("pa"), 1)], Corner.NE), Location(px, 30.0)],
            layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert any("NE corner" in f and "PA.1" in f for f in plan.findings), plan.findings


def test_across_with_a_corner_is_refused():
    with pytest.raises(TypeError, match="across"):
        Past([PadRef(Part("pa"), 1)], Corner.NE, across=Along.START)


def test_a_past_edge_is_an_edge_or_a_corner():
    with pytest.raises(TypeError, match="Corner"):
        Past([PadRef(Part("pa"), 1)], "NE")


# ---------------------------------------------------------------- Beside
LANE_W, LANE_C, VIN_C, G_C = 0.25, 0.1, 0.25, 0.2
CLASSES = {"L": NetClass("L", LANE_W, LANE_C, 0.6, 0.3),
           "VIN": NetClass("VIN", 0.2, VIN_C, 0.6, 0.3),
           "G": NetClass("G", 0.2, G_C, 0.6, 0.3)}
LANE = max(VIN_C, LANE_C) + LANE_W + max(LANE_C, G_C)       # VIN to L, L's width, L to G: 0.7


def _beside_board():
    fps = [footprint("CV", 20, 20, w=4, h=2, inst="c_vdd", nets=("VDD", "GND")),     # body (18, 19)-(22, 21)
           _one_pad_part("CI", "c_in", "VIN", 21.0, 23.0, 1.0, 1.0),       # pad box (20.5, 22.5)-(21.5, 23.5)
           footprint("Q", 40, 40, w=3, h=1.5, inst="q", nets=("G", "OUT"))]
    geom = board_geometry(fps, width=60, height=60, extra_nets=["L"])
    netclasses = dict(geom.netclasses)
    netclasses.update(CLASSES)
    b = Board(dataclasses.replace(geom, netclasses=netclasses), edge_margin=1.0)
    b.place(Part("c_vdd"), at=Location(20, 20))
    b.place(Part("c_in"), at=Location(21.0, 23.0))
    return b


def _pad_box(plan, ref, number):
    return Box.union([s.box for s in plan.occupancy.items[ref].shapes if s.label == str(number) and s.kind == "pad"])


def test_a_beside_pad_stands_a_lane_off_the_45_past_a_pads_corner():
    """The lane runs NW to SE past c_in's pad's SW corner; q stands on its
    south-west side, its pad 2's NE corner facing the lane. That corner
    stands the lane (VIN to L, L's width, L to OUT) off the pad's corner,
    measured across the diagonal."""
    b = _beside_board()
    past = Past([PadRef(Part("c_in"), 1)], Corner.SW, lane=Net("L"))
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(2, past)))
    plan = b.resolve()
    own = _pad_box(plan, "Q", 2)
    # c_in's pad's SW corner (20.5, 23.5); q's pad's NE corner (right, top), along the (-1, 1) diagonal
    across = ((20.5 - own.right) + (own.top - 23.5)) / math.sqrt(2)
    assert LANE - 1e-9 <= across <= LANE + 1e-5                         # rounded away from the pads, never nearer
    # Beside still decides the y: courtyards (each 0.1 past its body) touching, c_vdd's body bottom at 21
    assert plan.box("q").top == pytest.approx(21.2)


def test_a_beside_pad_off_a_45_leaves_the_lane_track_clear():
    b = _beside_board()
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH,
                                 align=(2, Past([PadRef(Part("c_in"), 1)], Corner.SW, lane=Net("L")))))
    b.track(Net("L"), [Location(12.0, 16.0), Past([PadRef(Part("c_in"), 1)], Corner.SW), Location(28.0, 32.0)],
            layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan), declared_findings(plan)
    lane = [t for t in _legs(plan) if t.net == "L"]
    to_q = min(poly_distance(t.polygon, _pad_poly(plan, "Q", 2)) for t in lane)
    to_ci = min(poly_distance(t.polygon, _pad_poly(plan, "CI", 1)) for t in lane)
    assert 0.2 - 1e-6 <= to_q <= 0.2 + 0.01           # L to OUT, the default class
    assert VIN_C - 1e-6 <= to_ci <= VIN_C + 0.01


# ---------------------------------------------------------------- migration
def _comb_board():
    """A comb: three resistors down a column, pad 2 east. The feeds to r_a's
    and r_b's pad 2 leave on parallel 45s to the south-east, each held a
    clearance off the next resistor's pad 2 NE corner."""
    fps = [footprint("R%s" % n.upper(), 10.0, y, w=2.0, h=1.0, inst="r_%s" % n, nets=("GND", "S_%s" % n.upper()))
           for n, y in (("a", 20.0), ("b", 22.0), ("c", 24.0))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def _place_comb(b):
    for n, y in (("a", 20.0), ("b", 22.0), ("c", 24.0)):
        b.place(Part("r_%s" % n), at=Location(10.0, y), rotation=0)


FEEDS = (("a", "b", Location(30.0, 36.0)), ("b", "c", Location(30.0, 40.0)))


def _diagonals(plan, net):
    """x - y of every drawn NW-to-SE 45 of `net`: the line a lane sits on."""
    return [round(t.start.x - t.start.y, 6) for t in _legs(plan)
            if t.net == net and abs((t.end.x - t.start.x) - (t.end.y - t.start.y)) < 1e-6
            and abs(t.end.x - t.start.x) > 1e-6]


def test_migration_a_hand_computed_45_lane_matches_past_with_a_corner():
    """The hand form (PLACEMAT_GAPS 2026-09-29, a position that is a sum of
    an x and a y): a point on a NW-to-SE 45 is fixed by x - y, so the
    script works out the constant off the next pad's NE corner - corner x
    minus corner y, plus the clearance and half the width times root 2 -
    and puts a waypoint on it level with the corner. The intent form says
    Past(next pad, Corner.NE). The drawn 45s lie on the same line, within
    0.01 mm."""
    hand = _comb_board()
    _place_comb(hand)
    for own, nxt, end in FEEDS:
        corner = PadRef(Part("r_%s" % nxt), 2)          # pad 2 is 1 x 1 at (10.4, y): NE corner (x + 0.5, y - 0.5)
        k = OFF * math.sqrt(2)                          # (x - y) past the corner's own
        hand.track(Net("S_%s" % own.upper()),
                   [PadRef(Part("r_%s" % own), 2), (X(corner, 0.5 + k), Y(corner, -0.5)), end],
                   layer=CopperLayer.F, chamfer=0)
    hand_plan = hand.resolve()

    intent = _comb_board()
    _place_comb(intent)
    for own, nxt, end in FEEDS:
        intent.track(Net("S_%s" % own.upper()),
                     [PadRef(Part("r_%s" % own), 2), Past([PadRef(Part("r_%s" % nxt), 2)], Corner.NE), end],
                     layer=CopperLayer.F, chamfer=0)
    intent_plan = intent.resolve()
    assert not declared_findings(intent_plan), declared_findings(intent_plan)

    for own, nxt, _ in FEEDS:
        net = "S_%s" % own.upper()
        h, i = _diagonals(hand_plan, net), _diagonals(intent_plan, net)
        assert h and i, (h, i)
        assert any(abs(a - b) < 0.01 for a in h for b in i), (h, i)
        # and the intent's 45 passes the next pad's corner at the clearance
        gap = min(poly_distance(t.polygon, _pad_poly(intent_plan, "R%s" % nxt.upper(), 2))
                  for t in _legs(intent_plan) if t.net == net)
        assert C - 1e-6 <= gap <= C + 0.01
