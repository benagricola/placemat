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
    b.track(Net("P"), [Location(10.0, 20.1), Location(30.0, 20.1)], layer=CopperLayer.F, chamfer=0)
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
