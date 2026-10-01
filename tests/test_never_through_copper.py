"""The plan never draws a track or a via through another net's copper: a pad, a track, a via or a pour. Copper that
would be is not drawn, and a finding says which and what it met. A track that may bridge still passes under a track it
crosses; copper that merely stands nearer than the clearance is a finding and is drawn, as before."""
import pytest

from placemat.copper import Pour, Track, Via
from placemat.geometry import polys_overlap
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, declared_findings, footprint

F = CopperLayer.F


def through(plan) -> list:
    """Every track or via of the plan that overlaps the copper of another net on a layer they share: a placed pad,
    or another track, via or pour. Empty is the invariant."""
    pads = [(p.net, p.layers, o) for fp in plan.geometry.footprints for p in fp.pads for o in p.outlines]
    wires = [op for op in plan.copper if isinstance(op, (Track, Via))]
    pours = [op for op in plan.copper if isinstance(op, Pour)]
    layers = lambda op: frozenset(op.layers) if isinstance(op, Via) and op.layers else (
        frozenset(CopperLayer) if isinstance(op, Via) else frozenset([op.layer]))
    out = []
    for w in wires:
        for net, pl, outline in pads:
            if net != w.net and layers(w) & pl and polys_overlap(w.polygon, outline):
                out.append("%s %s over a %s pad" % (type(w).__name__, w.net, net))
        for o in wires + pours:
            if o is not w and o.net != w.net and layers(w) & layers(o) and polys_overlap(w.polygon, o.polygon):
                out.append("%s %s over %s %s" % (type(w).__name__, w.net, type(o).__name__, o.net))
    return out


def _plan(parts, declare, width=50, height=30):
    b = Board(board_geometry(parts, width=width, height=height), edge_margin=0.5, keep_going=True)
    for fp in parts:
        b.place(Part(fp.inst), at=Location(fp.location.x, fp.location.y))
    declare(b)
    return b.resolve()


def _wall(n=14):
    """A column of another net's pads (WALL) across the way from A1's SIG pad to A2's, too tall to go round."""
    return [footprint("W%d" % i, 20, 2 + i * 1.3, w=2.0, h=1.0, nets=("WALL", "WALL")) for i in range(n)]


def _ends():
    return [footprint("A1", 10, 10, nets=("X1", "SIG")), footprint("A2", 30, 10, nets=("SIG", "X2"))]


def test_a_track_whose_only_way_runs_through_another_nets_pads_is_not_drawn():
    plan = _plan(_ends() + _wall(), lambda b: b.track(
        Net("SIG"), [PadRef(Part("a1"), 2), PadRef(Part("a2"), 1)], layer=F))
    assert not [op for op in plan.copper if isinstance(op, Track)]
    assert through(plan) == []
    said = [f for f in declared_findings(plan) if "SIG" in str(f) and "not drawn" in str(f)]
    assert said and "WALL" in str(said[0]), declared_findings(plan)


def test_a_track_no_way_of_which_is_clear_still_goes_round_another_nets_pad_rather_than_through_it():
    """A rule that no leg can meet (SIG 30 mm from WALL) leaves every way too near. The track takes a way that
    touches no WALL pad, where the planner once took the fewest turns whatever they ran through."""
    parts = [footprint("A1", 10, 10, nets=("X1", "SIG")), footprint("A2", 30, 12, nets=("SIG", "X2")),
             footprint("W0", 20, 12, w=2.0, h=1.0, nets=("WALL", "WALL"))]

    def declare(b):
        b.rule(clearance=30.0, between=(Net("SIG"), Net("WALL")), why="nothing clears it")
        b.track(Net("SIG"), [PadRef(Part("a1"), 2), PadRef(Part("a2"), 1)], layer=F)
    plan = _plan(parts, declare, width=60, height=40)
    assert [op for op in plan.copper if isinstance(op, Track)]
    assert through(plan) == []


def test_a_track_with_a_clear_way_round_is_still_drawn():
    plan = _plan(_ends() + _wall(2), lambda b: b.track(
        Net("SIG"), [PadRef(Part("a1"), 2), PadRef(Part("a2"), 1)], layer=F))
    assert [op for op in plan.copper if isinstance(op, Track)]
    assert through(plan) == []


def test_a_via_placed_on_another_nets_pad_is_not_drawn():
    plan = _plan(_ends(), lambda b: b.via(Net("SIG"), Location(8.6, 10.0), why="on X1's pad"))
    assert not [op for op in plan.copper if isinstance(op, Via)]
    assert through(plan) == []
    assert [f for f in declared_findings(plan) if "not drawn" in str(f) and "X1" in str(f)], declared_findings(plan)


def test_a_via_that_ends_a_track_takes_the_track_with_it():
    def declare(b):
        v = b.via(Net("SIG"), Location(8.6, 10.0), why="on X1's pad")
        b.track(Net("SIG"), [PadRef(Part("a1"), 2), v], layer=F)
    plan = _plan(_ends(), declare)
    assert not [op for op in plan.copper if isinstance(op, (Track, Via))]
    assert through(plan) == []


def test_a_track_across_a_pour_of_another_net_is_not_drawn():
    def declare(b):
        b.pour(Net("WALL"), [Location(18, 4), Location(22, 4), Location(22, 16), Location(18, 16)], layer=F)
        b.track(Net("SIG"), [PadRef(Part("a1"), 2), PadRef(Part("a2"), 1)], layer=F)
    plan = _plan(_ends() + [footprint("W0", 20, 25, w=2.0, h=1.0, nets=("WALL", "WALL"))], declare)
    assert [op for op in plan.copper if isinstance(op, Pour)]
    assert not [op for op in plan.copper if isinstance(op, Track)]
    assert through(plan) == []


def test_two_tracks_that_cross_and_neither_may_bridge_leave_one_drawn():
    parts = [footprint("P1", 10, 10, nets=("X1", "N1")), footprint("P2", 30, 10, nets=("N1", "X2")),
             footprint("Q1", 20, 4, w=2.0, h=1.0, nets=("N2", "X3")), footprint("Q2", 20, 18, w=2.0, h=1.0, nets=("N2", "X4"))]

    def declare(b):
        b.track(Net("N1"), [PadRef(Part("p1"), 2), PadRef(Part("p2"), 1)], layer=F, chamfer=0)
        b.track(Net("N2"), [PadRef(Part("q1"), 1), PadRef(Part("q2"), 1)], layer=F, chamfer=0)
    plan = _plan(parts, declare)
    drawn = {op.net for op in plan.copper if isinstance(op, Track)}
    assert len(drawn) == 1, drawn
    assert through(plan) == []
    assert [f for f in declared_findings(plan) if "not drawn" in str(f)], declared_findings(plan)


def test_a_track_that_may_bridge_still_passes_under_the_track_it_crosses():
    parts = [footprint("P1", 10, 10, nets=("X1", "N1")), footprint("P2", 30, 10, nets=("N1", "X2")),
             footprint("Q1", 20, 4, w=2.0, h=1.0, nets=("N2", "X3")), footprint("Q2", 20, 18, w=2.0, h=1.0, nets=("N2", "X4"))]

    def declare(b):
        b.track(Net("N1"), [PadRef(Part("p1"), 2), PadRef(Part("p2"), 1)], layer=F, chamfer=0)
        b.track(Net("N2"), [PadRef(Part("q1"), 1), PadRef(Part("q2"), 1)], layer=F, chamfer=0, bridge=True)
    plan = _plan(parts, declare)
    assert {op.net for op in plan.copper if isinstance(op, Track)} == {"N1", "N2"}
    assert [op for op in plan.copper if isinstance(op, Via) and op.net == "N2"]
    assert through(plan) == []
