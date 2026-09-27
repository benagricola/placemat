"""A track's end is round, as KiCad draws it: a square cap's corner came
0.04 mm nearer a pad's corner than the copper does, and a clean board read
0.13 mm against a 0.16 rule. Pure."""
import dataclasses
import math

from placemat.copper import Track
from placemat.geometry import poly_distance
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, Part
from tests.fixtures import board_geometry, footprint, rect


def test_a_track_end_measures_round():
    t = Track("X", CopperLayer.F, 0.2, Location(10.0, 0.0), Location(5.0, 0.0))
    corner = 0.1 + 0.0909                             # a pad corner off the end, diagonally
    pad = rect(10.0 + corner + 0.5, corner + 0.5, 1.0, 1.0)
    true_gap = math.hypot(corner, corner) - 0.1       # 0.17: what KiCad measures
    assert abs(poly_distance(t.polygon, pad) - true_gap) < 0.005


def test_a_track_ending_diagonally_off_a_pad_corner_is_no_finding():
    fp = footprint("U1", 10.0 + 0.1909 + 0.5, 0.1909 + 0.5 + 10, w=1.2, h=1.0, inst="u1", nets=("Y", "Y"))
    g = board_geometry([fp, footprint("R1", 2, 10, w=2, h=1, inst="r1", nets=("X", "Z"))], width=30, height=30,
                       clearance=0.16)
    b = Board(g, edge_margin=0.5)
    b.place(Part("u1"), at=fp.location)
    b.place(Part("r1"), at=Location(2, 10))
    b.track(Net("X"), [Location(4.0, 10.0), Location(10.0, 10.0)], layer=CopperLayer.F, width=0.2)
    plan = b.resolve()
    assert not [f for f in plan.findings if "copper" in f], plan.findings


def test_a_conflict_names_a_track_as_copper_not_a_pad():
    fp = footprint("U1", 10.6, 10.0, w=1.2, h=1.0, inst="u1", nets=("Y", "Y"))
    g = board_geometry([fp, footprint("R1", 2, 10, w=2, h=1, inst="r1", nets=("X", "Z"))], width=30, height=30,
                       clearance=0.16)
    b = Board(g, edge_margin=0.5)
    b.place(Part("u1"), at=fp.location)
    b.place(Part("r1"), at=Location(2, 10))
    b.track(Net("X"), [Location(4.0, 10.0), Location(10.0, 10.0)], layer=CopperLayer.F, width=0.2)
    hits = [f for f in b.resolve().findings if "copper X" in f]
    assert hits and all(" copper X is " in f and " pad X " not in f for f in hits), hits


def _advice(crossing: bool):
    """A waypoint that steers a track into a pad draws the advice to go pad to
    pad only when pad to pad clears - another net's track in the way counts."""
    fps = [footprint("U1", 10, 10, w=4, h=1, inst="u1", nets=("A", "X")),
           footprint("R1", 22, 10, w=4, h=1, inst="r1", nets=("X", "B")),
           footprint("Z1", 16, 12, w=1.2, h=1, inst="z1", nets=("Z", "Z"))]
    b = Board(board_geometry(fps, width=40, height=30, extra_nets=("W",)), edge_margin=0.5)
    for p, at in (("u1", (10, 10)), ("r1", (22, 10)), ("z1", (16, 12))):
        b.place(Part(p), at=Location(*at))
    if crossing:
        b.track(Net("W"), [Location(14.0, 4.0), Location(14.0, 16.0)], layer=CopperLayer.F, width=0.3)
    from placemat.values import PadRef
    b.track(Net("X"), [PadRef(Part("u1"), 2), Location(16.0, 12.0), PadRef(Part("r1"), 1)], layer=CopperLayer.F)
    return [f for f in b.resolve().findings if "pad to pad it clears" in f]


def test_the_pad_to_pad_advice_is_given_when_that_line_clears():
    assert _advice(crossing=False)


def test_the_pad_to_pad_advice_is_not_given_when_that_line_crosses_another_track():
    assert not _advice(crossing=True)
