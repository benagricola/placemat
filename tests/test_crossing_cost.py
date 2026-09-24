"""The search weighs a candidate's ratsnest crossings: each crossing its
airwires would add to the airwires already on the board costs
`score.crossing` millimetres of wire, as it does in the run score."""
import dataclasses

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Near, Net, Part
from tests.fixtures import board_geometry, footprint


def _board(**settings):
    # A placed airwire of net S runs east-west along y=30 from x=23.6 to x=36.4. R1 joins
    # U, placed at (28.6, 18), and W, placed at (28.6, 42): turned upright on x=28.6 its
    # wire is the same anywhere between them, so wire alone leaves it at the hint. Only
    # straddling y=30 - U's pad north of S, W's south - keeps both its airwires off S.
    fps = [footprint("A1", 25, 30, inst="a1", nets=("S", "X1")),
           footprint("A2", 35, 30, inst="a2", nets=("X2", "S")),
           footprint("N1", 30, 18, inst="n1", nets=("U", "X3")),
           footprint("W1", 30, 42, inst="w1", nets=("W", "X4")),
           footprint("R1", 5, 5, inst="r1", nets=("U", "W"))]
    cfg = dataclasses.replace(Settings(), **settings)
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg)


def _declare(b, hint=Location(28.6, 34)):
    for ref, at in (("a1", (25, 30)), ("a2", (35, 30)), ("n1", (30, 18)), ("w1", (30, 42))):
        b.place(Part(ref), at=Location(*at))
    b.place(Part("r1"), at=Near(hint, radius=6.0))


def _crossings(b, plan):
    from placemat import score
    return score.plan_measures(b, plan)["crossings"]


def test_a_spot_whose_airwires_cross_a_placed_net_costs_more_than_one_that_does_not():
    blind = _board(score_crossing=0.0)
    _declare(blind)
    assert _crossings(blind, blind.resolve())["signal"] == 1          # the hint's spot: W's pad south, U's airwire across S
    b = _board(score_crossing=50.0)
    _declare(b)
    assert _crossings(b, b.resolve())["signal"] == 0


def test_a_planes_crossing_costs_nothing_at_the_default_plane_weight():
    b = _board(score_crossing=50.0)
    b.plane(Net("S"), [CopperLayer.B])
    _declare(b)
    blind = _board(score_crossing=0.0)
    blind.plane(Net("S"), [CopperLayer.B])
    _declare(blind)
    assert b.resolve().placement("r1") == blind.resolve().placement("r1")


def test_the_occupancys_ratsnest_follows_commits():
    b = _board()
    _declare(b)
    plan = b.resolve()
    rn = plan.occupancy.ratsnest()
    assert {e.net for e in rn.edges()} == {"S", "U", "W"}
    u = [e for e in rn.edges() if e.net == "U"][0]
    assert {u.a.ref, u.b.ref} == {"N1", "R1"}
