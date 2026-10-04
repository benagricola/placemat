"""Track waypoints Between(a, b) (the centreline of the gap between two
pads) and Past(pads, edge) (the clearance off those pads' side): resolved
once the pads are placed, accepted wherever a track point is. Pure."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Track
from placemat.layout import Board
from placemat.values import Between, Box, CopperLayer, Edge, Face, Location, Net, PadRef, Part, Past
from tests.fixtures import board_geometry, declared_findings, pad


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _geometry_with_a_no_net_pad(footprints, **kw):
    """As board_geometry(), but a pad's own "" net is not a real net on the
    board - the real reader never adds one either (kicad/read.py's
    _netclasses skips a net with no name), so a no-net pad's net is not in
    geometry.nets, same as on a real board."""
    geom = board_geometry(footprints, **kw)
    return dataclasses.replace(geom, nets=geom.nets - {""})


def _legs(plan):
    return [op for op in plan.copper if isinstance(op, Track)]


def test_between_runs_the_track_through_the_gaps_centreline():
    pa = _one_pad_part("PA", "pa", "MID", 9.0, 20.0, 2.0, 1.0)      # box (8, 19.5)-(10, 20.5)
    pb = _one_pad_part("PB", "pb", "GND", 11.7, 20.0, 2.0, 1.0)     # box (10.7, 19.5)-(12.7, 20.5): 0.7 mm gap
    b = Board(board_geometry([pa, pb], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    mid_x = (9.0 + 11.7) / 2.0
    # a track straight down the gap's centreline (x = mid_x throughout), so it never crosses either pad
    b.track(Net("SIG"), [Location(mid_x, 5.0), Between(PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)),
                         Location(mid_x, 35.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan)
    legs = _legs(plan)
    assert all(t.start.x == mid_x and t.end.x == mid_x for t in legs)     # straight down the centreline throughout
    ys = sorted({round(t.start.y, 6) for t in legs} | {round(t.end.y, 6) for t in legs})
    assert ys == [5.0, 20.0, 35.0]                                        # Between's own point is a real waypoint


def test_between_is_a_finding_naming_both_pads_when_the_gap_is_too_tight():
    """Track width 0.2 mm, 0.2 mm clearance to each pad's net: 0.6 mm of
    gap is needed. This board gives it 0.4."""
    pa = _one_pad_part("PA", "pa", "MID", 9.0, 20.0, 2.0, 1.0)       # right edge at 10
    pb = _one_pad_part("PB", "pb", "GND", 11.4, 20.0, 2.0, 1.0)      # left edge at 10.4: a 0.4 mm gap
    b = Board(board_geometry([pa, pb], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    mid_x = (9.0 + 11.4) / 2.0
    b.track(Net("SIG"), [Location(mid_x, 5.0), Between(PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)),
                         Location(mid_x, 35.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert any("PA.1" in f and "PB.1" in f and "gap" in f for f in plan.findings), plan.findings


def test_past_keeps_the_tracks_clearance_off_the_pads_side():
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 1.0, 1.0)
    pb = _one_pad_part("PB", "pb", "MID", 10.0, 23.0, 1.0, 1.0)      # box union: (9.5, 19.5)-(10.5, 23.5)
    b = Board(board_geometry([pa, pb], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    past = Past([PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], Edge.EAST)
    # 0.2 mm track, 0.2 mm clearance to MID: 10.5 + 0.1 + 0.2 = 10.8; y centred on the pads' box, 21.5
    b.track(Net("SIG"), [Location(5.0, 21.5), past, Location(10.8, 30.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan)
    legs = _legs(plan)
    assert any(t.start == Location(10.8, 21.5) or t.end == Location(10.8, 21.5) for t in legs)


def test_past_edges_are_read_off_the_pads_combined_box():
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 1.0, 1.0)      # box (9.5, 19.5)-(10.5, 20.5)
    b = Board(board_geometry([pa], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    past = Past([PadRef(Part("pa"), 1)], Edge.NORTH)
    # 19.5 - 0.1 - 0.2 = 19.2
    b.track(Net("SIG"), [Location(10.0, 5.0), past, Location(20.0, 19.2)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan)
    legs = _legs(plan)
    assert any(t.start == Location(10.0, 19.2) or t.end == Location(10.0, 19.2) for t in legs)


def test_between_uses_the_default_clearance_next_to_a_pad_with_no_net():
    """A corner-reference pad with no net (GetNetCode() <= 0 on a real
    board) sits next to the gap: Between must fall back to the default
    clearance for it, not raise looking up a netclass for ''."""
    pa = _one_pad_part("PA", "pa", "", 9.0, 20.0, 2.0, 1.0)         # no net: right edge at 10.0
    pb = _one_pad_part("PB", "pb", "GND", 11.7, 20.0, 2.0, 1.0)     # left edge at 11.7: a 0.7 mm gap
    b = Board(_geometry_with_a_no_net_pad([pa, pb], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    mid_x = (9.0 + 11.7) / 2.0
    b.track(Net("SIG"), [Location(mid_x, 5.0), Between(PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)),
                         Location(mid_x, 35.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()             # used to raise KeyError: no net named ''
    assert not declared_findings(plan)


def test_past_uses_the_default_clearance_next_to_a_pad_with_no_net():
    pa = _one_pad_part("PA", "pa", "", 10.0, 20.0, 1.0, 1.0)        # no net
    b = Board(_geometry_with_a_no_net_pad([pa], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    past = Past([PadRef(Part("pa"), 1)], Edge.NORTH)
    b.track(Net("SIG"), [Location(10.0, 5.0), past, Location(20.0, 30.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()             # used to raise KeyError: no net named ''
    assert not declared_findings(plan)


def test_a_past_with_no_edge_enum_is_refused():
    with pytest.raises(TypeError):
        Past([PadRef(Part("pa"), 1)], "east")


def test_a_past_with_no_pads_is_refused():
    with pytest.raises(ValueError):
        Past([], Edge.EAST)


# ---------------------------------------------------------------- migration
def test_migration_a_hand_computed_lane_matches_between():
    """The audit's recurring pattern (docs/audits/2026-09-29-layout-scripts.md
    section 3, R5; a module's hand-computed lane constants): a lane's x
    hand-computed as the mid-gap between two facing pads, then a track run
    along it. With equal-sized, facing pads the mid-gap and the pad-centre
    midpoint are the same line, so Between(a, b) must draw the same
    centreline the hand arithmetic did, within 0.01 mm."""
    pa = _one_pad_part("PA", "pa", "MID", 9.0, 20.0, 2.0, 1.0)       # right edge at 10.0
    pb = _one_pad_part("PB", "pb", "GND", 12.0, 20.0, 2.0, 1.0)      # left edge at 11.0: a 1.0 mm gap
    # the hand-computed lane, as the audited script did it: LANE = the mid-gap between the two facing edges
    hand_lane_x = (10.0 + 11.0) / 2.0                # = 10.5

    hand = Board(board_geometry([pa, pb], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    hand.track(Net("SIG"), [Location(hand_lane_x, 5.0), (hand_lane_x, 20.0), Location(hand_lane_x, 35.0)],
              layer=CopperLayer.F, chamfer=0)
    hand_plan = hand.resolve()
    assert not declared_findings(hand_plan)
    hand_xs = {round(t.start.x, 6) for t in _legs(hand_plan)} | {round(t.end.x, 6) for t in _legs(hand_plan)}
    assert round(hand_lane_x, 6) in hand_xs

    intent = Board(board_geometry([pa, pb], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    intent.track(Net("SIG"), [Location(hand_lane_x, 5.0), Between(PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)),
                              Location(hand_lane_x, 35.0)], layer=CopperLayer.F, chamfer=0)
    intent_plan = intent.resolve()
    assert not declared_findings(intent_plan)
    intent_xs = {round(t.start.x, 6) for t in _legs(intent_plan)} | {round(t.end.x, 6) for t in _legs(intent_plan)}

    assert abs(min(intent_xs, key=lambda x: abs(x - hand_lane_x)) - hand_lane_x) < 0.01
    assert hand_xs == intent_xs                     # the same centreline, point for point


def test_between_is_the_middle_of_the_gap_not_of_the_pad_centres():
    """Pads of different widths: the gap's middle lies between their facing
    edges (10.5 and 13.5: 12.0), not between their centres (10 and 15: 12.5)."""
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 1.0, 1.0)      # east edge 10.5
    pb = _one_pad_part("PB", "pb", "GND", 15.0, 20.0, 3.0, 1.0)      # west edge 13.5
    b = Board(board_geometry([pa, pb], width=60, height=60, extra_nets=["SIG"]), edge_margin=1.0)
    b.track(Net("SIG"), [Location(12.0, 5.0), Between(PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)),
                         Location(12.0, 35.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    xs = {round(t.start.x, 6) for t in _legs(plan)} | {round(t.end.x, 6) for t in _legs(plan)}
    assert xs == {12.0}, xs


def test_between_two_pads_of_the_tracks_own_net_needs_no_clearance_to_them():
    """Clearance is to each pad's net: a pad of the track's own net asks none, so a 0.4 mm gap between two
    pads of the track's net takes a 0.2 mm track with no finding."""
    pa = _one_pad_part("PA", "pa", "SIG", 9.0, 20.0, 2.0, 1.0)
    pb = _one_pad_part("PB", "pb", "SIG", 11.4, 20.0, 2.0, 1.0)      # a 0.4 mm gap
    b = Board(board_geometry([pa, pb], width=60, height=60), edge_margin=1.0)
    mid_x = (9.0 + 11.4) / 2.0
    b.track(Net("SIG"), [Location(mid_x, 5.0), Between(PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)),
                         Location(mid_x, 35.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not any("gap between" in f for f in plan.findings), plan.findings
