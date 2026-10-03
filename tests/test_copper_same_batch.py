"""Copper planned in one batch is judged against the rest of that batch, not
only against what was on the board before it: a track of one net run
through a via of another, both declared with nothing to wait on, is a
finding. Pure: synthetic boards."""
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net
from tests.fixtures import board_geometry


def _board():
    return Board(board_geometry([], width=40, height=40, extra_nets=["P", "N"]), edge_margin=1.0, keep_going=True)


def test_a_track_through_a_via_of_another_net_in_the_same_batch_is_a_finding():
    b = _board()
    b.via(Net("N"), at=Location(20.0, 20.0))
    b.track(Net("P"), [Location(10.0, 20.5), Location(30.0, 20.5)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert any("copper P" in f and "N" in f for f in plan.findings) or \
        any("copper N" in f and "P" in f for f in plan.findings), plan.findings


def test_copper_clear_of_each_other_in_the_same_batch_is_no_finding():
    b = _board()
    b.via(Net("N"), at=Location(20.0, 25.0))
    b.track(Net("P"), [Location(10.0, 20.0), Location(30.0, 20.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not [f for f in plan.findings if f.startswith("copper")], plan.findings


def test_same_net_copper_in_the_same_batch_is_no_finding():
    b = _board()
    b.via(Net("P"), at=Location(20.0, 20.0))
    b.track(Net("P"), [Location(10.0, 20.0), Location(30.0, 20.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert not [f for f in plan.findings if f.startswith("copper")], plan.findings


def test_a_vias_finding_names_only_the_boards_own_layers():
    """A via is copper through the whole stack, which on this board is two
    layers: its finding names those, not every inner layer placemat knows."""
    b = _board()
    b.via(Net("N"), at=Location(20.0, 20.0))
    b.via(Net("P"), at=Location(20.7, 20.0))               # two vias stand too near on every layer they share
    plan = b.resolve()
    hits = [f for f in plan.findings if f.startswith("copper") and "via" in f]
    assert hits and all("In1" not in f and "In30" not in f for f in hits), hits
    assert all("B.Cu" in f and "F.Cu" in f for f in hits), hits


def test_a_refusal_by_copper_names_the_copper():
    """A part refused round its hint by copper already on the board (no part
    owns it): the refusal's copper count names the net and kind of what was
    in the way, not only a number."""
    from placemat.values import Near, Part
    from tests.fixtures import footprint, track
    fps = [footprint("U1", 5, 5, w=3, h=2, inst="u1", nets=("A", "B"))]
    lines = [track("GND", 0.2, 0.5 + k, 29.8, 0.5 + k) for k in range(30)]    # tracks every 1 mm
    b = Board(board_geometry(fps, copper=lines, width=30, height=30), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Near(Location(15.0, 15.0), radius=2.0))
    plan = b.resolve()
    refused = [f for f in plan.findings if "u1" in f and "copper x" in f]
    assert refused and all("GND" in f for f in refused), plan.findings


def test_a_via_just_over_the_clearance_from_a_track_is_no_finding():
    """A via is a circle: measured as its polygon (a few microns outside the
    circle) a gap just over the clearance read as just under it, which KiCad's
    DRC, measuring the circle, does not report."""
    b = Board(board_geometry([], width=40, height=40, extra_nets=["P", "N"], clearance=0.16), edge_margin=1.0,
              keep_going=True)
    b.via(Net("N"), at=Location(20.0, 20.0), size=0.45, drill=0.2)
    y = 20.0 + 0.225 + 0.162 + 0.125                         # a true gap of 0.162 to a 0.25 mm track
    b.track(Net("P"), [Location(10.0, y), Location(30.0, y)], layer=CopperLayer.F, width=0.25, chamfer=0)
    plan = b.resolve()
    assert not [f for f in plan.findings if f.startswith("copper")], plan.findings


def test_a_via_just_under_the_clearance_from_a_track_is_still_a_finding():
    b = Board(board_geometry([], width=40, height=40, extra_nets=["P", "N"], clearance=0.16), edge_margin=1.0,
              keep_going=True)
    b.via(Net("N"), at=Location(20.0, 20.0), size=0.45, drill=0.2)
    y = 20.0 + 0.225 + 0.158 + 0.125
    b.track(Net("P"), [Location(10.0, y), Location(30.0, y)], layer=CopperLayer.F, width=0.25, chamfer=0)
    plan = b.resolve()
    assert [f for f in plan.findings if f.startswith("copper")], plan.findings


def test_a_refusal_by_another_parts_pads_names_that_part():
    """A copper refusal whose blockers are another part's pads (a cell's via
    field meeting the far face's pads) names that part: its pads are filed
    as pads, and they count under copper."""
    from collections import Counter
    from types import SimpleNamespace
    from placemat.blame import blame_of
    from placemat.finding_text import blame_text
    from placemat.refusals import Owner, ReservedBy
    result = SimpleNamespace(rejected=Counter({"copper": 471, "reservation": 163}), reasons={},
                             blockers=Counter({("pad", Owner("who", "J4", "debug", "GND"), "back"): 300,
                                               ("through", Owner("who", "via", "", "GND"), "back/front"): 171,
                                               ("reservation", Owner("member_in", "C49", by=ReservedBy("keepout", "seal_rim", "seal")), ""): 163}))
    text = blame_text(blame_of(result))
    assert "copper x471: cell debug's J4 GND back face x300" in text, text


def test_copper_is_named_even_when_other_kinds_refused_more():
    from collections import Counter
    from types import SimpleNamespace
    from placemat.blame import blame_of
    from placemat.finding_text import blame_text
    from placemat.refusals import Owner
    result = SimpleNamespace(rejected=Counter({"edge": 797980, "reservation": 69551, "body": 14376, "copper": 2210}),
                             reasons={}, blockers=Counter({("pad", Owner("who", "U7", "", "GND"), "front"): 2210}))
    text = blame_text(blame_of(result))
    assert "copper x2210: U7 GND front face x2210" in text, text
