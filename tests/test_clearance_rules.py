"""A clearance rule a script declares is kept by placemat's own copper
judgement as KiCad keeps it: the clearance between two items is that of the
last declared rule whose condition matches them, else the netclass pair's."""
import pytest

from placemat.layout import Board
from placemat.rules import ClearanceRules, Rule
from placemat.values import Net
from tests.fixtures import board_geometry, footprint


def test_the_last_matching_rule_decides():
    rules = ClearanceRules([Rule("clearance", 0.5, "on a", on="A"),
                            Rule("clearance", 0.1, "a to b", between=("A", "B"))], {})
    assert rules.match("A", "B", "", "").why == "a to b"
    assert rules.match("B", "A", "", "").why == "a to b"
    assert rules.match("A", "C", "", "").why == "on a"
    assert rules.match("C", "A", "", "").why == "on a"
    assert rules.match("C", "B", "", "") is None
    rules = ClearanceRules([Rule("clearance", 0.1, "a to b", between=("A", "B")),
                            Rule("clearance", 0.5, "on a", on="A")], {})
    assert rules.match("A", "B", "", "").why == "on a"


def test_a_rule_within_a_cell_needs_both_items_among_its_owners():
    rules = ClearanceRules([Rule("clearance", 0.1, "in tmc", within="tmc")], {"tmc": frozenset(["U1", "tmc"])})
    assert rules.match("A", "B", "U1", "tmc").why == "in tmc"
    assert rules.match("A", "B", "U1", "R9") is None
    assert rules.match("A", "B", "R9", "R8") is None
    assert rules.match("A", "B", "", "") is None


def _board(rules=(), clearance=0.2):
    fps = [footprint("U1", 10, 10, nets=("A", "A")), footprint("R1", 20, 10, nets=("B", "B"))]
    b = Board(board_geometry(fps, width=40, height=40, clearance=clearance), edge_margin=0.5, keep_going=True)
    for kw in rules:
        b.rule(**kw)
    return b


def test_the_board_clearance_is_the_netclass_figure_without_a_rule():
    assert _board()._clearance("A", "B") == pytest.approx(0.2)


def test_a_rule_replaces_the_netclass_figure_higher_or_lower():
    up = _board([dict(clearance=0.35, between=(Net("A"), Net("B")), why="up")])
    assert up._clearance("A", "B") == pytest.approx(0.35)
    assert up._clearance("B", "A") == pytest.approx(0.35)
    down = _board([dict(clearance=0.1, between=(Net("A"), Net("B")), why="down")])
    assert down._clearance("A", "B") == pytest.approx(0.1)


def test_a_rule_on_a_net_holds_against_a_pad_with_no_net():
    b = _board([dict(clearance=0.4, on=Net("A"), why="a is fussy")])
    assert b._clearance("A", "") == pytest.approx(0.4)
    assert b._clearance("", "") == pytest.approx(0.2)


def test_on_then_between_and_between_then_on_keep_the_later():
    on = dict(clearance=0.4, on=Net("A"), why="on")
    between = dict(clearance=0.1, between=(Net("A"), Net("B")), why="between")
    assert _board([on, between])._clearance("A", "B") == pytest.approx(0.1)
    assert _board([between, on])._clearance("A", "B") == pytest.approx(0.4)


# ---------------------------------------------------------------- the router and the findings
import dataclasses
import math

from placemat.board_geometry import Footprint
from placemat.copper import Track
from placemat.geometry import poly_distance
from placemat.occupancy import Occupancy
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location, PadRef, Part, Past, Edge
from tests.fixtures import declared_findings, pad, track as fixture_track

F = CopperLayer.F


def _one_pad(ref, cx, cy, net, size=1.0):
    p = pad(ref, ref.lower(), 1, net, cx, cy, size, size)
    body = Box(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _run(rules, gap, width=0.2):
    """Track A from U1's east pad (11.4, 10) to (25, 16): the router leaves along the 45 first when that
    clears, else along y = 10. A 1 mm pad of net B stands `gap` mm off the 45's north-east side, with room
    round it. 0.2 mm netclass clearance."""
    u1 = footprint("U1", 10, 10, nets=("A", "A"))
    t = 0.5 * math.sqrt(2.0) + width / 2.0 + gap
    cx, cy = 14.4 + t / math.sqrt(2.0), 13.0 - t / math.sqrt(2.0)
    near = _one_pad("R1", cx, cy, "B")
    b = Board(board_geometry([u1, near], width=40, height=40, clearance=0.2), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"), at=Location(cx, cy))
    for kw in rules:
        b.rule(**kw)
    b.track(Net("A"), [PadRef(Part("u1"), 2), Location(25, 16)], layer=F, width=width, chamfer=0)
    return b.resolve(), near


def _tracks(plan):
    return [op for op in plan.copper if isinstance(op, Track)]


def _nearest(plan, fp):
    return min(poly_distance(t.polygon, p.outlines[0]) for t in _tracks(plan) for p in fp.pads)


def _copper_findings(plan):
    return [f for f in declared_findings(plan) if f.kind == "copper"]


def test_the_router_keeps_a_raising_rule_where_the_netclass_would_pass_it_nearer():
    plan, near = _run([], gap=0.25)
    assert _tracks(plan)[0].end.y == pytest.approx(16.0)             # the 45 first, 0.25 mm off the pad
    assert _nearest(plan, near) == pytest.approx(0.25, abs=1e-6)
    plan, near = _run([dict(clearance=0.4, between=(Net("A"), Net("B")), why="a kept off b")], gap=0.25)
    assert _tracks(plan)[0].end.y == pytest.approx(10.0)             # along y = 10 first instead
    assert _nearest(plan, near) >= 0.4 - 1e-6
    assert not _copper_findings(plan)


def test_the_router_takes_a_leg_the_netclass_refuses_under_a_lowering_rule():
    plan, near = _run([], gap=0.15)
    assert _tracks(plan)[0].end.y == pytest.approx(10.0)             # the 45 first is refused
    plan, near = _run([dict(clearance=0.1, between=(Net("A"), Net("B")), why="a close to b")], gap=0.15)
    assert _tracks(plan)[0].end.y == pytest.approx(16.0)
    assert _nearest(plan, near) == pytest.approx(0.15, abs=1e-6)
    assert not _copper_findings(plan)


def test_a_copper_finding_under_a_rule_quotes_its_why():
    u1 = footprint("U1", 10, 10, nets=("A", "A"))
    near = _one_pad("R1", 18, 10.7, "B")
    b = Board(board_geometry([u1, near], width=40, height=40), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"), at=Location(18, 10.7))
    b.rule(clearance=0.4, between=(Net("A"), Net("B")), why="a kept off b")
    b.track(Net("A"), [PadRef(Part("u1"), 2), Location(25, 10)], layer=F, width=0.2, chamfer=0)
    hits = [str(f) for f in b.resolve().findings if f.kind == "copper" and "mm from" in f]
    assert hits and all("a kept off b" in h and "needs 0.40" in h for h in hits), hits


def test_a_past_holds_its_point_off_by_the_rules_clearance():
    def point(rules):
        u1 = footprint("U1", 10, 10, nets=("A", "A"))
        r1 = footprint("R1", 20, 10, nets=("B", "B"))
        b = Board(board_geometry([u1, r1], width=40, height=40), edge_margin=0.5, keep_going=True)
        b.place(Part("u1"), at=Location(10, 10))
        b.place(Part("r1"), at=Location(20, 10))
        for kw in rules:
            b.rule(**kw)
        b.track(Net("A"), [PadRef(Part("u1"), 2), Past([PadRef(Part("r1"), 1)], Edge.WEST), Location(15, 20)],
                layer=F, width=0.2, chamfer=0)
        return [x for t in _tracks(b.resolve()) for x in (t.start.x, t.end.x)]
    # R1's pad 1 spans x 18.1..19.1; the point is half the track width plus the clearance west of it
    assert any(abs(x - (18.1 - 0.1 - 0.2)) < 1e-6 for x in point([]))
    ruled = point([dict(clearance=0.5, between=(Net("A"), Net("B")), why="a kept off b")])
    assert any(abs(x - (18.1 - 0.1 - 0.5)) < 1e-6 for x in ruled)


# ---------------------------------------------------------------- within a cell
def _cell_occupancy(rule_min=None):
    """U1 and R1 are the cell's members, their pads 0.15 mm apart (U1.2 x 10.9..11.9, R1.1 x 12.05..13.05); X1,
    no member, has a pad 0.15 mm north of U1.2; the cell's own copper is a track of net C 0.15 mm south of it."""
    from placemat.rules import Rule
    u1 = footprint("U1", 10, 10, cell="tmc", inst="tmc.u1", nets=("A", "A"))
    r1 = footprint("R1", 13.95, 10, cell="tmc", inst="tmc.r1", nets=("B", "B"))
    x1 = footprint("X1", 12.8, 8.85, inst="x1", nets=("B", "B"))
    own = fixture_track("C", 10.9, 10.75, 11.9, 10.75, w=0.2, owner="tmc")
    g = board_geometry([u1, r1, x1], cells=["tmc"], copper=[own], width=40, height=40)
    rules = [] if rule_min is None else [Rule("clearance", rule_min, "inside the cell", within="tmc")]
    return Occupancy(g, 0.5, rules=rules)


def _pad_shape(occ, ref, number):
    return next(s for s in occ.items[ref].shapes if s.kind == "pad" and s.label == str(number))


def test_a_rule_within_a_cell_judges_its_members_pads_and_its_own_copper_not_another_parts():
    occ = _cell_occupancy(0.05)
    u1, r1, x1 = _pad_shape(occ, "U1", 2), _pad_shape(occ, "R1", 1), _pad_shape(occ, "X1", 1)
    own = next(c for c in occ.copper if c.owner == "tmc")
    assert occ._conflict(u1, r1, None, exact=True) is None          # two members: the 0.05 rule
    assert occ._conflict(u1, own, None, exact=True) is None         # a member and the cell's own copper
    assert occ._conflict(u1, x1, None, exact=True) is not None      # another part's pad: the netclass 0.2
    plain = _cell_occupancy()
    assert plain._conflict(_pad_shape(plain, "U1", 2), _pad_shape(plain, "R1", 1), None, exact=True) is not None


def test_a_rule_within_a_cell_that_raises_the_figure_holds_between_its_members_only():
    occ = _cell_occupancy(0.4)
    u1, r1, x1 = _pad_shape(occ, "U1", 2), _pad_shape(occ, "R1", 1), _pad_shape(occ, "X1", 1)
    assert occ._conflict(u1, r1, None, exact=True) is not None
    plain = _cell_occupancy()
    far = _pad_shape(plain, "X1", 1)
    assert plain._conflict(_pad_shape(plain, "U1", 2), far, None, exact=True) is not None   # 0.15 < 0.2 anyway
    assert "rule: inside the cell" in occ._conflict(u1, r1, None, exact=True)
    assert "rule" not in occ._conflict(u1, x1, None, exact=True)


def test_a_conflict_gap_is_a_floor_under_the_largest_clearance_a_rule_asks():
    """`[place] conflict_gap` is how far a conflict reaches; a rule that asks for more than it raises the reach by
    itself, so the setting never has to copy a rule's number."""
    from placemat.rules import Rule
    g = board_geometry([footprint("U1", 10, 10)], width=40, height=40)
    settings = dataclasses.replace(Settings(), place_conflict_gap=0.5)
    assert Occupancy(g, 0.5, settings=settings, rules=[Rule("clearance", 0.8, "wide", on="A")])._gap == 0.8
    assert Occupancy(g, 0.5, settings=settings, rules=[Rule("clearance", 0.3, "narrow", on="A")])._gap == 0.5
    assert Occupancy(g, 0.5, settings=settings)._gap == 0.5


def test_a_free_spot_holds_its_via_off_a_fixed_via_by_the_rules_clearance():
    from placemat import FreeSpot

    def gap(rules):
        fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG"))]
        b = Board(board_geometry(fps, width=40, height=40, extra_nets=("GND",)), edge_margin=0.5)
        b.place(Part("u1"), at=Location(20, 20))
        for kw in rules:
            b.rule(**kw)
        b.via(Net("GND"), at=Location(23.0, 20.0), why="fixed")
        b.via(Net("SIG"), at=FreeSpot(near=PadRef(Part("u1"), "SIG")), why="tap")
        fixed, spot = [v for v in b.resolve().copper if type(v).__name__ == "Via"]
        return fixed.at.distance(spot.at) - (fixed.size + spot.size) / 2.0
    assert gap([]) < 0.5 - 1e-6
    assert gap([dict(clearance=0.5, between=(Net("GND"), Net("SIG")), why="wide")]) >= 0.5 - 1e-6


def test_a_rule_within_a_cell_and_between_nets_needs_both():
    rules = ClearanceRules([Rule("clearance", 0.1, "in tmc, a to b", within="tmc", between=("A", "B"))],
                           {"tmc": frozenset(["U1", "tmc"])})
    assert rules.match("A", "B", "U1", "tmc").why == "in tmc, a to b"
    assert rules.match("B", "A", "tmc", "U1").why == "in tmc, a to b"
    assert rules.match("A", "C", "U1", "tmc") is None               # another pair of nets
    assert rules.match("A", "B", "U1", "R9") is None                # not both in the cell
    on = ClearanceRules([Rule("clearance", 0.1, "in tmc, on a", within="tmc", on="A")],
                        {"tmc": frozenset(["U1", "tmc"])})
    assert on.match("A", "C", "U1", "tmc") is not None and on.match("A", "C", "U1", "R9") is None


def test_a_rule_within_a_cell_and_between_nets_judges_the_cells_pads_only_on_those_nets():
    from placemat.rules import Rule
    u1 = footprint("U1", 10, 10, cell="tmc", inst="tmc.u1", nets=("A", "A"))
    r1 = footprint("R1", 13.95, 10, cell="tmc", inst="tmc.r1", nets=("B", "B"))
    x1 = footprint("X1", 12.8, 8.85, inst="x1", nets=("B", "B"))
    g = board_geometry([u1, r1, x1], cells=["tmc"], width=40, height=40)
    occ = Occupancy(g, 0.5, rules=[Rule("clearance", 0.1, "tmc a to b", within="tmc", between=("A", "B"))])
    s_u1, s_r1, s_x1 = _pad_shape(occ, "U1", 2), _pad_shape(occ, "R1", 1), _pad_shape(occ, "X1", 1)
    assert occ._conflict(s_u1, s_r1, None, exact=True) is None          # in the cell, on A and B: 0.1 holds
    assert occ._conflict(s_u1, s_x1, None, exact=True) is not None      # X1 is no member: the netclass 0.2
