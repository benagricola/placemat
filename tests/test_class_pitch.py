"""A net class whose clearance does not fit its pads' pitch is a setup
finding: a track leaving one of those pads straight out breaks the
clearance to the next pad, so the router cannot escape them. The lane out
of a pad is the distance from the class's track, leaving the pad straight
out from the body and centred on it, to the next pad."""
import dataclasses

from placemat.board_geometry import Footprint, NetClass
from placemat.layout import Board
from placemat.values import Box, Face, Location, Part
from tests.fixtures import board_geometry, pad


def _row(pitch=0.4, pad_w=0.3, n=6):
    pads = tuple(pad("U1", "u1", k + 1, "N%d" % (k + 1), 20 + k * pitch, 20, pad_w, 0.8) for k in range(n))
    body = Box(19, 20.5, 21 + n * pitch, 24)      # the row is the body's north side: its pads escape north
    return Footprint("U1", "u1", None, "U1", Location(20, 20), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def _plan(clearance, width=0.2, **row):
    g = board_geometry([_row(**row)])
    g = dataclasses.replace(g, netclasses={n: NetClass("Fine", width, clearance, 0.6, 0.3) for n in g.nets})
    b = Board(g, edge_margin=1.0)
    b.place(Part("u1"), at=Location(20.0, 20.0))
    return b.resolve()


def _said(plan):
    return [f for f in plan.findings if f.kind == "setup" and "pitch" in f]


def test_a_clearance_wider_than_the_lane_is_a_setup_finding():
    # 0.3 mm pads at 0.4 mm: 0.1 mm apart, and a 0.2 mm track 0.05 mm inside its pad
    said = _said(_plan(0.2))
    assert len(said) == 1, list(_plan(0.2).findings)
    text = str(said[0])
    assert "U1" in text and "'Fine'" in text and "0.150 mm for a 0.20 mm clearance" in text
    assert "a clearance of 0.15 mm or less fits" in text


def test_the_clearance_that_fits_is_rounded_down():
    said = _said(_plan(0.2, pad_w=0.224))           # a 0.188 mm lane
    assert "0.188 mm" in str(said[0]) and "a clearance of 0.18 mm or less fits" in str(said[0])


def test_a_clearance_the_gap_fits_is_not():
    assert not _said(_plan(0.15))
    assert not _said(_plan(0.2, pad_w=0.2))       # exactly the clearance
    # pads closer than the clearance, but wide: the track's lane is wider
    assert not _said(_plan(0.2, pitch=0.8, pad_w=0.65))


def test_a_track_wider_than_its_pad_needs_the_overhang_too():
    # 0.2 mm pads, 0.2 mm apart; a 0.3 mm track overhangs each side by 0.05
    assert not _said(_plan(0.15, width=0.3, pad_w=0.2))
    said = _said(_plan(0.18, width=0.3, pad_w=0.2))
    assert len(said) == 1 and "0.15" in str(said[0])


def test_a_corner_neighbour_the_track_leaves_away_from_is_not_measured():
    # two pads round a corner of a package: 0.1 mm apart, each escaping away
    # from the other
    pads = (pad("U1", "u1", 1, "N1", 20.0, 22.0, 0.3, 0.8), pad("U1", "u1", 2, "N2", 20.55, 21.35, 0.8, 0.3))
    body = Box(17, 18, 20.4, 21.6)
    fp = Footprint("U1", "u1", None, "U1", Location(19, 20), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)
    g = board_geometry([fp])
    b = Board(g, edge_margin=1.0)
    b.place(Part("u1"), at=Location(19.0, 20.0))
    assert not _said(b.resolve())


def test_a_ball_grid_is_not_measured_straight_through():
    pads = tuple(pad("U1", "u1", "%d%d" % (i, j), "N%d_%d" % (i, j), 20 + i * 0.5, 20 + j * 0.5, 0.3, 0.3)
                 for i in range(4) for j in range(4))
    body = Box(19.6, 19.6, 21.9, 21.9)
    fp = Footprint("U1", "u1", None, "U1", Location(20.75, 20.75), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)
    b = Board(board_geometry([fp]), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20.75, 20.75))
    assert not _said(b.resolve())


def test_an_exposed_pad_inside_a_row_is_not_measured_through_it():
    # a dual-row part: pins north and south, a wide exposed pad just north of
    # the body's centre, its middle opposite the 0.24 mm gap between two pins
    north = tuple(pad("U1", "u1", k + 1, "N%d" % k, 20.0 + k * 0.64, 20.0, 0.4, 0.6) for k in range(4))
    south = tuple(pad("U1", "u1", k + 5, "S%d" % k, 20.0 + k * 0.64, 23.0, 0.4, 0.6) for k in range(4))
    ep = pad("U1", "u1", 9, "EP", 20.96, 21.08, 2.5, 1.0)
    body = Box(19.5, 19.7, 22.4, 23.3)
    fp = Footprint("U1", "u1", None, "U1", Location(20.96, 21.5), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                   north + south + (ep,))
    b = Board(board_geometry([fp]), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20.96, 21.5))
    assert not _said(b.resolve())
