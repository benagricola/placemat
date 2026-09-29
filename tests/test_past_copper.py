"""Past(items, edge, across=) over copper: its items may be pads, vias
(what board.via() or board.vias(along=) returns) and tracks (what
board.track() returns), in any mix; `across=` sets where the point lies
across `edge`. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat import FreeSpot
from placemat.board_geometry import Footprint, NetClass
from placemat.copper import Track, Via
from placemat.layout import Board
from placemat.values import Along, Box, CopperLayer, Edge, Face, Location, Net, PadRef, Part, Past
from tests.fixtures import board_geometry, declared_findings, pad


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board(parts, nets=("SIG", "V", "T"), classes=None):
    geom = board_geometry(parts, width=60, height=60, extra_nets=list(nets))
    if classes:
        netclasses = dict(geom.netclasses)
        netclasses.update(classes)
        geom = dataclasses.replace(geom, netclasses=netclasses)
    b = Board(geom, edge_margin=1.0)
    for fp in parts:
        b.place(Part(fp.inst), at=fp.location)
    return b


def _points(plan, net):
    return {(round(p.x, 6), round(p.y, 6))
            for t in plan.copper if isinstance(t, Track) and t.net == net for p in (t.start, t.end)}


# ---------------------------------------------------------------- Past over vias and tracks
def test_a_track_passes_a_vias_clearance_below_it():
    b = _board([])
    v = b.via(Net("V"), at=Location(10.0, 20.0))          # 0.6 mm: its copper reaches y = 20.3
    # 20.3 + 0.2 clearance + 0.1 (half the 0.2 mm track) = 20.6, centred on the via
    b.track(Net("SIG"), [Location(5.0, 20.6), Past([v], Edge.SOUTH), Location(15.0, 20.6)],
            layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan), plan.findings
    assert (10.0, 20.6) in _points(plan, "SIG")


def test_a_track_passes_another_tracks_clearance_east_of_it():
    b = _board([])
    t = b.track(Net("T"), [Location(10.0, 10.0), Location(10.0, 30.0)], layer=CopperLayer.F, chamfer=0)
    # the 0.2 mm track's copper reaches x = 10.1: 10.1 + 0.2 + 0.1 = 10.4; y the middle of 9.9..30.1
    b.track(Net("SIG"), [Location(10.4, 5.0), Past([t], Edge.EAST), Location(10.4, 35.0)],
            layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan), plan.findings
    assert (10.4, 20.0) in _points(plan, "SIG")


def test_pads_and_vias_mixed_take_the_worst_clearance_by_net_pair():
    pa = _one_pad_part("PA", "pa", "HV", 10.0, 20.0, 1.0, 1.0)       # box (9.5, 19.5)-(10.5, 20.5)
    b = _board([pa], nets=("SIG", "V", "HV"), classes={"HV": NetClass("HV", 0.2, 0.5, 0.6, 0.3)})
    v = b.via(Net("V"), at=Location(12.0, 20.0))                     # box (11.7, 19.7)-(12.3, 20.3)
    # the pads' and vias' box bottom 20.5; SIG to HV 0.5, SIG to V 0.2: 20.5 + 0.5 + 0.1 = 21.1,
    # x the middle of 9.5..12.3
    b.track(Net("SIG"), [Location(5.0, 21.1), Past([PadRef(Part("pa"), 1), v], Edge.SOUTH),
                         Location(15.0, 21.1)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan), plan.findings
    assert (10.9, 21.1) in _points(plan, "SIG")


# ---------------------------------------------------------------- across=
def test_across_a_pad_puts_the_point_on_that_pads_centre_line():
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 1.0, 1.0)
    pb = _one_pad_part("PB", "pb", "MID", 13.0, 20.0, 1.0, 1.0)
    b = _board([pa, pb], nets=("SIG", "MID"))
    past = Past([PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], Edge.SOUTH, across=PadRef(Part("pb"), 1))
    b.track(Net("SIG"), [Location(5.0, 20.8), past, Location(20.0, 20.8)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan), plan.findings
    assert (13.0, 20.8) in _points(plan, "SIG")         # pb's x, not the middle of the two (11.5)


def test_across_a_via_puts_the_point_on_the_vias_centre_line():
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 4.0, 1.0)      # box (8, 19.5)-(12, 20.5)
    b = _board([pa], nets=("SIG", "MID", "V"))
    v = b.via(Net("V"), at=Location(11.0, 25.0))
    b.track(Net("SIG"), [Location(5.0, 20.8), Past([PadRef(Part("pa"), 1)], Edge.SOUTH, across=v),
                         Location(20.0, 20.8)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert (11.0, 20.8) in _points(plan, "SIG")


def test_across_along_start_is_the_start_of_the_boxs_side():
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 1.0, 1.0)
    pb = _one_pad_part("PB", "pb", "MID", 10.0, 23.0, 1.0, 1.0)      # union (9.5, 19.5)-(10.5, 23.5)
    b = _board([pa, pb], nets=("SIG", "MID"))
    past = Past([PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], Edge.EAST, across=Along.START)
    b.track(Net("SIG"), [Location(10.8, 5.0), past, Location(10.8, 30.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not declared_findings(plan), plan.findings
    assert (10.8, 19.5) in _points(plan, "SIG")         # the top of the east side


def test_across_is_a_pad_a_via_or_an_along():
    with pytest.raises(TypeError, match="across"):
        Past([PadRef(Part("pa"), 1)], Edge.EAST, across=3.0)


def test_lane_is_a_net():
    with pytest.raises(TypeError, match="lane"):
        Past([PadRef(Part("pa"), 1)], Edge.EAST, lane="L")


def test_a_past_of_something_other_than_pads_vias_and_tracks_is_refused():
    with pytest.raises(TypeError, match="Past"):
        Past([Location(1.0, 2.0)], Edge.EAST)
    b = _board([])
    pour = b.pour(Net("V"), [Location(0, 0), Location(4, 0), Location(4, 4)], layer=CopperLayer.F)
    with pytest.raises(TypeError, match="pour V"):
        Past([pour], Edge.EAST)


def test_a_track_refuses_lane_on_its_past():
    b = _board([])
    v = b.via(Net("V"), at=Location(10.0, 20.0))
    with pytest.raises(TypeError, match="lane"):
        b.track(Net("SIG"), [Location(5.0, 20.6), Past([v], Edge.SOUTH, lane=Net("T")), Location(15.0, 20.6)],
                layer=CopperLayer.F)


# ---------------------------------------------------------------- order and loss
def test_a_past_naming_a_via_declared_after_the_track_is_a_finding():
    """A script cannot name a via before declaring it, so the order is set
    here by hand: the via's declaration moved after the track's."""
    b = _board([])
    v = b.via(Net("V"), at=Location(10.0, 20.0))
    t = b.track(Net("SIG"), [Location(5.0, 20.6), Past([v], Edge.SOUTH), Location(15.0, 20.6)],
                layer=CopperLayer.F, chamfer=0)
    v.index, t.index = t.index, v.index
    b._copper.sort(key=lambda c: c.index)
    plan = b.resolve()
    assert not [op for op in plan.copper if isinstance(op, Track) and op.net == "SIG"]
    assert any("track SIG" in f and "via V" in f and "declared after" in f for f in plan.findings), plan.findings


def test_a_past_naming_a_via_that_found_no_spot_is_a_finding_and_draws_no_track():
    pa = _one_pad_part("PA", "pa", "V", 10.0, 20.0, 1.0, 1.0)
    b = _board([pa], nets=("SIG", "V"))
    v = b.via(Net("V"), at=FreeSpot(near=PadRef(Part("pa"), 1), radius=0.05))
    b.track(Net("SIG"), [Location(5.0, 25.0), Past([v], Edge.SOUTH), Location(15.0, 25.0)],
            layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not [op for op in plan.copper if isinstance(op, Via)]
    assert not [op for op in plan.copper if isinstance(op, Track) and op.net == "SIG"]
    assert any("track SIG" in f and "via V" in f and "found no spot" in f for f in plan.findings), plan.findings


def test_a_past_naming_another_boards_via_is_refused():
    other = _board([])
    v = other.via(Net("V"), at=Location(10.0, 20.0))
    b = _board([])
    with pytest.raises(TypeError, match="another board"):
        b.track(Net("SIG"), [Location(5.0, 20.6), Past([v], Edge.SOUTH), Location(15.0, 20.6)],
                layer=CopperLayer.F)


# ---------------------------------------------------------------- a via at a Past point
TIP_Y, PAD_H, CLEARANCE, VIA = 20.0, 1.0, 0.2, 0.6      # the fixture's contact row, its clearance and via size
ROW_NETS = ("GND", "SIG_P", "SIG_N", "SIG_P", "SIG_N", "GND")


def _contact_row():
    """A connector's contact row: six 0.3 x 1.0 mm pads 0.5 mm apart, on
    y = 20, their tips (south ends) at y = 20.5."""
    pads = tuple(pad("J1", "j1", i + 1, net, 10.0 + 0.5 * i, TIP_Y, 0.3, PAD_H) for i, net in enumerate(ROW_NETS))
    body = Box(9.0, 18.0, 13.5, 20.6)
    return Footprint("J1", "j1", None, "J1", Location(11.25, 19.3), 0.0, Face.FRONT, body, body.inflate(0.1),
                     body, pads)


def _tips():
    return [PadRef(Part("j1"), i + 1) for i in range(len(ROW_NETS))]


def _vias(plan, net):
    return [op.at for op in plan.copper if isinstance(op, Via) and op.net == net]


def test_a_via_stands_its_clearance_past_the_tips_on_a_pads_axis():
    b = _board([_contact_row()], nets=("SIG_P", "SIG_N", "GND"))
    b.via(Net("SIG_N"), at=Past(_tips(), Edge.SOUTH, across=PadRef(Part("j1"), 3)))
    plan = b.resolve()
    (at,) = _vias(plan, "SIG_N")
    assert at.x == pytest.approx(11.0)                          # pad 3's axis
    assert at.y == pytest.approx(20.5 + 0.2 + 0.3)              # the tips, the clearance, the via's radius


def test_a_track_ends_on_a_via_at_a_past_and_another_turns_past_the_vias():
    b = _board([_contact_row()], nets=("SIG_P", "SIG_N", "GND"))
    v3 = b.via(Net("SIG_N"), at=Past(_tips(), Edge.SOUTH, across=PadRef(Part("j1"), 3)))
    v5 = b.via(Net("SIG_N"), at=Past(_tips(), Edge.SOUTH, across=PadRef(Part("j1"), 5)))
    b.track(Net("SIG_N"), [PadRef(Part("j1"), 3), v3], layer=CopperLayer.F, chamfer=0)
    b.track(Net("SIG_P"), [PadRef(Part("j1"), 2), Past([v3, v5], Edge.SOUTH), PadRef(Part("j1"), 4)],
            layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert (11.0, 21.0) in _points(plan, "SIG_N")               # the track ends on v3
    # the vias' copper reaches 21.3: 21.3 + 0.2 + 0.1 = 21.6, centred between them (11.0 and 12.0)
    assert (11.5, 21.6) in _points(plan, "SIG_P")


def test_a_via_at_a_past_naming_a_via_that_found_no_spot_is_a_finding():
    pa = _one_pad_part("PA", "pa", "V", 10.0, 20.0, 1.0, 1.0)
    b = _board([pa], nets=("SIG", "V"))
    lost = b.via(Net("V"), at=FreeSpot(near=PadRef(Part("pa"), 1), radius=0.05))
    b.via(Net("SIG"), at=Past([lost], Edge.SOUTH))
    plan = b.resolve()
    assert not [op for op in plan.copper if isinstance(op, Via)]
    assert any("via SIG" in f and "via V" in f and "found no spot" in f for f in plan.findings), plan.findings


def test_a_via_refuses_lane_on_its_past():
    b = _board([_contact_row()], nets=("SIG_P", "SIG_N", "GND"))
    with pytest.raises(TypeError, match="lane"):
        b.via(Net("SIG_N"), at=Past(_tips(), Edge.SOUTH, lane=Net("GND")))


def test_migration_a_via_under_a_contact_row_matches_the_hand_computed_one():
    """A module's hand arithmetic: a via on a contact's axis, the via's
    clearance below the row's tips - TIP + clearance + via/2 - against the
    same via said as a Past. They must agree within 0.01 mm."""
    tip = TIP_Y + PAD_H / 2.0
    hand = _board([_contact_row()], nets=("SIG_P", "SIG_N", "GND"))
    hand.via(Net("SIG_N"), at=Location(11.0, tip + CLEARANCE + VIA / 2.0))
    hand_plan = hand.resolve()

    intent = _board([_contact_row()], nets=("SIG_P", "SIG_N", "GND"))
    intent.via(Net("SIG_N"), at=Past(_tips(), Edge.SOUTH, across=PadRef(Part("j1"), 3)))
    intent_plan = intent.resolve()

    (a,), (b,) = _vias(hand_plan, "SIG_N"), _vias(intent_plan, "SIG_N")
    assert abs(a.x - b.x) < 0.01 and abs(a.y - b.y) < 0.01
